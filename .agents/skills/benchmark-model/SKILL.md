---
name: benchmark-model
description: Benchmark the router's models on vulnerability reasoning (find, explain, fix) and coding, with graded scores and speed. Use when the user wants to rank or compare models on coding or security ("which model is best at finding bugs", "benchmark the models"), or re-test one model after a change.
---

# benchmark-model

Scores each preset the llama-server router serves on two skills, plus speed
(decode t/s, time per answer, tokens):

- **Vuln reasoning**: given a C/C++/C# function, find any vulnerability, explain
  root cause and attacker impact, and fix it. Includes **traps**: safe code that
  looks dangerous, where the right answer is "safe".
- **Coding**: implement a function; graded by compiling it against hidden tests.

Run from this folder with `python` (Windows) or `python3`. Tasks live in
`tasks/` (16: `c01`–`c08` coding, `v01`–`v08` vuln, `v07`/`v08` traps); each
`answer.md` is the key and is never sent to a model. Defaults are in
`config.json`; `local/benchmark-config.json` overrides them (the model list goes
there). `bench.py --base-url` points at another router, e.g. a `tryout-model` trial.

## Prerequisites

1. **A router serving the models:** `start-llama-ini` / `./start-llama-ini.sh`
   (127.0.0.1:9931). It swaps models by memory, so a full run needs no help;
   models not on disk are skipped.
2. **A C/C++ compiler with AddressSanitizer:** MSVC on Windows
   (`python _vcenv.py` prints `"msvc": true`), clang or gcc elsewhere
   (`$CC`/`$CXX` override). Step 1 proves it works.
3. **The .NET SDK** for the C# tasks: `dotnet --version`.

## Procedure

1. **Validate the harness** (first run, or after editing tasks):
   `python selftest_setup.py && python autograde.py --run _selftest`. Expect every
   `ref` = PASS (`v03` BUILD_OK), `vulnorig` `v01`–`v06` = FAIL (`v03` BUILD_OK)
   and `vulnorig` `v07`/`v08` = PASS. Any other result means a task or driver is
   broken and would misjudge every model: fix it before going on.

2. **Run the models:** `python bench.py` (`--models <id>...`, `--tasks <id>...` to
   narrow; `--dry-run` to preview; run it in the background). This is the slow step,
   roughly 10–20 min per model. It writes `results/<run>/` (answers, extracted
   code, `manifest.json`, and `speed.json` with per-model speed and, for MTP
   presets, mean accepted length by task kind).

3. **Auto-grade:** `python autograde.py --run <run_id>` → `auto_scores.json`.

4. **Judge the vuln reasoning** (your job). For each
   `results/<run>/answers/<model>__v*.json`, read `content` (and
   `reasoning_content`) and grade it against the task's `answer.md`, 0–2 on each
   axis:
   - **found**: correctly said whether a vuln exists. On a trap the right answer is
     "safe"; crying wolf scores 0 and is the key trap signal;
   - **rootcause**: root cause and attacker impact, correct and specific;
   - **fix**: the fix explanation is correct.
   The patch itself is graded by `auto_scores.json`, so judge the prose only.
   Save the grades to `results/<run>/judge_scores.json`, in this shape
   (`tryout-model` reads it):
   `{"<model>": {"v01": {"found": 0-2, "rootcause": 0-2, "fix": 0-2, "note": "<why>"}, ...}}`.
   Done when every `v*` answer of every model in the run has an entry with a note.

5. **Write the report** to `results/<run>/report.md` from `report_template.md`: a
   per-model scoreboard (coding pass rate, vuln auto-pass rate, reasoning score,
   trap false positives, median decode t/s, median time per answer, mean thinking
   tokens), then per-task detail, and for MTP presets the speculative-decoding
   table from `speed.json`. Each run keeps its own directory and raw JSON.

6. Offer to append the scoreboard to `local/TUNING_STATUS.md`.

## Scoring

- Coding task: PASS (tests green) = 1, else 0.
- Vuln task: auto = patch PASS under ASan/tests (1/0); reasoning =
  (found + rootcause + fix) / 6. Report both; the headline vuln score is their mean.
- Trap false positives are a notable failure: show the per-model count
  prominently.

## Notes

- Each preset runs with its own settings (reasoning budget, MTP, sampling), so
  scores are as the model is actually used. OCR and greedy vision presets score
  low on code, as expected; drop them from `local/benchmark-config.json`.
- One attempt per task with each preset's own sampling, so small differences
  between models are noise; say so when ranking close results. (`bench.py` sends
  no sampling settings and has no repeat option.)
- The vuln snippets are small, self-contained and defensive (find and fix).
