"""Exercise security-critical dependencies and yt-dlp inside the runtime image."""

from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import shutil
import subprocess
import sys

from yt_dlp import YoutubeDL


def run(
    command: list[str], *, expected_status: int = 0, input_text: str | None = None
) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        input=input_text,
    )
    output = result.stdout + result.stderr
    if result.returncode != expected_status:
        raise AssertionError(
            f"{command!r} exited {result.returncode}, expected {expected_status}:\n{output}"
        )
    return output


assert version("yt-dlp") == "2026.6.9"
assert version("yt-dlp-ejs") == "0.8.0"
assert version("deno") == "2.8.1"
assert version("fastapi") == "0.135.1"
assert version("starlette") == "1.3.1"
assert version("pip") == "26.1.2"
try:
    setuptools_version = version("setuptools")
except PackageNotFoundError:
    pass
else:
    assert int(setuptools_version.partition(".")[0]) >= 83
assert os.getuid() != 0, "runtime image is unexpectedly running as root"
assert os.access(Path.home(), os.W_OK), "runtime home is not writable"

run([sys.executable, "-m", "pip", "check"])

deno = shutil.which("deno")
assert deno == "/app/venv/bin/deno", "Deno is not available from the copied venv"
assert "deno 2." in run([deno, "--version"])
assert (
    run(
        [deno, "run", "--no-remote", "--no-prompt", "--no-config", "-"],
        input_text="console.log('deno-ok')",
    ).strip()
    == "deno-ok"
)

assert YoutubeDL({"quiet": True})._js_runtimes["deno"].info.supported

yt_dlp = shutil.which("yt-dlp")
assert yt_dlp is not None, "yt-dlp is not available on the runtime PATH"
debug_output = run([yt_dlp, "--verbose", "--simulate"], expected_status=2)
assert "yt_dlp_ejs-0.8.0" in debug_output
assert "JS runtimes: deno-" in debug_output

print("yt-dlp, EJS, and Deno runtime smoke passed")
