# What `probe.py` reads, per OS

Read this when a field comes out empty or wrong: find the source here, check the
`unavailable` list in `results/probe.json`, and fix `probe.py`.

| Area | Windows | Linux | macOS |
|---|---|---|---|
| OS | `Win32_OperatingSystem` | `/etc/os-release`, kernel, WSL detection, kernel command line | `sw_vers` |
| Machine, BIOS | `Win32_ComputerSystem`, `Win32_BIOS` | `/sys/class/dmi/id` | `sysctl hw.model`, `system_profiler SPHardwareDataType` (serial/UUID dropped) |
| CPU | `Win32_Processor` | `lscpu -J` (inference-relevant flags only), governor | `sysctl` (brand, physical/logical, P- and E-cores) |
| Memory | `Win32_PhysicalMemory` (per module speed, configured speed, width), page file, free now | `/proc/meminfo`; per-DIMM detail needs `dmidecode` as root | `hw.memsize`, `iogpu.wired_limit_mb` (GPU cap), `SPMemoryDataType` |
| GPU | `Win32_VideoController` (dedicated memory = BIOS carve-out) | `lspci`, amdgpu `mem_info_vram_total` / `mem_info_gtt_total`, `nvidia-smi` | `SPDisplaysDataType` (GPU cores, Metal family) |
| Vulkan | `vulkaninfo`: device, driver, memory heaps (device-local or not) | same | not used (Metal) |
| Storage | `Get-PhysicalDisk`, logical volumes | `lsblk -J`, `df` | `df -k -l`, `SPStorageDataType` |
| llama.cpp | binaries on PATH, `--version`, `llama-server --list-devices`, `LLAMA_*` / `HF_*` variables | same | same |
| Power | `powercfg /getactivescheme` | governor, ACPI platform profile | `pmset -g` (power mode, low power mode) |

Test status: Windows has run for real. Linux has run under WSL (Ubuntu 22.04),
where `/sys/class/dmi`, `lspci` and `vulkaninfo` are usually missing; bare-metal
Linux has not run. The macOS paths were written from Apple's documented tools and
checked only against simulated output: they have not run on a Mac.
