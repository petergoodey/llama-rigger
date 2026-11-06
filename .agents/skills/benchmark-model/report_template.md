# Model benchmark — <run_id>

Router: <base_url> · llama.cpp build <bXXXXX> · power mode <?> · date <YYYY-MM-DD>
Tasks: 8 coding (c01–c08), 8 vuln (v01–v06 real, v07–v08 traps). 1 attempt each.

## Scoreboard (sorted by overall)

| Model | Coding | Vuln auto | Vuln reason | Traps OK | Overall | Decode t/s (med) | s/answer (med) | Think tok (mean) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| <model> | x/8 | x/6 | x.x/6 | x/2 | 0.00 | 00 | 00 | 0000 |

- **Coding** = unit-test passes / 8.
- **Vuln auto** = patches passing ASan/tests / 6 real vuln tasks.
- **Vuln reason** = mean reasoning score over the 8 vuln tasks (found+rootcause+fix, 0–6).
- **Traps OK** = traps correctly called safe / 2 (false positives are the inverse).
- **Overall** = mean of {coding rate, vuln-auto rate, vuln-reason rate, traps rate}.

## Per-task detail

### Coding
| Task | <model A> | <model B> | ... |
|---|---|---|---|
| c01 safe_add | PASS | BUILD_FAIL | |

### Vuln (auto patch result / reasoning found-rootcause-fix)
| Task | <model A> | ... |
|---|---|---|
| v01 record overflow | PASS · 2-2-2 | |
| v07 TRAP safe clamp | (n/a) · correctly safe | |

## False positives (crying wolf on traps)
- <model>: v07? v08? — one line each with what it wrongly claimed.

## Speed notes
- Fastest decode: <model> at <t/s>. Slowest: ...
- Thinking-token cost: <model> spent <n> tokens/answer on average.

## Speculative decoding (MTP) — only presets with spec-type set
From `speed.json`. Mean accepted length = tokens produced per decode step
(1 = no gain, `spec-draft-n-max` + 1 = every draft accepted).

| Model | n-max | Accept rate | Mean accepted len | Coding len | Vuln len | Median decode t/s |
|---|---:|---:|---:|---:|---:|---:|
| <model> | 2 | 00% | 0.00 | 0.00 | 0.00 | 00 |

- Judge by mean accepted length, not accept rate. Say where it drops (task kind).

## Takeaways
- Best for exploit triage: <model> — why.
- Best for coding: <model> — why.
- Surprises / anomalies worth a re-run: ...
