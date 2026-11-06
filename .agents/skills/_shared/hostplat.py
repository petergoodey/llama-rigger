"""OS-specific bits for the skill scripts: processes, power mode, router restart.

Windows, Linux and macOS. Standard library only. Everything else in the skill
scripts is portable; keep platform checks in this file.
"""
import os, re, shutil, signal, socket, subprocess, sys, time
from pathlib import Path

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
SERVER_EXE = "llama-server.exe" if IS_WIN else "llama-server"


def _run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout or ""
    except Exception:
        return ""


# ------------------------------------------------------------------ processes
def port_listening(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def llama_server_pids():
    if IS_WIN:
        out = _run(["tasklist", "/FI", f"IMAGENAME eq {SERVER_EXE}", "/FO", "CSV", "/NH"])
        return [l.split('","')[1] for l in out.splitlines() if l.lower().startswith('"llama-server')]
    if shutil.which("pgrep"):
        return _run(["pgrep", "-x", "llama-server"]).split()
    return []


def kill_llama_servers():
    if IS_WIN:
        _run(["taskkill", "/F", "/IM", SERVER_EXE])
    elif shutil.which("pkill"):
        _run(["pkill", "-TERM", "-x", "llama-server"])
        time.sleep(3)
        _run(["pkill", "-KILL", "-x", "llama-server"])


def popen_server(cmd, **kw):
    """Start a server so that stop_process() can kill it and its children."""
    if not IS_WIN:
        kw.setdefault("start_new_session", True)
    return subprocess.Popen(cmd, **kw)


def popen_detached(cmd, log_path):
    """Start a long-lived background server that outlives this script, logging to
    log_path (appended). Its children die with it via kill_tree(pid)."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    kw = {"stdout": open(log_path, "ab"), "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if IS_WIN:
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


def kill_tree(pid, wait=None):
    """Kill a process started by popen_server()/popen_detached(), with its children.
    `wait` is an optional Popen to reap afterwards."""
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            if wait is None:
                time.sleep(3)
                continue
            try:
                wait.wait(10)
                break
            except subprocess.TimeoutExpired:
                continue
    if wait is not None:
        try:
            wait.wait(30)
        except Exception:
            pass


def stop_process(proc):
    """Kill a process started by popen_server(), with its children, and reap it."""
    if proc.poll() is None:
        kill_tree(proc.pid, wait=proc)


def restart_router(repo_dir, ini, log_path):
    """Start the router again with the repo's launcher, detached from this process."""
    repo_dir = Path(repo_dir)
    if IS_WIN:
        subprocess.Popen(["cmd", "/c", str(repo_dir / "start-llama-ini.cmd"), str(ini)],
                         cwd=str(repo_dir), creationflags=subprocess.CREATE_NEW_CONSOLE)
        return f"new console window ({repo_dir / 'start-llama-ini.cmd'})"
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as f:
        subprocess.Popen(["bash", str(repo_dir / "start-llama-ini.sh"), str(ini)],
                         cwd=str(repo_dir), stdout=f, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    return f"background, log: {log_path}"


# ------------------------------------------------------------------ power mode
def power_plan():
    """The active power plan / profile as a short lower-case-able name ('' if unknown).

    Windows: powercfg's active scheme. Linux: power-profiles-daemon, else the ACPI
    platform profile, else the CPU governor. macOS: pmset's power mode / low power mode.
    """
    if IS_WIN:
        out = _run(["powercfg", "/getactivescheme"])
        m = re.search(r"\(([^)]+)\)", out)
        return m.group(1) if m else out.strip()
    if IS_MAC:
        out = _run(["pmset", "-g"])
        m = re.search(r"^\s*powermode\s+(\d)", out, re.M)
        if m:  # Apple silicon: 0 automatic, 1 low power, 2 high power
            return {"0": "automatic", "1": "low power", "2": "high power"}.get(m.group(1), m.group(1))
        m = re.search(r"^\s*lowpowermode\s+(\d)", out, re.M)
        if m:
            return "low power" if m.group(1) == "1" else "automatic"
        return ""
    if shutil.which("powerprofilesctl"):
        out = _run(["powerprofilesctl", "get"]).strip()
        if out:
            return out  # performance | balanced | power-saver
    for p in ("/sys/firmware/acpi/platform_profile",
              "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"):
        try:
            return Path(p).read_text().strip()
        except OSError:
            pass
    return ""


def default_modes():
    """Mode name -> substring of power_plan() expected in that mode, per OS."""
    if IS_MAC:
        return {"modes": {"automatic": "automatic", "high": "high power"},
                "low_power": ["low power"],
                "switch_hint": "System Settings > Battery > Energy Mode"}
    if IS_WIN:
        return {"modes": {"balanced": "balanced", "performance": "performance"},
                "low_power": ["power saver", "quiet", "silent", "eco"],
                "switch_hint": "Windows power settings or your vendor's tool"}
    return {"modes": {"balanced": "balanced", "performance": "performance"},
            "low_power": ["power-saver", "low-power", "quiet"],
            "switch_hint": "powerprofilesctl set <profile>, or your desktop's power settings"}
