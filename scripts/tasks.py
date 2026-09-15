#!/usr/bin/env python
"""Canonical task entry points for the repo -- run them as `npm run <task>`.

Why the logic lives here instead of in package.json one-liners:

* npm picks a different shell per platform (cmd.exe on Windows, sh elsewhere), so
  shell-quoted one-liners are not portable.
* The host environment is not clean -- PYTHONPATH carries entries belonging to
  another project, which loads the wrong FastAPI/Starlette. Every child is given
  a stripped PYTHONPATH so test runs stay hermetic (see docs/TDD.md section 9).
* A bare ``bash`` on Windows resolves to the WSL relay and fails outright.

``python scripts/tasks.py --list`` shows the available tasks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

# Every python tree ruff is expected to cover, including the repo-level tooling
# that used to sit outside the configured scope entirely.
PY_SOURCES = ["backend/app", "backend/tests", "backend/migrations", "scripts"]

# Machine-local QA setup (a separate venv, so Playwright never enters the project
# dependency tree). Override with the env vars when running elsewhere.
QA_PY = Path(
    os.environ.get("AI_STUDIO_QA_PYTHON", "D:/HermesWorkplace/cache/qa-venv/Scripts/python.exe")
)
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "D:/HermesWorkplace/cache/ms-playwright")
# One entry per phase: they seed their own data over HTTP, then drive real
# Chrome. Kept as a list so adding a phase cannot silently leave its UI
# unverified -- `verify:ui` runs all of them.
UI_VERIFIERS = [
    Path(os.environ.get("AI_STUDIO_UI_VERIFIER", "D:/HermesWorkplace/cache/verify_ui_phase3.py")),
    Path(
        os.environ.get(
            "AI_STUDIO_UI_VERIFIER_PHASE4", "D:/HermesWorkplace/cache/verify_ui_phase4.py"
        )
    ),
]


def run(cmd: list, cwd: Path = ROOT, env: dict | None = None) -> int:
    """Run a child process with a clean PYTHONPATH; return its exit code."""
    print(f"+ {' '.join(str(c) for c in cmd)}", flush=True)
    child = {**os.environ, "PYTHONPATH": "", "PYTHONIOENCODING": "utf-8", **(env or {})}
    return subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=child).returncode


def bash() -> Path:
    """Locate git-bash. On Windows a bare ``bash`` is the WSL relay, which fails."""
    if os.name != "nt":
        return Path(shutil.which("bash") or "/bin/bash")
    for candidate in (
        os.environ.get("AI_STUDIO_BASH"),
        "D:/Git/usr/bin/bash.exe",
        "C:/Program Files/Git/usr/bin/bash.exe",
        "C:/Program Files (x86)/Git/usr/bin/bash.exe",
    ):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    sys.exit("git-bash not found -- set AI_STUDIO_BASH to the path of bash.exe")


def npm(*args: str) -> int:
    """npm is a .cmd shim on Windows and needs the command interpreter."""
    npm_exe = shutil.which("npm") or "npm"
    cmd = ["cmd", "/c", npm_exe, *args] if os.name == "nt" else [npm_exe, *args]
    return run(cmd, cwd=FRONTEND)


# --------------------------------------------------------------------------- tasks
def test() -> int:
    """Backend test suite (hermetic)."""
    return run([VENV_PY, "-m", "pytest"], cwd=BACKEND)


def lint() -> int:
    """ruff check + format check across every python tree."""
    return run([VENV_PY, "-m", "ruff", "check", *PY_SOURCES]) or run(
        [VENV_PY, "-m", "ruff", "format", "--check", *PY_SOURCES]
    )


def fmt() -> int:
    """Apply ruff fixes and formatting."""
    run([VENV_PY, "-m", "ruff", "check", "--fix", *PY_SOURCES])
    return run([VENV_PY, "-m", "ruff", "format", *PY_SOURCES])


def typecheck() -> int:
    """tsc --noEmit on the frontend."""
    return npm("run", "typecheck")


def build() -> int:
    """Production build of the frontend, then the container images."""
    return npm("run", "build") or run(["docker", "compose", "build"])


def verify() -> int:
    """Every acceptance suite against the running stack (real model calls)."""
    rc = run([bash(), "scripts/verify_phase1.sh"])
    for script in PHASE_SCRIPTS:
        rc = run([sys.executable, script]) or rc
    return rc


def verify_phase4() -> int:
    """Phase 4 acceptance only: Episode Agent, script, storyboard, shots."""
    return run([sys.executable, "scripts/verify_phase4.py"])


def verify_ui() -> int:
    """Render every delivered phase's UI in real Chrome via Playwright."""
    if not QA_PY.exists():
        sys.exit(f"QA venv missing at {QA_PY} -- set AI_STUDIO_QA_PYTHON")
    missing = [str(v) for v in UI_VERIFIERS if not v.exists()]
    if missing:
        sys.exit(f"UI verifier(s) missing: {', '.join(missing)}")

    rc = 0
    for verifier in UI_VERIFIERS:
        rc = (
            run([QA_PY, verifier], env={"PLAYWRIGHT_BROWSERS_PATH": BROWSERS}, cwd=Path.cwd()) or rc
        )
    return rc


def seed() -> int:
    """Create the demo account and a fully analysed project."""
    return run([sys.executable, "scripts/seed_demo.py"])


def up() -> int:
    """Start the compose stack."""
    return run(["docker", "compose", "up", "-d"])


def down() -> int:
    """Stop the compose stack."""
    return run(["docker", "compose", "down"])


# Phase acceptance scripts, in order. Phase 1 is a shell script because it only
# curls the stack; the rest drive the API with explicit UTF-8 (git-bash mangles
# inline Chinese).
PHASE_SCRIPTS = (
    "scripts/verify_phase2.py",
    "scripts/verify_phase3.py",
    "scripts/verify_phase4.py",
)

TASKS = {
    "test": test,
    "lint": lint,
    "fmt": fmt,
    "typecheck": typecheck,
    "build": build,
    "verify": verify,
    "verify:ui": verify_ui,
    "verify:phase4": verify_phase4,
    "seed": seed,
    "up": up,
    "down": down,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "--list"}:
        print(__doc__.strip().splitlines()[0])
        for name, fn in TASKS.items():
            summary = (fn.__doc__ or "").strip().splitlines()
            print(f"  {name:11} {summary[0] if summary else ''}")
        return 0
    task = TASKS.get(argv[0])
    if task is None:
        sys.exit(f"unknown task {argv[0]!r} -- try --list")
    return task()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
