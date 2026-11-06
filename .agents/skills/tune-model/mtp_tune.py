#!/usr/bin/env python3
"""mtp_tune: tune --spec-draft-n-max for the MTP presets in models.ini.

llama-bench cannot run speculative decoding, so tune.py tunes MTP presets without
it. This script covers that gap: for each GGUF used by a preset with
spec-type = draft-mtp it starts a private llama-server (port 9946) with the
preset's own settings, once per candidate --spec-draft-n-max, sends a small fixed
set of prompts and reads the draft statistics from the response `timings`
(draft_n, draft_n_accepted):

  decode t/s           total predicted tokens / total decode time
  accept rate          draft_n_accepted / draft_n
  mean accepted length tokens per decode step = (accepted + steps) / steps,
                       steps ~ draft_n / n_max (approximate: the last step of an
                       answer can draft fewer)

A run without speculation (n-max 0) is measured as the baseline so the real
speed-up is visible. The winner is the n-max with the best decode t/s, adopted
only if it beats the preset's current n-max by --min-gain (default 2%), ties going
to the smaller n-max. Mean accepted length is reported next to it.

Nothing here edits models.ini; proposals.json is read by apply_ini.py:
  python apply_ini.py --run <run_id> [--apply]

Usage:
  python mtp_tune.py --dry-run
  python mtp_tune.py --mode windows --stop-router --restart-after
  python mtp_tune.py --models Qwen3.8-27B --n-max 1 2 3 --reps 3 --mode performance
"""
import argparse, json, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

from tune import INI_PATH, KNOWN_MODES, RESULTS, is_low_power, mode_error, \
    parse_ini, power_plan, restart_router, router_state, stop_router, tool
import hostplat, rigger          # importable once tune has put _shared on sys.path

PORT = 9946                      # private server; not the router's 9931
BASE = f"http://127.0.0.1:{PORT}"
# ini keys that must not be passed through (router-owned or overridden below)
SKIP = {"host", "port", "api-key", "alias", "models-max", "sleep-idle-seconds",
        "c", "ctx-size", "cache-ram", "parallel", "spec-type", "spec-draft-n-max",
        "mmproj", "models-memory-margin"}
FLAG = {"fa": "--flash-attn", "ngl": "--n-gpu-layers", "b": "--batch-size",
        "ub": "--ubatch-size", "t": "--threads", "lm": "--load-mode",
        "temp": "--temp", "m": "--model"}

# Varied on purpose: code is the easy case for drafting, prose and reasoning the hard
# one. Thinking is switched off so the measured text is the answer itself.
PROMPTS = {
    "code": "Write a Python function that merges overlapping intervals, with a docstring "
            "and two short usage examples.",
    "prose": "Explain in about 150 words why the sky is blue and why sunsets are red.",
    "reasoning": "A train leaves at 09:10 and travels 180 km at 72 km/h, then waits 15 "
                 "minutes and travels 60 km at 90 km/h. When does it arrive? Show the steps.",
    "structured": "Return a JSON array of five objects, each with the keys name, "
                  "population and country, describing five large European cities.",
}
MAX_TOKENS = 256

_logfile = None


