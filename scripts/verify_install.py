"""Smoke-test the already installed distribution outside the source checkout."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def verify():
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="india-installed-check-") as temporary:
        workspace = Path(temporary) / "demo"
        command = [sys.executable, "-m", "india_trader", "--workspace", str(workspace)]
        subprocess.run(
            command + ["setup", "--demo"],
            cwd=temporary,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            command + ["--now", "2026-10-19T09:35:00+05:30", "desk", "today"],
            cwd=temporary,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            command + ["validate", "readiness"],
            cwd=temporary,
            env=environment,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    print("Installed distribution works outside the checkout")


if __name__ == "__main__":
    verify()
