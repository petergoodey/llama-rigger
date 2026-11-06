# Tuning `spec-draft-n-max` for MTP presets (`mtp_tune.py`)

`llama-bench` can't run speculative decoding, so `mtp_tune.py` covers presets with
`spec-type = draft-mtp`. It starts a private `llama-server` (port 9946) with the
preset's own settings once per candidate `spec-draft-n-max` (default 1-4) plus a
no-speculation baseline, sends four varied prompts (code, prose, reasoning,
structured JSON; thinking off; fixed seeds) and reads `draft_n` /
`draft_n_accepted` from the response `timings`.

- It reports decode t/s, accept rate and **mean accepted length** (tokens per
  decode step) per n-max, and the real speed-up over no speculation.
- The winner is the n-max with the best decode t/s (ties go to the smaller
  n-max); it is proposed only if it beats the current value by `--min-gain`
  (2%). If speculation is *slower* than none, the report says so.
- Run it per power mode like `tune.py`: the same questions first (which mode;
  stop the router?) and the same `--stop-router --restart-after` /
  `--ignore-router` flags and `--mode` check:
  `python mtp_tune.py --mode <mode> [--models <names>] [--n-max 1 2 3] [--reps 3]`.
  `--dry-run` prints the plan and the server command lines. It loads the model
  about 5 times per GGUF; give the user a time estimate.
- Output: `results/mtp_<time>_<mode>/mtp.md`, `mtp.json`, `proposals.json`. Apply
  with `python apply_ini.py --run mtp_<...>` (dry run first, then `--apply`),
  same as a normal tuning run.
- `compare_modes.py` ignores `mtp_` runs; compare the two modes' `mtp.md` by hand.
- Limits: four short prompts, 256 tokens each, thinking off, 16K context. Real
  reasoning and long-context sessions accept fewer drafts, so treat the result as
  a starting point and confirm with `benchmark-model`, which records mean
  accepted length per task kind.
