# YAYS Repository Cleanup Design

## Goal

Finish the repository's already-documented migration away from `config.txt`, remove proven orphan files, repair stale documentation, and add the license the README already claims.

## Scope

- Remove the unreferenced root `yays_logo.png`; retain the live `src/static/yays_logo.png`.
- Remove the two obsolete `config.txt` bind mounts from Docker Compose.
- Remove the unused `CONFIG_FILE` constant.
- Remove the unused `src/utils/file_lock.py` module.
- Remove backward-compatibility-only `config_path` parameters from `ConfigManager`, `ExportManager`, and `ImportManager`, updating in-repository call sites if required.
- Remove stale comments and documentation that describe `config.txt`, the orphan lock module, nonexistent `test_validation.py`, and commit-history-style "Recent Improvements" notes.
- Add the standard MIT license with copyright attributed to `icon3333`.

## Explicitly Preserved

- The database-backed `ConfigManager` public behavior and its name.
- Both Docker services, all application entry points, screenshots, lock/data ignore rules, install/update scripts, and runtime code not tied to the retired file configuration path.
- Large `app.py` and `app.js` files; splitting them requires tests and a separate refactor.

## Verification

- Add focused tests or signature checks before changing Python interfaces where needed.
- Confirm no live code references `config.txt`, `CONFIG_FILE`, `locked_file`, or the removed root logo.
- Compile all Python modules.
- Validate the Compose file with `docker compose config` when Docker is available.
- Review the final diff and run available smoke checks without contacting external services.

## Non-Goals

No API behavior changes, frontend restructuring, database migration, scraper/transcript changes, deployment execution, GitHub settings changes, or branch changes.
