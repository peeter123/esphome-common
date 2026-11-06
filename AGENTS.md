# Shared ESPHome guidance

## Repository boundaries

This repository owns shared packages and tooling, not firmware for a device.
Read `README.md` before changing it. Each consuming firmware project is a
separate repository whose root `AGENTS.md` supplies its specific commands,
hardware, and constraints; a workspace that groups several projects may add
its own `AGENTS.md` above them. Projects that do not use this repository only
take the general safety and change-preservation rules here.

Consumers use this repository as a `common/` submodule pinned by gitlink;
other projects use local packages and Makefiles. Check each project's
`.gitmodules`, `packages/base.yml`, and tooling rather than assuming it uses
these wrappers. A consumer's pinned `common/` is not interchangeable with a
separate, writable clone of this repository, which may be newer. When a
requested change here is meant to be consumed by a firmware project, update
that project's pinned `common/` to the intended commit as part of the work
unless the user asks not to. Do not stop after changing only this repository
when the consumer is expected to use the new behavior immediately.

Check status in both the parent repository and any submodule being edited.
Preserve existing work, including staged additions/deletions and untracked
protocol captures. Do not commit, push, advance gitlinks, or fetch latest shared
code as part of builds without authorization.

## Standard firmware repository structure

A firmware repository that uses common has this layout:

```text
<repository>/
  <device>-<board-variant>.yml   firmware entrypoints; root only
  boards/<board-variant>.yml     hardware for one board variant
  packages/base.yml              device identity, shared includes, API/OTA/WiFi
  packages/board.yml             optional esp32 block built from board substitutions
  packages/<feature>.yml         application behavior
  common/                        esphome-common submodule, pinned by gitlink
  requirements.txt               esphome==X.Y.Z
  secrets.yaml.example           secret key names; secrets.yaml is ignored
  .gitignore                     .esphome, secrets.yaml, editor folders
  AGENTS.md, README.md, LICENSE, docs/, static/
```

- Entrypoints set only `substitutions.board_name` and their packages:
  `base: !include packages/base.yml`, `device_base: !include
  boards/<board-variant>.yml`, and any variant-only packages. Package YAML and
  board YAML are never firmware entrypoints.
- `boards/<board-variant>.yml` owns pins, board entities, and either the
  `board`, `variant`, and `flash_size` substitutions consumed by
  `packages/board.yml` or a direct `esp32:` block.
- `packages/base.yml` defines the `friendly_name`, `device_name`,
  `device_description`, and `project_name` substitutions. It includes
  `../common/packages/common.yml` exactly once, `../common/packages/project.yml`,
  `../common/packages/heap-min.yml`, `heap-fragmentation.yml`, and
  `psram-free.yml` where supported, and the application packages. It also
  defines `esphome` name/friendly name/comment, `debug`, `logger`, `api` and
  `ota` encryption with `!secret api_encryption_key`, and `wifi` with
  `id: wifi_id`.
- `project_name` is `<owner>.<repository-name>`, where the owner is the
  repository's GitHub user or organisation, for example
  `peeter123.esphome-ble-proxy`. `esphome.project` is defined only by
  `common/packages/project.yml`.
- `board_name` names the device variant in the entrypoint's filename, not the
  generic ESP32 compile target. Main-configuration substitutions override the
  `${board}` default in `common.yml`.

Individual projects deviate where their hardware or upstream origin requires it.
Read the project's actual files before applying this layout to them.

## Project version

- `packages/project.yml` sets `esphome.project.version` to `${project_version}`,
  which defaults to `dev`.
- The wrappers pass `-s project_version YYYY.MM.DD` with the current local date.
  Command-line substitutions take precedence over YAML substitutions.
- An explicit `-s project_version <version>` before the command overrides the
  wrapper's date, because ESPHome applies the last value given for a key.
- The firmware project version is independent of the ESPHome version pinned in
  `requirements.txt`.

## Packages and tooling

