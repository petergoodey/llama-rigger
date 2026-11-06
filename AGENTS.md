# Agent notes

Rules for running llama.cpp's router (`llama-server --models-preset`) on Windows,
Linux or macOS, with unified memory (section 1a) or a discrete GPU (1b). Find out
which one this machine has first (`local/SYSTEM_INFO.md`, or run
`get-system-info`). Every model is a GGUF run by llama.cpp; recommend and
configure nothing else.

**This repo is public and generic; machine-specific facts, policy and data live
in `local/`**, a separate private git repo ignored here. Write anything about
this machine (measurements, model inventory, the real preset file) under
`local/`. `local/AGENTS.md` adds to these rules and wins where they differ:

@local/AGENTS.md

Layout:
- Launcher: `start-llama.cmd` (Windows) / `start-llama.sh` (Linux,
  macOS). `--help` has the preset lookup, defaults and env vars.
- Presets: `local/models.ini` (the real one), else `models.example.ini`;
  `LLAMA_PRESET` overrides. The launcher and every skill use the same lookup.
- Skills: `.agents/skills/` is the tracked copy. `.claude/skills` is a junction
  (Windows) or symlink to it and is git-ignored, because git would follow it and
  commit every skill twice. A `SessionStart` hook recreates the junction on
  Windows; on Linux/macOS: `ln -s ../.agents/skills .claude/skills`.
- `**/results/` (benchmark and tuning output) is git-ignored, local only.

---

## 1a. Unified memory (Apple silicon, AMD Strix Halo)

- CPU and GPU share one physical pool of RAM. "Offloading to GPU" copies nothing
  over a PCIe bus; it decides which compute units read the weights. Always use
  full GPU offload (`ngl = 999`).
- The GPU memory heap the backend reports (Vulkan heap, or Metal's
  `recommendedMaxWorkingSetSize`) is a cap on that same RAM, not separate memory.
  On macOS the cap is `iogpu.wired_limit_mb` (0 = the OS default, roughly 2/3 to
  3/4 of RAM); raising it is the user's decision.
- **Memory budget:** what models may use after the OS and apps. The launcher's
  margin is (GPU heap MiB − budget MiB).

## 1b. Discrete GPU (NVIDIA / AMD cards)

- VRAM and system RAM are separate. Weights in VRAM are read at the card's
  bandwidth (hundreds of GB/s to ~2 TB/s); weights spilled to system RAM are read
  by the CPU at RAM speed (often 10-20x slower) and dominate decode time.
- `ngl = 999` only when model + KV + compute fit in VRAM. Otherwise keep attention
  and KV on the GPU and spill weights: for MoE models `n-cpu-moe = N` (or
  `override-tensor` on the expert tensors) beats a lower `ngl`, because the
  rarely-used experts are what belongs in RAM.
- The router's `--models-memory-margin` counts **device** memory (VRAM): set it
  to (VRAM MiB − the VRAM budget). Check spilled weights against system RAM
  yourself.
- Several GPUs: llama.cpp splits layers across them (`split-mode`, `tensor-split`).
- NVIDIA usually runs a CUDA build, Vulkan also works: `llama-server --list-devices`
  shows which.

## 1c. Both

- `cache-ram` (the prompt-state pool) is system RAM that fills lazily, and **the
  router's memory margin doesn't count it.** Large `cache-ram` values on several
  loaded models can exhaust RAM after every model loaded fine.
- Size `cache-ram` from the "removing oldest entry (size = N MiB)" log lines:
  about 4× the largest entry holds ~4 states.

---

## 2. Measuring

- **Every measurement carries its power mode**, and only same-mode numbers are
  compared. Low-power modes mostly slow prefill (compute-bound). The user switches
  modes; `tune-model` reads and checks the current one.
- A tuning or benchmark run has the machine to itself: other heavy jobs share the
  memory bandwidth and skew it.
- Decode is **memory-bandwidth-bound** everywhere; what differs is which
  bandwidth (1a / 1b). Decode t/s ≈ bandwidth ÷ bytes read per token, where bytes
  per token ≈ active parameters × bits per weight (plus spilled bytes at RAM
  bandwidth on a discrete GPU). It is a rough guide: quant speed ratios often
  differ from it, so measure.
- **Prefill** is compute-bound, depends on power mode and quant type (Q8_0
  unpacks cheaply on Vulkan) and **decays sharply with context depth**. Spilled
  weights slow it too (they cross PCIe).
- **Two loaded models decoding at once halve each other** (shared bandwidth on one
  device): one model with several batched slots (`parallel`) beats two models side
  by side.
- **MTP speculative decoding** (`spec-type = draft-mtp`) is a lossless speed-up that
  pays off well when bandwidth-bound. It needs a GGUF with an MTP head (e.g. the
  `unsloth/...-MTP-GGUF` repos), `parallel = 1` and no `mmproj`. Judge
  `spec-draft-n-max` by **mean accepted length**, not acceptance rate.

---

## 3. llama.cpp flags (old advice online is often wrong)

Backends: Vulkan (AMD, Intel, also NVIDIA), CUDA (NVIDIA), Metal (macOS), ROCm/HIP
(AMD). This machine's build: `local/SYSTEM_INFO.md`.

- `--no-mmap` / `no-mmap = true` **no longer exist.** Use `--load-mode` (`-lm`):
  `auto | none | mmap | mlock | mmap+mlock | dio`. `none` is the old no-mmap.
- `--draft-max` / `--draft-n` were **removed**. Use `--spec-draft-n-max` (default 3).
- `--spec-type` supports `draft-mtp` along with `draft-simple`, `draft-eagle3`,
  `draft-dflash`, `draft-dspark` and the `ngram-*` types.
- Router options: `--models-preset`, `--models-max` (default 4, 0 = no limit),
  `--models-memory-margin N` (MiB to keep free; unloads least-recently-used models
  until a new one fits; **default 0 = disabled**), `--models-autoload`,
  `--sleep-idle-seconds`. With `--models-max 0` and no margin nothing ever
  unloads, so the launcher passes either a margin (`--models-max 0`) or
  `--models-max 1` (swap on request).
- `--jinja` defaults on, but presets still set `jinja = true` explicitly. Keep it:
  tool calling breaks without it.
- On Vulkan, the build must include PR **#27812** (view-alias fix, b10795+).
  Before it, AMD Vulkan silently produced wrong tokens on recurrent-state models.

---

## 4. Router rules

- Clients pick a preset by section name: the GGUF file name without `.gguf` (plus
  a role suffix for extra presets on the same file). The router loads it on first
  request and evicts others as memory requires.
- `model =` paths in presets are absolute.
- Presets are **only validated when the first request spawns the model**: a bad
  key still shows up fine in `/v1/models`. Send one request after every edit.
- Edits apply on the model's **next cold start**; a busy model never idles out.
  New sections need a router restart (presets are read only at start).
- **The settings in effect are in `GET /props` and `GET /slots`, not the ini.**
  The router's own startup line misreports `n_parallel` (#23135); read the child
  process's log.
- `c` is the **total** KV budget and `parallel` splits it (c = 131072 with
  parallel = 3 gives ~43K per slot). An explicit `parallel` partitions KV unless
  `kv-unified = true`.
- Set `parallel` equal to the client's subagent concurrency limit. Above it,
  requests queue invisibly inside llama-server.
- `host`, `port`, `api-key`, `alias` and `models-max` are router-owned and
  ignored inside presets.
- Launcher extra args come after its defaults. **Unverified:** that llama-server
  lets a later duplicate flag win; check the startup log.
