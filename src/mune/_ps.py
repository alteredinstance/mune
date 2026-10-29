from __future__ import annotations

import os
import shutil
import subprocess


def run(script: str, *, env: dict | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    env = dict(os.environ if env is None else env)
    exe = shutil.which("pwsh")
    if not exe:
        # A system PSModulePath pointing at PowerShell 7 modules breaks 5.1's built-ins.
        exe = "powershell"
        root = env.get("SystemRoot", r"C:\Windows")
        env["PSModulePath"] = rf"{root}\System32\WindowsPowerShell\v1.0\Modules"
    return subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
