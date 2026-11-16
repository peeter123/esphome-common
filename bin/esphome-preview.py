#!/usr/bin/env python3
"""Renders a project's display preview in a Docker container (see --help).

Standard library only. Run from a project root. Docker calls go through an
injectable runner and the report is written through an injectable stream, so
the tests exercise everything without a Docker engine.
"""
import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

TOOL = 'esphome-preview'
DEFAULT_TIMEOUT = 180
DEFAULT_OUT = os.path.join('captures', 'preview')
MAX_TIMEOUT = 1e6
CLIENT_TIMEOUT = 60  # docker rm and docker version
EXIT_NO_PROGRAM_IN_CONTAINER = 97

# Exit codes: non-zero, each naming one cause.
EXIT_OTHER = 1
EXIT_INVALID = 2        # invalid manifest, pin or denied input; bad usage
EXIT_NO_ENGINE = 3
EXIT_NOT_LINUX = 4
EXIT_BUILD = 5
EXIT_COMPILE = 6
EXIT_TIMEOUT = 7
EXIT_RUN = 8
EXIT_MISSING_IMAGE = 9  # missing scenario image or invalid BMP
EXIT_NO_DOCKER = 127
EXIT_INTERRUPTED = 130

DENIED_COMPONENTS = ('secrets.yaml', '.git', '.esphome', 'captures')
NAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
PIN_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


