#!/usr/bin/env python3
"""get-system-info probe: collect hardware and llama.cpp-relevant facts as JSON.

Cross-platform (Windows, Linux and macOS), standard library only, read-only. Every
sub-probe is isolated: a missing tool or a permission error becomes an entry in
"unavailable" and never stops the run. Serial numbers, MAC addresses, the host
name and user names are deliberately not collected.

Usage:
  python probe.py                 # JSON to stdout
  python probe.py --out probe.json
  python probe.py --summary       # short human-readable summary on stderr as well
"""
import argparse, json, os, platform, re, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
OUT = {"probed": datetime.now().isoformat(timespec="seconds"), "unavailable": {}}


def run(cmd, timeout=60, shell=False, merge_stderr=False):
    """Return stdout text (plus stderr if merge_stderr), or None on any failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           shell=shell, errors="replace")
        text = r.stdout + (r.stderr if merge_stderr else "")
        return text if r.returncode == 0 or text.strip() else None
    except Exception:
        return None


def miss(key, why):
    OUT["unavailable"][key] = why


def ps_json(query):
    """Windows: run a PowerShell query that ends in ConvertTo-Json; always return a list."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return None
    out = run([exe, "-NoProfile", "-NonInteractive", "-Command",
               query + " | ConvertTo-Json -Compress -Depth 4"])
    if not out or not out.strip():
        return None
    try:
        v = json.loads(out)
    except ValueError:
        return None
    return fix_dates(v if isinstance(v, list) else [v])


def fix_dates(v):
    """PowerShell serialises dates as /Date(ms)/; turn them into ISO dates."""
    if isinstance(v, str):
        m = re.fullmatch(r"/Date\((-?\d+)\)/", v)
        return datetime.fromtimestamp(int(m.group(1)) / 1000).date().isoformat() if m else v
    if isinstance(v, list):
        return [fix_dates(x) for x in v]
    if isinstance(v, dict):
        return {k: fix_dates(x) for k, x in v.items()}
    return v


def sysctl(*names):
    """macOS: {name: value} for the sysctl keys that exist."""
    out = {}
    for n in names:
        v = run(["sysctl", "-n", n])
        if v is not None and v.strip():
            out[n] = v.strip()
    return out


def sp_json(datatype):
    """macOS: system_profiler <datatype> -json as a list of entries, minus identifiers."""
    out = run(["system_profiler", datatype, "-json"], timeout=90)
    try:
        items = json.loads(out)[datatype] if out else None
    except (ValueError, KeyError):
        return None
    return redact(items)   # nested entries (e.g. per-DIMM _items) carry serials too


# ------------------------------------------------------------------ privacy
# Applied to everything the probe returns (main() runs it once over OUT), so no
# sub-probe can leak an identifier: keys naming one are dropped at any depth, and
# UUIDs/GUIDs, the home folder, user name and host name are masked in text.
ID_KEYS = ("serial", "uuid", "udid", "guid", "provisioning", "mac_address", "macaddress")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def _private_words():
    import getpass, socket
    words = []
    for fn in (lambda: str(Path.home()), getpass.getuser, socket.gethostname, platform.node):
        try:
            w = fn()
        except Exception:
            continue
        if w and len(w) > 2:
            words.append(w)
    # longest first, so the home path is masked before the bare user name inside it
    return sorted(set(words), key=len, reverse=True)


_PRIVATE = None


def redact(v):
    global _PRIVATE
    if _PRIVATE is None:
        _PRIVATE = [(w, "~" if os.sep in w or "/" in w else "<redacted>") for w in _private_words()]
    if isinstance(v, dict):
        return {k: redact(x) for k, x in v.items() if not any(d in k.lower() for d in ID_KEYS)}
    if isinstance(v, list):
        return [redact(x) for x in v]
    if isinstance(v, str):
        v = _UUID.sub("<uuid>", v)
        v = re.sub(r"\b(root|resume)=UUID=\S+", r"\1=<uuid>", v)
        for w, mask in _PRIVATE:
            for form in {w, w.replace("\\", "/")}:
                # whole words only, so a short user name never masks part of a model name
                v = re.sub(rf"(?<![A-Za-z0-9]){re.escape(form)}(?![A-Za-z0-9])", mask, v, flags=re.I)
        return v
    return v


def gib(n):
    return round(n / 2**30, 2) if n else None


