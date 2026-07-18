import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch


try:
    from starlette.exceptions import StarletteDeprecationWarning
except ImportError:
    # Starlette < 1.0 did not expose this targeted warning category.
    pass
else:
    warnings.simplefilter("error", StarletteDeprecationWarning)

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def snapshot_tree(path: Path):
    if not path.exists():
        return None

    snapshot = {}
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        stat = file_path.stat()
        snapshot[str(file_path.relative_to(path))] = (
            stat.st_size,
            stat.st_mtime_ns,
        )
    return snapshot


REPOSITORY_STATE_BEFORE_IMPORT = {
    "data": snapshot_tree(ROOT / "data"),
    "logs": snapshot_tree(ROOT / "logs"),
}
TEST_STATE = tempfile.TemporaryDirectory(prefix="yays-fastapi-contracts-")
TEST_DATA_DIR = Path(TEST_STATE.name) / "data"
TEST_LOG_DIR = Path(TEST_STATE.name) / "logs"
TEST_ENV_FILE = Path(TEST_STATE.name) / "isolated.env"
TEST_DOTENV_VARIABLE = "YAYS_FASTAPI_TEST_ENV"
TEST_ENV_FILE.write_text(f"{TEST_DOTENV_VARIABLE}=isolated\n", encoding="utf-8")
TEST_ENVIRONMENT = {
    "YAYS_DATA_DIR": str(TEST_DATA_DIR),
    "YAYS_LOG_DIR": str(TEST_LOG_DIR),
    "YAYS_ENV_FILE": str(TEST_ENV_FILE),
}
ORIGINAL_ENVIRONMENT = {
    name: os.environ.get(name) for name in (*TEST_ENVIRONMENT, TEST_DOTENV_VARIABLE)
}
os.environ.pop(TEST_DOTENV_VARIABLE, None)
os.environ.update(TEST_ENVIRONMENT)

try:
    from src.web import app as web_app
except BaseException:
    for name, original_value in ORIGINAL_ENVIRONMENT.items():
        if original_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = original_value
    TEST_STATE.cleanup()
    raise


def cleanup_test_environment():
    try:
        state_after_tests = {
            "data": snapshot_tree(ROOT / "data"),
            "logs": snapshot_tree(ROOT / "logs"),
        }
        if state_after_tests != REPOSITORY_STATE_BEFORE_IMPORT:
            raise AssertionError("FastAPI contract tests mutated repository data or logs")
    finally:
        for handler in (web_app.file_handler, web_app.console_handler):
            web_app.root_logger.removeHandler(handler)
            handler.close()
        for name, original_value in ORIGINAL_ENVIRONMENT.items():
            if original_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = original_value
        TEST_STATE.cleanup()


unittest.addModuleCleanup(cleanup_test_environment)


class FastAPIImportIsolationTests(unittest.TestCase):
    def test_environment_paths_isolate_all_import_time_state(self):
        self.assertTrue(
            all(
                hasattr(web_app, name)
                for name in ("DATA_DIR", "LOG_DIR", "ENV_FILE")
            ),
            "the web app must expose its resolved state roots",
        )
        self.assertEqual(web_app.DATA_DIR, TEST_DATA_DIR)
        self.assertEqual(web_app.LOG_DIR, TEST_LOG_DIR)
        self.assertEqual(web_app.ENV_FILE, TEST_ENV_FILE)
        self.assertEqual(web_app.DATABASE_PATH, TEST_DATA_DIR / "videos.db")
        self.assertEqual(os.environ[TEST_DOTENV_VARIABLE], "isolated")
        self.assertTrue(web_app.DATABASE_PATH.is_file())
        self.assertTrue((TEST_LOG_DIR / "web.log").is_file())

        manager_databases = (
            web_app.config_manager.db.db_path,
            web_app.settings_manager.db.db_path,
            web_app.video_db.db_path,
            web_app.export_manager.db.db_path,
            web_app.import_manager.db.db_path,
        )
        self.assertTrue(
            all(Path(database) == web_app.DATABASE_PATH for database in manager_databases)
        )
        self.assertTrue(
            hasattr(web_app.ytdlp_client, "db_path"),
            "the app-level yt-dlp client must expose its injected settings database",
        )
        self.assertEqual(Path(web_app.ytdlp_client.db_path), web_app.DATABASE_PATH)
        self.assertIs(web_app.youtube_client.ytdlp, web_app.ytdlp_client)

    def test_repository_database_and_logs_are_unchanged_after_import(self):
        self.assertEqual(
            {
                "data": snapshot_tree(ROOT / "data"),
                "logs": snapshot_tree(ROOT / "logs"),
            },
            REPOSITORY_STATE_BEFORE_IMPORT,
        )

    def test_log_listing_uses_the_isolated_log_root(self):
        self.assertTrue(
            TEST_LOG_DIR.is_dir(), "the configured log root must be created at import"
        )
        (TEST_LOG_DIR / "summarizer.log").write_text("isolated\n", encoding="utf-8")

        response = TestClient(web_app.app).get("/api/logs/list")

        self.assertEqual(response.status_code, 200)
        paths = {item["name"]: item["file_path"] for item in response.json()["logs"]}
        self.assertEqual(paths["web"], str(TEST_LOG_DIR / "web.log"))
        self.assertEqual(paths["summarizer"], str(TEST_LOG_DIR / "summarizer.log"))