- `packages/common.yml`: diagnostics (including heap, main loop time, CPU
  frequency, device info, and reset reason), status, version, board, IP
  address, WiFi, Home Assistant time, and restart button. It requires the relevant
  logger/debug/network/time configuration in consumers; inspect their actual
  composition.
- `packages/heap-min.yml`: minimum free heap since boot. Requires `debug`,
  ESP32 or LibreTiny, and ESPHome 2026.2.0 or later.
- `packages/heap-fragmentation.yml`: heap fragmentation percentage. Requires
  `debug` and ESP32 or ESP8266.
- `packages/psram-free.yml`: free PSRAM. Requires `debug`, ESP32, and a
  configured `psram` component; include it only for boards with PSRAM.
- `packages/project.yml`: project metadata; consumers supply `project_name`.
- `bin/esphome` (POSIX shells) and `bin/esphome.ps1` (PowerShell): run ESPHome
  through `uvx` using the consuming project's `requirements.txt`. Run from that
  project's root.

The wrappers inject the date-based project version and default `CCACHE_DIR`
to `.ccache` in the user's home directory. A consumer's pinned wrapper matches
its pinned common revision; read the checked-out wrapper rather than assuming
it matches the latest version of this repository.

Keep each project's exact ESPHome pin and external dependencies unchanged unless
the task specifically requires an update. Do not align all versions implicitly.
Raise a pin only by following "Updating ESPHome" below.

Preserve argument forwarding and nonzero exit codes when changing tooling.
Missing tools or mismatched environments must be reported, not hidden behind
global ESPHome fallbacks.

Only genuinely equivalent behavior belongs in common. Similar filenames do not
make wiring, boards, sleep policy, protocol control, API/OTA settings, or display
configuration interchangeable. Review entity IDs, defaults, dependencies, and
compatibility before changing a shared package; check affected consumer variants.

## Updating ESPHome

Follow these steps when asked to update a project to the latest (or a named)
ESPHome release. The `esphome-update` skill in `.claude/skills/` runs them.

1. Check Git status in the project and its `common/`; preserve existing work.
2. Find the target: the newest stable version on PyPI
   (`https://pypi.org/pypi/esphome/json`, `info.version`). Skip `bN` betas
   unless the user names one.
3. Read `docs/esphome-upgrades/<YYYY.MM>.md` for every minor release between
   the old and new pin, from the newest esphome-common available: a separate
   clone, the submodule's upstream (`git -C common fetch`, then
   `git -C common show origin/HEAD:docs/esphome-upgrades/<YYYY.MM>.md`, which
   leaves the gitlink alone), or the pinned `common/`. When a file is missing
   or does not cover the target patch release, review that release once and
   write or extend the file in a writable esphome-common clone (see
   `docs/esphome-upgrades/README.md`) before touching the project; never edit
   the pinned `common/`. Do not rely on memory of earlier releases.
4. Check every listed breaking change, C++ API change, and behaviour change
   against the project's entrypoints, `boards`, `packages`, lambdas, and local
   components. Record per-project findings only in the commit message, not in
   the shared review.
5. Change `requirements.txt` and the pin stated in the project's `AGENTS.md`
   (and README, if it states one). Leave the `common` gitlink alone unless the
   update needs a newer common revision.
6. Confirm the wrapper resolves the new version with
   `uvx --with-requirements requirements.txt esphome version`, then run
   `config` on every entrypoint (including `.dashboard.yml` variants) with
   stdout suppressed and exit codes checked. Dashboard variants that import
   components from GitHub validate only after the matching component changes
   are pushed. Report warnings, and say whether each was already present
   before the update.
7. State that `config` does not compile lambdas, and leave compiling to the
   user unless they approve it.
8. Commit only when asked. The commit is titled `Update ESPHome to X.Y.Z` and
   names the reviewed releases, the changes that applied, and the validation.

## Adding or migrating a project

Apply these steps when adding a firmware project or moving an existing one
onto common. When only updating a consumer's common revision, apply steps 4,
5, 7, and 8.

