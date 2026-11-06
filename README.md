# esphome-common

Shared packages and tooling for the `esphome-*` firmware project family. Sibling projects consume this repository as a git submodule at `common/`, so a fix or new sensor added here is available to each consumer when its pinned `common/` revision is updated. Each consumer's gitlink, not this repository's latest commit, defines the revision it uses.

## What's in here

- `packages/common.yml` — the shared diagnostics package: WiFi signal, uptime, free heap, main loop time, CPU frequency, device info, status binary sensor, firmware version, board name, IP address, reset reason, Home Assistant time, and a restart button.
- `packages/project.yml` — project metadata: define `project_name` in the consuming project; `project_version` defaults to `dev` for direct ESPHome calls.
- `packages/heap-min.yml` — optional minimum free heap since boot, for ESP32 or LibreTiny consumers on ESPHome 2026.2.0 or later.
- `packages/heap-fragmentation.yml` — optional heap fragmentation percentage, for ESP32 or ESP8266 consumers.
- `packages/psram-free.yml` — optional free PSRAM, for ESP32 consumers with a configured `psram` component.
- `bin/esphome` / `bin/esphome.ps1` — wrapper scripts that run ESPHome via `uvx`, pinned to whatever version is in the calling project's `requirements.txt`. No local venv, no activation step, works the same on Windows/macOS/Linux as long as `uv` is installed.
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
memory. It requires `debug` and an ESPHome version supporting `debug.min_free`
(2026.2.0 or later, ESP32 or LibreTiny). It is a separate package so consumers
on other platforms or ESPHome versions can use `packages/common.yml` without it.

Two further optional packages follow the same pattern:

```yaml
packages:
  heap_fragmentation: !include ../common/packages/heap-fragmentation.yml
  psram_free: !include ../common/packages/psram-free.yml
```

`Heap Fragmentation` reports the percentage of free heap that is not part of
the largest free block. It requires `debug` on ESP32 or ESP8266. `PSRAM Free`
reports free external PSRAM in bytes. It requires `debug` and a configured
`psram` component on ESP32; include it only for boards that have PSRAM.

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

Before starting ESPHome, both wrappers check that `requirements.txt` exists in the current directory and that `uvx` is on `PATH`. If either is missing, they stop with a message and exit code 2 or 127 respectively.

They then print a report to stderr, between a `---- esphome wrapper ----` and a `---- esphome ----` line. After ESPHome exits, a closing line gives its exit code and the elapsed time, in red when the code isn't 0:

```text
---- esphome wrapper -----------------------------------------------------------
  project_version             wrapper  2026.11.06
  esphome                     project  2026.10.2
  common                      project  34c2bc4  F:\GIT\esphome\esphome-ble-proxy\common
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