class FastAPIApplicationContractTests(unittest.TestCase):
    def test_lifespan_starts_and_stops_the_scheduler(self):
        with (
            patch.object(
                web_app.settings_manager,
                "get_all_settings",
                return_value={"CHECK_INTERVAL_HOURS": {"value": "6"}},
            ),
            patch.object(web_app, "scheduler") as scheduler,
        ):
            with TestClient(web_app.app):
                scheduler.start.assert_called_once_with()

        scheduler.add_job.assert_called_once_with(
            web_app.scheduled_video_check,
            "interval",
            hours=6,
            id="video_check",
            replace_existing=True,
        )
        scheduler.shutdown.assert_called_once_with()

    def test_health_endpoint_returns_the_public_contract(self):
        with patch.object(web_app.config_manager, "ensure_config_exists"):
            response = TestClient(web_app.app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy", "version": "0.1"})

    def test_channel_validation_returns_a_structured_422_response(self):
        response = TestClient(web_app.app).post(
            "/api/channels",
            json={"channels": ["bad"], "names": {"bad": "Invalid channel"}},
        )

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail[0]["loc"], ["body", "channels"])
        self.assertEqual(detail[0]["type"], "value_error")

    def test_settings_endpoint_preserves_its_response_shape(self):
        with (
            patch.object(
                web_app.settings_manager,
                "get_all_settings",
                return_value={"OPENAI_API_KEY": {"value": "********"}},
            ),
            patch.object(
                web_app.config_manager,
                "get_settings",
                return_value={"SKIP_SHORTS": "true"},
            ),
        ):
            response = TestClient(web_app.app).get("/api/settings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "env": {"OPENAI_API_KEY": {"value": "********"}},
                "config": {"SKIP_SHORTS": "true"},
                "restart_required": False,
            },
        )

    def test_homepage_renders_with_the_supported_template_signature(self):
        response = TestClient(web_app.app).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("YAYS", response.text)

    def test_static_assets_keep_the_no_cache_contract(self):
        response = TestClient(web_app.app).get("/static/css/main.css")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["cache-control"], "no-cache, no-store, must-revalidate"
        )
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertEqual(response.headers["expires"], "0")


class BackendDependencyPolicyTests(unittest.TestCase):
    def test_runtime_framework_versions_are_pinned_to_the_fixed_stack(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("fastapi==0.135.1", requirements)
        self.assertIn("starlette==1.3.1", requirements)
        self.assertNotIn("fastapi==0.128.0", requirements)

    def test_test_client_and_audit_tool_are_development_only_dependencies(self):
        development_path = ROOT / "requirements-dev.txt"
        self.assertTrue(
            development_path.is_file(), "requirements-dev.txt must isolate test tooling"
        )
        development = development_path.read_text(encoding="utf-8")
        runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("-r requirements.txt", development)
        self.assertIn("httpx2==2.7.0", development)
        self.assertIn("pip-audit==2.10.1", development)
        self.assertNotIn("httpx2", runtime)
        self.assertNotIn("pip-audit", runtime)

    def test_builder_pins_the_fixed_pip_before_installing_runtime_dependencies(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        upgrade = "RUN pip install --no-cache-dir --upgrade pip==26.1.2"
        install = "RUN pip install --no-cache-dir -r requirements.txt"
        self.assertIn(upgrade, dockerfile)
        self.assertIn(install, dockerfile)
        self.assertLess(dockerfile.index(upgrade), dockerfile.index(install))

    def test_ci_repairs_python_311s_vulnerable_setuptools_seed(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn(
            "python3 -m pip install --upgrade pip==26.1.2 setuptools==83.0.0",
            workflow,
        )

    def test_ci_installs_development_dependencies_and_audits_resolved_images(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("python3 -m pip install -r requirements-dev.txt", workflow)
        self.assertIn("python3 -m pip_audit --strict", workflow)
        self.assertIn("-m pip freeze --all", workflow)
        self.assertIn("yays-web:ci", workflow)
        self.assertIn("yays-summarizer:ci", workflow)

        exact_inventory_audit = (
            "python3 -m pip_audit --strict --no-deps --disable-pip --requirement"
        )
        self.assertEqual(workflow.count(exact_inventory_audit), 2)

    def test_starlette_test_client_fallback_warning_is_promoted_to_an_error(self):
        test_module = (ROOT / "tests/test_fastapi_contracts.py").read_text(
            encoding="utf-8"
        )

        warning_filter = 'warnings.simplefilter("error", StarletteDeprecationWarning)'
        self.assertIn(warning_filter, test_module)
        self.assertLess(
            test_module.index(warning_filter),
            test_module.index("from fastapi.testclient import TestClient"),
        )

    def test_container_smoke_asserts_the_fixed_backend_toolchain(self):
        smoke = (ROOT / "tests/container_runtime_smoke.py").read_text(encoding="utf-8")

        self.assertIn('version("fastapi") == "0.135.1"', smoke)
        self.assertIn('version("starlette") == "1.3.1"', smoke)
        self.assertIn('version("pip") == "26.1.2"', smoke)
        self.assertIn("PackageNotFoundError", smoke)
        self.assertIn("setuptools_version", smoke)


if __name__ == "__main__":
    unittest.main()