1. Check Git status and preserve staged, unstaged, and untracked work.
2. From the project root, add the submodule from this repository's published
   URL: `git submodule add <esphome-common-url> common`, then check out the
   intended common commit in `common/`. To develop against a local clone
   instead, point `submodule.common.url` in the project's `.git/config` at
   that clone, keep the published URL in `.gitmodules`, and do not run
   `git submodule sync`, which overwrites the local setting. Git blocks
   local-path submodule transports unless allowed, so prefix those commands
   with `git -c protocol.file.allow=always`.
3. Keep `requirements.txt` as the single ESPHome pin (`esphome==X.Y.Z`). Raise
   it only when requested, following "Updating ESPHome".
4. In `packages/base.yml`, define the four substitutions above and include
   `common.yml`, `project.yml`, and `heap-min.yml` from `../common/packages/`.
   Check that logger, debug, network, and time dependencies are present. Delete
   the project's local `common.yml` and any local `esphome.project` block after
   checking local diagnostics for duplicate entities or IDs. If the platform or
   pinned ESPHome version does not support `heap-min.yml`, document the
   exclusion instead of omitting it silently or upgrading without approval.
   Include `heap-fragmentation.yml` on ESP32 or ESP8266, and `psram-free.yml`
   only when the board configures `psram`.
5. Set `board_name` in every entrypoint. Keep `esp32.board` and hardware
   configuration unchanged. Rename entrypoints or move files into `boards` and
   `packages` only when requested.
6. Delete the project's `Makefile`, `shell.bat`, and GitHub workflows that the
   user does not run; `common/bin/esphome` is the build entrypoint. Remove
   `.venv` from `.gitignore` only when no `.venv` directory exists. Never
   delete an existing virtual environment.
7. Document the project. The README covers setup with
   `git submodule update --init --recursive` and the wrapper commands. The
   project's `AGENTS.md` references the pinned `common/AGENTS.md`. Both state
   the entrypoints, ESPHome pin, common revision, board diagnostic, enabled
   shared sensor packages, and compatibility exclusions.
8. Validate every entrypoint from the project root with
   `common/bin/esphome config <entrypoint>` (or `common/bin/esphome.ps1` in
   PowerShell), with expanded output suppressed and exit codes checked. Do not
   compile, deploy, or commit as part of these checks.

## Sources, validation, and safety

Edit authored YAML and original component sources, not `.esphome` copies,
generated CMake/PlatformIO files, compilation databases, or firmware artifacts.
Regenerate outputs using the existing backend when needed. Generated build caches
and virtual environments may contain stale absolute paths.

Use the smallest relevant existing validation command, from the correct project
root. Use that project's workflow, not one global ESPHome installation. Shared
changes need representative validation against affected consumers and their pins.
Do not install or upgrade unrelated dependencies.

For firmware changes, default to `esphome config <entrypoint>` through the
project's pinned wrapper or existing environment. Suppress expanded configuration
output, check the exit code, and do not expose secrets when reporting failures.
The user compiles and uploads firmware themselves. Do not run compilation,
build cleanup, or toolchain regeneration as routine validation. If compilation
is absolutely necessary to resolve an issue that configuration checks and source
inspection cannot answer, explain why and obtain explicit user approval first.
Configuration validation alone does not establish C++ compilation or hardware
correctness; state limitations without launching a build.

Never read, print, copy into documentation, or commit credentials from
`secrets.yaml`, environment settings, expanded configurations, generated C++,
logs, or firmware bundles. Use `secrets.yaml.example` to understand key names.
Avoid publishing configuration output even when a command claims to redact it.

Configuration and compilation are not permission to deploy. Upload, `run`, OTA,
device resets, and hardware-affecting operations require explicit authorization
and an explicit device target. Do not use stored IP/hostname defaults for an
unsolicited operation. Do not treat simulation or compilation as proof of
hardware safety.
