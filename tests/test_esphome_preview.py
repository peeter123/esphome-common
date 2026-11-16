"""Unit tests for bin/esphome-preview.py. No test contacts a Docker engine."""
import importlib.util
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_PATH = os.path.join(os.path.dirname(HERE), 'bin', 'esphome-preview.py')
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('esphome_preview', TOOL_PATH)
tool = importlib.util.module_from_spec(spec)
sys.modules['esphome_preview'] = tool
spec.loader.exec_module(tool)

SCENARIOS = ['heating', 'idle']
ENDPOINT = 'ssh://someone@secret-host.example'


def make_bmp(width, height, pixel, top_down=False):
    """24-bit BI_RGB BMP; pixel(x, y) -> (r, g, b) with y = 0 the top row."""
    stride = (width * 3 + 3) // 4 * 4
    rows = []
    for y in range(height):
        row = b''.join(bytes(pixel(x, y)[::-1]) for x in range(width))
        rows.append(row + b'\0' * (stride - len(row)))
    if not top_down:
        rows.reverse()
    body = b''.join(rows)
    header = struct.pack('<2sIHHI', b'BM', 54 + len(body), 0, 0, 54)
    info = struct.pack('<IiiHHIIiiII', 40, width, -height if top_down else height, 1, 24, 0,
                       len(body), 2835, 2835, 0, 0)
    return header + info + body