def read(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except Exception:
        return None


# ------------------------------------------------------------------ OS
def probe_os():
    o = {"system": platform.system(), "release": platform.release(),
         "version": platform.version(), "machine": platform.machine(),
         "python": platform.python_version()}
    if IS_WIN:
        r = ps_json("Get-CimInstance Win32_OperatingSystem | Select Caption,Version,BuildNumber,OSArchitecture")
        if r:
            o["windows"] = r[0]
    elif IS_MAC:
        o["macos"] = {k: (run(["sw_vers", f"-{k}"]) or "").strip()
                      for k in ("productName", "productVersion", "buildVersion")}
    else:
        osr = read("/etc/os-release") or ""
        o["distro"] = dict(re.findall(r'^(NAME|VERSION|PRETTY_NAME)="?([^"\n]*)"?', osr, re.M))
        ver = read("/proc/version") or ""
        o["kernel"] = platform.release()
        o["wsl"] = "microsoft" in ver.lower() or "wsl" in ver.lower()
        o["kernel_cmdline"] = read("/proc/cmdline")
    OUT["os"] = o


# ------------------------------------------------------------------ machine / BIOS
def probe_machine():
    if IS_WIN:
        cs = ps_json("Get-CimInstance Win32_ComputerSystem | Select Manufacturer,Model,SystemType,TotalPhysicalMemory")
        bios = ps_json("Get-CimInstance Win32_BIOS | Select Manufacturer,SMBIOSBIOSVersion,ReleaseDate")
        if cs:
            m = cs[0]
            OUT["machine"] = {"manufacturer": m.get("Manufacturer"), "model": m.get("Model"),
                              "os_visible_ram_gib": gib(m.get("TotalPhysicalMemory"))}
        else:
            miss("machine", "Win32_ComputerSystem query failed")
        if bios:
            OUT.setdefault("machine", {})["bios"] = bios[0]
    elif IS_MAC:
        hw = sp_json("SPHardwareDataType")
        m = sysctl("hw.model")
        if hw:
            h = hw[0]
            m.update({"model_name": h.get("machine_name"), "model_number": h.get("model_number"),
                      "chip": h.get("chip_type") or h.get("cpu_type"),
                      "memory": h.get("physical_memory"), "firmware": h.get("boot_rom_version")})
        OUT["machine"] = {k: v for k, v in m.items() if v}
        if not OUT["machine"]:
            miss("machine", "sysctl / system_profiler failed")
    else:
        d = {k: read(f"/sys/class/dmi/id/{k}") for k in
             ("sys_vendor", "product_name", "bios_vendor", "bios_version", "bios_date")}
        OUT["machine"] = {k: v for k, v in d.items() if v}
        if not OUT["machine"]:
            miss("machine", "/sys/class/dmi/id not readable")


# ------------------------------------------------------------------ CPU
def probe_cpu():
    if IS_WIN:
        r = ps_json("Get-CimInstance Win32_Processor | Select Name,Manufacturer,NumberOfCores,"
                    "NumberOfLogicalProcessors,MaxClockSpeed,L2CacheSize,L3CacheSize")
        if r:
            OUT["cpu"] = r[0] | {"sockets": len(r)}
        else:
            miss("cpu", "Win32_Processor query failed")
        return
    if IS_MAC:
        # perflevel0 = performance cores, perflevel1 = efficiency cores (Apple silicon)
        OUT["cpu"] = sysctl("machdep.cpu.brand_string", "hw.physicalcpu", "hw.logicalcpu",
                            "hw.perflevel0.physicalcpu", "hw.perflevel1.physicalcpu",
                            "hw.l2cachesize", "hw.cpufrequency_max")
        if not OUT["cpu"]:
            miss("cpu", "sysctl failed")
        return
    out = run(["lscpu", "-J"])
    cpu = {}
    if out:
        try:
            for e in json.loads(out)["lscpu"]:
                cpu[e["field"].rstrip(":")] = e["data"]
        except Exception:
            pass
    if not cpu:
        info = read("/proc/cpuinfo") or ""
        m = re.search(r"model name\s*:\s*(.+)", info)
        cpu = {"Model name": m.group(1) if m else None,
               "CPU(s)": str(len(re.findall(r"^processor", info, re.M)))}
    keep = ("Model name", "Architecture", "CPU(s)", "Thread(s) per core", "Core(s) per socket",
            "Socket(s)", "CPU max MHz", "L2 cache", "L3 cache", "Flags")
    OUT["cpu"] = {k: cpu[k] for k in keep if k in cpu}
    if "Flags" in OUT["cpu"]:      # only the flags that matter for inference
        flags = OUT["cpu"]["Flags"].split()
        OUT["cpu"]["Flags"] = [f for f in flags if f.startswith(("avx", "fma", "amx", "sse4", "f16c", "bmi"))]
    gov = read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if gov:
        OUT["cpu"]["scaling_governor"] = gov


# ------------------------------------------------------------------ memory
def probe_memory():
    mem = {}
    if IS_WIN:
        r = ps_json("Get-CimInstance Win32_PhysicalMemory | Select Capacity,Speed,ConfiguredClockSpeed,"
                    "Manufacturer,PartNumber,SMBIOSMemoryType,FormFactor,DataWidth,TotalWidth")
        if r:
            mem["modules"] = [{**m, "capacity_gib": gib(m.get("Capacity"))} for m in r]
            mem["total_installed_gib"] = round(sum(m.get("Capacity") or 0 for m in r) / 2**30, 1)
        else:
            miss("memory.modules", "Win32_PhysicalMemory query failed")
        pf = ps_json("Get-CimInstance Win32_PageFileUsage | Select Name,AllocatedBaseSize,CurrentUsage")
        if pf:
            mem["page_file"] = pf
        os_ = ps_json("Get-CimInstance Win32_OperatingSystem | Select FreePhysicalMemory,TotalVisibleMemorySize")
        if os_:
            mem["os_visible_gib"] = round(os_[0]["TotalVisibleMemorySize"] / 2**20, 2)
            mem["free_now_gib"] = round(os_[0]["FreePhysicalMemory"] / 2**20, 2)
    elif IS_MAC:
        s = sysctl("hw.memsize", "iogpu.wired_limit_mb", "vm.swapusage")
        if "hw.memsize" in s:
            mem["os_visible_gib"] = gib(int(s["hw.memsize"]))
        if "iogpu.wired_limit_mb" in s:
            # GPU-wired memory cap; 0 = macOS default (roughly 2/3-3/4 of RAM)
            mem["gpu_wired_limit_mb"] = int(s["iogpu.wired_limit_mb"])
        if "vm.swapusage" in s:
            mem["swap"] = s["vm.swapusage"]
        hw = sp_json("SPMemoryDataType")
        if hw:
            mem["memory_profiler"] = hw
        mem["note"] = "Unified memory: CPU and GPU share it. Modules are soldered, not listed."
    else:
        info = read("/proc/meminfo") or ""
        for key, name in (("MemTotal", "os_visible_gib"), ("MemAvailable", "available_now_gib"),
                          ("SwapTotal", "swap_gib")):
            m = re.search(rf"^{key}:\s+(\d+) kB", info, re.M)
            if m:
                mem[name] = round(int(m.group(1)) / 2**20, 2)
        dmi = run(["dmidecode", "-t", "memory"]) if shutil.which("dmidecode") else None
        if dmi:
            devs = []
            for blk in dmi.split("\n\n"):
                if "Memory Device" in blk and "Size: No Module" not in blk:
                    g = lambda k: (re.search(rf"^\s*{k}:\s*(.+)$", blk, re.M) or [None, None])[1]
                    devs.append({"size": g("Size"), "type": g("Type"), "speed": g("Speed"),
                                 "configured_speed": g("Configured Memory Speed"),
                                 "manufacturer": g("Manufacturer"), "part_number": g("Part Number"),
                                 "data_width": g("Data Width")})
            mem["modules"] = devs
        else:
            miss("memory.modules", "dmidecode missing or needs root (run the probe with sudo for DIMM details)")
    OUT["memory"] = mem


# ------------------------------------------------------------------ GPU
def probe_gpu():
    gpu = {}
    if IS_WIN:
        r = ps_json("Get-CimInstance Win32_VideoController | Select Name,AdapterRAM,DriverVersion,DriverDate,"
                    "VideoProcessor,PNPDeviceID")
        if r:
            for g in r:
                g["adapter_ram_mib"] = round(g["AdapterRAM"] / 2**20) if g.get("AdapterRAM") else None
                g.pop("PNPDeviceID", None)
            gpu["adapters"] = r
            gpu["note"] = ("AdapterRAM is the dedicated (BIOS carve-out) memory as Windows reports it; "
                           "it can wrap at 4 GiB on older drivers.")
        else:
            miss("gpu.adapters", "Win32_VideoController query failed")
    elif IS_MAC:
        d = sp_json("SPDisplaysDataType")
        if d:
            gpu["adapters"] = [{"Name": g.get("sppci_model"), "cores": g.get("sppci_cores"),
                                "metal": g.get("spdisplays_mtlgpufamilysupport"),
                                "vendor": g.get("spdisplays_vendor")} for g in d]
        else:
            miss("gpu.adapters", "system_profiler SPDisplaysDataType failed")
    else:
        pci = run(["lspci", "-nn"]) if shutil.which("lspci") else None
        if pci:
            gpu["pci"] = [l for l in pci.splitlines() if re.search(r"VGA|3D|Display", l)]
        else:
            miss("gpu.pci", "lspci not installed")
        drm = {}
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]")) if Path("/sys/class/drm").exists() else []:
            d = card / "device"
            vals = {k: read(d / k) for k in ("mem_info_vram_total", "mem_info_gtt_total",
                                              "mem_info_vis_vram_total")}
            vals = {k: gib(int(v)) for k, v in vals.items() if v and v.isdigit()}
            if vals:
                drm[card.name] = vals
        if drm:
            gpu["amdgpu_memory_gib"] = drm
            gpu["note"] = "vram_total is the BIOS carve-out; gtt_total is shared system memory the GPU may map."
        if shutil.which("nvidia-smi"):
            nv = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
            if nv:
                gpu["nvidia_smi"] = nv.strip().splitlines()
    OUT["gpu"] = gpu


