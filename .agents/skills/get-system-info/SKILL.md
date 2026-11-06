---
name: get-system-info
description: Probe this machine's hardware and llama.cpp setup (Windows, Linux or macOS), look up the published specs of what it finds, and write local/SYSTEM_INFO.md. Use when the user asks what hardware this is or to refresh the system info, or after a BIOS, driver, llama.cpp or hardware change.
---

# get-system-info

Builds a dated picture of the machine in `local/SYSTEM_INFO.md`, the file the
other skills read for memory, bandwidth, GPU and build. It is machine-specific,
so it lives in the private `local/` repo. Every fact in it is one of two kinds,
and the file says which:

- **Measured**: read from this machine by `probe.py` (read-only, standard library;
  skips serial numbers, MAC addresses, host and user names).
- **Looked up**: published specs from the web, each with its source URL. A
  looked-up value sits beside a measured one, never replaces it; if they disagree,
  report both.

Some settings no tool reads: vendor GPU-memory sliders (e.g. AMD Adrenalin's),
the BIOS UMA frame-buffer size beyond what the OS reports, and vendor power modes.
Ask the user, or mark them "unknown".

## Procedure

1. **Probe** from this folder: `python probe.py --out results/probe.json --summary`
   (`python3` on Linux/macOS). On Linux, if `memory.modules` is unavailable, offer
   to re-run with `sudo` (DIMM speed and type need root) and run it only after a
   yes. Note everything under `unavailable`; [PROBES.md](PROBES.md) lists each
   field's source per OS for when one comes out empty or wrong.

2. **Read the existing `local/SYSTEM_INFO.md`** if there is one. Keep hand-written
   notes that are still true; correct what the probe contradicts and say so.

3. **Look up what the probe can't tell you**, for each distinct component: CPU or
   APU model; GPU model (compute units, architecture, rated bandwidth); memory type
   and rated speed from the module part number; the machine model (what the vendor
   says about memory, upgradeability, power modes); the NVMe model if it matters.
   Search the web, preferring the manufacturer's own pages; treat blogs and forums
   as weak and say so. Done when every component has a looked-up fact with a URL,
   or "not found".

4. **Derive, showing the formula**, and mark each "derived, not measured": e.g.
   theoretical bandwidth = bus width (bits) / 8 × configured MT/s (the *configured*
   speed, which can be lower than rated); installed vs OS-visible memory; the
   GPU-usable pool (llama.cpp reports Vulkan's device-local + shared heaps as the
   device size).

5. **Write `local/SYSTEM_INFO.md`**, dated with the probe date, with sections:
   - **Hardware**: machine, CPU, GPU, RAM (modules, rated vs configured speed,
     bandwidth), storage, OS-visible memory.
   - **GPU memory**: first, unified (Apple silicon, APUs) or discrete (own VRAM);
     then BIOS dedicated memory, Vulkan heaps / VRAM / macOS GPU wired limit, the
     pool llama.cpp sees, free now; what is not readable and, if the user said, its
     value with who said so and when.
   - **Software**: OS build, GPU driver (version and date), Vulkan API, llama.cpp
     build and devices, relevant environment variables.
   - **Power**: the active plan, and the vendor mode if the user told you.
   - **Sources**: the URLs used.
   - **Notes**: carried-forward hand-written notes.
   Link `../AGENTS.md` and `TUNING_STATUS.md` at the top.

6. **Confirm the public repo ignores it:** from the repo root,
   `git check-ignore -v local/SYSTEM_INFO.md` prints the `/local/` rule. If it
   doesn't, stop and tell the user.

7. **Report what changed** since the previous file (memory pool, driver, build,
   BIOS version, free disk). If the GPU pool size changed, the launcher's memory
   margin (pool minus budget, `AGENTS.md` 1a/1b) may need recomputing: say what to
   change and leave the edit to the user.
