---
name: tune-model
description: Tune llama.cpp settings (ubatch, batch, flash-attn, threads, load-mode, KV cache type, MTP draft length) per local GGUF with llama-bench, once per power mode, and propose models.ini edits. Use when the user wants faster prefill or decode, the best settings for a model, or to see how the power mode moves them ("tune the models", "is q8_0 KV worth it", "why is prefill slow").
---

# tune-model

Finds the fastest llama.cpp settings for each GGUF and proposes edits to the
preset ini (`local/models.ini`, or `LLAMA_PRESET`). The ini changes only after
the user approves the diff.

## What it measures

`llama-bench` with synthetic tokens: **pp4096** (prefill) and **tg128** (decode).
Score = √(prefill t/s × decode t/s), so a 10% gain in either counts equally.

- The **baseline** is each model's current preset. Then it tunes **one variable
  at a time, keeping the best so far**: ubatch → batch → flash-attn → threads →
  load-mode → KV cache type. Presets that spill weights on a discrete GPU
  (`n-cpu-moe`, lower `ngl`) are benchmarked with that spill.
- Sweeps use a cheap **proxy depth (4096)**, because llama-bench refills the
  context before every repetition. The baseline and the winner are then
  re-measured at the **real depth (16384)**, and that is the number judged.
- A change is adopted only if it beats the incumbent by **≥ 2%** (the noise
  floor), and still does at 16K.
- **q8_0 KV cache** is recommended only if it is ≥ 2% faster **and**
  `llama-perplexity` on `local/ppl_text.txt` rises < 1% vs f16. A crash or a
  failed check means "not recommended".
- Limits to tell the user: synthetic tokens (no real MoE expert routing, no
  prompt-cache effects, no speculative decoding); throughput only (load-mode's
  real benefit, load time and no second page-cache copy, is invisible).

**MTP presets** (`spec-type = draft-mtp`) are tuned for everything above by
`tune.py` without speculation; their `spec-draft-n-max` is tuned by
`mtp_tune.py`: read [MTP.md](MTP.md) when the run includes one.

## Power modes

The optimum can move with the power mode, so a model is fully tuned after **one
run per mode** the user cares about (`local/AGENTS.md` names them). The mode
names and the OS power plan each one expects come from `local/tune-modes.json`,
else per-OS defaults; `--check-env` prints both the mapping and the active plan.

- The user switches modes; you ask, then verify with `--check-env`.
- `--mode <name>` **refuses to run (exit 4)** when the active plan doesn't match,
  so a run can't be mislabelled (`--no-mode-check` overrides).
- The mode stays fixed for the whole run.
- The second mode's run uses `--seed-from <first run>`: it also measures the first
  mode's optimum, giving the cost of using one setting for both modes.
- The ini holds **one** set of settings. When the modes' optima differ, show both
  and let the user choose (usually the mode they run in most, or the setting with
  the smaller cross-mode cost).

## Procedure

Run from this folder with `python` (Windows) or `python3`.

1. **Check the environment:** `python tune.py --check-env`: power plan and modes,
   whether `llama-server` is running, tools, and every GGUF with its preset
   baseline.

2. **Ask the user** before launching (one round of questions):
   - **which models** (multi-select, default all; dense and very large models take
     much longer than small-active MoEs);
   - **which parameters** (multi-select: `ubatch`, `batch`, `fa`, `threads`,
     `loadmode`, `kv`);
   - **if the router is running:** "stop it and restart it afterwards"
     (`--stop-router --restart-after`), "stop it, I'll restart" (`--stop-router`),
     or "run anyway" (`--ignore-router`, skewed numbers);
   - **which power mode(s)**: say which mode the active plan corresponds to, and if
     it isn't the one to measure first, ask them to switch and tell you. If
     `results/*/meta.json` shows a mode already tuned for these models, offer just
     the other one.

3. **Run it** in the background (it is long; follow `results/<run>/progress.log`):
   `python tune.py --models <names> --params <list> --mode <mode> [--seed-from <first run>] [--stop-router --restart-after]`.
   `--run <id>` resumes an interrupted run; `--dry-run` checks the plan and the
   mode guard; `--help` has the rest. Give the user a time estimate: a full
   all-parameter run of a 35B-A3B Q4 MoE on a Strix Halo laptop took ~14.5 min;
   big and dense models and slower machines take longer. Re-estimate from
   `progress.log` after the first stage.

4. **Summarise `results/<run>/tuning.md`**: for every model in the run, baseline vs
   recommended score at 16K, the settings to change, the KV-guard verdict, and
   anything surprising (a stage that errored, a winner that didn't hold at 16K).
   State the power mode.

5. **Propose the ini edits:** `python apply_ini.py --run <run>` shows the diff and
   writes nothing; after the user agrees, `--apply` (it backs the ini up first).
   It edits each GGUF's primary preset; list the other presets on the same file so
   the user can mirror the change. Settings apply on each preset's next cold
   start. If one mode is still unmeasured, say so.

6. **When every wanted mode is done:** `python compare_modes.py` → `results/modes.md`.
   Summarise per model: same optimum in both modes or not, what each mode is
   worth, the cross-mode cost. Propose edits for the mode the user chooses.

`make_ppl_text.py` builds `local/ppl_text.txt` (it embeds the preset ini, hence
private). Run it once per machine; rebuilding it makes earlier perplexity numbers
incomparable.
