"""Locate the MSVC build environment once and cache it.

Runs vcvars64.bat and captures the resulting environment so cl.exe / link.exe
(and the AddressSanitizer runtime it adds to PATH) can be invoked from Python
with that env, without needing a Developer prompt.
"""
import json, os, subprocess, tempfile
from functools import lru_cache
from pathlib import Path

SENTINEL = "___MB_ENV_DUMP___"

VSWHERE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
    / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"


@lru_cache(maxsize=1)
def vc_env():
    """Return a dict env with MSVC x64 tools available, or None if VS not found
    (always None off Windows; autograde.py then uses clang/gcc)."""
    if os.name != "nt" or not VSWHERE.exists():
        return None
    try:
        inst = subprocess.check_output(
            [str(VSWHERE), "-latest", "-property", "installationPath"],
            text=True).strip()
    except Exception:
        return None
    if not inst:
        return None
    vcvars = Path(inst) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not vcvars.exists():
        return None
    # Run vcvars from a temp .bat: passing a quoted path straight to `cmd /c`
    # from Python mangles the quotes, so a batch file is the reliable way.
    # Print a sentinel, then `set`, and parse only the lines after it. Don't
    # trust the exit code (vcvars can exit non-zero on success); detect success
    # by whether cl.exe ends up on PATH.
    bat = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".bat", delete=False) as f:
            f.write(f'@echo off\r\ncall "{vcvars}" >nul 2>&1\r\n'
                    f'echo {SENTINEL}\r\nset\r\n')
            bat = f.name
        p = subprocess.run(["cmd", "/c", bat], capture_output=True, text=True)
    finally:
        if bat:
            try:
                os.unlink(bat)
            except OSError:
                pass
    out = p.stdout
    if SENTINEL in out:
        out = out.split(SENTINEL, 1)[1]
    env = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    paths = env.get("PATH", env.get("Path", ""))
    if not any((Path(d) / "cl.exe").exists() for d in paths.split(os.pathsep) if d):
        return None
    return env


def have_msvc():
    return vc_env() is not None


def tool_path(name):
    """Absolute path to an MSVC tool (e.g. 'cl.exe') on the vc env PATH.

    Needed because Windows resolves a bare exe name against the *parent*
    process PATH, not the env dict passed to subprocess.
    """
    env = vc_env()
    if not env:
        return None
    paths = env.get("PATH", env.get("Path", ""))
    for d in paths.split(os.pathsep):
        if d and (Path(d) / name).exists():
            return str(Path(d) / name)
    return None


if __name__ == "__main__":
    e = vc_env()
    print(json.dumps({"msvc": bool(e), "cl": tool_path("cl.exe")}, indent=2))
