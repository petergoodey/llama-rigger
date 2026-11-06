#!/usr/bin/env python3
"""Compare tuned settings across power modes (e.g. balanced vs performance).

Reads every completed run in results/ (needs meta.json + tuning.json), keeps the
latest run per (model, mode), and writes results/modes.md:
  - the optimum settings per model in each mode, differences highlighted
  - baseline vs tuned throughput in each mode, and how much the mode itself matters
  - if a run used --seed-from: what the other mode's optimum scores here, i.e. the
    cost of using one setting for both modes

Usage:
  python compare_modes.py                     # all completed runs
  python compare_modes.py --runs RUN1 RUN2    # only these runs
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path

from tune import INI_KEY, KNOWN_MODES, RESULTS, score_of

ORDER = KNOWN_MODES   # column order: the configured modes, as tune-modes.json lists them
KEYS = ["ub", "b", "fa", "t", "lm", "ctk", "ctv"]


def fix(d):
    return None if d is None else {int(k): v for k, v in d.items()}


def load(run_ids=None):
    best = {}
    if not RESULTS.exists():
        return best
    for d in sorted(RESULTS.iterdir()):
        mp, tj = d / "meta.json", d / "tuning.json"
        if not (d.is_dir() and mp.exists() and tj.exists()):
            continue
        if run_ids and d.name not in run_ids:
            continue
        meta = json.loads(mp.read_text(encoding="utf-8"))
        if not meta.get("completed"):
            continue
        for r in json.loads(tj.read_text(encoding="utf-8")):
            mode = r.get("mode") or meta["mode"]
            key = (r["name"], mode)
            started = meta.get("started", "")
            if key not in best or started >= best[key][1]:
                best[key] = (d.name, started, r)
    return best


def scores(r):
    fd = r["final"]["final_depth"]
    base = fix(r["final"]["baseline"])
    win = fix(r["final"]["winner"])
    tuned = win if r["recommended"] == r["final"]["winner_cfg"] and win else base
    return fd, base, tuned


def cell(d, fd, kind):
    v = ((d or {}).get(fd, {}).get(kind) or (None,))[0]
    return "—" if v is None else f"{v:.0f}"


def fscore(d, fd):
    s = score_of(d or {}, fd)
    return "—" if s is None else f"{s:.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="*")
    args = ap.parse_args()
    best = load(set(args.runs) if args.runs else None)
    if not best:
        print("no completed runs with meta.json + tuning.json found", file=sys.stderr)
        return 1

    models = sorted({m for m, _ in best})
    modes_all = sorted({md for _, md in best},
                       key=lambda x: (ORDER.index(x.lower()) if x.lower() in ORDER else 99, x))
    L = [f"# Power-mode comparison — {datetime.now():%Y-%m-%d %H:%M}\n",
         "Latest completed run per model and mode. Score = √(prefill t/s × decode t/s) at the "
         "scored depth (higher is better).\n",
         "| Mode | Runs |", "|---|---|"]
    for md in modes_all:
        runs = sorted({v[0] for (m, mm), v in best.items() if mm == md})
        L.append(f"| {md} | {', '.join(runs)} |")

    for model in models:
        have = [md for md in modes_all if (model, md) in best]
        L.append(f"\n## {model}\n")
        recs = {md: best[(model, md)][2] for md in have}

        L.append("### Optimum settings\n")
        L.append("| Setting | " + " | ".join(have) + " | Same in all? |")
        L.append("|---|" + "---|" * (len(have) + 1))
        diff = []
        for k in KEYS:
            vals = [recs[md]["recommended"][k] for md in have]
            same = len(set(map(str, vals))) == 1
            if not same:
                diff.append(INI_KEY[k])
            L.append(f"| {INI_KEY[k]} | " + " | ".join(str(v) for v in vals)
                     + f" | {'yes' if same else '**no**'} |")
        if len(have) < 2:
            missing = [m for m in ORDER if m not in [h.lower() for h in have]]
            L.append(f"\n> Only **{have[0]}** measured. Still to do: {', '.join(missing)}. "
                     "Switch the mode, then run `tune.py --mode <mode> --seed-from "
                     f"{best[(model, have[0])][0]}`.")
        elif diff:
            L.append(f"\n> **Optimum differs between modes** in: {', '.join(diff)}. "
                     "`models.ini` holds one set, so pick the mode you run in most, or "
                     "see the cross-mode cost below.")
        else:
            L.append("\n> **One set of settings is optimal in all measured modes.**")

        L.append("\n### Throughput\n")
        fd0 = scores(recs[have[0]])[0]
        L.append(f"Scored at depth {fd0}.\n")
        L.append("| Mode | Settings | pp t/s | tg t/s | Score |")
        L.append("|---|---|---:|---:|---:|")
        tuned_scores, base_scores = {}, {}
        for md in have:
            fd, base, tuned = scores(recs[md])
            base_scores[md], tuned_scores[md] = score_of(base or {}, fd), score_of(tuned or {}, fd)
            L.append(f"| {md} | baseline | {cell(base, fd, 'pp')} | {cell(base, fd, 'tg')} "
                     f"| {fscore(base, fd)} |")
            if recs[md]["changes"]:
                L.append(f"| {md} | **tuned** | {cell(tuned, fd, 'pp')} | {cell(tuned, fd, 'tg')} "
                         f"| {fscore(tuned, fd)} |")
        if len(have) >= 2:
            a, b = have[0], have[1]
            if base_scores.get(a) and base_scores.get(b):
                L.append(f"\nSame baseline settings: **{b} is {100 * (base_scores[b] / base_scores[a] - 1):+.1f}%** "
                         f"vs {a} - this is what the power mode itself is worth.")

        cross = []
        for md in have:
            seed = recs[md]["final"].get("seed")
            if seed and seed.get("depths"):
                fd = recs[md]["final"]["final_depth"]
                s_seed = score_of(fix(seed["depths"]), fd)
                s_own = tuned_scores.get(md)
                if s_seed and s_own:
                    cross.append(f"- {seed.get('mode') or 'other-mode'}'s optimum, run in **{md}**: "
                                 f"score {s_seed:.0f} vs {md}'s own optimum {s_own:.0f} "
                                 f"(**{100 * (s_seed / s_own - 1):+.1f}%**)")
        if cross:
            L.append("\n### Using one setting for both modes\n")
            L += cross

    out = RESULTS / "modes.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