def decode_png(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat, ihdr = 8, b'', None
    while pos < len(data):
        length, kind = struct.unpack_from('>I4s', data, pos)
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack_from('>I', data, pos + 8 + length)[0]
        assert crc == zlib.crc32(kind + body) & 0xffffffff
        if kind == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat += body
        pos += 12 + length
    width, height, depth, colour, _, _, _ = ihdr
    assert (depth, colour) == (8, 2)
    raw = zlib.decompress(idat)
    pixels = []
    for y in range(height):
        row = raw[y * (width * 3 + 1):(y + 1) * (width * 3 + 1)]
        assert row[0] == 0
        pixels.append([tuple(row[1 + x * 3:4 + x * 3]) for x in range(width)])
    return width, height, pixels


def gradient(x, y):
    return (x * 40 % 256, y * 50 % 256, (x + y) * 17 % 256)


class BmpToPngTests(unittest.TestCase):
    def check(self, width, height, top_down):
        png = tool.bmp_to_png(make_bmp(width, height, gradient, top_down))
        w, h, pixels = decode_png(png)
        self.assertEqual((w, h), (width, height))
        for y in range(height):
            for x in range(width):
                self.assertEqual(pixels[y][x], gradient(x, y))

    def test_width_not_divisible_by_four_bottom_up(self):
        self.check(5, 3, False)

    def test_width_not_divisible_by_four_top_down(self):
        self.check(7, 4, True)

    def test_width_divisible_by_four(self):
        self.check(8, 2, False)

    def test_rejects_other_depth(self):
        data = bytearray(make_bmp(2, 2, gradient))
        struct.pack_into('<H', data, 28, 32)
        with self.assertRaises(ValueError):
            tool.bmp_to_png(bytes(data))

    def test_rejects_compression(self):
        data = bytearray(make_bmp(2, 2, gradient))
        struct.pack_into('<I', data, 30, 3)
        with self.assertRaises(ValueError):
            tool.bmp_to_png(bytes(data))

    def test_rejects_truncated_and_non_bmp(self):
        with self.assertRaises(ValueError):
            tool.bmp_to_png(make_bmp(4, 4, gradient)[:-5])
        with self.assertRaises(ValueError):
            tool.bmp_to_png(b'x' * 100)


class ProjectCase(unittest.TestCase):
    """A temporary project root with a manifest, inputs and a pin."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='preview-test-')
        self.addCleanup(shutil.rmtree, self.root, True)
        self.write('requirements.txt', 'esphome==2026.9.1\n')
        self.write('preview/display-preview.yml', 'esphome:\n  name: dev\n')
        self.write('preview/preview_clock.h', '// clock\n')
        self.write('secrets.yaml', 'wifi: hunter2\n')
        self.manifest = {'root': 'preview/display-preview.yml', 'name': 'dev',
                         'inputs': ['preview/display-preview.yml', 'preview/preview_clock.h'],
                         'scenarios': list(SCENARIOS)}
        self.write_manifest()

    def write(self, rel, text):
        path = os.path.join(self.root, *rel.split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as handle:
            handle.write(text)

    def write_manifest(self):
        self.write('preview/preview.json', json.dumps(self.manifest))


class ManifestTests(ProjectCase):
    def read(self):
        return tool.read_manifest(self.root, os.path.join(self.root, 'preview', 'preview.json'))

    def fails(self, fragment):
        self.write_manifest()
        with self.assertRaises(tool.Fail) as caught:
            self.read()
        self.assertEqual(caught.exception.code, tool.EXIT_INVALID)
        self.assertIn(fragment, caught.exception.message)

    def test_valid(self):
        self.assertEqual(self.read()['scenarios'], SCENARIOS)

    def test_pin(self):
        self.assertEqual(tool.read_pin(self.root), '2026.9.1')

    def test_pin_missing(self):
        self.write('requirements.txt', 'esphome>=1\n')
        with self.assertRaises(tool.Fail):
            tool.read_pin(self.root)

    def test_missing_key_unknown_key_and_types(self):
        del self.manifest['name']
        self.fails("missing 'name'")
        self.manifest['name'] = 'dev'
        self.manifest['extra'] = 1
        self.fails('unknown key')
        del self.manifest['extra']
        self.manifest['name'] = 'bad name; rm'
        self.fails("'name'")
        self.manifest['name'] = 'dev'
        self.manifest['scenarios'] = ['a/b']
        self.fails('scenario')
        self.manifest['scenarios'] = ['a', 'a']
        self.fails('duplicate')
        self.manifest['scenarios'] = []
        self.fails('non-empty')

    def test_root_must_be_an_input(self):
        self.manifest['root'] = 'other.yml'
        self.fails('one of its inputs')

    def test_denied_inputs_even_when_declared(self):
        self.write('captures/x.png', 'x')
        self.write('.git/config', 'x')
        self.write('.esphome/x', 'x')
        self.write('sub/secrets.yaml', 'x')
        for denied in ('secrets.yaml', 'sub/secrets.yaml', '.git/config', '.esphome/x', 'captures/x.png'):
            self.manifest['inputs'] = ['preview/display-preview.yml', denied]
            self.fails('denied')

    def test_outside_root_and_absolute(self):
        for bad in ('../x.yml', '/etc/passwd', 'C:/x.yml', 'a\\b.yml', 'a//b.yml'):
            self.manifest['inputs'] = ['preview/display-preview.yml', bad]
            self.fails('input')

    def test_missing_file(self):
        self.manifest['inputs'] = ['preview/display-preview.yml', 'preview/nope.h']
        self.fails('not a file')

    def test_invalid_json(self):
        self.write('preview/preview.json', '{')
        with self.assertRaises(tool.Fail):
            self.read()


class Fake(object):
    """Fake docker runner: records every call and answers by command."""

    def __init__(self, project, os_name='linux', engine=True, bmps=None, build_rc=0,
                 compile_rc=0, run_rc=0, timeout=False, context='desktop-linux', image_ok=True,
                 rm_timeout=False):
        self.project = project
        self.calls = []
        self.os_name = os_name
        self.engine = engine
        self.bmps = SCENARIOS if bmps is None else bmps
        self.build_rc, self.compile_rc, self.run_rc = build_rc, compile_rc, run_rc
        self.timeout = timeout
        self.context = context
        self.image_ok = image_ok
        self.rm_timeout = rm_timeout
        self.created = []
        self.copied_inputs = []

    def sub(self, call):
        """The docker subcommand, after the CLI and an optional --context NAME."""
        rest = call[1:]
        if rest[:1] == ['--context']:
            rest = rest[2:]
        return rest

    def __call__(self, args, capture=False, quiet=False, timeout=None):
        self.calls.append((list(args), timeout))
        rest = self.sub(args)
        verb = rest[0]
        if verb == '--version':
            return tool.Result(0, 'Docker version 24.0.6, build abc\n')
        if verb == 'context':
            return tool.Result(0, self.context + '\n')
        if verb == 'version':
            if not self.engine:
                return tool.Result(1, '')
            return tool.Result(0, '%s amd64 24.0.6\n' % self.os_name)
        if verb == 'build':
            context = rest[-1]
            self.build_files = sorted(os.listdir(context))
            with open(os.path.join(context, 'requirements.txt')) as handle:
                self.build_requirements = handle.read()
            return tool.Result(self.build_rc)
        if verb == 'image':
            return tool.Result(0 if self.image_ok else 1)
        if verb == 'create':
            name = 'cid%d' % (len(self.created) + 1)
            self.created.append((name, rest))
            return tool.Result(0, name + '\n')
        if verb == 'cp':
            if rest[1].startswith('cid') and ':/out' in rest[1]:
                for scenario in self.bmps:
                    with open(os.path.join(rest[2], scenario + '.bmp'), 'wb') as handle:
                        handle.write(make_bmp(5, 3, gradient))
            else:
                base = os.path.normpath(rest[1])
                self.copied_inputs = sorted(
                    os.path.relpath(os.path.join(d, f), base).replace(os.sep, '/')
                    for d, _, files in os.walk(base) for f in files)
            return tool.Result(0)
        if verb == 'start':
            container = rest[-1]
            is_run = '--network' in dict(self.created)[container]
            if is_run and self.timeout:
                raise tool.RunTimeout()
            return tool.Result(self.run_rc if is_run else self.compile_rc)
        if verb == 'rm':
            if self.rm_timeout:
                raise tool.RunTimeout()
            return tool.Result(0)
        raise AssertionError('unexpected docker call %r' % (args,))

    def verbs(self):
        return [self.sub(c)[0] for c, _ in self.calls]

    def removed(self):
        return [self.sub(c)[-1] for c, _ in self.calls if self.sub(c)[0] == 'rm']


def which_docker(name):
    return {'docker': 'C:/docker.exe', 'D:/my/docker.exe': 'D:/my/docker.exe'}.get(name)


def run_main(project, argv, env=None, runner=None, which=which_docker, isatty=False):
    stream = io.StringIO()
    code = tool.main(argv, env=env or {}, runner=runner, stream=stream, isatty=isatty,
                     root=project.root, which=which, describe=lambda d: 'abc1234',
                     common_dir=os.path.dirname(HERE))
    return code, stream.getvalue()


MANIFEST_ARG = 'preview/preview.json'


class PrecedenceTests(ProjectCase):
    def test_cli_selection(self):
        env = {'ESPHOME_PREVIEW_DOCKER': 'D:/my/docker.exe'}
        self.assertEqual(tool.resolve_cli('D:/my/docker.exe', env, which_docker)[0], 'option')
        self.assertEqual(tool.resolve_cli(None, env, which_docker)[0], 'env')
        self.assertEqual(tool.resolve_cli(None, {}, which_docker)[0], 'default')
        self.assertIsNone(tool.resolve_cli(None, {}, lambda n: None)[2])

    def test_context_selection(self):
        env = {'ESPHOME_PREVIEW_CONTEXT': 'fromenv'}
        self.assertEqual(tool.resolve_context('opt', env), ('option', 'opt'))
        self.assertEqual(tool.resolve_context(None, env), ('env', 'fromenv'))
        self.assertEqual(tool.resolve_context(None, {}), ('default', None))

    def test_option_context_on_every_call_except_client_only(self):
        fake = Fake(self)
        env = {'ESPHOME_PREVIEW_CONTEXT': 'fromenv'}
        code, _ = run_main(self, [MANIFEST_ARG, '--context', 'chosen'], env, fake)
        self.assertEqual(code, 0)
        for call, _ in fake.calls:
            if fake.sub(call)[0] == '--version':
                continue
            self.assertEqual(call[1:3], ['--context', 'chosen'], call)
        self.assertNotIn('context', fake.verbs())

    def test_env_context_on_every_call(self):
        fake = Fake(self)
        code, _ = run_main(self, [MANIFEST_ARG], {'ESPHOME_PREVIEW_CONTEXT': 'fromenv'}, fake)
        self.assertEqual(code, 0)
        for call, _ in fake.calls:
            if fake.sub(call)[0] != '--version':
                self.assertEqual(call[1:3], ['--context', 'fromenv'])

    def test_default_context_passes_no_context_flag(self):
        fake = Fake(self)
        run_main(self, [MANIFEST_ARG], {}, fake)
        for call, _ in fake.calls:
            self.assertNotIn('--context', call)
        self.assertIn('context', fake.verbs())

    def test_docker_option_is_the_executable(self):
        fake = Fake(self)
        run_main(self, [MANIFEST_ARG, '--docker', 'D:/my/docker.exe'], {}, fake)
        self.assertEqual({c[0] for c, _ in fake.calls}, {'D:/my/docker.exe'})


class ReportTests(ProjectCase):
    def lines(self, argv, env, **kwargs):
        code, text = run_main(self, argv, env, Fake(self, **kwargs))
        table = {}
        for line in text.splitlines():
            if line.startswith('  ') and not line.startswith('  !'):
                parts = line.split(None, 2)
                if len(parts) == 3:
                    table[parts[0]] = (parts[1], parts[2])
        return code, text, table

    def test_default_case(self):
        code, text, t = self.lines([MANIFEST_ARG], {})
        self.assertEqual(code, 0)
        self.assertTrue(text.startswith('---- esphome-preview -'))
        self.assertEqual(t['manifest'][0], 'project')
        self.assertEqual(t['esphome'], ('project', '2026.9.1'))
        self.assertEqual(t['ESPHOME_PREVIEW_DOCKER'], ('default', 'docker on PATH'))
        self.assertEqual(t['docker'][0], 'found')
        self.assertIn('24.0.6', t['docker'][1])
        self.assertEqual(t['ESPHOME_PREVIEW_CONTEXT'], ('default', 'desktop-linux'))
        self.assertEqual(t['engine'], ('found', 'linux/amd64  24.0.6'))
        self.assertEqual(t['image'], ('wrapper', 'esphome-preview:2026.9.1'))
        self.assertEqual(t['volume'], ('wrapper', 'esphome-preview-2026.9.1'))
        self.assertEqual(t['inputs'], ('project', '2 files'))
        self.assertEqual(t['out'][0], 'default')
        self.assertEqual(t['timeout'], ('default', '180 s'))
        self.assertNotIn('DOCKER_HOST', t)
        self.assertRegex(text.splitlines()[-1], r'^---- esphome-preview exited 0 after \d')

    def test_option_and_env_sources(self):
        _, _, t = self.lines([MANIFEST_ARG, '--docker', 'D:/my/docker.exe', '--context', 'c1',
                              '--out', 'o', '--timeout', '5'], {})
        self.assertEqual(t['ESPHOME_PREVIEW_DOCKER'][0], 'option')
        self.assertEqual(t['ESPHOME_PREVIEW_CONTEXT'], ('option', 'c1'))
        self.assertEqual(t['out'], ('option', 'o'))
        self.assertEqual(t['timeout'], ('option', '5 s'))
        _, _, t = self.lines([MANIFEST_ARG], {'ESPHOME_PREVIEW_DOCKER': 'D:/my/docker.exe',
                                              'ESPHOME_PREVIEW_CONTEXT': 'c2'})
        self.assertEqual(t['ESPHOME_PREVIEW_DOCKER'][0], 'env')
        self.assertEqual(t['ESPHOME_PREVIEW_CONTEXT'], ('env', 'c2'))

    def test_docker_host_shown_only_as_set(self):
        _, text, t = self.lines([MANIFEST_ARG], {'DOCKER_HOST': ENDPOINT, 'DOCKER_CONTEXT': 'ctx'})
        self.assertEqual(t['DOCKER_HOST'], ('env', 'set (endpoint not shown)'))
        self.assertEqual(t['DOCKER_CONTEXT'], ('env', 'ctx'))
        self.assertNotIn('secret-host', text)
        self.assertNotIn('ssh://', text)

    def test_endpoint_never_printed_on_failures(self):
        for kwargs in ({'engine': False}, {'os_name': 'windows'}, {'compile_rc': 1}):
            _, text, _ = self.lines([MANIFEST_ARG], {'DOCKER_HOST': ENDPOINT}, **kwargs)
            self.assertNotIn('secret-host', text)
            self.assertNotIn('someone', text)

    def test_check_only_report_and_no_docker_call(self):
        fake = Fake(self)
        code, text = run_main(self, [MANIFEST_ARG, '--check-only'], {'DOCKER_HOST': ENDPOINT}, fake)
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [])
        self.assertIn('engine                      skipped', text)
        self.assertIn('set (endpoint not shown)', text)
        self.assertNotIn('secret-host', text)

    def test_check_only_invalid_manifest_fails(self):
        self.manifest['inputs'].append('secrets.yaml')
        self.write_manifest()
        fake = Fake(self)
        code, text = run_main(self, [MANIFEST_ARG, '--check-only'], {}, fake)
        self.assertEqual(code, tool.EXIT_INVALID)
        self.assertEqual(fake.calls, [])
        self.assertIn('denied', text)
        self.assertRegex(text.splitlines()[-1], r'exited 2 after')

    def test_colour_rules(self):
        esc = '\x1b['
        self.assertNotIn(esc, run_main(self, [MANIFEST_ARG, '--check-only'], {})[1])
        self.assertIn(esc, run_main(self, [MANIFEST_ARG, '--check-only'], {'FORCE_COLOR': '1'})[1])
        self.assertIn(esc, run_main(self, [MANIFEST_ARG, '--check-only'], {}, isatty=True)[1])
        self.assertNotIn(esc, run_main(self, [MANIFEST_ARG, '--check-only'],
                                       {'NO_COLOR': '1', 'FORCE_COLOR': '1'}, isatty=True)[1])

    def test_failed_footer_is_red(self):
        code, text = run_main(self, [MANIFEST_ARG], {'FORCE_COLOR': '1'}, Fake(self, engine=False))
        self.assertEqual(code, tool.EXIT_NO_ENGINE)
        self.assertTrue(text.splitlines()[-1].startswith('\x1b[1;31m'))

    def test_missing_docker_cli(self):
        code, text = run_main(self, [MANIFEST_ARG], {}, Fake(self), which=lambda n: None)
        self.assertEqual(code, tool.EXIT_NO_DOCKER)
        self.assertIn('Docker CLI was not found', text)
        self.assertIn('missing', text)


class SequenceTests(ProjectCase):
    def out_dir(self):
        return os.path.join(self.root, 'captures', 'preview')

    def test_success_sequence(self):
        fake = Fake(self)
        code, text = run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(code, 0, text)
        verbs = fake.verbs()
        order = [v for v in verbs if v in ('version', 'build', 'create', 'cp', 'start', 'rm')]
        self.assertEqual(order[:2], ['version', 'build'])
        self.assertEqual(order[2:5], ['create', 'cp', 'start'])
        self.assertLess(verbs.index('version'), verbs.index('build'))
        self.assertEqual(fake.build_files, ['Dockerfile', 'requirements.txt'])
        self.assertEqual(fake.build_requirements, 'esphome==2026.9.1\n')
        compile_args, run_args = fake.created[0][1], fake.created[1][1]
        self.assertEqual(compile_args[-4:], ['esphome-preview:2026.9.1',
                                              'esphome', 'compile', 'preview/display-preview.yml'])
        self.assertIn('--mount=type=volume,source=esphome-preview-2026.9.1,target=/cache', compile_args)
        self.assertIn('--mount=type=volume,source=esphome-preview-2026.9.1,target=/cache', run_args)
        self.assertEqual(sorted(os.listdir(self.out_dir())), ['heating.png', 'idle.png'])
        with open(os.path.join(self.out_dir(), 'idle.png'), 'rb') as handle:
            w, h, pixels = decode_png(handle.read())
        self.assertEqual((w, h, pixels[1][2]), (5, 3, gradient(2, 1)))
        self.assertEqual(sorted(fake.removed()), ['cid1', 'cid2'])

    def test_no_bind_mounts_anywhere(self):
        fake = Fake(self)
        run_main(self, [MANIFEST_ARG], {}, fake)
        for call, _ in fake.calls:
            text = ' '.join(call)
            self.assertNotIn('type=bind', text)
            self.assertNotIn(' -v ', ' ' + text + ' ')
            self.assertNotIn('--volume', text)
        for _, rest in fake.created:
            for arg in rest:
                if arg.startswith('--mount'):
                    self.assertTrue(arg.startswith('--mount=type=volume,source=esphome-preview-'))

    def test_only_listed_inputs_staged(self):
        fake = Fake(self)
        run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(fake.copied_inputs, sorted(self.manifest['inputs']))
        self.assertNotIn('secrets.yaml', fake.copied_inputs)

    def test_run_container_is_offline_and_clears_snapshots_first(self):
        fake = Fake(self)
        run_main(self, [MANIFEST_ARG], {}, fake)
        compile_args, run_args = fake.created[0][1], fake.created[1][1]
        self.assertNotIn('--network', compile_args)
        self.assertEqual(run_args[run_args.index('--network') + 1], 'none')
        script = run_args[-1]
        self.assertEqual(run_args[-3:-1], ['sh', '-c'])
        clear = script.index('rm -rf "$ESPHOME_DATA_DIR/snapshots/dev"')
        program = script.index('"$ESPHOME_DATA_DIR/build/dev/.pioenvs/dev/program"')
        copy = script.index('/out/')
        self.assertLess(clear, program)
        self.assertLess(program, copy)
        self.assertTrue(script.startswith('set -e;'))

    def test_timeout_passed_to_run_start_only(self):
        fake = Fake(self)
        run_main(self, [MANIFEST_ARG, '--timeout', '42'], {}, fake)
        timeouts = [(fake.sub(c)[0], t) for c, t in fake.calls if t is not None]
        self.assertIn(('start', 42.0), timeouts)
        self.assertEqual({v for v, t in timeouts if v != 'start'}, {'version', 'image', 'rm'})
        self.assertTrue(all(t == tool.CLIENT_TIMEOUT for v, t in timeouts if v != 'start'))

    def test_timeout_removes_container_and_saves_nothing(self):
        fake = Fake(self, timeout=True)
        code, text = run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(code, tool.EXIT_TIMEOUT)
        self.assertIn('did not finish within 180 s', text)
        self.assertIn('cid2', fake.removed())
        self.assertFalse(os.path.exists(self.out_dir()))

    def test_missing_scenario(self):
        fake = Fake(self, bmps=['heating'])
        code, text = run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(code, tool.EXIT_MISSING_IMAGE)
        self.assertIn('missing scenario image(s): idle', text)
        self.assertFalse(os.path.exists(self.out_dir()))
        self.assertEqual(sorted(fake.removed()), ['cid1', 'cid2'])

    def test_no_engine_sends_nothing(self):
        fake = Fake(self, engine=False)
        code, text = run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(code, tool.EXIT_NO_ENGINE)
        self.assertIn('no Docker engine is reachable', text)
        self.assertEqual(set(fake.verbs()) - {'--version', 'context', 'version'}, set())

    def test_non_linux_engine_refused_naming_os(self):
        fake = Fake(self, os_name='windows')
        code, text = run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(code, tool.EXIT_NOT_LINUX)
        self.assertIn("'windows'", text)
        self.assertNotIn('build', fake.verbs())
        self.assertNotIn('create', fake.verbs())

    def test_build_failure(self):
        fake = Fake(self, build_rc=1)
        code, text = run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(code, tool.EXIT_BUILD)
        self.assertIn('build failed', text)
        self.assertNotIn('create', fake.verbs())

    def test_compile_failure_removes_container(self):
        fake = Fake(self, compile_rc=1)
        code, text = run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(code, tool.EXIT_COMPILE)
        self.assertEqual(fake.removed(), ['cid1'])
        self.assertEqual(len(fake.created), 1)
        self.assertFalse(os.path.exists(self.out_dir()))

    def test_run_failure_removes_container_and_saves_nothing(self):
        fake = Fake(self, run_rc=3)
        code, _ = run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(code, tool.EXIT_RUN)
        self.assertIn('cid2', fake.removed())
        self.assertFalse(os.path.exists(self.out_dir()))

    def test_invalid_bmp_saves_nothing(self):
        class Bad(Fake):
            def __call__(self, args, **kw):
                rest = self.sub(args)
                if rest[0] == 'cp' and rest[1].startswith('cid'):
                    for scenario in SCENARIOS:
                        with open(os.path.join(rest[2], scenario + '.bmp'), 'wb') as handle:
                            handle.write(b'junk')
                    return tool.Result(0)
                return Fake.__call__(self, args, **kw)
        bad = Bad(self)
        code, text = run_main(self, [MANIFEST_ARG], {}, bad)
        self.assertEqual(code, tool.EXIT_MISSING_IMAGE)
        self.assertFalse(os.path.exists(self.out_dir()))

    def test_custom_out_directory(self):
        target = os.path.join(self.root, 'elsewhere')
        code, _ = run_main(self, [MANIFEST_ARG, '--out', target], {}, Fake(self))
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(target)), ['heating.png', 'idle.png'])

    def test_run_script_uses_validated_name_only(self):
        self.assertIn('/snapshots/dev"', tool.Preview.run_script('dev'))


    def test_project_requirements_not_sent(self):
        self.write('requirements.txt', 'esphome==2026.9.1\nprivate-package==1\n')
        fake = Fake(self)
        run_main(self, [MANIFEST_ARG], {}, fake)
        self.assertEqual(fake.build_requirements, 'esphome==2026.9.1\n')

    def test_run_script_tolerates_no_bmp_and_flags_exit_codes(self):
        script = tool.Preview.run_script('dev')
        self.assertIn('for f in "$ESPHOME_DATA_DIR/snapshots/dev"/*.bmp; do if [ -e "$f" ]; then cp "$f" /out/; fi; done', script)
        self.assertIn('[ -x "$ESPHOME_DATA_DIR/build/dev/.pioenvs/dev/program" ] || { echo "no compiled program for dev" >&2; exit 97; }', script)
        self.assertLess(script.index('[ -x'), script.index('; "$ESPHOME_DATA_DIR/build/dev/.pioenvs/dev/program";'))

    def test_program_exit_still_gives_8_and_no_bmp_gives_9(self):
        code, _ = run_main(self, [MANIFEST_ARG], {}, Fake(self, run_rc=1))
        self.assertEqual(code, tool.EXIT_RUN)
        code, text = run_main(self, [MANIFEST_ARG], {}, Fake(self, bmps=[]))
        self.assertEqual(code, tool.EXIT_MISSING_IMAGE)
        self.assertIn('heating, idle', text)

    def test_missing_program_names_the_manifest_name(self):
        code, text = run_main(self, [MANIFEST_ARG], {}, Fake(self, run_rc=tool.EXIT_NO_PROGRAM_IN_CONTAINER))
        self.assertEqual(code, tool.EXIT_RUN)
        self.assertIn("no compiled program for 'dev'", text)
        self.assertIn('esphome name', text)

    def test_image_missing_after_build_points_at_builder(self):
        code, text = run_main(self, [MANIFEST_ARG], {}, Fake(self, image_ok=False))
        self.assertEqual(code, tool.EXIT_BUILD)
        self.assertIn('buildx', text)

    def test_unexpected_oserror_exits_1_with_footer(self):
        class Boom(Fake):
            def __call__(self, args, **kw):
                if self.sub(args)[0] == 'build':
                    raise OSError(5, 'Input/output error', '/secret/path')
                return Fake.__call__(self, args, **kw)
        code, text = run_main(self, [MANIFEST_ARG], {}, Boom(self))
        self.assertEqual(code, tool.EXIT_OTHER)
        self.assertIn('Input/output error', text)
        self.assertNotIn('/secret/path', text)
        self.assertRegex(text.splitlines()[-1], r'exited 1 after')

    def test_undecodable_requirements_is_a_named_failure(self):
        with open(os.path.join(self.root, 'requirements.txt'), 'wb') as handle:
            handle.write(b'\xff\xfe\x00bad')
        code, text = run_main(self, [MANIFEST_ARG, '--check-only'], {}, Fake(self))
        self.assertEqual(code, tool.EXIT_INVALID)
        self.assertIn('cannot read requirements.txt', text)

    def test_manifest_read_error_does_not_repeat_path(self):
        os.remove(os.path.join(self.root, 'preview', 'preview.json'))
        code, text = run_main(self, [MANIFEST_ARG, '--check-only'], {}, Fake(self))
        self.assertEqual(code, tool.EXIT_INVALID)
        self.assertNotIn('preview.json', text.split('cannot read the manifest')[1].splitlines()[0])

    def test_save_failure_leaves_no_partial_set(self):
        out = os.path.join(self.root, 'o')
        report = tool.Report(io.StringIO(), {}, False)
        preview = tool.Preview(None, {}, None, report, self.root)
        with self.assertRaises(tool.Fail) as caught:
            preview.save({'ok': b'x', 'sub/bad': b'y'}, out)
        self.assertEqual(caught.exception.code, tool.EXIT_OTHER)
        self.assertEqual(os.listdir(out), [])

    def test_save_replaces_only_scenario_files(self):
        os.makedirs(os.path.join(self.root, 'captures', 'preview'))
        stale = os.path.join(self.root, 'captures', 'preview', 'removed.png')
        with open(stale, 'wb') as handle:
            handle.write(b'old')
        run_main(self, [MANIFEST_ARG], {}, Fake(self))
        self.assertEqual(sorted(os.listdir(self.out_dir())), ['heating.png', 'idle.png', 'removed.png'])

    def test_rm_timeout_warns(self):
        code, text = run_main(self, [MANIFEST_ARG], {}, Fake(self, rm_timeout=True))
        self.assertIn('did not finish within 60 s', text)

    def test_version_timeout_reports_no_engine(self):
        class Hang(Fake):
            def __call__(self, args, **kw):
                if self.sub(args)[0] == 'version':
                    raise tool.RunTimeout()
                return Fake.__call__(self, args, **kw)
        code, text = run_main(self, [MANIFEST_ARG], {}, Hang(self))
        self.assertEqual(code, tool.EXIT_NO_ENGINE)
        self.assertIn('did not answer', text)

    def test_docker_host_line_for_context_named_default(self):
        env = {'DOCKER_HOST': ENDPOINT}
        for argv, e in (([MANIFEST_ARG, '--context', 'default'], env),
                        ([MANIFEST_ARG], dict(env, ESPHOME_PREVIEW_CONTEXT='default'))):
            _, text = run_main(self, argv, e, Fake(self))
            self.assertIn('DOCKER_HOST                 env      set (endpoint not shown)', text)
            self.assertNotIn('secret-host', text)
        _, text = run_main(self, [MANIFEST_ARG, '--context', 'other'], env, Fake(self))
        self.assertNotIn('DOCKER_HOST', text)

    def test_timeout_validation(self):
        for bad in ('nan', 'inf', '-1', '0', '1e9'):
            with self.assertRaises(SystemExit) as caught:
                run_main(self, [MANIFEST_ARG, '--timeout', bad], {}, Fake(self))
            self.assertEqual(caught.exception.code, 2)


class HelpTests(unittest.TestCase):
    def test_help_does_not_invoke_docker(self):
        def boom(*a, **k):
            raise AssertionError('docker invoked')
        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        try:
            with self.assertRaises(SystemExit) as caught:
                tool.main(['--help'], env={}, runner=boom)
        finally:
            sys.stdout = old
        self.assertEqual(caught.exception.code, 0)
        self.assertIn('usage: esphome-preview MANIFEST', out.getvalue())


if __name__ == '__main__':
    unittest.main()