def probe_vulkan():
    if IS_MAC:
        miss("vulkan", "not used on macOS (llama.cpp uses Metal)")
        return
    exe = shutil.which("vulkaninfo")
    if not exe:
        miss("vulkan", "vulkaninfo not found")
        return
    text = run([exe]) or ""
    if not text:
        text = run([exe, "--summary"]) or ""
    if not text:
        miss("vulkan", "vulkaninfo produced no output")
        return
    v = {}
    for key in ("deviceName", "driverName", "driverInfo", "apiVersion", "deviceType", "driverID"):
        m = re.search(rf"^\s*{key}\s*=\s*(.+)$", text, re.M)
        if m:
            v[key] = m.group(1).strip()
    heaps = re.findall(r"memoryHeaps\[(\d+)\]:\s*\n\s*size\s*=\s*(\d+)[^\n]*\n(?:\s*budget[^\n]*\n)?(?:\s*usage[^\n]*\n)?\s*flags:\s*\n?\s*(?:count = \d+\s*\n)?\s*([A-Z_|\s]*)", text)
    if heaps:
        v["memory_heaps"] = [{"heap": int(i), "size_gib": gib(int(s)),
                              "device_local": "DEVICE_LOCAL" in f} for i, s, f in heaps]
    OUT["vulkan"] = v


