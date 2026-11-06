---
name: esphome-update
description: Update an ESPHome firmware project that uses esphome-common to the latest stable (or a named) ESPHome release, reviewing the release notes against the project and validating every entrypoint. Use when asked to update, bump, or upgrade ESPHome in a project, or to check which projects are behind.
---

# Update ESPHome in a firmware project

The procedure is "Updating ESPHome" in esphome-common's `AGENTS.md`. Read
that section and the project's own `AGENTS.md` (if any) first; they take
precedence over this summary. Paths below are relative to the project root
and use forward slashes; adapt them to the local shell.

## Steps

1. Run from the project root (the directory with `requirements.txt` and the
   firmware entrypoints). Check `git status` in the project and in
   `common/`, and preserve existing work.
2. Target version: `info.version` from `https://pypi.org/pypi/esphome/json`,
   unless the user named one. Skip pre-releases. If the project is already on
   the target, say so and stop.
3. Find the release reviews in `docs/esphome-upgrades/` of the newest
   esphome-common available. The project's pinned `common/` may predate
   them, so check in this order and say which source was used:
   - a separate esphome-common clone the user points to or that sits next to
     the project (`../esphome-common`);
   - the submodule's upstream, read without moving the gitlink:
     `git -C common fetch` then
     `git -C common show origin/HEAD:docs/esphome-upgrades/<YYYY.MM>.md`;
   - the pinned `common/docs/esphome-upgrades/`.
4. Read the review for each minor release between the old pin (exclusive)
   and the target (inclusive). If one is missing or its `Reviewed up to` is
   older than the target, review the release yourself following
   `docs/esphome-upgrades/README.md`. Write the review into a writable
   esphome-common clone, if there is one, and tell the user it is an
   uncommitted change there. Never edit the pinned `common/` checkout.
5. Check each entry against the project: entrypoints, `boards/`,
   `packages/`, lambdas, and local components. Search for the components and
   C++ names each entry mentions. Note which entries apply, and why the
   others do not.
6. Update `requirements.txt` and any documentation that states the pin
   (`AGENTS.md`, `README.md`). Search for the old version string to find
   other references; ignore the `.esphome/` build folder.
7. Validate:
   - `uvx --with-requirements requirements.txt esphome version` reports the
     target.
   - Run the wrapper's `config` command (`common/bin/esphome` in POSIX
     shells, `common/bin/esphome.ps1` in PowerShell) on every root
     entrypoint, discarding stdout and checking each exit code. Never print
     the expanded configuration or secrets.
   - For any warning, say whether it was already present before the update.
8. Report the reviewed releases, the changes that applied, the validation,
   and that `config` does not compile lambdas. Do not compile, flash, or run
   OTA unless the user asks.
9. Commit only when the user asks: title `Update ESPHome to X.Y.Z`, with a
   body naming the reviewed releases, applicable changes, and validation.

## Several projects

When the user asks to update several projects, list the ones they name (or
the sibling directories they point to) with their current `requirements.txt`
pin. Follow this skill as written only for projects that use the `common/`
submodule; for others, follow their own `AGENTS.md` or ask. Review each
release once, then update the projects one at a time, each committed in its
own repository.