class Fail(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class DockerMissing(Exception):
    pass


class RunTimeout(Exception):
    pass


class Result(object):
    def __init__(self, returncode=0, stdout=''):
        self.returncode = returncode
        self.stdout = stdout


def subprocess_runner(args, capture=False, quiet=False, timeout=None):
    """Runs one command. capture returns stdout; otherwise stdout goes to
    stderr so the tool's own stdout stays empty. quiet drops stderr."""
    try:
        if capture:
            done = subprocess.run(
                args, stdout=subprocess.PIPE, universal_newlines=True,
                stderr=subprocess.DEVNULL if quiet else None, timeout=timeout)
            return Result(done.returncode, done.stdout)
        sys.stderr.flush()
        done = subprocess.run(args, stdout=sys.stderr.fileno(), timeout=timeout)
        return Result(done.returncode, '')
    except FileNotFoundError:
        raise DockerMissing(args[0])
    except subprocess.TimeoutExpired:
        raise RunTimeout()


# ---- Report ---------------------------------------------------------------

ESC = '\x1b['
COLORS = {
    'option': ESC + '34m', 'env': ESC + '32m', 'wrapper': ESC + '36m',
    'default': ESC + '2m', 'project': '', 'found': ESC + '32m',
    'missing': ESC + '31m', 'skipped': ESC + '2m', 'warning': ESC + '31m',
    'rule': ESC + '1m', 'failed': ESC + '1;31m', 'off': ESC + '0m',
}


def format_duration(seconds):
    if seconds < 60:
        return '%.1fs' % seconds
    return '%dm %02ds' % (int(seconds // 60), int(seconds % 60))


class Report(object):
    """The wrappers' report: header rule, one line per setting, footer rule."""

    def __init__(self, stream, env, isatty):
        self.stream = stream
        self.use_color = not env.get('NO_COLOR') and (bool(env.get('FORCE_COLOR')) or bool(isatty))

    def line(self, text, color=''):
        if self.use_color and COLORS.get(color):
            text = COLORS[color] + text + COLORS['off']
        self.stream.write(text + '\n')
        self.stream.flush()

    def rule(self, title, color='rule'):
        self.line(('---- %s ' % ((TOOL + ' ' + title).strip())).ljust(80, '-'), color)

    def value(self, name, source, value):
        self.line('  %-27s %-8s %s' % (name, source, value), source)

    def warning(self, message):
        self.line('  ! ' + message, 'warning')

    def error(self, message):
        self.line('%s: %s' % (TOOL, message), 'failed')

    def footer(self, code, seconds):
        if code is None:
            self.rule('interrupted after ' + format_duration(seconds), 'failed')
        elif code == 0:
            self.rule('exited 0 after ' + format_duration(seconds))
        else:
            self.rule('exited %d after %s' % (code, format_duration(seconds)), 'failed')


# ---- Manifest and inputs --------------------------------------------------

def describe_error(error):
    """A short cause that does not repeat a path."""
    if isinstance(error, OSError):
        return error.strerror or type(error).__name__
    return type(error).__name__


def read_pin(root):
    path = os.path.join(root, 'requirements.txt')
    if not os.path.isfile(path):
        raise Fail(EXIT_INVALID, 'requirements.txt not found in %s; run from a project root.' % root)
    try:
        with open(path, encoding='utf-8') as handle:
            lines = handle.read().splitlines()
    except (OSError, UnicodeError) as error:
        raise Fail(EXIT_INVALID, 'cannot read requirements.txt: %s' % describe_error(error))
    for text in lines:
        match = re.match(r'^\s*esphome\s*==\s*([^\s;#]+)', text)
        if match:
            pin = match.group(1)
            if not PIN_PATTERN.match(pin):
                raise Fail(EXIT_INVALID, "requirements.txt pins esphome to '%s', which is not usable in an image tag." % pin)
            return pin
    raise Fail(EXIT_INVALID, 'requirements.txt has no esphome==X.Y.Z line; the preview needs the exact pin.')


def check_input_path(root, text):
    """Returns the validated relative path (forward slashes) or raises Fail."""
    if not isinstance(text, str) or not text:
        raise Fail(EXIT_INVALID, 'manifest input %r is not a non-empty string.' % (text,))
    if '\\' in text or text.startswith('/') or re.match(r'^[A-Za-z]:', text):
        raise Fail(EXIT_INVALID, "input '%s' is not a relative path with forward slashes." % text)
    parts = text.split('/')
    if any(part in ('', '.') for part in parts):
        raise Fail(EXIT_INVALID, "input '%s' is not a normalised relative path." % text)
    if '..' in parts:
        raise Fail(EXIT_INVALID, "input '%s' lies outside the project root." % text)
    for part in parts:
        if part.lower() in DENIED_COMPONENTS:
            raise Fail(EXIT_INVALID, "input '%s' is denied: %s is never sent to an engine." % (text, part))
    full = os.path.join(root, *parts)
    real_root = os.path.realpath(root)
    real = os.path.realpath(full)
    if os.path.commonpath([real_root, real]) != real_root:
        raise Fail(EXIT_INVALID, "input '%s' resolves outside the project root." % text)
    for part in os.path.relpath(real, real_root).replace('\\', '/').split('/'):
        if part.lower() in DENIED_COMPONENTS:
            raise Fail(EXIT_INVALID, "input '%s' is denied: it resolves into %s." % (text, part))
    if not os.path.isfile(full):
        raise Fail(EXIT_INVALID, "input '%s' is not a file in the project." % text)
    return text


def read_manifest(root, manifest_path):
    """Returns the validated manifest dict."""
    try:
        with open(manifest_path, encoding='utf-8') as handle:
            data = json.load(handle)
    except OSError as error:
        raise Fail(EXIT_INVALID, 'cannot read the manifest: %s' % describe_error(error))
    except ValueError as error:
        raise Fail(EXIT_INVALID, 'the manifest is not valid JSON: %s' % error)
    if not isinstance(data, dict):
        raise Fail(EXIT_INVALID, 'manifest %s is not a JSON object.' % manifest_path)
    expected = ('root', 'name', 'inputs', 'scenarios')
    for key in expected:
        if key not in data:
            raise Fail(EXIT_INVALID, "manifest is missing '%s'." % key)
    for key in data:
        if key not in expected:
            raise Fail(EXIT_INVALID, "manifest has an unknown key '%s'." % key)
    if not isinstance(data['name'], str) or not NAME_PATTERN.match(data['name']):
        raise Fail(EXIT_INVALID, "manifest 'name' must match %s." % NAME_PATTERN.pattern)
    for key in ('inputs', 'scenarios'):
        value = data[key]
        if not isinstance(value, list) or not value:
            raise Fail(EXIT_INVALID, "manifest '%s' must be a non-empty list." % key)
        if not all(isinstance(v, str) for v in value):
            raise Fail(EXIT_INVALID, "manifest '%s' must hold strings only." % key)
        if len(set(value)) != len(value):
            raise Fail(EXIT_INVALID, "manifest '%s' has duplicate entries." % key)
    for scenario in data['scenarios']:
        if not isinstance(scenario, str) or not NAME_PATTERN.match(scenario):
            raise Fail(EXIT_INVALID, "scenario %r must match %s." % (scenario, NAME_PATTERN.pattern))
    inputs = [check_input_path(root, item) for item in data['inputs']]
    if data['root'] not in inputs:
        raise Fail(EXIT_INVALID, "manifest 'root' %r must be one of its inputs." % (data['root'],))
    return {'root': data['root'], 'name': data['name'], 'inputs': inputs,
            'scenarios': list(data['scenarios'])}


# ---- BMP to PNG -----------------------------------------------------------

def bmp_to_png(data):
    """Converts a 24-bit BI_RGB BMP (bottom-up or top-down) to PNG bytes."""
    if len(data) < 54 or data[:2] != b'BM':
        raise ValueError('not a BMP file')
    offset = struct.unpack_from('<I', data, 10)[0]
    header = struct.unpack_from('<I', data, 14)[0]
    if header < 40:
        raise ValueError('unsupported BMP header size %d' % header)
    width, height, planes, bpp, compression = struct.unpack_from('<iiHHI', data, 18)
    if bpp != 24 or compression != 0:
        raise ValueError('only 24-bit BI_RGB BMP files are supported (got %d-bit, compression %d)' % (bpp, compression))
    if width <= 0 or height == 0:
        raise ValueError('invalid BMP size %dx%d' % (width, height))
    rows = abs(height)
    stride = (width * 3 + 3) // 4 * 4
    if offset + stride * rows > len(data):
        raise ValueError('BMP pixel data is truncated')
    raw = bytearray()
    for y in range(rows):
        source = y if height < 0 else rows - 1 - y
        start = offset + source * stride
        row = bytearray(data[start:start + width * 3])
        row[0::3], row[2::3] = row[2::3], row[0::3]  # BGR to RGB
        raw.append(0)
        raw.extend(row)

    def chunk(kind, body):
        crc = zlib.crc32(kind + body) & 0xffffffff
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', crc)

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, rows, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
            + chunk(b'IEND', b''))


# ---- Selection ------------------------------------------------------------

def resolve_cli(option, env, which):
    """Returns (source, display, path or None): --docker, ESPHOME_PREVIEW_DOCKER, docker on PATH."""
    if option:
        return 'option', option, which(option)
    if env.get('ESPHOME_PREVIEW_DOCKER'):
        return 'env', env['ESPHOME_PREVIEW_DOCKER'], which(env['ESPHOME_PREVIEW_DOCKER'])
    return 'default', 'docker on PATH', which('docker')


def resolve_context(option, env):
    """Returns (source, name or None): --context, ESPHOME_PREVIEW_CONTEXT, Docker's own choice."""
    if option:
        return 'option', option
    if env.get('ESPHOME_PREVIEW_CONTEXT'):
        return 'env', env['ESPHOME_PREVIEW_CONTEXT']
    return 'default', None


def git_describe(directory):
    try:
        done = subprocess.run(['git', '-C', directory, 'describe', '--always', '--dirty', '--abbrev=7'],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    except OSError:
        pass
    return 'unknown'


# ---- The preview ----------------------------------------------------------

class Preview(object):
    def __init__(self, args, env, runner, report, root, which=shutil.which,
                 describe=git_describe, common_dir=None, clock=time.monotonic):
        self.args = args
        self.env = env
        self.runner = runner
        self.report = report
        self.root = root
        self.which = which
        self.describe = describe
        self.common_dir = common_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.clock = clock
        self.cli = None
        self.context = None
        self.containers = []

    # docker plumbing

    def docker(self, *arguments, **options):
        command = [self.cli]
        if self.context:
            command += ['--context', self.context]
        command += list(arguments)
        return self.runner(command, **options)

    def docker_plain(self, *arguments, **options):
        # For calls that name no engine (client-only): context show, --version.
        return self.runner([self.cli] + list(arguments), **options)

    def remove_containers(self):
        while self.containers:
            self.rm_container(self.containers.pop())

    def rm_container(self, name):
        try:
            self.docker('rm', '-f', name, capture=True, quiet=True, timeout=CLIENT_TIMEOUT)
        except DockerMissing:
            pass
        except RunTimeout:
            self.report.warning('docker rm -f %s did not finish within %d s; remove the container by hand.'
                                % (name, CLIENT_TIMEOUT))

    def create(self, *arguments):
        done = self.docker('create', *arguments, capture=True)
        container = done.stdout.strip()
        if done.returncode != 0 or not container:
            raise Fail(EXIT_OTHER, 'docker create failed (see the Docker message above).')
        self.containers.append(container)
        return container

    # steps

    def start_report(self, manifest, pin):
        report, args = self.report, self.args
        manifest_name = args.manifest.replace(os.sep, '/')
        report.value('manifest', 'project', manifest_name)
        report.value('esphome', 'project', pin)
        report.value('common', 'project', '%s  %s' % (self.describe(self.common_dir), self.common_dir))
        report.value('inputs', 'project', '%d files' % len(manifest['inputs']))

    def engine_report_head(self):
        """Prints the CLI and context lines; returns after resolving both."""
        report, args, env = self.report, self.args, self.env
        source, shown, path = resolve_cli(args.docker, env, self.which)
        report.value('ESPHOME_PREVIEW_DOCKER', source, shown)
        context_source, name = resolve_context(args.context, env)
        self.context = name
        if args.check_only:
            report.value('docker', 'skipped', 'not run (--check-only)')
        elif path is None:
            report.value('docker', 'missing', shown if source != 'default' else 'docker')
            report.warning('the Docker CLI was not found; install Docker or set --docker or ESPHOME_PREVIEW_DOCKER.')
            raise Fail(EXIT_NO_DOCKER, 'the Docker CLI was not found (%s).' % shown)
        else:
            self.cli = path
            version = self.docker_plain('--version', capture=True, quiet=True)
            text = version.stdout.strip()
            match = re.search(r'Docker version ([^\s,]+)', text)
            report.value('docker', 'found', '%s  %s' % (match.group(1) if match else 'unknown', path))
        if name:
            report.value('ESPHOME_PREVIEW_CONTEXT', context_source, name)
            if name == 'default' and env.get('DOCKER_HOST'):
                report.value('DOCKER_HOST', 'env', 'set (endpoint not shown)')
        else:
            shown_name = "Docker's current context (not queried)"
            if not args.check_only:
                done = self.docker_plain('context', 'show', capture=True, quiet=True)
                shown_name = done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else 'unknown'
            report.value('ESPHOME_PREVIEW_CONTEXT', 'default', shown_name)
            if env.get('DOCKER_CONTEXT'):
                report.value('DOCKER_CONTEXT', 'env', env['DOCKER_CONTEXT'])
            if env.get('DOCKER_HOST'):
                report.value('DOCKER_HOST', 'env', 'set (endpoint not shown)')

    def check_engine(self):
        report = self.report
        if self.args.check_only:
            report.value('engine', 'skipped', 'not contacted (--check-only)')
            return
        try:
            done = self.docker('version', '--format', '{{.Server.Os}} {{.Server.Arch}} {{.Server.Version}}',
                               capture=True, quiet=True, timeout=CLIENT_TIMEOUT)
        except RunTimeout:
            report.value('engine', 'missing', 'no answer within %d s' % CLIENT_TIMEOUT)
            raise Fail(EXIT_NO_ENGINE, 'no Docker engine is reachable: it did not answer within %d s%s.' % (
                CLIENT_TIMEOUT, " (context '%s')" % self.context if self.context else ''))
        words = done.stdout.split()
        if done.returncode != 0 or not words:
            report.value('engine', 'missing', 'no Docker engine reachable')
            report.warning('the selected engine did not answer; check the context and that the engine is running.')
            raise Fail(EXIT_NO_ENGINE, 'no Docker engine is reachable%s.' % (
                " (context '%s')" % self.context if self.context else ''))
        if words[0] != 'linux':
            report.value('engine', 'missing', words[0])
            report.warning('the preview needs a Linux engine.')
            raise Fail(EXIT_NOT_LINUX, "the Docker engine is '%s', not linux; use a Linux engine (WSL 2 backend or a Linux server)." % words[0])
        report.value('engine', 'found', '%s/%s  %s' % (words[0], words[1] if len(words) > 1 else '?',
                                                         words[2] if len(words) > 2 else '?'))

    def run(self, manifest, pin):
        report, args = self.report, self.args
        image = 'esphome-preview:' + pin
        volume = 'esphome-preview-' + pin
        out_dir = args.out if os.path.isabs(args.out) else os.path.join(self.root, args.out)
        report.value('image', 'wrapper', image)
        report.value('volume', 'wrapper', volume)
        report.value('out', 'option' if args.out_given else 'default', args.out)
        report.value('timeout', 'option' if args.timeout_given else 'default', '%g s' % args.timeout)
        temp = tempfile.mkdtemp(prefix='esphome-preview-')
        try:
            self.build(temp, image, pin)
            self.compile(temp, manifest, image, volume)
            bmps = self.run_program(temp, manifest, image, volume)
            pngs = self.convert(manifest, bmps)
            self.save(pngs, out_dir)
        finally:
            self.remove_containers()
            shutil.rmtree(temp, ignore_errors=True)

    def build(self, temp, image, pin):
        self.report.rule('build')
        context = os.path.join(temp, 'build')
        os.makedirs(context)
        try:
            shutil.copyfile(os.path.join(self.common_dir, 'docker', 'preview', 'Dockerfile'),
                            os.path.join(context, 'Dockerfile'))
            with open(os.path.join(context, 'requirements.txt'), 'w', encoding='utf-8', newline='\n') as handle:
                handle.write('esphome==%s\n' % pin)
        except OSError as error:
            raise Fail(EXIT_OTHER, 'cannot prepare the build context: %s' % describe_error(error))
        done = self.docker('build', '--tag', image, context)
        if done.returncode != 0:
            raise Fail(EXIT_BUILD, 'the image build failed (exit %d).' % done.returncode)
        done = self.docker('image', 'inspect', image, capture=True, quiet=True, timeout=CLIENT_TIMEOUT)
        if done.returncode != 0:
            raise Fail(EXIT_BUILD, ('the build succeeded but image %s is not in the engine; a non-default buildx '
                                    'builder (docker-container driver) may not load images into it. Run '
                                    '`docker buildx use default` (or select the default builder) and retry.') % image)

    def mount(self, volume):
        return '--mount=type=volume,source=%s,target=/cache' % volume

    def compile(self, temp, manifest, image, volume):
        self.report.rule('compile')
        stage = os.path.join(temp, 'work')
        for item in manifest['inputs']:
            target = os.path.join(stage, *item.split('/'))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(os.path.join(self.root, *item.split('/')), target)
            except OSError as error:
                raise Fail(EXIT_OTHER, "cannot stage input '%s': %s" % (item, describe_error(error)))
        container = self.create(self.mount(volume), image, 'esphome', 'compile', manifest['root'])
        done = self.docker('cp', os.path.join(stage, '.'), container + ':/work')
        if done.returncode != 0:
            raise Fail(EXIT_OTHER, 'copying the inputs into the container failed.')
        done = self.docker('start', '-a', container)
        if done.returncode != 0:
            raise Fail(EXIT_COMPILE, 'the compile failed (exit %d).' % done.returncode)
        self.rm_container(container)
        self.containers.remove(container)

    @staticmethod
    def run_script(name):
        snapshots = '"$ESPHOME_DATA_DIR/snapshots/%s"' % name
        program = '"$ESPHOME_DATA_DIR/build/%s/.pioenvs/%s/program"' % (name, name)
        return ('set -e; rm -rf %s; mkdir -p %s "$ESPHOME_PREFDIR" /out; '
                '[ -x %s ] || { echo "no compiled program for %s" >&2; exit %d; }; '
                '%s; for f in %s/*.bmp; do if [ -e "$f" ]; then cp "$f" /out/; fi; done'
                % (snapshots, snapshots, program, name, EXIT_NO_PROGRAM_IN_CONTAINER, program, snapshots))

    def run_program(self, temp, manifest, image, volume):
        self.report.rule('run')
        container = self.create('--network', 'none', self.mount(volume), image,
                                'sh', '-c', self.run_script(manifest['name']))
        try:
            done = self.docker('start', '-a', container, timeout=self.args.timeout)
        except RunTimeout:
            self.rm_container(container)
            self.containers.remove(container)
            raise Fail(EXIT_TIMEOUT, 'the preview program did not finish within %g s; container removed, nothing saved.'
                       % self.args.timeout)
        if done.returncode == EXIT_NO_PROGRAM_IN_CONTAINER:
            raise Fail(EXIT_RUN, ("there is no compiled program for '%s'; the manifest 'name' must equal the "
                                  "esphome name in the root.") % manifest['name'])
        if done.returncode != 0:
            raise Fail(EXIT_RUN, 'the preview program failed (exit %d).' % done.returncode)
        out = os.path.join(temp, 'out')
        os.makedirs(out)
        done = self.docker('cp', container + ':/out/.', out)
        if done.returncode != 0:
            raise Fail(EXIT_MISSING_IMAGE, 'no images could be copied out of the container.')
        return out

    def convert(self, manifest, bmp_dir):
        missing = [s for s in manifest['scenarios'] if not os.path.isfile(os.path.join(bmp_dir, s + '.bmp'))]
        if missing:
            raise Fail(EXIT_MISSING_IMAGE, 'missing scenario image(s): %s.' % ', '.join(missing))
        pngs = {}
        for scenario in manifest['scenarios']:
            with open(os.path.join(bmp_dir, scenario + '.bmp'), 'rb') as handle:
                try:
                    pngs[scenario] = bmp_to_png(handle.read())
                except ValueError as error:
                    raise Fail(EXIT_MISSING_IMAGE, 'scenario image %s.bmp is invalid: %s.' % (scenario, error))
        return pngs

    def save(self, pngs, out_dir):
        staging = None
        try:
            os.makedirs(out_dir, exist_ok=True)
            staging = tempfile.mkdtemp(prefix='.preview-', dir=out_dir)
            for scenario, data in pngs.items():
                with open(os.path.join(staging, scenario + '.png'), 'wb') as handle:
                    handle.write(data)
            for scenario in pngs:
                os.replace(os.path.join(staging, scenario + '.png'), os.path.join(out_dir, scenario + '.png'))
        except OSError as error:
            raise Fail(EXIT_OTHER, 'cannot write images to %s: %s' % (out_dir, describe_error(error)))
        finally:
            if staging:
                shutil.rmtree(staging, ignore_errors=True)
        self.report.line('  saved %d images in %s' % (len(pngs), out_dir))

    def execute(self):
        """Runs everything; returns the exit code."""
        start = self.clock()
        code = None
        self.report.rule('')
        try:
            try:
                pin = read_pin(self.root)
                manifest = read_manifest(self.root, os.path.join(self.root, self.args.manifest)
                                         if not os.path.isabs(self.args.manifest) else self.args.manifest)
                self.start_report(manifest, pin)
                self.engine_report_head()
                self.check_engine()
                if self.args.check_only:
                    self.report.line('  manifest, pin and %d inputs are valid.' % len(manifest['inputs']))
                else:
                    self.run(manifest, pin)
                code = 0
            except Fail as failure:
                self.report.error(failure.message)
                code = failure.code
            except (OSError, UnicodeError) as error:
                self.report.error('unexpected file or system error: %s' % describe_error(error))
                code = EXIT_OTHER
            except DockerMissing:
                self.report.error('the Docker CLI could not be started.')
                code = EXIT_NO_DOCKER
            except KeyboardInterrupt:
                code = None
        finally:
            self.remove_containers()
        self.report.footer(code, self.clock() - start)
        return EXIT_INTERRUPTED if code is None else code


# ---- Command line ---------------------------------------------------------

HELP_DESCRIPTION = """\
Renders a project's display preview in a Linux Docker container and saves one
PNG per scenario. Run it from a project root. The manifest names the ESPHome
root, the device name, the input files and the scenarios. ESPHome is built at
the version pinned in requirements.txt. Only these are sent to the engine: the
manifest's inputs, plus the Dockerfile and a generated one-line requirements.txt
for the image (the project's own requirements.txt is only read for the pin).
secrets.yaml, .git/, .esphome/ and captures/ never are, and no bind mount is
used, so a remote engine works.

Before contacting any engine the tool prints a report to stderr: one line per
setting with its source, then the engine check. After the run it prints the
exit code and the elapsed time. The tool's own report and messages never
contain an endpoint, user or host name; messages printed by the Docker CLI or
ssh themselves pass through unchanged. --check-only validates the manifest,
the pin and the inputs, and never invokes Docker."""

HELP_EPILOG = """\
Report tags:
  option    given on the command line
  env       set in the caller's environment
  wrapper   chosen by this tool
  default   not set; the default shown applies
  project   read from the project or the common checkout
  found, missing, skipped
            checks; a warning follows a problem, skipped: --check-only

Environment:
  ESPHOME_PREVIEW_DOCKER   Docker CLI executable (default: docker on PATH)
  ESPHOME_PREVIEW_CONTEXT  Docker context to use (default: Docker's own choice)
  DOCKER_CONTEXT, DOCKER_HOST
                           honoured by Docker when no context is chosen; the
                           report shows DOCKER_HOST as set, never its value
  FORCE_COLOR              colour the report even when stderr is redirected
  NO_COLOR                 never colour the report

Exit codes: 0 success; 1 other Docker or file error; 2 invalid manifest, pin or
input, or bad usage; 3 no engine reachable; 4 engine is not Linux; 5 image build
failed; 6 compile failed; 7 timeout; 8 program failed; 9 scenario image missing
or invalid; 127 Docker CLI missing; 130 interrupted.

Example:
  esphome-preview preview/preview.json
  esphome-preview preview/preview.json --context <name> --out captures/preview
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog=TOOL, description=HELP_DESCRIPTION, epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        usage='%(prog)s MANIFEST [--context NAME] [--docker PATH] [--out DIR] [--timeout SECONDS] [--check-only]')
    parser.add_argument('manifest', metavar='MANIFEST', help='manifest JSON, e.g. preview/preview.json')
    parser.add_argument('--context', metavar='NAME',
                        help='Docker context for every call (default: ESPHOME_PREVIEW_CONTEXT, else Docker\'s own)')
    parser.add_argument('--docker', metavar='PATH',
                        help='Docker CLI (default: ESPHOME_PREVIEW_DOCKER, else docker on PATH)')
    parser.add_argument('--out', metavar='DIR', default=None,
                        help='output directory (default: %s)' % DEFAULT_OUT.replace(os.sep, '/'))
    parser.add_argument('--timeout', metavar='SECONDS', type=float, default=None,
                        help='limit for the preview program (default: %d)' % DEFAULT_TIMEOUT)
    parser.add_argument('--check-only', action='store_true',
                        help='validate the manifest, pin and inputs; never invoke Docker')
    return parser


def main(argv=None, env=None, runner=None, stream=None, isatty=None, root=None, **options):
    env = os.environ if env is None else env
    stream = sys.stderr if stream is None else stream
    if isatty is None:
        isatty = hasattr(stream, 'isatty') and stream.isatty()
    args = build_parser().parse_args(argv)
    args.out_given = args.out is not None
    args.timeout_given = args.timeout is not None
    if args.out is None:
        args.out = DEFAULT_OUT
    if args.timeout is None:
        args.timeout = DEFAULT_TIMEOUT
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > MAX_TIMEOUT:
        build_parser().error('--timeout must be a number of seconds above 0 and at most %g' % MAX_TIMEOUT)
    root = os.getcwd() if root is None else root
    report = Report(stream, env, isatty)
    return Preview(args, env, runner or subprocess_runner, report, root, **options).execute()


if __name__ == '__main__':
    sys.exit(main())
