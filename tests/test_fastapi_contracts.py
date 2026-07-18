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

from src.web import app as web_app


ROOT = Path(__file__).resolve().parents[1]


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
