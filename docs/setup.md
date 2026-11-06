# Setting up and running

Install the prerequisites first: [install.md](install.md).

## First-time setup

1. Clone this repo. Put GGUF files under `models/` (git-ignored), or let
   `tryout-model` download them there.
2. Create your private config folder `local/` (git-ignored by this repo; make it
   its own private git repo if you want it versioned):

   ```
   mkdir local
   copy models.example.ini local\models.ini      # Windows
   cp models.example.ini local/models.ini        # Linux, macOS
   ```

   Edit `local/models.ini` for your models. The skills also keep their
   machine-specific output here (`SYSTEM_INFO.md`, `TUNING_STATUS.md`,
   `tryouts/`, `benchmark-config.json`, `ppl_text.txt`), and `local/AGENTS.md`
   can hold machine-specific notes for agents.
3. Make the skills visible to your agent. They live in `.agents/skills/`, one
   folder per skill with a `SKILL.md`, and the repo's rules are in `AGENTS.md`.
   - Agents that read skills from `.agents/skills/` find them as they are.
   - **Claude Code** reads `.claude/skills/`, a link to `.agents/skills/`. On
     Windows a session hook creates it; on Linux/macOS create it once from the
     repo root: `ln -s ../.agents/skills .claude/skills`.
   - Any other agent: point it at `AGENTS.md` and the `SKILL.md` files (e.g. "read
     `.agents/skills/suggest-models/SKILL.md` and follow it").
4. Start your agent in the repo and ask it to "update the system info", then
   "suggest a model for <your use case>" or "try out <Hugging Face link>".

## Running the router

```
start-llama-ini            # Windows
./start-llama-ini.sh       # Linux, macOS
```

This uses `$LLAMA_PRESET`, else `local/models.ini`, else `models.example.ini`,
and is equivalent to:

```
llama-server --models-preset local/models.ini --host 127.0.0.1 --port 9931 --models-max 1
# or, with a memory margin set:  ... --models-max 0 --models-memory-margin N
```

`--help` lists every option. On Windows it opens a new console window (`--here`
runs it in the current one); on Linux/macOS it runs in the foreground
(`nohup ./start-llama-ini.sh > router.log 2>&1 &` to background it).

The router swaps models itself: a request for a preset that isn't loaded loads
it, and it unloads others automatically in one of two ways.

- **One at a time (the default).** With no memory margin set, the launcher
  passes `--models-max 1`: requesting another model unloads the current one
  first. Safe on any machine, including a 16 GB one.
- **By memory.** Set a margin and the launcher passes
  `--models-max 0 --models-memory-margin N`: several models stay loaded, and the
  least-recently-used ones are unloaded only when a new one wouldn't fit. `N` is
  the MiB of GPU memory to keep free: (your GPU's memory MiB − the budget you
  want for models). For example, a 104,671 MiB Vulkan heap with a 96 GiB budget
  gives 6367; a 24 GiB card with a 22 GiB budget gives 2048. Put it in an
  optional `local/env.cmd` (Windows) or `local/env.sh` (Linux, macOS), which the
  launcher runs before it starts:

  ```
  @if not defined LLAMA_MODELS_MEMORY_MARGIN set "LLAMA_MODELS_MEMORY_MARGIN=6367"   & rem env.cmd
  LLAMA_MODELS_MEMORY_MARGIN="${LLAMA_MODELS_MEMORY_MARGIN:-6367}"                   # env.sh
  ```

llama-server's own defaults would not unload anything (its margin defaults to 0,
disabled), which is why the launcher always sets one of these. Presets also
unload after `sleep-idle-seconds` of idleness (900 s in the example's `[*]`).

## Optional machine config in `local/`

- `env.cmd` / `env.sh`: launcher defaults (`LLAMA_MODELS_MEMORY_MARGIN`,
  `LLAMA_PORT`, `LLAMA_PRESET`, ...).
- `tune-modes.json`: power-mode names for `tune-model` and the power plan or
  profile the OS reports in each (see the skill).
- `benchmark-config.json`: overrides for `benchmark-model` (e.g. the model list).
