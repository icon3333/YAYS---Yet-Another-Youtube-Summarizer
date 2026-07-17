# YAYS Repository Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the retired file-configuration compatibility layer and proven orphan files while preserving database-backed behavior.

**Architecture:** Encode the completed `config.txt` migration as a repository invariant, then remove only compatibility parameters, mounts, constants, and utilities that have no live consumers. Keep `ConfigManager` as the database-backed facade used throughout the application.

**Tech Stack:** Python 3, unittest, Docker Compose, Markdown, MIT license text

## Global Constraints

- Preserve database-backed settings behavior, both Docker services, application entry points, install/update scripts, screenshots, and runtime data ignores.
- Do not restructure large application files or change APIs beyond removing unused internal `config_path` parameters.
- Attribute the MIT copyright to `icon3333` for 2026.
- Do not deploy, publish, or change GitHub settings.

---

### Task 1: Encode the retired-config invariant

**Files:**
- Create: `tests/test_repository_cleanup.py`

**Interfaces:**
- Consumes: repository source files as text and Python AST
- Produces: a regression test proving no live file-configuration compatibility layer remains

- [ ] **Step 1: Write the failing invariant test**

Create `tests/test_repository_cleanup.py`:

```python
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def init_parameters(path: str, class_name: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    return {arg.arg for arg in item.args.args}
    raise AssertionError(f"{class_name}.__init__ not found")


class RepositoryCleanupTests(unittest.TestCase):
    def test_retired_file_configuration_is_absent(self):
        self.assertFalse((ROOT / "src/utils/file_lock.py").exists())
        self.assertNotIn("CONFIG_FILE", (ROOT / "src/core/constants.py").read_text())
        self.assertNotIn("./config.txt:/app/config.txt", (ROOT / "docker-compose.yml").read_text())
        self.assertNotIn("config_path", init_parameters("src/managers/config_manager.py", "ConfigManager"))
        self.assertNotIn("config_path", init_parameters("src/managers/export_manager.py", "ExportManager"))
        self.assertNotIn("config_path", init_parameters("src/managers/import_manager.py", "ImportManager"))

    def test_only_live_logo_remains(self):
        self.assertFalse((ROOT / "yays_logo.png").exists())
        self.assertTrue((ROOT / "src/static/yays_logo.png").is_file())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python3 -m unittest tests/test_repository_cleanup.py -v`

Expected: failures for the existing legacy files, mounts, constant, parameters, and root logo.

### Task 2: Remove the retired compatibility layer

**Files:**
- Delete: `src/utils/file_lock.py`
- Delete: `yays_logo.png`
- Modify: `docker-compose.yml`
- Modify: `src/core/constants.py`
- Modify: `src/managers/config_manager.py`
- Modify: `src/managers/export_manager.py`
- Modify: `src/managers/import_manager.py`

**Interfaces:**
- Consumes: failing invariant from Task 1
- Produces: database-only configuration interfaces with unchanged live call behavior

- [ ] **Step 1: Remove dead files, mounts, and constant**

Delete the two files. Remove both `./config.txt:/app/config.txt` volume entries and their comments from Compose. Remove `CONFIG_FILE = 'config.txt'` from `src/core/constants.py`.

- [ ] **Step 2: Remove compatibility-only constructor parameters**

Change the constructors so their live arguments remain and `config_path` disappears:

```python
class ConfigManager:
    def __init__(self, db_path='data/videos.db'):
        from src.managers.database import VideoDatabase
        self.db = VideoDatabase(db_path)
```

For `ExportManager` and `ImportManager`, remove only the `config_path: str = "config.txt"` parameter and its unused/backward-compatibility comment. Preserve every other parameter, default, assignment, and manager construction.

- [ ] **Step 3: Run the test and verify GREEN**

Run: `python3 -m unittest tests/test_repository_cleanup.py -v`

Expected: 2 tests pass.

### Task 3: Repair documentation and licensing

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docker-compose.yml:1-2`
- Create: `LICENSE`

**Interfaces:**
- Consumes: cleaned database-only configuration state
- Produces: documentation that describes only the current system and a detectable MIT license

- [ ] **Step 1: Remove stale documentation**

Remove references claiming that Compose still mounts `config.txt`, that `file_lock.py` provides concurrency protection, and that `test_validation.py` exists. Remove the entire `Recent Improvements` section and its commit-by-commit history. Keep current architecture, operational commands, and deployment notes.

Remove the obsolete commented Compose `version` header, leaving `services:` as the first configuration key.

- [ ] **Step 2: Add the MIT license**

Create `LICENSE` using the canonical MIT text headed:

```text
MIT License

Copyright (c) 2026 icon3333
```

Include the standard permission, notice-preservation, and warranty-disclaimer paragraphs without alteration.

- [ ] **Step 3: Run full verification**

Run: `python3 -m unittest tests/test_repository_cleanup.py -v`

Expected: 2 tests pass.

Run: `python3 -m compileall -q main.py process_videos.py start_summarizer.py src tests`

Expected: exit 0.

Run: `rg -n 'config\.txt|CONFIG_FILE|locked_file|file_lock|test_validation|Recent Improvements' --glob '!.git/**' --glob '!tests/test_repository_cleanup.py' || true`

Expected: no output.

Run: `docker compose config -q`

Expected: exit 0 when Docker Compose is installed.

Run: `git diff --check`

Expected: exit 0 with no output.

- [ ] **Step 4: Remove transient planning artifacts and commit**

Delete `docs/superpowers/`, then run:

```bash
git add -A
git commit -m "chore: finish legacy configuration cleanup"
```

Expected: implementation and regression test committed together.
