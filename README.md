# esphome-common

Shared packages and tooling for the `esphome-*` firmware project family. Sibling projects consume this repository as a git submodule at `common/`, so a fix or new sensor added here is available to each consumer when its pinned `common/` revision is updated. Each consumer's gitlink, not this repository's latest commit, defines the revision it uses.

## What's in here

- `packages/common.yml` — the shared diagnostics package: WiFi signal, uptime, free heap, main loop time, CPU frequency, device info, status binary sensor, firmware version, board name, IP address, reset reason, Home Assistant time, and a restart button.
- `packages/project.yml` — project metadata: define `project_name` in the consuming project; `project_version` defaults to `dev` for direct ESPHome calls.
- `packages/heap-min.yml` — optional minimum free heap since boot, for ESP32 or LibreTiny consumers on ESPHome 2026.2.0 or later; requires `common.yml`.
- `packages/heap-fragmentation.yml` — optional heap fragmentation percentage, for ESP32 or ESP8266 consumers; requires `common.yml`.
- `packages/psram-free.yml` — optional free PSRAM, for ESP32 consumers with a configured `psram` component; requires `common.yml`.
- `packages/credentials.yml` — the API and OTA encryption keys, the Wi-Fi network and the fallback hotspot password from `secrets.yaml`, for the entrypoints of a [remote consumer](#remote-consumers).
- `bin/esphome` / `bin/esphome.ps1` — wrapper scripts that run ESPHome via `uvx`, pinned to whatever version is in the calling project's `requirements.txt`. No local venv, no activation step, works the same on Windows/macOS/Linux as long as `uv` is installed.
- `bin/esphome-preview` / `bin/esphome-preview.ps1` — shims for `bin/esphome-preview.py`, a Docker-based preview that renders a project's LVGL display on the `host` platform and saves PNGs (see [Display preview](#display-preview-esphome-preview)); `docker/preview/Dockerfile` is its image.
- `docs/esphome-upgrades/` — one review per ESPHome minor release (breaking changes, C++ API changes, patch fixes), written once and checked against each project when its pin is raised.
- `.claude/skills/esphome-update/` — Claude Code skill that runs the ESPHome update procedure in `AGENTS.md` for a consuming project.

## Memory and network diagnostics

`packages/common.yml` also exposes `Heap Largest Free Block` (bytes),
`Main Loop Time` (longest loop iteration, milliseconds), `CPU Frequency`
(MHz), `Device Info` (chip, framework, and flash summary), `WiFi SSID`
(connected network), `WiFi BSSID` (connected access point), and
`WiFi MAC Address` (device WiFi interface). All are Home Assistant diagnostic
entities. Memory, loop timing, and CPU frequency use the consumer's `debug`
update interval; network identifiers update through the WiFi info component.

To track the minimum free heap since boot, include the optional package from
your application's base package:

```yaml
packages:
  heap_min: !include ../common/packages/heap-min.yml
```

This reports the boot's heap low-water mark, not just the currently free
memory. It requires `common.yml`, `debug` and an ESPHome version supporting `debug.min_free`
(2026.2.0 or later, ESP32 or LibreTiny). It is a separate package so consumers
on other platforms or ESPHome versions can use `packages/common.yml` without it.

Two further optional packages follow the same pattern:

```yaml
packages:
  heap_fragmentation: !include ../common/packages/heap-fragmentation.yml
  psram_free: !include ../common/packages/psram-free.yml
```

`Heap Fragmentation` reports the percentage of free heap that is not part of
the largest free block. It requires `common.yml` and `debug` on ESP32 or ESP8266. `PSRAM Free`
reports free external PSRAM in bytes. It requires `common.yml`, `debug` and a configured
`psram` component on ESP32; include it only for boards that have PSRAM.

## Adapter sub-device

`packages/common.yml` declares the sub-device `adapter_device`. Each entity of
`common.yml`, `heap-min.yml`, `heap-fragmentation.yml` and `psram-free.yml`
sets `device_id: adapter_device` itself, so Home Assistant
lists the ESP's diagnostics apart from the device's own entities. The
sub-device is named by the substitution `adapter_name`, which defaults to
`${friendly_name} Adapter`; the consuming project needs a `friendly_name`
substitution (without one, ESPHome only warns that it could not resolve all
the variables and names the sub-device literally `${friendly_name} Adapter`), and renames the sub-device by setting `adapter_name`. The heap
and PSRAM packages require `common.yml`, which declares the sub-device they
refer to. A consumer cannot move the nested entries (`debug`, `wifi_info`) with
`!extend`, which reaches only top-level list items by id, so the packages
place their own entities.

## Board diagnostic

The `Board` diagnostic text sensor uses the `board_name` substitution. Set it
in each firmware entrypoint to the device variant used in that filename:

```yaml
substitutions:
  board_name: m5stack-atoms3-lite
```

For example, this value identifies `ble-proxy-m5stack-atoms3-lite.yml` instead
of only its generic ESP32 compile target. If not overridden, `board_name`
defaults to the `${board}` substitution. It does not change `esp32.board` or
any hardware settings.

## Project structure

A firmware project that uses this repository has this layout:

```text
<repository>/
  <device>-<board-variant>.yml   firmware entrypoints; root only
  boards/<board-variant>.yml     hardware for one board variant
  packages/base.yml              device identity, shared includes, API/OTA/WiFi
  packages/board.yml             optional esp32 block built from board substitutions
  packages/<feature>.yml         application behavior
  common/                        this repository, as a pinned submodule
  requirements.txt               esphome==X.Y.Z
  secrets.yaml.example           secret key names; secrets.yaml is ignored
```

Each entrypoint sets its `board_name` and includes the base and board packages:

```yaml
substitutions:
  board_name: m5stack-atoms3-lite

packages:
  base: !include packages/base.yml
  device_base: !include boards/m5stack-atoms3-lite.yml
```

`packages/base.yml` defines the device identity and includes the shared packages:

```yaml
substitutions:
  friendly_name: Bluetooth Proxy
  device_name: ble-proxy
  device_description: BLE Proxy
  project_name: peeter123.esphome-ble-proxy

packages:
  common: !include ../common/packages/common.yml
  heap_min: !include ../common/packages/heap-min.yml
  project: !include ../common/packages/project.yml
  board: !include board.yml
  ble: !include ble.yml
```

## Remote consumers

A project whose packages should also work from the ESPHome dashboard without cloning, as remote (`github://` or `url:`) packages, takes the shared packages from GitHub instead of from `common/`. ESPHome fetches a remote package as a shallow clone without submodules, so `common/` is empty there. Its `packages/base.yml` pins this repository to the commit of the `common` gitlink, as a full SHA:

```yaml
packages:
  common:
    url: https://github.com/peeter123/esphome-common
    ref: bcb7f07b707779f3875f7d9def22d11856e7b32e   # the commit of the common gitlink
    refresh: never
    files:
      - packages/common.yml
      - packages/project.yml
      - packages/heap-min.yml
      - packages/heap-fragmentation.yml
```

Keep the `ref:` line directly after the `url:` line: both wrappers read the entry line by line and stop with exit code 2 when the ref is not the full commit of the project's `common/` checkout. The base package reads no secret: it declares `api:`, an `ota:` list with one `- platform: esphome` entry with `id: ota_esphome`, and `wifi:` with `id: wifi_id` and `ap: {}`. Each local entrypoint adds the credentials:

```yaml
packages:
  base: !include packages/base.yml
  credentials: !include common/packages/credentials.yml
  device_base: !include boards/m5stack-atoms3-lite.yml
```

A dashboard configuration that takes the project's packages remotely supplies its own API key and Wi-Fi credentials instead. Packages refer to the project's own components by a path relative to the package file (`source: ../../components` from `packages/<group>/`), which ESPHome 2026.9 and later resolve from the same checkout as the YAML, locally and in a remote clone.

This repository's `master` is never rewritten, because remote consumers pin its commits. To update a remote consumer, push the commit here first, then move its gitlink and its `ref:` together. See "Remote consumers" in `AGENTS.md` for the full rules.

## Usage (from a consuming project)

Run these from the project root (the directory containing that project's `requirements.txt` and `.yml` config), not from inside `common/`:

```sh
common/bin/esphome compile <project>.yml
common/bin/esphome run <project>.yml
common/bin/esphome run <project>.yml --device <ip-or-hostname>
common/bin/esphome logs <project>.yml
```

On Windows PowerShell, use `common/bin/esphome.ps1` instead. The ESPHome version used is always whatever `esphome==x.y.z` is pinned in the project's own `requirements.txt` — bump that file to change versions, there's nothing to configure here.

## Shared compiler cache

Both wrappers default `CCACHE_DIR` to `.ccache` in the current user's home directory (`~\.ccache` on Windows, `~/.ccache` on Linux/macOS), sharing cached compiler output across projects outside their build directories. An existing `CCACHE_DIR` environment variable overrides this default. Git Bash converts its default to a native Windows path for the Windows compiler tools.

ESPHome's native toolchain automatically uses a working `ccache` executable on `PATH`; the wrappers do not install it or force caching when it is unavailable. This cache does not replace incremental builds, and linking is not cached.

To inspect the shared cache in PowerShell:

```powershell
$env:CCACHE_DIR = Join-Path $HOME '.ccache'
ccache --show-stats
```

## Cache locations and Windows Defender

Builds read and write three caches outside the project. Each can be moved with an environment variable:

| Variable | Default (Windows) | Contents |
|---|---|---|
| `ESPHOME_ESP_IDF_PREFIX` | `%LOCALAPPDATA%\esphome\Cache\idf` | ESP-IDF frameworks, toolchains (`xtensa-esp-elf`, `riscv32-esp`), cmake/ninja, and the IDF Python environments (`penvs`) |
| `CCACHE_DIR` | `~\.ccache` (set by the wrappers) | compiler cache; without the wrappers ESPHome uses `<idf prefix>\ccache` |
| `UV_CACHE_DIR` | `%LOCALAPPDATA%\uv\cache` | the ESPHome installation that `uvx` runs, and its dependencies |

ESPHome 2026.x builds ESP32 targets with native ESP-IDF instead of PlatformIO, so the toolchain no longer lives in `~\.platformio`. The IDF location comes from `esphome/build_helpers/tools_cache.py`: `ESPHOME_ESP_IDF_PREFIX` when set, otherwise `platformdirs.user_cache_dir("esphome")\idf`. `ESPHOME_SDK_NRF_PREFIX` and `ESPHOME_ARDUINO8266_PREFIX` do the same for nRF52 and ESP8266. Set the variables as user environment variables so builds started from an IDE see them too, then restart the IDE (and JetBrains Toolbox, if it launches the IDE) to pick them up.

Windows Defender real-time protection scans every compiler executable, header, and `.py`/`.pyc` file that a build opens. Excluding the project folder does not cover these caches. In a recorded build, most scan time went to `python.exe` and `uv.exe` reading the IDF Python environment and the uv cache, followed by IDF's `cmake.exe` and the `cc1`/`cc1plus` compilers. With all three caches under one folder, one exclusion covers them:

```powershell
[Environment]::SetEnvironmentVariable('ESPHOME_ESP_IDF_PREFIX', 'F:\cache\esphome-idf', 'User')
[Environment]::SetEnvironmentVariable('CCACHE_DIR', 'F:\cache\ccache', 'User')
[Environment]::SetEnvironmentVariable('UV_CACHE_DIR', 'F:\cache\uv', 'User')
# from an elevated terminal:
Add-MpPreference -ExclusionPath 'F:\cache'
```

The compiler's own temporary files need one more step. Without `-save-temps`, `cc1` writes each translation unit's assembly to a `cc*.s` file in the temporary directory. That directory isn't excluded, so Defender scans every one; in the recorded build this was 1,376 scans and 16.5 s, after the caches were already excluded. The native Windows toolchain picks the directory with `GetTempPath`, which reads `TMP`, then `TEMP`, and ignores `TMPDIR`. GCC on Linux/macOS reads `TMPDIR`. Both wrappers therefore point `TMPDIR`, and on Windows also `TMP` and `TEMP`, at `.esphome/tmp` in the project root, for the ESPHome process and its children. That folder is ignored by git and lies inside the project, so a project-folder exclusion covers it. The wrappers override existing values because Cygwin login shells, such as the IDE run configurations, already set these variables to their own temporary directories. Python's `tempfile` reads the same variables, so ESPHome's own temporary files land there too.

Keep the IDF prefix short: toolchain paths nest about 245 characters below it, past Windows' 260-character limit unless long path support (`LongPathsEnabled`) is on. Keep the cache folder out of synced or backed-up project folders. Don't copy an old cache to the new location, because the IDF Python environments contain absolute paths; let the next build download again, then delete the old folders. To undo, set each variable to `$null` and remove the exclusion with `Remove-MpPreference -ExclusionPath`.

## Wrapper help, checks, and report

`common/bin/esphome --help` (or `esphome.ps1 --help`) prints the wrapper's own help, followed by ESPHome's. Running a wrapper without arguments does the same. Help for a subcommand, such as `compile --help`, goes straight to ESPHome.

Before starting ESPHome, both wrappers check that `requirements.txt` exists in the current directory and that `uvx` is on `PATH`. If either is missing, they stop with a message and exit code 2 or 127 respectively. In a [remote consumer](#remote-consumers), they also compare each esphome-common remote package entry in the project's root YAML files and `packages/` with the commit of the project's `common/` checkout, or of their own checkout when the project has none. An entry with another commit, an abbreviated SHA or no `ref:` line right after its `url:` line stops them with a message and exit code 2.

They then print a report to stderr, between a `---- esphome wrapper ----` and a `---- esphome ----` line. After ESPHome exits, a closing line gives its exit code and the elapsed time, in red when the code isn't 0:

```text
---- esphome wrapper -----------------------------------------------------------
  project_version             wrapper  2026.11.06
  esphome                     project  2026.10.2
  common                      project  34c2bc4  F:\GIT\esphome\esphome-ble-proxy\common
  UV_PYTHON                   project  <3.15,>=3.12.0
  python                      found    3.14.8  C:\Users\<user>\AppData\Roaming\uv\python\cpython-3.14-windows-x86_64-none\python.exe
  ccache                      found    4.14.2  C:\ProgramData\chocolatey\bin\ccache.exe
  CCACHE_DIR                  env      F:\CACHE\ccache
  TMPDIR                      wrapper  F:\GIT\esphome\esphome-ble-proxy\.esphome\tmp
  ...
  ESPHOME_ESP_IDF_PREFIX      env      F:\CACHE\esphome-idf
  LongPathsEnabled            system   1
  ESPHOME_SDK_NRF_PREFIX      default  C:\Users\<user>\AppData\Local\esphome\Cache\sdk-nrf
---- esphome -------------------------------------------------------------------
...
---- esphome exited 0 after 3m 12s ---------------------------------------------
```

The report contains:

- `esphome`: the `esphome==X.Y.Z` pin from `requirements.txt`. Without a pin, the wrappers warn that `uvx` will install the latest release.
- `common`: the revision of the common checkout the wrapper runs from (`git describe --always --dirty`), and its path. This tells a project's pinned submodule apart from a separate clone of this repository.
- `common ref` (remote consumers only): the commit of the esphome-common remote package entry, which the check above found equal to the `common/` checkout, and the file that holds it.
- `UV_PYTHON`: the Python request passed to `uvx`: the pinned release's `requires-python`, or `UV_PYTHON` when set; see [Python version](#python-version).
- `python`: the version and path of the installed interpreter uv selects for that request (`uv python find`), which ESPHome and its ESP-IDF Python environment run on. When no installed Python matches, it reads `no match installed` and uv downloads one.
- `ccache`: the version and path of the `ccache` on `PATH`. ESPHome caches compiler output only when it finds one, so the wrappers warn when it's missing.
- `LongPathsEnabled` (Windows only): the system setting, after the effective IDF prefix. When it is off and the prefix plus the roughly 245 characters of toolchain paths below it exceed 260 characters, the wrappers warn and give the longest safe prefix length.
- `CCACHE_DIR`, `TMPDIR`, `TMP`, `TEMP` (Windows only in the Bash wrapper), `UV_CACHE_DIR`, `ESPHOME_ESP_IDF_PREFIX`, `ESPHOME_SDK_NRF_PREFIX`, and `ESPHOME_ARDUINO8266_PREFIX`.

The second column gives the source of each value, or the result of a check:

- `env` (green): set in the caller's environment.
- `wrapper` (cyan): set by the wrapper.
- `config` (yellow): `cache-dir` from a uv configuration file (`uv.toml` or `pyproject.toml`); applies to `UV_CACHE_DIR` only.
- `default` (dim): unset. The value shown is the location ESPHome or uv uses instead.
- `project` and `system`: read from the project, the common checkout, or Windows.
- `found` (green) and `missing` (red): tool checks. A warning line starting with `!` follows a problem.

The ESPHome defaults follow `platformdirs.user_cache_dir("esphome", appauthor=False)`:

- Windows: `%LOCALAPPDATA%\esphome\Cache`
- macOS: `~/Library/Caches/esphome`
- Linux: `$XDG_CACHE_HOME/esphome` or `~/.cache/esphome`

For the uv cache, the wrappers run `uv cache dir` from the project root, the same directory `uvx` runs from. The result reflects `UV_CACHE_DIR`, then `cache-dir` in a discovered uv configuration file, then uv's default: `%LOCALAPPDATA%\uv\cache` on Windows, and `$XDG_CACHE_HOME/uv` or `~/.cache/uv` elsewhere. When `uv` isn't on `PATH`, the wrappers show that default instead.

Colour is used when stderr is a terminal. Set `FORCE_COLOR=1` to colour redirected output, such as the IDE run console, or set `NO_COLOR` to disable colour. Stdout is unchanged, so redirected `config` output contains only ESPHome's output.

To print the closing line, the Bash wrapper runs ESPHome as a child process instead of replacing itself with `exec`. Ctrl+C reaches ESPHome through the terminal's process group as before, and the wrapper waits for ESPHome to exit before reporting. A signal sent only to the wrapper's own process ID, such as `kill <pid>`, no longer reaches ESPHome. If the PowerShell wrapper is interrupted, its closing line reads `esphome interrupted`.

## Python version

`uvx` runs ESPHome on the newest Python that uv finds, because uv ignores the upper bound of a package's `requires-python` and tool runs ignore `.python-version` files. ESPHome then creates the ESP-IDF Python environment from that same interpreter. When that Python is newer than the release supports, the first build fails while installing ESP-IDF's dependencies. For example, on Python 3.15, ESP-IDF 5.5's `esp-idf-kconfig` needs `windows-curses`, which has no 3.15 wheels.

Both wrappers therefore pass the pinned release's own `requires-python` (for example `<3.15,>=3.12.0` for 2026.10.2) to `uvx --python`. uv picks the newest installed Python within that range, and downloads one when none matches. The wrappers read the range from PyPI (`https://pypi.org/pypi/esphome/<version>/json`) and cache it in `.esphome/requires-python`, so PyPI is asked only when the pin changes, and later runs work offline.

- Set `UV_PYTHON` to choose a version yourself, such as `UV_PYTHON=3.13`. The report then shows it with the `env` tag.
- When the range can't be read (offline before the first run of a pin, or `curl` missing for the Bash wrapper), the report shows `UV_PYTHON  missing  unknown` with a warning, and uv picks the Python.
- A failed ESP-IDF Python environment is rebuilt on the next build, because ESPHome records the Python version it was built with.

## Process priority

Both wrappers run ESPHome below normal priority, so a build that saturates every core leaves the desktop responsive; on an otherwise idle machine it takes about as long. The PowerShell wrapper sets its own process to `BelowNormal` and restores the previous priority when ESPHome exits, because `& .\common\bin\esphome.ps1` runs inside the calling shell. Windows child processes inherit `BelowNormal`, so `uvx`, Python, ninja, and the compilers all run at that priority. A PowerShell caller already at `Idle` or `BelowNormal` keeps that priority. The Bash wrapper uses `nice -n 10`, which adds to the caller's niceness; on Windows, Cygwin and Git Bash map it to `BelowNormal`.

## Firmware project version

Both wrappers supply `-s project_version YYYY.MM.DD` using the current local date. This is independent of the ESPHome version pinned in `requirements.txt`. Other CLI arguments are forwarded unchanged. ESPHome applies the last value given for a substitution key, so an explicit `-s project_version <version>` before the command overrides the generated date.

Include the project package from your application's base package:

```yaml
packages:
  project: !include ../common/packages/project.yml
```

Define the project name as `<owner>.<repository-name>` in your application's `packages/base.yml` substitutions.
Keep the variant-specific `board_name` in each firmware entrypoint:

```yaml
substitutions:
  project_name: peeter123.esphome-ble-proxy
```

`packages/project.yml` is the only `esphome.project` definition; a project must not define its own. Without the wrapper, `project_version` defaults to `dev`; an explicit CLI substitution or top-level `project_version` can set a different value. Command-line substitutions take precedence over YAML values.

For example, on Windows:

```powershell
.\common\bin\esphome.ps1 compile device.yml
.\common\bin\esphome.ps1 -s project_version 2026.10.06.1 compile device.yml
```

Projects that do not include `packages/project.yml` keep their own metadata. Any of them that reference `${project_version}` also receive the wrapper's date substitution.

## Display preview (`esphome-preview`)

`bin/esphome-preview` (POSIX shells) and `bin/esphome-preview.ps1` (PowerShell) run `bin/esphome-preview.py`, a standard-library Python tool that renders a project's LVGL display on the `host` platform inside a Linux Docker container and saves one PNG per scenario. It needs no ESP32 and no native compiler on the PC. The shims pass their arguments and the tool's exit code through unchanged, and name a missing Python; the tool names a missing Docker CLI.

### Prerequisites

- Python 3.8 or later on `PATH`.
- The Docker CLI and a **Linux** Docker engine: either the local Docker Desktop engine with the WSL 2 backend, or a server or VM reached through a Docker context. A Windows-container engine is refused.
- Network access for the engine, which downloads the base image, the Debian packages, ESPHome and PlatformIO's LVGL library. The program itself runs with `--network none`.

### Using a server or VM: an SSH Docker context

The tool names no host. A remote engine lives only in your Docker context:

1. Set up key-based SSH from the PC to the server (`ssh <user>@<server>` works without a password prompt).
2. Add the remote user to the `docker` group on the server.
3. Accept the server's host key once by hand: run `ssh <user>@<server>` and answer `yes`.
4. Create the context: `docker context create <name> --docker "host=ssh://<user>@<server>"`. An alias from `~/.ssh/config` can replace `<user>@<server>`.
5. Check it: `docker --context <name> version`.

Choose it for a run with `--context <name>` or `ESPHOME_PREVIEW_CONTEXT=<name>`. The name is passed as `docker --context <name>` to every call the tool makes, so `docker context use` and other Docker commands keep their own current context. On Windows, a user environment variable (`setx ESPHOME_PREVIEW_CONTEXT <name>` or System Properties) reaches only processes started after it is set: restart the terminal and the IDE. Without either, Docker's own resolution applies (`DOCKER_HOST`, `DOCKER_CONTEXT`, then the current context).

The Docker CLI is `--docker PATH`, else `ESPHOME_PREVIEW_DOCKER`, else `docker` on `PATH`; use it when the CLI is not on `PATH`.

### Usage

Run from the project root:

```text
esphome-preview MANIFEST [--context NAME] [--docker PATH] [--out DIR] [--timeout SECONDS] [--check-only]
```

```powershell
common\bin\esphome-preview.ps1 preview\preview.json
common/bin/esphome-preview preview/preview.json --context <name> --out captures/preview
```

- `MANIFEST`: the manifest JSON, for example `preview/preview.json`.
- `--out DIR`: where the PNGs go (default `captures/preview/` in the project root, which should be git-ignored). Nothing is written there unless every scenario image arrived and converted (a write error while replacing files can leave some of them updated).
- `--timeout SECONDS`: limit for the preview program, above 0 and at most 1000000 (default 180). On timeout the container is removed, nothing is saved, and the exit code is 7.
- `--check-only`: validates the manifest, the `requirements.txt` pin and the input list, and never invokes Docker.

Steps: read the manifest and the `esphome==X` pin from `requirements.txt`; refuse denied inputs; check that the engine answers and is Linux; build the image `esphome-preview:<pin>` from a temporary context holding only the Dockerfile (`docker/preview/Dockerfile`) and a `requirements.txt` the tool generates with the single line `esphome==<pin>` (the project's own `requirements.txt` is read for the pin and never sent); compile with `esphome compile <root>` in a container whose cache is the named volume `esphome-preview-<pin>`, with the manifest's inputs copied in using `docker cp` (no bind mounts, so a remote engine works); run the compiled program in a second container with `--network none`, after clearing its snapshot directory; copy the BMPs out, convert them to 24-bit PNGs and move them to `--out`. What reaches the engine is exactly: the manifest's inputs, the Dockerfile and that generated one-line `requirements.txt`. Containers are removed on every path; the image and the volume stay as the build cache, so later runs only recompile what changed. Remove them with `docker image rm` and `docker volume rm` on the same engine.

The image and the volume are shared per ESPHome pin by every project that uses the engine. Run previews on one engine one after another: concurrent runs of projects with the same device `name` share a snapshot directory in the volume and can overwrite each other's images. Each scenario's PNG replaces its earlier file in `--out`; other files there, such as the PNGs of removed scenarios, are left alone and are not deleted.

The image is built with the engine's builder. A non-default `docker buildx` builder (for example one with the `docker-container` driver) may leave the image in its own cache instead of loading it into the engine; the tool then stops with a message pointing at the builder (exit 5). Select the default builder with `docker buildx use default` and retry.

Exit codes: 0 success; 1 other Docker or file error; 2 invalid manifest, pin or input, or bad usage; 3 no engine reachable; 4 engine is not Linux; 5 image build failed; 6 compile failed; 7 timeout; 8 program failed; 9 scenario image missing or invalid; 127 Docker CLI or Python missing; 130 interrupted.

### Manifest

```json
{
  "root": "preview/display-preview.yml",
  "name": "my-device-preview",
  "inputs": ["preview/display-preview.yml", "preview/preview_clock.h", "packages/display.yml"],
  "scenarios": ["heating", "idle"]
}
```

- `root`: the ESPHome root file, relative to the project root, with forward slashes. It must be one of `inputs`.
- `name`: the `esphome: name:` of that root. It names the build and snapshot directories, and may use letters, digits, `-` and `_`.
- `inputs`: every file the compile needs, as relative paths to files inside the project. Only these project files are sent to the engine. The tool refuses, even when declared, paths outside the project root, `secrets.yaml` anywhere, and anything under `.git/`, `.esphome/` or `captures/`.
- `scenarios`: the `filename:` of each `snapshot.take` in the root, without `.bmp`. Each needs a BMP after the run and becomes `<scenario>.png`.

By convention a project keeps the preview root, its helper headers and the manifest in a `preview/` directory, not at the repository root, which stays reserved for firmware entrypoints. The root builds for the `host` platform with a `snapshot` display (`id: disp`) and ends the program itself after the last `snapshot.take` (for example with `std::raise(SIGTERM)` in a lambda); the tool does not keep it alive or stop it.

### Startup report

Before contacting any engine the tool prints a report to stderr in the style of [the ESPHome wrappers](#wrapper-help-checks-and-report): a `---- esphome-preview ----` line, one line per setting with its name, source and value, then a closing line with the exit code and elapsed time (red when not 0). Colour follows the same rules: a terminal, `FORCE_COLOR`, `NO_COLOR`.

```text
---- esphome-preview -----------------------------------------------------------
  manifest                    project  preview/preview.json
  esphome                     project  2026.9.1
  common                      project  <describe>  <path of the common checkout>
  inputs                      project  4 files
  ESPHOME_PREVIEW_DOCKER      default  docker on PATH
  docker                      found    24.0.6  <path of the CLI>
  ESPHOME_PREVIEW_CONTEXT     default  <name Docker resolves>
  engine                      found    linux/amd64  24.0.6
  image                       wrapper  esphome-preview:2026.9.1
  volume                      wrapper  esphome-preview-2026.9.1
  out                         default  captures/preview
  timeout                     default  180 s
---- esphome-preview build -----------------------------------------------------
...
---- esphome-preview exited 0 after 1m 12s -------------------------------------
```

Source tags: `option` (command line), `env` (environment variable), `wrapper` (chosen by the tool), `default` (not set; the value shown applies), `project` (read from the project or the common checkout), and the checks `found`, `missing` and `skipped` (the engine and CLI lines under `--check-only`; a `!` warning line follows a problem). With the default context, the line shows the name from `docker context show`, and `DOCKER_CONTEXT` and `DOCKER_HOST` get lines of their own when set, `DOCKER_HOST` only as `set (endpoint not shown)`. The tool's own report and messages never contain an endpoint URL, user or host name. Errors that the Docker CLI or `ssh` print themselves, for example when a context cannot connect, pass through unchanged and may name the host. `DOCKER_HOST` is shown whenever the effective context is `default`, including when `default` is named with `--context` or `ESPHOME_PREVIEW_CONTEXT`.

### Fidelity limits

The preview draws LVGL at 16-bit depth through ESPHome's `snapshot` display with the same LVGL release and built-in fonts as the firmware. It does not model the panel: colour inversion, BGR order, gamma, the offsets of the visible window and the backlight are not applied, so colours and edges on the real screen can differ. The `snapshot` display reports no hardware rotation, so LVGL rotates in software; a device whose display driver reports hardware rotation (for example `mipi_spi`) rotates in the panel instead, so rotated images show the layout only and nothing about the panel's own addressing, pads or offsets is reproduced. Treat the images as layout and text checks, not colour references.

## Adding or migrating a project

1. From the project root, add this repository as the `common` submodule from its published URL:
   ```sh
   git submodule add https://github.com/peeter123/esphome-common.git common
   ```
   To develop against a local clone of this repository instead, point the project's own `.git/config` at it with `git config submodule.common.url <path-to-esphome-common>`, keep the published URL in `.gitmodules`, and do not run `git submodule sync`, which overwrites the local setting. Git blocks local-path submodule transports unless allowed, so prefix the submodule commands with `git -c protocol.file.allow=always`.
2. Pin ESPHome in `requirements.txt` (`esphome==X.Y.Z`).
3. In `packages/base.yml`, define `friendly_name`, `device_name`, `device_description`, and `project_name`, and include the shared packages:
   ```yaml
   packages:
     common: !include ../common/packages/common.yml
     heap_min: !include ../common/packages/heap-min.yml
     project: !include ../common/packages/project.yml
   ```
   Omit `heap_min` only for platforms or ESPHome versions that do not support it, and document the exclusion. Add `heap_fragmentation` on ESP32 or ESP8266, and `psram_free` on boards with PSRAM.
4. Delete the project's local `packages/common.yml` and any local `esphome.project` block, after checking for duplicate entities or IDs.
5. Set `board_name` in every firmware entrypoint.
6. Delete `Makefile`, `shell.bat`, and any GitHub Actions workflows under `.github/workflows/` that are not in use; `common/bin/esphome` is the build entrypoint. Remove `.venv` from `.gitignore` when no `.venv` directory exists.
7. In the project's `README.md`, document setup with `git submodule update --init --recursive` and point build instructions at this README instead of duplicating them.
8. Validate every entrypoint with `common/bin/esphome config <entrypoint>`.

## Adding something new to this shared repo

Keep it to things that are genuinely identical across projects (not just similarly named). For example, `boards/*.yml` files share a filename convention but differ in actual content per project (different displays, sensors, wiring) — those are *not* candidates for this repo.