# ------------------------------------------------------------------ storage
def probe_storage():
    st = {}
    if IS_WIN:
        r = ps_json("Get-PhysicalDisk | Select FriendlyName,MediaType,BusType,Size,HealthStatus")
        if r:
            st["physical"] = [{**d, "size_gib": gib(d.get("Size"))} for d in r]
        v = ps_json("Get-CimInstance Win32_LogicalDisk | Select DeviceID,VolumeName,FileSystem,Size,FreeSpace,DriveType")
        if v:
            st["volumes"] = [{"id": x["DeviceID"], "label": x.get("VolumeName"), "fs": x.get("FileSystem"),
                              "size_gib": gib(x.get("Size")), "free_gib": gib(x.get("FreeSpace")),
                              "drive_type": x.get("DriveType")} for x in v]
    elif IS_MAC:
        df = run(["df", "-k", "-l"])
        if df:
            st["filesystems_kib"] = df.strip().splitlines()
        sp = sp_json("SPStorageDataType")
        if sp:
            st["volumes"] = [{"name": v.get("_name"), "size_bytes": v.get("size_in_bytes"),
                              "free_bytes": v.get("free_space_in_bytes"),
                              "medium": (v.get("physical_drive") or {}).get("medium_type")} for v in sp]
    else:
        out = run(["lsblk", "-J", "-b", "-o", "NAME,MODEL,SIZE,ROTA,TRAN,TYPE,MOUNTPOINT"]) if shutil.which("lsblk") else None
        if out:
            try:
                st["block_devices"] = json.loads(out).get("blockdevices")
            except ValueError:
                pass
        df = run(["df", "-B1", "--output=source,size,avail,target", "-x", "tmpfs", "-x", "devtmpfs"])
        if df:
            st["filesystems"] = df.strip().splitlines()
    if not st:
        miss("storage", "no storage probe worked")
    OUT["storage"] = st


