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

    def test_retired_config_rules_and_dependency_are_absent(self):
        self.assertNotIn("config.txt", (ROOT / ".gitignore").read_text())
        self.assertNotIn("filelock", (ROOT / "requirements.txt").read_text().lower())

    def test_concurrency_docs_distinguish_pid_and_heartbeat_files(self):
        documentation = (ROOT / "CLAUDE.md").read_text()

        self.assertNotIn("filelock", documentation.lower())
        self.assertIn(
            "`data/.processor.pid` prevents concurrent processor instances and stores the active process ID",
            documentation,
        )
        self.assertIn(
            "`data/.processing.lock` records heartbeat timestamps used for stuck-process detection",
            documentation,
        )


if __name__ == "__main__":
    unittest.main()
