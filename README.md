# llama-rigger

**Find, try and tune the best local coding LLM your machine can actually run.**

llama-rigger pairs [llama.cpp](https://github.com/ggml-org/llama.cpp)'s router
mode with a set of agent skills: plain-Markdown `SKILL.md` instructions plus
small Python scripts, which any coding agent can follow (Claude Code, Codex,
OpenCode, Cursor, ...). It is built mainly for **local coding models**: the ones you run behind a coding agent,
for code review or for security triage. Its benchmark grades models on writing
code and on finding and fixing vulnerabilities, and its presets are sized for
long agent sessions and parallel subagents. Other uses (chat, OCR, long
documents) work too.

You tell your agent what you want a model for; the skills work out what fits in your
memory, try candidates out safely, benchmark them, and tune their settings. What
you end up with is a ready-to-run preset file and a router that swaps models in
and out on demand.

## The skills

Just ask in plain words; your agent picks the right skill.

| Skill | What it does | Try asking |
|---|---|---|
| **get-system-info** | Measures your machine (CPU, GPU, memory, bandwidth, llama.cpp build) and looks up the published specs, so every other skill knows what it's working with. The other skills run it for you when the info is missing or out of date. | "What hardware is this?" |
| **suggest-models** | Researches current open-weight models for your use case and shortlists the GGUF quants that fit your memory, with expected speed and evidence. | "What model should I use for code review?" |
| **tryout-model** | Takes a Hugging Face link (or a suggestion), downloads it, runs it on a private trial router next to your main one, smoke-tests and benchmarks it, and writes a trial report. Keep it and it joins your presets; drop it and nothing else changed. | "Try out hf.co/unsloth/Qwen3.6-35B-A3B-GGUF" |
| **tune-model** | Finds the fastest llama.cpp settings for each model (batch sizes, flash attention, threads, KV cache, MTP draft length), separately per power mode, and proposes the edits. | "Tune my models" or "Why is prefill slow?" |
| **benchmark-model** | Scores your models on finding and fixing real vulnerabilities and on coding, graded by compilers and tests, plus speed. | "Which of my models is best at finding bugs?" |

A typical first session runs top to bottom: ask for a suggestion and the system
info is gathered first, try out the one you like, then tune and benchmark the
models you keep. Nothing is downloaded, deleted or edited without your yes.

## What's in the repo

- `start-llama.cmd` / `start-llama.sh`: the launcher. It starts one
  router on `127.0.0.1:9931` that loads whichever model a client asks for and
  evicts others to stay within your memory budget.
- `models.example.ini`: a sample preset file to start from.
- `AGENTS.md`: the rules the skills follow (memory, speed, llama.cpp quirks).
- `.agents/skills/`: the skills themselves.

Your own setup stays yours: presets, measurements and trial reports live in a
`local/` folder that this repo ignores. Make it a private git repo if you want it
versioned.

## Get started

1. [Install the prerequisites](docs/install.md) for Windows, macOS or Linux.
2. [Set up and run](docs/setup.md): create `local/`, start the router, open
   your agent in the repo.

Runs on Windows, Linux and macOS, with unified memory (Apple silicon, AMD Strix
Halo) or a discrete GPU (NVIDIA / AMD cards). GGUF models only. Developed on a
Windows Strix Halo laptop and checked on Linux under WSL; macOS and NVIDIA haven't
been run yet, so reports are very welcome.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
