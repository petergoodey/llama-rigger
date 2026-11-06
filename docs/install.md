# Installing the prerequisites

| Tool | Needed for |
|---|---|
| **llama.cpp** (`llama-server`, `llama-bench`, `llama-perplexity` on `PATH`) | everything. Vulkan builds need b10795 or later. |
| **Python 3.10+** | every skill script (standard library only; nothing to `pip install`) |
| **A coding agent** that can run shell commands (Claude Code, Codex, OpenCode, Cursor, ...) | running the skills. The commands below install Claude Code; skip that line if you use another agent. |
| **Git** | cloning; your private `local/` repo |
| **`hf` CLI** (Hugging Face) | downloading models (`tryout-model`) |
| **C/C++ compiler with AddressSanitizer** | `benchmark-model` grading of the C/C++ tasks |
| **.NET 10 SDK** | `benchmark-model` grading of the C# tasks |
| `vulkaninfo` (optional) | `get-system-info`'s Vulkan heap details |

## Windows

From PowerShell:

```powershell
winget install ggml.llamacpp                # llama.cpp, Vulkan build (AMD, Intel, NVIDIA)
winget install Python.Python.3.12
winget install Git.Git
winget install Anthropic.ClaudeCode         # or your agent of choice
winget install astral-sh.uv
uv tool install "huggingface_hub[hf_xet]"   # provides the hf command
winget install Microsoft.DotNet.SDK.10
winget install Microsoft.VisualStudio.BuildTools --override "--add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.ASAN --includeRecommended --passive --wait"
winget install KhronosGroup.VulkanSDK       # optional: vulkaninfo
```

- NVIDIA: the winget build uses Vulkan, which works. For CUDA, download a
  `llama-*-bin-win-cuda-*.zip` from the
  [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) and put its
  folder on `PATH` instead.
- The Build Tools install gives MSVC (`cl.exe`) with AddressSanitizer; an existing
  Visual Studio with the "Desktop development with C++" workload and the "C++
  AddressSanitizer" component works too. Check with
  `python .agents\skills\benchmark-model\_vcenv.py` (prints `"msvc": true`).
- Open a new terminal after installing so `PATH` picks everything up.

## macOS (Apple silicon)

```bash
xcode-select --install                     # Apple clang, with AddressSanitizer
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   # if Homebrew is missing
brew install llama.cpp python git uv       # llama.cpp uses Metal
brew install --cask dotnet-sdk
uv tool install "huggingface_hub[hf_xet]"  # provides the hf command
curl -fsSL https://claude.ai/install.sh | bash   # Claude Code, or your agent of choice
```

## Linux (Debian / Ubuntu; use your distro's equivalents elsewhere)

```bash
sudo apt update
sudo apt install -y python3 git curl build-essential clang cmake pciutils
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install "huggingface_hub[hf_xet]"  # provides the hf command
curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0
curl -fsSL https://claude.ai/install.sh | bash   # Claude Code, or your agent of choice
```

llama.cpp, built from source with the backend for your GPU:

```bash
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
# Vulkan (AMD, Intel, NVIDIA):
sudo apt install -y libvulkan-dev glslc vulkan-tools
cmake -B build -DGGML_VULKAN=ON
# or CUDA (NVIDIA, with the CUDA toolkit installed): cmake -B build -DGGML_CUDA=ON
# or ROCm (AMD): see llama.cpp's docs/build.md
cmake --build build --config Release -j
export PATH="$PWD/build/bin:$PATH"         # add to ~/.bashrc to keep it
```

- Pre-built Linux binaries (`llama-*-bin-ubuntu-*.zip`) are on the
  [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) page too.
- `dotnet-install.sh` puts the SDK in `~/.dotnet`: add it to `PATH`
  (`export PATH="$HOME/.dotnet:$PATH"`).
- Optional for `get-system-info`: `dmidecode` (memory module details, needs
  `sudo`) and `vulkan-tools` (`vulkaninfo`).

## Check

```
llama-server --version
python --version            # python3 on Linux/macOS
hf version
dotnet --version            # 10.x
```

Next: [setup.md](setup.md).