# ------------------------------------------------------------------ software / llama.cpp
def probe_llama():
    sw = {}
    for name in ("llama-server", "llama-bench", "llama-cli"):
        exe = shutil.which(name)
        if not exe:
            continue
        entry = {"path": exe}
        ver = run([exe, "--version"], timeout=30, merge_stderr=True)
        if ver:
            entry["version"] = " ".join(ver.split())[:300]
        sw[name] = entry
    srv = sw.get("llama-server")
    if srv:
        dev = run([srv["path"], "--list-devices"], timeout=60)
        if dev:
            sw["devices"] = [l.strip() for l in dev.splitlines() if re.search(r"MiB|GiB", l)]
    if not sw:
        miss("llama_cpp", "no llama-* binaries on PATH")
    for env in ("LLAMA_MODELS_DIR", "LLAMA_ARG_MODELS_DIR", "LLAMA_CACHE", "HF_HOME", "HF_HUB_CACHE"):
        if os.environ.get(env):
            sw.setdefault("env", {})[env] = os.environ[env]
    OUT["llama_cpp"] = sw


def probe_power():
    if IS_WIN:
        out = run(["powercfg", "/getactivescheme"])
        if out:
            OUT["power"] = {"active_scheme": out.strip(),
                            "note": "Vendor power modes (laptop vendor tools) are not readable; ask the user."}
    elif IS_MAC:
        out = run(["pmset", "-g"])
        if out:
            OUT["power"] = {"pmset": [l.strip() for l in out.splitlines()
                                      if re.search(r"powermode|lowpowermode|highpowermode|sleep|AC Power|Battery", l)]}
    else:
        OUT["power"] = {"governor": read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
                        "platform_profile": read("/sys/firmware/acpi/platform_profile")}


# ------------------------------------------------------------------ main
def summary():
    L = ["", "== probe summary =="]
    m = OUT.get("machine", {})
    vendor = m.get("manufacturer") or m.get("sys_vendor") or ("Apple" if IS_MAC else "")
    model = m.get("model") or m.get("product_name") or m.get("model_name") or m.get("hw.model") or ""
    L.append(f"machine : {(vendor + ' ' + model).strip() or 'unknown'}")
    c = OUT.get("cpu", {})
    L.append(f"cpu     : {c.get('Name') or c.get('Model name') or c.get('machdep.cpu.brand_string')}  "
             f"({c.get('NumberOfCores') or c.get('Core(s) per socket') or c.get('hw.physicalcpu')} cores / "
             f"{c.get('NumberOfLogicalProcessors') or c.get('CPU(s)') or c.get('hw.logicalcpu')} threads)")
    mem = OUT.get("memory", {})
    L.append(f"memory  : {mem.get('os_visible_gib')} GiB visible; modules: "
             f"{len(mem.get('modules', []))}")
    for g in OUT.get("gpu", {}).get("adapters", []):
        if IS_MAC:
            L.append(f"gpu     : {g.get('Name')}  {g.get('cores')} cores  (unified memory, Metal)")
        else:
            L.append(f"gpu     : {g.get('Name')}  dedicated {g.get('adapter_ram_mib')} MiB  driver {g.get('DriverVersion')}")
    for line in OUT.get("gpu", {}).get("nvidia_smi", []):
        L.append(f"gpu     : {line}")
    for d in OUT.get("llama_cpp", {}).get("devices", []):
        L.append(f"llama   : {d}")
    if OUT["unavailable"]:
        L.append("unavailable: " + "; ".join(f"{k} ({v})" for k, v in OUT["unavailable"].items()))
    print("\n".join(L), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    for fn in (probe_os, probe_machine, probe_cpu, probe_memory, probe_gpu, probe_vulkan,
               probe_storage, probe_llama, probe_power):
        try:
            fn()
        except Exception as e:  # noqa - a failing sub-probe must not stop the rest
            miss(fn.__name__, f"{type(e).__name__}: {e}")
    clean = redact(json.loads(json.dumps(OUT, default=str)))   # the one privacy choke point
    OUT.clear()
    OUT.update(clean)                                         # so --summary prints it redacted too
    text = json.dumps(OUT, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    if args.summary:
        summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
