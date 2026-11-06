---
name: tryout-model
description: Trial a GGUF model before adding it: download, run on a private router, smoke-test, benchmark, report, then keep or drop. Use when the user gives a Hugging Face link to try ("try this model", "test hf.co/org/repo"), or wants to try a new model without naming one (it starts with suggest-models).
---

# tryout-model

A **trial** takes one GGUF from a Hugging Face link to a verdict. The trial runs
on a private router (port 9947) from its own preset file, `local/tryout.ini`, so
the main router and `local/models.ini` change only when the user keeps the model.

Every trial leaves a **trial report**, `local/tryouts/<preset>.md` (tracked in
the private repo), rendered from `local/tryouts/<preset>.json`. `tryout.py draft`,
`smoke` and `record` update it, so it is current after every step and a trial
that stops half-way still has one.

Run the scripts from this folder with `python` (Windows) or `python3`.

- `hf_gguf.py <link>`: the repo's GGUF variants (shards grouped, mmproj paired),
  sizes, what is already on disk, free disk space, and per variant the download
  command and `model_path` (under `models/`). Takes any link form, including
  `org/repo:QUANT`.
- `gguf_info.py <path-or-url>`: reads only the GGUF header (a few MB over HTTP)
  and prints architecture, context length, MTP layers and the `fit.py` KV
  arguments. For split models give the first shard.
- `tryout.py draft|memory|serve|status|smoke|stop|record|promote`: the trial
  router and the trial record. `--help` has the options.
- `../suggest-models/fit.py`: the memory and speed arithmetic.

## Steps

1. **Pick the candidate.** If the user gave a link, use it. Otherwise run the
   `suggest-models` skill for their use case and let them choose one entry from
   its shortlist; its Hugging Face repo is the link. Done when you hold one repo
   link and the use case it is for (that decides context length and `parallel`).

2. **Inspect the repo:** `python hf_gguf.py <link>`. If it has no GGUF files,
   stop and say so in one line. Note licence, gated status (a gated repo needs
   `HF_TOKEN` and the user's accepted terms), architecture and free disk space.

3. **Size it.** Read the memory budget and bandwidth from `local/AGENTS.md` and
   `local/SYSTEM_INFO.md` (missing: run `get-system-info` first). For the two or
   three quants that could fit, run `gguf_info.py <first_file_url>`, then
   `fit.py ... --json` with its `fit_args` at the context the use case needs (the
   `--vram-gib` mode on a discrete GPU). Run `python tryout.py memory` to see what
   the main router has loaded: the two routers do not see each other's memory.
   Done when you have one recommended quant, its footprint and headroom (next to
   what is loaded), the download size against free disk, and the `c` / `parallel`
   to start with. Carry `gguf_info.py`'s notes forward (MTP head, sliding window,
   recurrent layers).

4. **Ask before downloading**: the quant (recommended first,
   with size and headroom), the context, and a plain go-ahead for the download
   size. A model already on disk (`on_disk`) skips the download; say so.

5. **Download** with the variant's `download` command from `hf_gguf.py --json`
   in the background (tens of GB take a while). Done when every file of the
   variant exists at `model_path` and the sizes match the listing.

6. **Draft the trial preset and open the report:**
   `python tryout.py draft --name <preset> --model <model_path> [--mmproj <mmproj_path>] --ctx <c> --parallel <n> --source "<repo>"`,
   then `python tryout.py record --name <preset> --quant <quant> --license <licence> --download-gib <GiB> --power-mode <mode> --fit <fit.py json file>`.
   The preset name is the GGUF file name without `.gguf` and without the
   `-0000N-of-0000N` suffix. Add `--mtp 2` only when the model has MTP layers,
   no mmproj and `parallel = 1`. On a discrete GPU that cannot hold the weights,
   add `--set n-cpu-moe=<N>` (MoE) per `AGENTS.md` 1b. The draft copies `[*]`
   from `local/models.ini`, so the trial runs with the same defaults (plus
   `verbosity = 4`, trial only, which logs the memory figures for the report).
   The power mode comes from `local/AGENTS.md` / `tune-model`'s `--check-env`.

7. **Serve and smoke-test:** `python tryout.py serve`, then
   `python tryout.py smoke --name <preset>`. Smoke writes its results and the
   measured memory (KV cache, model and compute buffers, from the load log) into
   the report. If the load fails, read `results/tryout/router.log`: an unknown
   architecture means the llama.cpp build is too old; out-of-memory means a
   smaller quant or `c`; a bad key names itself. Fix the draft, `stop`, `serve`,
   smoke again. Done when every smoke check has a result. A failed tool-call
   check is a finding (some models, e.g. OCR, have no tool calling), not a blocker.

8. **Benchmark** (the default once the smoke test passes). Estimate the time
   first: about 16 tasks × 2,000 tokens ÷ the smoke decode t/s, more for
   reasoning models (60 t/s ≈ 10 min, 12 t/s ≈ 45 min). Tell the user and run it
   unless they say skip. Follow the `benchmark-model` skill (bench, autograde,
   judge, report) against the trial router:
   `python bench.py --base-url http://127.0.0.1:9947 --models <preset>`
   in the background. Then `python tryout.py record --name <preset> --benchmark-run <run_id>`
   adds its scoreboard and a link to its `report.md`. Skipped:
   `record --benchmark-skipped "<why>"`. Done when the trial report shows the
   scoreboard (with reasoning scores, so judging is finished) or the skip reason.

9. **Compare and report.** Write two or three lines comparing the trial with the
   closest installed model, from `local/TUNING_STATUS.md` and earlier
   benchmark runs (same power mode only; say which), and record them:
   `record --name <preset> --compare "<markdown>"`. Anything else worth keeping
   (surprises, settings to try next) goes in with `record --note`. Then show the
   user the report's path and its key numbers. Offer `tune-model` for settings:
   it benchmarks the file directly, so stop the trial router first, and set
   `LLAMA_PRESET` to `local/tryout.ini` so its baseline is the trial preset.

10. **Decide with the user**, record it with
    `record --name <preset> --decision keep|drop --reason "<one line>"`, then finish:
    - **Keep:** `python tryout.py promote --name <preset>` shows the diff (use
      `--as <name>` if the name is taken); after a yes, `--apply` (it writes a
      backup). Add the model to `local/MODELS.md` and the trial's numbers to
      `local/TUNING_STATUS.md`. The main router reads presets only at start: tell
      the user it needs a restart to offer the model, and leave the restart to them.
    - **Drop:** list the downloaded files with sizes and delete them only after a
      yes. The report stays, as the record of why.
    - Either way, `python tryout.py stop`, so the trial model stops holding
      memory. Done when `tryout.py status` shows the trial router down and the
      report shows the decision.