def log(msg=""):
    print(msg, flush=True)
    if _logfile:
        with open(_logfile, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


# ------------------------------------------------------------------ preset lookup
def merged(sections, name):
    out = dict(sections.get("*", {}))
    out.update(sections.get(name, {}))
    return out


def mtp_models(sections, only=None):
    """[{name, preset, others, kv}] one per GGUF used by a draft-mtp preset."""
    norm = lambda p: p.replace("\\", "/").lower()
    groups = {}
    for name in sections:
        if name == "*":
            continue
        kv = merged(sections, name)
        if "mtp" not in kv.get("spec-type", "").lower() or "model" not in kv:
            continue
        groups.setdefault(norm(kv["model"]), []).append(name)
    out = []
    for path, names in groups.items():
        stem = Path(path).stem
        primary = next((n for n in names if n.lower() == stem), names[0])
        if only and not any(w.lower() in primary.lower() for w in only):
            continue
        out.append({"name": primary, "preset": primary,
                    "others": [n for n in names if n != primary],
                    "kv": merged(sections, primary)})
    return out


def current_n_max(kv):
    try:
        return int(kv.get("spec-draft-n-max", 3))
    except ValueError:
        return 3


def server_cmd(kv, n_max, ctx):
    """llama-server command line: the preset's settings, private port, small context."""
    cmd = [tool("llama-server") or "llama-server", "--host", "127.0.0.1", "--port", str(PORT),
           "--ctx-size", str(ctx), "--cache-ram", "0", "--parallel", "1"]
    for k, v in kv.items():
        if k in SKIP:
            continue
        flag = FLAG.get(k, "--" + k)
        lv = v.lower()
        if lv == "true":
            cmd.append(flag)
        elif lv == "false":
            continue
        else:
            cmd += [flag, v]
    if n_max > 0:
        cmd += ["--spec-type", kv.get("spec-type", "draft-mtp"),
                "--spec-draft-n-max", str(n_max)]
    return cmd


# ------------------------------------------------------------------ server + requests
def wait_ready(proc, timeout_s):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if proc.poll() is not None:
            return False, f"llama-server exited with code {proc.returncode}"
        try:
            if rigger.http_json(BASE, "/health", timeout=5).get("status") == "ok":
                return True, f"ready after {time.time() - t0:.0f}s"
        except Exception:
            pass
        time.sleep(3)
    return False, f"not ready after {timeout_s}s"


def chat(prompt, seed):
    return rigger.http_json(BASE, "/v1/chat/completions", {
        "model": "x", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS, "stream": False, "seed": seed,
        "chat_template_kwargs": {"enable_thinking": False}}, timeout=600)


def measure(n_max, reps):
    """Run the prompt set; return aggregate and per-prompt statistics."""
    chat("Reply with: ok", 0)                       # warm-up, not counted
    tot = {"n": 0, "ms": 0.0, "draft": 0, "acc": 0, "steps": 0.0}
    per = {}
    for kind, prompt in PROMPTS.items():
        p = {"n": 0, "ms": 0.0, "draft": 0, "acc": 0, "steps": 0.0}
        for rep in range(reps):
            tm = chat(prompt, 1000 + rep).get("timings", {})
            d, a = tm.get("draft_n") or 0, tm.get("draft_n_accepted") or 0
            vals = {"n": tm.get("predicted_n") or 0, "ms": tm.get("predicted_ms") or 0.0,
                    "draft": d, "acc": a, "steps": (d / n_max) if n_max else 0.0}
            for k, v in vals.items():
                p[k] += v
                tot[k] += v
        per[kind] = p
    return tot, per


def stats(a, n_max):
    tps = a["n"] / (a["ms"] / 1000) if a["ms"] else None
    out = {"decode_tps": round(tps, 2) if tps else None, "tokens": a["n"]}
    if n_max and a["draft"]:
        out["accept_rate"] = round(a["acc"] / a["draft"], 4)
        out["mean_accepted_len"] = round((a["acc"] + a["steps"]) / a["steps"], 3)
    return out


# ------------------------------------------------------------------ tuning
def tune_model(m, candidates, args, run_dir):
    kv = m["kv"]
    cur = current_n_max(kv)
    rec = {"name": m["name"], "preset": m["preset"], "other_presets": m["others"],
           "current_n_max": cur, "runs": {}, "done": False}
    log(f"\n=== {m['name']}  (current spec-draft-n-max = {cur})")
    for n_max in candidates:
        label = "no speculation" if n_max == 0 else f"n-max {n_max}"
        cmd = server_cmd(kv, n_max, args.ctx)
        log(f"-- {label}: starting server")
        slog = open(run_dir / f"server_{re.sub(r'[^A-Za-z0-9._-]', '_', m['name'])}_{n_max}.log", "wb")
        proc = hostplat.popen_server(cmd, stdout=slog, stderr=subprocess.STDOUT)
        try:
            ok, msg = wait_ready(proc, args.load_timeout)
            log(f"   {msg}")
            if not ok:
                rec["runs"][str(n_max)] = {"error": msg}
                continue
            tot, per = measure(n_max, args.reps)
            res = {**stats(tot, n_max), "by_prompt": {k: stats(v, n_max) for k, v in per.items()}}
            rec["runs"][str(n_max)] = res
            extra = (f", accept {res['accept_rate']:.0%}, mean accepted length "
                     f"{res['mean_accepted_len']:.2f}") if "accept_rate" in res else ""
            log(f"   decode {res['decode_tps']} t/s{extra}")
        except Exception as e:  # noqa
            rec["runs"][str(n_max)] = {"error": str(e)}
            log(f"   ERROR {e}")
        finally:
            hostplat.stop_process(proc)
            slog.close()
            time.sleep(3)

    ok = {int(k): v for k, v in rec["runs"].items() if v.get("decode_tps")}
    spec = {k: v for k, v in ok.items() if k > 0}
    rec["best_n_max"], rec["gain_vs_current"], rec["speedup_vs_no_spec"] = None, None, None
    if spec:
        top = max(v["decode_tps"] for v in spec.values())
        # smallest n-max within the noise band of the best (less verify work)
        best = min(k for k, v in spec.items() if v["decode_tps"] >= top * (1 - args.min_gain))
        rec["best_n_max"] = best
        base = ok.get(cur)
        if base:
            rec["gain_vs_current"] = round(spec[best]["decode_tps"] / base["decode_tps"] - 1, 4)
        if 0 in ok:
            rec["speedup_vs_no_spec"] = round(spec[best]["decode_tps"] / ok[0]["decode_tps"], 3)
    rec["done"] = True
    return rec


def write_outputs(run_dir, results, meta, args):
    (run_dir / "mtp.json").write_text(json.dumps({"meta": meta, "models": results}, indent=2),
                                      encoding="utf-8")
    L = [f"# MTP tuning - {meta['run_id']}", "",
         f"Power mode: **{meta['mode']}** (plan '{meta['power_plan']}') - {meta['date']}  ",
         f"Prompts: {', '.join(PROMPTS)} (thinking off, {MAX_TOKENS} max tokens, "
         f"{args.reps} rep(s) each, fixed seeds). Context {args.ctx}, cache-ram 0, parallel 1.", "",
         "Decode t/s = tokens / decode time over all prompts. Mean accepted length = tokens per "
         "decode step (1 = no gain; n-max + 1 = every draft accepted).", ""]
    props = {"run": run_dir.name, "mode": meta["mode"],
             "ini": str(INI_PATH).replace("\\", "/"), "models": {}}
    for r in results:
        L += [f"## {r['name']}", "", "| n-max | Decode t/s | vs no-spec | Accept | Mean len |",
              "|---:|---:|---:|---:|---:|"]
        base = (r["runs"].get("0") or {}).get("decode_tps")
        for k in sorted(r["runs"], key=int):
            v = r["runs"][k]
            if "error" in v:
                L.append(f"| {k} | error: {v['error']} | | | |")
                continue
            sp = f"{v['decode_tps'] / base:.2f}x" if base and v["decode_tps"] else ""
            acc = f"{v['accept_rate']:.0%}" if "accept_rate" in v else ""
            ml = f"{v['mean_accepted_len']:.2f}" if "mean_accepted_len" in v else ""
            tag = " (current)" if int(k) == r["current_n_max"] else ""
            tag += " **best**" if r["best_n_max"] == int(k) else ""
            L.append(f"| {k if int(k) else 'off'}{tag} | {v['decode_tps']} | {sp} | {acc} | {ml} |")
        L.append("")
        b = r["best_n_max"]
        if b is None:
            L.append("No speculative run completed; nothing to recommend.")
        else:
            L.append(f"Best n-max: **{b}** (current {r['current_n_max']}). "
                     + (f"Speed-up over no speculation: {r['speedup_vs_no_spec']}x. "
                        if r["speedup_vs_no_spec"] else "")
                     + ("Spec is SLOWER than no speculation here - consider turning it off. "
                        if r["speedup_vs_no_spec"] and r["speedup_vs_no_spec"] < 1 else ""))
            bp = r["runs"][str(b)].get("by_prompt", {})
            L.append("Mean accepted length by prompt: "
                     + ", ".join(f"{k} {v['mean_accepted_len']:.2f}" for k, v in bp.items()
                                 if "mean_accepted_len" in v) + ".")
            gain = r["gain_vs_current"]
            if b != r["current_n_max"] and gain is not None and gain >= args.min_gain:
                props["models"][r["name"]] = {
                    "preset": r["preset"], "other_presets": r["other_presets"],
                    "changes": {"spec-draft-n-max": b}, "gain_pct": round(100 * gain, 1)}
                L.append(f"Proposed change: spec-draft-n-max {r['current_n_max']} -> {b} "
                         f"({gain:+.1%}).")
            else:
                L.append("No change proposed (best is the current value or within the "
                         f"{args.min_gain:.0%} noise threshold).")
        if r["other_presets"]:
            L.append(f"Other presets using this GGUF are untouched: {', '.join(r['other_presets'])}.")
        L.append("")
    (run_dir / "mtp.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (run_dir / "proposals.json").write_text(json.dumps(props, indent=2), encoding="utf-8")


def main():
    global _logfile
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", help="preset name substrings (default: all MTP models)")
    ap.add_argument("--n-max", nargs="*", type=int, default=[1, 2, 3, 4], dest="n_max")
    ap.add_argument("--no-baseline", action="store_true", help="skip the no-speculation run")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--min-gain", type=float, default=0.02)
    ap.add_argument("--load-timeout", type=int, default=900)
    ap.add_argument("--mode", help="power mode being measured: windows | performance")
    ap.add_argument("--no-mode-check", action="store_true")
    ap.add_argument("--run")
    ap.add_argument("--stop-router", action="store_true")
    ap.add_argument("--restart-after", action="store_true")
    ap.add_argument("--ignore-router", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not INI_PATH.exists():
        print(f"missing {INI_PATH}", file=sys.stderr)
        return 2
    models = mtp_models(parse_ini(INI_PATH), args.models)
    if not models:
        print("no presets with spec-type = draft-mtp matched", file=sys.stderr)
        return 2
    candidates = ([] if args.no_baseline else [0]) + sorted(set(args.n_max))

    plan = power_plan()
    mode = args.mode.strip() if args.mode else plan
    if args.mode and not args.no_mode_check:
        err = mode_error(args.mode, plan)
        if err:
            print(f"ERROR: {err}.", file=sys.stderr)
            return 4
    elif not args.mode:
        print(f"note: no --mode given; labelling with the power plan '{plan}'. "
              f"Use --mode {'|'.join(KNOWN_MODES)}.", file=sys.stderr)

    slug = re.sub(r"[^a-z0-9]+", "-", mode.lower()).strip("-") or "run"
    run_id = args.run or f"mtp_{datetime.now():%Y-%m-%d_%H%M%S}_{slug}"
    run_dir = RESULTS / run_id
    print(f"run {run_id}: mode '{mode}'; candidates {candidates} (0 = no speculation); "
          f"{args.reps} rep(s) x {len(PROMPTS)} prompts")
    for m in models:
        print(f"  - {m['name']} (current n-max {current_n_max(m['kv'])}"
              + (f"; also used by {', '.join(m['others'])}" if m["others"] else "") + ")")
    if args.dry_run:
        for m in models:
            print("\n" + " ".join(f'"{c}"' if " " in c else c
                                  for c in server_cmd(m["kv"], candidates[-1], args.ctx)))
        print(f"\n{len(models) * len(candidates)} server load(s) in total; each load of a "
              "20-40 GB model takes roughly 20-60 s.")
        return 0

    run_dir.mkdir(parents=True, exist_ok=True)
    _logfile = run_dir / "progress.log"
    rs = router_state()
    if rs["running"] and not (args.stop_router or args.ignore_router):
        print("ERROR: llama-server is running. It would compete for memory and bandwidth. "
              "Re-run with --stop-router (and --restart-after) or --ignore-router.",
              file=sys.stderr)
        return 3
    if rs["running"] and args.stop_router:
        log("stopping llama-server ...")
        if not stop_router():
            print("ERROR: could not stop llama-server", file=sys.stderr)
            return 3
    if is_low_power(plan):
        log(f"WARNING: power plan is '{plan}' (low-power); results won't reflect full speed.")

    results = []
    try:
        for m in models:
            f = run_dir / f"{re.sub(r'[^A-Za-z0-9._-]', '_', m['name'])}.json"
            if f.exists() and json.loads(f.read_text(encoding="utf-8")).get("done"):
                log(f"\n=== {m['name']}: already done, loading saved result")
                results.append(json.loads(f.read_text(encoding="utf-8")))
                continue
            r = tune_model(m, candidates, args, run_dir)
            f.write_text(json.dumps(r, indent=2), encoding="utf-8")
            results.append(r)
    finally:
        if args.restart_after:
            log("restarting router ...")
            restart_router()
    meta = {"run_id": run_id, "mode": mode, "power_plan": plan,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")}
    write_outputs(run_dir, results, meta, args)
    log(f"\nreport: {run_dir / 'mtp.md'}\nproposals: {run_dir / 'proposals.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
