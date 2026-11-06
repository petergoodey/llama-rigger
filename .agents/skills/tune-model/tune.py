#!/usr/bin/env python3
"""tune-model: one-variable-at-a-time llama-bench tuning for each GGUF.

For every model it starts from the settings its preset in models.ini
implies, then sweeps one parameter at a time (ubatch -> batch -> flash-attn ->
threads -> load-mode -> KV cache type), keeping the best so far. Sweep stages
use a cheap proxy depth; the baseline and the winner are then re-measured at
the real depth (default 16384), which is the score reported.

Score = sqrt(prefill t/s * decode t/s) at that depth (geometric mean).
A change is only adopted if it beats the incumbent by --min-gain (default 2%).
A q8_0 KV cache is only adopted if llama-perplexity shows the perplexity
change vs f16 is under --ppl-threshold (default 1%).

Nothing here edits models.ini; see apply_ini.py.

Usage:
  python tune.py --check-env
  python tune.py --dry-run [--models A B] [--params ubatch fa ...]
  python tune.py --models GLM-OCR-Q8_0 --params ubatch,fa,kv --stop-router
"""
import argparse, json, math, os, re, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
import hostplat, rigger

ROOT = Path(__file__).resolve().parent
MODELS_DIR = rigger.REPO          # repo root (paths, ports: _shared/rigger.py)
LOCAL_DIR = rigger.LOCAL
INI_PATH = rigger.find_preset()
RESULTS = Path(os.environ.get("TUNE_RESULTS", ROOT / "results"))
PPL_TEXT = LOCAL_DIR / "ppl_text.txt"  # built by make_ppl_text.py
ROUTER_PORT = rigger.ROUTER_PORT

PP, TG = 4096, 128          # measured workload: prefill tokens, decode tokens
# Physical cores (llama.cpp's own default); cpu_count() counts SMT threads.
DEFAULT_THREADS = max(1, (os.cpu_count() or 2) // 2)
ALL_PARAMS = ["ubatch", "batch", "fa", "threads", "loadmode", "kv"]

# Power modes to find an optimum for. --mode <name> checks that the OS reports the
# matching power plan / profile (hostplat.power_plan), so a run can't be labelled
# with the wrong mode. Per-OS defaults are in hostplat.default_modes(); a
# machine-specific mapping (e.g. a vendor tool's modes -> the plan each selects)
# goes in local/tune-modes.json:
#   {"modes": {"<mode>": "<substring of the OS plan name>", ...},
#    "low_power": ["<plan substring>", ...], "switch_hint": "<how the user switches>"}
_MODES_CFG = hostplat.default_modes()
if (LOCAL_DIR / "tune-modes.json").exists():
    _MODES_CFG.update(json.loads((LOCAL_DIR / "tune-modes.json").read_text(encoding="utf-8")))
MODE_PLAN = {k.lower(): v.lower() for k, v in _MODES_CFG["modes"].items()}
KNOWN_MODES = list(MODE_PLAN)
LOW_POWER = [s.lower() for s in _MODES_CFG["low_power"]]
SWITCH_HINT = _MODES_CFG["switch_hint"]


def is_low_power(plan):
    return any(s in (plan or "").lower() for s in LOW_POWER)


def mode_error(mode, plan):
    """Why `--mode mode` must not run under the active `plan`, or None if it may.
    An unknown mode name is an error too: a label nothing can verify."""
    want = MODE_PLAN.get(mode.strip().lower())
    if want is None:
        return (f"--mode {mode} is not a configured mode ({', '.join(KNOWN_MODES)}); "
                f"add it to local/tune-modes.json, or pass --no-mode-check")
    if want not in (plan or "").lower():
        return (f"--mode {mode} expects the power plan to contain '{want}', but the OS reports "
                f"'{plan}'. Switch the mode ({SWITCH_HINT}), check, and re-run - or pass "
                f"--no-mode-check if you know it's right")
    return None

CAND = {
    "ub": [128, 256, 512, 1024, 2048, 4096],
    "b": [512, 1024, 2048, 4096],
    # half the physical cores, physical cores, 1.5x, all logical CPUs
    "t": sorted({max(1, DEFAULT_THREADS // 2), DEFAULT_THREADS,
                 DEFAULT_THREADS * 3 // 2, os.cpu_count() or DEFAULT_THREADS}),
    "lm": ["none", "mmap"],
}

# ini key aliases -> internal cfg key
ALIASES = {
    "ngl": "ngl", "n-gpu-layers": "ngl",
    "n-cpu-moe": "ncmoe", "ncmoe": "ncmoe",   # discrete GPU: MoE experts in RAM
    "fa": "fa", "flash-attn": "fa",
    "b": "b", "batch-size": "b",
    "ub": "ub", "ubatch-size": "ub",
    "ctk": "ctk", "cache-type-k": "ctk",
    "ctv": "ctv", "cache-type-v": "ctv",
    "lm": "lm", "load-mode": "lm",
    "t": "t", "threads": "t",
    "model": "model", "m": "model",
}
# internal cfg key -> ini key written by apply_ini.py
INI_KEY = {"ub": "ubatch-size", "b": "batch-size", "fa": "fa", "t": "threads",
           "lm": "load-mode", "ctk": "cache-type-k", "ctv": "cache-type-v"}

_logfile = None
BUILD = {}   # filled from llama-bench output: build number + gpu name


def log(msg=""):
    print(msg, flush=True)
    if _logfile:
        with open(_logfile, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def tool(name):
    return shutil.which(name) or shutil.which(name + ".exe")


# --------------------------------------------------------------------------- env
def sh(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # noqa
        class R:  # minimal stand-in
            returncode, stdout, stderr = 1, "", str(e)
        return R()


def router_state():
    listening = hostplat.port_listening(ROUTER_PORT)
    procs = hostplat.llama_server_pids()
    return {"listening": listening, "llama_server_pids": procs,
            "running": listening or bool(procs)}


power_plan = hostplat.power_plan


def stop_router():
    hostplat.kill_llama_servers()
    for _ in range(30):
        if not router_state()["running"]:
            return True
        time.sleep(1)
    return False


def restart_router():
    where = hostplat.restart_router(MODELS_DIR, INI_PATH, RESULTS / "router.log")
    log(f"router restarted: {where}")


# ------------------------------------------------------------------ models + ini
SHARD = re.compile(r"^(?P<stem>.+)-(?P<i>\d{5})-of-(?P<n>\d{5})$")


def discover_ggufs():
    out = {}
    for p in sorted((MODELS_DIR / "models").rglob("*.gguf")):
        if ".cache" in p.parts or p.name.lower().startswith("mmproj"):
            continue
        m = SHARD.match(p.stem)
        if m:
            if int(m["i"]) != 1:
                continue
            name = m["stem"]
            size = sum(q.stat().st_size for q in p.parent.glob(f"{name}-*-of-{m['n']}.gguf"))
        else:
            name, size = p.stem, p.stat().st_size
        out[name] = {"name": name, "path": str(p), "size_gb": round(size / 2**30, 1)}
    return list(out.values())


def parse_ini(path=INI_PATH):
    sections, cur = {}, None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith(";"):
            continue
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
            sections.setdefault(cur, {})
            continue
        if "=" in s and cur is not None:
            k, v = s.split("=", 1)
            sections[cur][k.strip()] = re.split(r"\s;", v, 1)[0].strip()
    return sections


def _flag(v):
    return 0 if str(v).lower() in ("off", "0", "false", "no") else 1


def preset_baseline(m, sections):
    norm = lambda s: s.replace("\\", "/").lower()
    mp = norm(m["path"])
    matches = [n for n, kv in sections.items()
               if n != "*" and norm(kv.get("model", kv.get("m", ""))) == mp]
    primary = m["name"] if m["name"] in matches else (matches[0] if matches else None)
    merged = {}
    for src in (sections.get("*", {}), sections.get(primary, {}) if primary else {}):
        for k, v in src.items():
            if k in ALIASES:
                merged[ALIASES[k]] = v
    lm = merged.get("lm", "auto").lower()
    cfg = {
        "ngl": int(merged.get("ngl", 999)),
        "ncmoe": int(merged.get("ncmoe", 0)),
        "fa": _flag(merged.get("fa", "on")),
        "b": int(merged.get("b", 2048)),
        "ub": int(merged.get("ub", 512)),
        "t": int(merged.get("t", DEFAULT_THREADS)),
        "ctk": merged.get("ctk", "f16"),
        "ctv": merged.get("ctv", "f16"),
        "lm": "mmap" if lm == "auto" else lm,
    }
    return cfg, primary, [n for n in matches if n != primary]


# --------------------------------------------------------------------- llama-bench
def csv(vals):
    return ",".join(str(v) for v in vals)


def key_of(c):
    return (c["b"], c["ub"], c["t"], c["ctk"], c["ctv"], int(c["fa"]), c["lm"])


def run_bench(path, cur, lists, depths, reps, timeout):
    """One llama-bench process. `lists` overrides cfg fields with value lists."""
    L = {k: [v] for k, v in cur.items()}
    L.update(lists)
    cmd = [tool("llama-bench"), "-m", str(path),
           "-p", str(PP), "-n", str(TG), "-d", csv(depths), "-r", str(reps),
           "-ngl", str(cur["ngl"]),
           *(["-ncmoe", str(cur["ncmoe"])] if cur.get("ncmoe") else []),
           "-b", csv(L["b"]), "-ub", csv(L["ub"]),
           "-fa", csv("on" if x else "off" for x in L["fa"]),
           "-t", csv(L["t"]), "-ctk", csv(L["ctk"]), "-ctv", csv(L["ctv"]),
           "-lm", csv(L["lm"]), "-o", "json"]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout}s"
    if p.returncode != 0:
        return None, f"rc={p.returncode}: {(p.stderr or p.stdout)[-600:]}"
    try:
        out = p.stdout
        rows = json.loads(out[out.find("["): out.rfind("]") + 1])
    except Exception as e:  # noqa
        return None, f"unparseable output: {e}: {p.stdout[-300:]}"
    if rows:
        BUILD.update(build=rows[0].get("build_number"), gpu=rows[0].get("gpu_info"))
    log(f"      ({time.time() - t0:.0f}s, {len(rows)} rows)")
    return rows, None


def group_rows(rows):
    """rows -> {cfgkey: {depth: {'pp': (avg,std), 'tg': (avg,std)}}}"""
    table = {}
    for r in rows:
        key = (r["n_batch"], r["n_ubatch"], r["n_threads"], r["type_k"], r["type_v"],
               int(r["flash_attn"]), r["load_mode"])
        kind = "pp" if r["n_prompt"] > 0 else "tg"
        table.setdefault(key, {}).setdefault(int(r["n_depth"]), {})[kind] = \
            (float(r["avg_ts"]), float(r["stddev_ts"]))
    return table


def score_of(depths, depth):
    d = depths.get(depth) or {}
    if "pp" not in d or "tg" not in d:
        return None
    return math.sqrt(d["pp"][0] * d["tg"][0])


def assign(field, v):
    return {"ctk": v[0], "ctv": v[1]} if field == "kv" else {field: v}


def bench_candidates(path, cur, field, values, force, depths, reps, timeout,
                     individual=False):
    """Evaluate candidate values of one field. Returns {value: record}."""
    recs = {v: {"value": v, "error": None, "depths": {}} for v in values}

    def cfg_for(v):
        c = dict(cur)
        c.update(force)
        c.update(assign(field, v))
        return c

    groups = [values] if (not individual and len(values) > 1) else [[v] for v in values]
    for g in groups:
        lists = {k: [x] for k, x in force.items()}
        if field == "kv":
            lists["ctk"], lists["ctv"] = [g[0][0]], [g[0][1]]
        else:
            lists[field] = list(g)
        log(f"    bench {field} = {g}")
        rows, err = run_bench(path, cur, lists, depths, reps, timeout)
        if rows is None:
            if len(g) > 1:
                log(f"      ! failed ({err[:120]}); retrying values one at a time")
                for v in g:
                    recs[v] = bench_candidates(path, cur, field, [v], force, depths,
                                               reps, timeout, individual=True)[v]
            else:
                recs[g[0]]["error"] = err
                log(f"      ! {err[:200]}")
            continue
        table = group_rows(rows)
        for v in g:
            k = key_of(cfg_for(v))
            if k in table:
                recs[v]["depths"] = table[k]
            else:
                recs[v]["error"] = "no result row for this config"
    return recs


def pick(recs, cur_value, depth, min_gain):
    scores = {v: score_of(r["depths"], depth) for v, r in recs.items()}
    base = scores.get(cur_value)
    valid = {v: s for v, s in scores.items() if s}
    if not valid or not base:
        return cur_value
    best = max(valid, key=valid.get)
    return best if best != cur_value and valid[best] >= base * (1 + min_gain) else cur_value


# ----------------------------------------------------------------- perplexity guard
PPL_RE = re.compile(r"Final estimate: PPL = ([0-9.]+)")


def ppl_guard(path, cur, chunks, threshold, timeout):
    res = {"threshold": threshold, "chunks": chunks, "error": None}
    exe = tool("llama-perplexity")
    if not exe or not PPL_TEXT.exists():
        res["error"] = "llama-perplexity or ppl_text.txt missing"
        res["pass"] = False
        return res
    for label in ("f16", "q8_0"):
        cmd = [exe, "-m", str(path), "-f", str(PPL_TEXT), "-c", "512",
               "-b", "512", "-ub", "512", "--chunks", str(chunks),
               "-ngl", str(cur["ngl"]), "-fa", "on", "-ctk", label, "-ctv", label,
               *(["--n-cpu-moe", str(cur["ncmoe"])] if cur.get("ncmoe") else [])]
        log(f"    perplexity {label} ...")
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            res["error"] = f"{label}: timeout"
            res["pass"] = False
            return res
        m = PPL_RE.search((p.stdout or "") + (p.stderr or ""))
        if p.returncode != 0 or not m:
            res["error"] = f"{label}: rc={p.returncode}, no PPL in output: " \
                           f"{(p.stderr or p.stdout)[-300:]}"
            res["pass"] = False
            return res
        res[label] = float(m.group(1))
    res["rel_increase"] = (res["q8_0"] - res["f16"]) / res["f16"]
    res["pass"] = math.isfinite(res["q8_0"]) and res["rel_increase"] < threshold
    log(f"      f16 {res['f16']:.4f}  q8_0 {res['q8_0']:.4f}  "
        f"(+{res['rel_increase'] * 100:.2f}%)  -> {'PASS' if res['pass'] else 'FAIL'}")
    return res


# --------------------------------------------------------------------- per model
def tune_model(m, sections, args, params):
    path = m["path"]
    baseline, primary, others = preset_baseline(m, sections)
    cur = dict(baseline)
    sd, fd = args.sweep_depth, args.final_depth
    rec = {"name": m["name"], "path": path, "size_gb": m["size_gb"],
           "mode": args.mode_label, "power_plan": args.plan,
           "preset": primary, "other_presets": others,
           "baseline": baseline, "stages": [], "kv_guard": None, "notes": []}
    t0 = time.time()
    log(f"\n=== {m['name']}  ({m['size_gb']} GB)  preset={primary}")
    log(f"  baseline: {baseline}")

    def stage(name, field, values, force=None):
        force = force or {}
        recs = bench_candidates(path, cur, field, values, force, [sd], args.reps,
                                args.timeout, individual=(field == "kv"))
        base_val = (cur["ctk"], cur["ctv"]) if field == "kv" else cur[field]
        chosen = pick(recs, base_val, sd, args.min_gain)
        rec["stages"].append({
            "param": name, "field": field, "depth": sd, "forced": force,
            "records": [{"value": list(v) if isinstance(v, tuple) else v,
                         "error": r["error"],
                         "pp": r["depths"].get(sd, {}).get("pp"),
                         "tg": r["depths"].get(sd, {}).get("tg"),
                         "score": score_of(r["depths"], sd)} for v, r in recs.items()],
            "current": list(base_val) if isinstance(base_val, tuple) else base_val,
            "chosen": list(chosen) if isinstance(chosen, tuple) else chosen})
        marker = "  (kept)" if chosen == base_val else f"  -> {chosen}"
        log(f"  [{name}] current={base_val}{marker}")
        return recs, chosen, base_val

    def uniq(vals):
        return list(dict.fromkeys(vals))

    if "ubatch" in params:
        vals = uniq(CAND["ub"] + [cur["ub"]])
        _, chosen, _ = stage("ubatch", "ub", sorted(vals),
                             force={"b": max(max(vals), cur["b"])})
        cur["ub"] = chosen
        if cur["b"] < cur["ub"]:
            # llama.cpp clamps ubatch down to batch, so a ubatch above the batch size
            # would silently run as ubatch == batch. Keep batch >= ubatch.
            rec["notes"].append(f"batch raised {cur['b']} -> {cur['ub']} to match the chosen "
                                f"ubatch (ubatch is clamped to batch).")
            cur["b"] = cur["ub"]
    if "batch" in params:
        vals = sorted(v for v in uniq(CAND["b"] + [cur["b"]]) if v >= cur["ub"])
        _, chosen, _ = stage("batch", "b", vals)
        cur["b"] = chosen
    if "fa" in params:
        _, chosen, _ = stage("flash-attn", "fa", [0, 1])
        cur["fa"] = chosen
    if "threads" in params:
        _, chosen, _ = stage("threads", "t", sorted(uniq(CAND["t"] + [cur["t"]])))
        cur["t"] = chosen
    if "loadmode" in params:
        _, chosen, _ = stage("load-mode", "lm", uniq([cur["lm"]] + CAND["lm"]))
        cur["lm"] = chosen
    if "kv" in params:
        if not cur["fa"]:
            rec["notes"].append("KV sweep skipped: flash-attn is off (V cache can't be quantised).")
            log("  [kv] skipped (fa off)")
        else:
            kv_vals = [("f16", "f16"), ("q8_0", "q8_0")]
            if (cur["ctk"], cur["ctv"]) not in kv_vals:
                kv_vals.append((cur["ctk"], cur["ctv"]))
            recs, _, base_val = stage("kv-cache", "kv", kv_vals)
            # the stage's own pick is speed-only; q8_0 needs the quality guard
            f, q = recs.get(("f16", "f16")), recs.get(("q8_0", "q8_0"))
            sf = score_of(f["depths"], sd) if f else None
            sq = score_of(q["depths"], sd) if q else None
            kv_now = (cur["ctk"], cur["ctv"])
            if kv_now == ("f16", "f16") and sf and sq and sq >= sf * (1 + args.min_gain):
                g = ppl_guard(path, cur, args.ppl_chunks, args.ppl_threshold, args.timeout)
                g["speed_gain"] = sq / sf - 1
                rec["kv_guard"] = g
                if g.get("pass"):
                    cur["ctk"] = cur["ctv"] = "q8_0"
                else:
                    rec["notes"].append(
                        "q8_0 KV was faster but is NOT recommended: "
                        + (g.get("error") or f"perplexity +{g['rel_increase'] * 100:.2f}% "
                           f"exceeds {args.ppl_threshold * 100:.1f}%") + ".")
            elif kv_now == ("f16", "f16") and sf and sq:
                rec["notes"].append(
                    f"q8_0 KV gave {100 * (sq / sf - 1):+.1f}% (below the {args.min_gain * 100:.0f}% "
                    "gain bar), so f16 was kept and no perplexity check was run.")
            elif kv_now == ("f16", "f16") and q and q["error"]:
                rec["notes"].append(f"q8_0 KV failed to run: {q['error'][:160]}")
            # the stage recorded the speed-only pick; show what was really chosen
            rec["stages"][-1]["chosen"] = [cur["ctk"], cur["ctv"]]

    # ---- final: real depth, baseline vs winner
    changed = {k: (baseline[k], cur[k]) for k in cur if cur[k] != baseline[k]}
    depths = [0, fd]
    log(f"  [final] depths {depths}, changed: {changed or 'nothing'}")

    def measure(cfg):
        rows, err = run_bench(path, cfg, {}, depths, args.reps, args.timeout)
        if rows is None:
            return None, err
        return group_rows(rows).get(key_of(cfg)), None

    base_d, berr = measure(baseline)
    win_d = base_d
    if changed:
        win_d, werr = measure(cur)
        if win_d is None:
            rec["notes"].append(f"winner config failed at final depth: {werr}")
    rec["final"] = {"baseline": base_d, "winner": win_d, "baseline_error": berr,
                    "final_depth": fd, "winner_cfg": dict(cur)}
    bs, ws = (score_of(base_d, fd) if base_d else None), (score_of(win_d, fd) if win_d else None)
    if changed and bs and ws and ws >= bs * (1 + args.min_gain):
        rec["recommended"] = dict(cur)
        rec["gain_at_final"] = ws / bs - 1
    else:
        rec["recommended"] = dict(baseline)
        rec["gain_at_final"] = (ws / bs - 1) if (changed and bs and ws) else 0.0
        if changed:
            rec["notes"].append(
                f"Sweep winner did not beat the baseline by {args.min_gain * 100:.0f}% at "
                f"{fd} depth ({100 * rec['gain_at_final']:+.1f}%); keeping baseline.")
    # Optionally measure the optimum found in another power mode, so we learn what
    # using one setting for both modes would cost.
    if args.seed_from:
        sp = RESULTS / args.seed_from / "models" / f"{m['name']}.json"
        if sp.exists():
            s = json.loads(sp.read_text(encoding="utf-8"))
            sc = s.get("recommended")
            if sc:  # runs from before n-cpu-moe support have no "ncmoe" key
                sc = {"ncmoe": 0, **sc}
            if sc and sc != baseline and sc != rec["recommended"]:
                log(f"  [seed] measuring {args.seed_from}'s optimum ({s.get('mode', '?')}) here")
                sd_, serr = measure(sc)
                rec["final"]["seed"] = {"run": args.seed_from, "mode": s.get("mode"),
                                        "cfg": sc, "depths": sd_, "error": serr}
            else:
                rec["notes"].append(
                    f"{args.seed_from}'s optimum ({s.get('mode', '?')}) is identical to this run's "
                    "baseline/recommendation, so no extra measurement was needed.")
        else:
            rec["notes"].append(f"--seed-from {args.seed_from}: no result for this model.")

    rec["changes"] = {INI_KEY[k]: v for k, v in
                      ((k, rec["recommended"][k]) for k in INI_KEY)
                      if v != baseline[k]}
    # ini-friendly values
    if "fa" in rec["changes"]:
        rec["changes"]["fa"] = "on" if rec["changes"]["fa"] else "off"
    rec["elapsed_s"] = round(time.time() - t0)
    rec["done"] = True
    log(f"  done in {rec['elapsed_s']}s; recommended changes: {rec['changes'] or 'none'}")
    return rec


# ------------------------------------------------------------------------ report
def fmt(x, nd=1):
    return "—" if x is None else f"{x:.{nd}f}"


def write_report(run_dir, results, meta, args):
    L = []
    L.append(f"# Model tuning — {meta['run_id']}\n")
    warn = "  ⚠ **This is a low-power mode; numbers are not representative of full performance.**" \
        if is_low_power(meta["power_plan"]) else ""
    L.append(f"- Power mode: **{meta['mode']}** (power plan: {meta['power_plan']}){warn}")
    L.append("- These settings are the optimum **for this power mode**. Compare with the other "
             "mode using `compare_modes.py`.")
    L.append(f"- llama.cpp build {meta.get('build', '?')} · {meta.get('gpu', '?')} · {meta['date']}")
    L.append(f"- Workload: pp{PP} / tg{TG}; sweep depth {args.sweep_depth}, scored depth "
             f"{args.final_depth}; {args.reps} repetition(s); change adopted only if ≥ "
             f"{args.min_gain * 100:.0f}% better; score = √(pp × tg)")
    L.append(f"- Parameters swept: {', '.join(meta['params'])}")
    L.append("- Limits: llama-bench uses synthetic tokens (no real MoE routing, no MTP "
             "speculative decoding), and reports throughput only, not load time or quality "
             "(except the KV perplexity guard).\n")

    L.append("## Summary\n")
    L.append("| Model | Baseline score @ depth | Recommended | Change | Settings to change |")
    L.append("|---|---:|---:|---:|---|")
    for r in results:
        fd = r["final"]["final_depth"]
        b = score_of(r["final"]["baseline"] or {}, fd)
        w = score_of(r["final"]["winner"] or {}, fd) if r["recommended"] == r["final"]["winner_cfg"] \
            else b
        ch = ", ".join(f"{k}={v}" for k, v in r["changes"].items()) or "none"
        pct = f"{100 * r['gain_at_final']:+.1f}%" if r["changes"] else "—"
        L.append(f"| {r['name']} | {fmt(b)} | {fmt(w)} | {pct} | {ch} |")

    for r in results:
        fd = r["final"]["final_depth"]
        L.append(f"\n## {r['name']}\n")
        L.append(f"{r['size_gb']} GB · preset `{r['preset']}`"
                 + (f" (also: {', '.join(r['other_presets'])})" if r['other_presets'] else "")
                 + f" · {r['elapsed_s']}s\n")
        L.append("| Setting | Baseline | Recommended |")
        L.append("|---|---|---|")
        for k in ("ub", "b", "fa", "t", "lm", "ctk", "ctv"):
            bv, rv = r["baseline"][k], r["recommended"][k]
            mark = " **←**" if bv != rv else ""
            L.append(f"| {INI_KEY[k]} | {bv} | {rv}{mark} |")
        L.append("\n| Config | pp t/s @0 | tg t/s @0 | pp @" + str(fd) + " | tg @" + str(fd)
                 + " | score @" + str(fd) + " |")
        L.append("|---|---:|---:|---:|---:|---:|")
        seed = r["final"].get("seed")
        rows_ = [("baseline", r["final"]["baseline"]), ("winner", r["final"]["winner"])]
        if seed and seed.get("depths"):
            rows_.append((f"{seed.get('mode') or 'other-mode'} optimum (run {seed['run']})",
                          seed["depths"]))
        for label, d in rows_:
            if not d:
                continue
            g = lambda dep, kind: (d.get(dep, {}).get(kind) or (None,))[0]
            L.append(f"| {label} | {fmt(g(0, 'pp'))} | {fmt(g(0, 'tg'))} | {fmt(g(fd, 'pp'))} "
                     f"| {fmt(g(fd, 'tg'))} | {fmt(score_of(d, fd))} |")
        for n in r["notes"]:
            L.append(f"\n> {n}")
        if r["kv_guard"]:
            g = r["kv_guard"]
            L.append("\n**KV perplexity guard:** "
                     + (f"f16 {g['f16']:.4f} vs q8_0 {g['q8_0']:.4f} "
                        f"(+{g['rel_increase'] * 100:.2f}%, limit {g['threshold'] * 100:.1f}%) → "
                        f"{'PASS' if g['pass'] else 'FAIL'}; speed gain "
                        f"{g['speed_gain'] * 100:+.1f}%" if "f16" in g and "q8_0" in g
                        else f"could not run: {g.get('error')}"))
        L.append("\n<details><summary>Sweep stages</summary>\n")
        for s in r["stages"]:
            forced = (", " + ", ".join(f"{k}={v} fixed" for k, v in s["forced"].items())) \
                if s.get("forced") else ""
            L.append(f"**{s['param']}** (depth {s['depth']}{forced}, kept `{s['current']}`, "
                     f"chose `{s['chosen']}`)\n")
            L.append("| value | pp | tg | score |")
            L.append("|---|---:|---:|---:|")
            for x in s["records"]:
                if x["error"]:
                    L.append(f"| {x['value']} | error | | {x['error'][:60]} |")
                else:
                    L.append(f"| {x['value']} | {fmt(x['pp'][0] if x['pp'] else None)} | "
                             f"{fmt(x['tg'][0] if x['tg'] else None)} | {fmt(x['score'])} |")
            L.append("")
        L.append("</details>")
    (run_dir / "tuning.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def write_proposals(run_dir, results, mode="?"):
    props = {"run": run_dir.name, "mode": mode, "ini": str(INI_PATH).replace("\\", "/"),
             "models": {}}
    for r in results:
        if r["changes"] and r["preset"]:
            props["models"][r["name"]] = {
                "preset": r["preset"], "other_presets": r["other_presets"],
                "changes": r["changes"], "gain_pct": round(100 * r["gain_at_final"], 1)}
    (run_dir / "proposals.json").write_text(json.dumps(props, indent=2), encoding="utf-8")


# -------------------------------------------------------------------------- main
def main():
    global _logfile
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-env", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--models", nargs="*", help="model names (substring match)")
    ap.add_argument("--params", nargs="*", default=ALL_PARAMS,
                    help="ubatch batch fa threads loadmode kv (space or comma separated)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--sweep-depth", type=int, default=4096)
    ap.add_argument("--final-depth", type=int, default=16384)
    ap.add_argument("--min-gain", type=float, default=0.02)
    ap.add_argument("--ppl-threshold", type=float, default=0.01)
    ap.add_argument("--ppl-chunks", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=7200, help="per llama-bench/perplexity process")
    ap.add_argument("--run")
    ap.add_argument("--stop-router", action="store_true")
    ap.add_argument("--restart-after", action="store_true")
    ap.add_argument("--ignore-router", action="store_true")
    ap.add_argument("--mode", help="power mode being measured: windows | performance "
                                   "(or any label). Checked against the active power plan.")
    ap.add_argument("--no-mode-check", action="store_true",
                    help="skip the check that the power plan matches --mode")
    ap.add_argument("--seed-from", help="earlier run id: also measure its recommended settings "
                                        "(from the other power mode) in the final stage")
    args = ap.parse_args()
    params = [p for chunk in args.params for p in chunk.split(",") if p]
    bad = [p for p in params if p not in ALL_PARAMS]
    if bad:
        print(f"unknown params: {bad}; choose from {ALL_PARAMS}", file=sys.stderr)
        return 2

    models = discover_ggufs()
    sections = parse_ini() if INI_PATH.exists() else {}

    if args.check_env:
        info = {"power_plan": power_plan(), "modes": MODE_PLAN,
                "low_power_plan": is_low_power(power_plan()), "router": router_state(),
                "tools": {t: bool(tool(t)) for t in ("llama-bench", "llama-perplexity", "llama-server")},
                "ppl_text": PPL_TEXT.exists(), "ini": str(INI_PATH), "models": []}
        for m in models:
            b, primary, others = preset_baseline(m, sections)
            info["models"].append({**m, "preset": primary, "baseline": b})
        print(json.dumps(info, indent=2))
        return 0

    if args.models:
        want = [w.lower() for w in args.models]
        models = [m for m in models if any(w in m["name"].lower() for w in want)]
    if not models:
        print("no matching models", file=sys.stderr)
        return 2

    # ---- power mode: label this run and make sure the machine is really in that mode
    plan = power_plan()
    mode = args.mode.strip() if args.mode else plan
    args.mode_label, args.plan = mode, plan
    if args.mode and not args.no_mode_check:
        err = mode_error(args.mode, plan)
        if err:
            print(f"ERROR: {err}.", file=sys.stderr)
            return 4
    elif not args.mode:
        print(f"note: no --mode given; labelling this run with the power plan name '{plan}'. "
              f"Use --mode {'|'.join(KNOWN_MODES)} so runs can be compared across modes.",
              file=sys.stderr)

    slug = re.sub(r"[^a-z0-9]+", "-", mode.lower()).strip("-") or "run"
    run_id = args.run or f"{datetime.now():%Y-%m-%d_%H%M%S}_{slug}"
    run_dir = RESULTS / run_id
    if not args.dry_run:
        (run_dir / "models").mkdir(parents=True, exist_ok=True)
        _logfile = run_dir / "progress.log"

    log(f"run {run_id}: mode '{mode}' (power plan '{plan}'); {len(models)} model(s); "
        f"params {params}; reps {args.reps}; sweep depth {args.sweep_depth}; "
        f"final depth {args.final_depth}"
        + (f"; seed from {args.seed_from}" if args.seed_from else ""))
    for m in models:
        log(f"  - {m['name']} ({m['size_gb']} GB)")
    if args.dry_run:
        return 0
    meta_path = run_dir / "meta.json"
    meta_path.write_text(json.dumps({
        "run_id": run_id, "mode": mode, "power_plan": plan,
        "started": datetime.now().isoformat(timespec="seconds"),
        "models": [m["name"] for m in models], "params": params, "reps": args.reps,
        "sweep_depth": args.sweep_depth, "final_depth": args.final_depth,
        "min_gain": args.min_gain, "seed_from": args.seed_from, "completed": False,
    }, indent=2), encoding="utf-8")

    rs = router_state()
    if rs["running"] and not (args.stop_router or args.ignore_router):
        print(f"ERROR: llama-server is running (port {ROUTER_PORT} / process). It would compete for "
              "memory bandwidth and skew results. Re-run with --stop-router (and "
              "--restart-after) or --ignore-router.", file=sys.stderr)
        return 3
    if rs["running"] and args.stop_router:
        log("stopping llama-server ...")
        if not stop_router():
            print("ERROR: could not stop llama-server", file=sys.stderr)
            return 3

    if is_low_power(plan):
        log(f"WARNING: power plan is '{plan}' (low-power); results won't reflect full speed.")

    results, build, gpu = [], None, None
    try:
        for m in models:
            f = run_dir / "models" / f"{m['name']}.json"
            if f.exists() and json.loads(f.read_text()).get("done"):
                log(f"\n=== {m['name']}: already done, loading saved result")
                results.append(json.loads(f.read_text()))
                continue
            r = tune_model(m, sections, args, params)
            f.write_text(json.dumps(r, indent=2, default=list), encoding="utf-8")
            results.append(json.loads(f.read_text()))
    finally:
        if args.restart_after:
            log("restarting router ...")
            restart_router()

    # JSON round-trip turns int depth keys into strings; normalise for the report
    def fix(d):
        return None if d is None else {int(k): v for k, v in d.items()}
    for r in results:
        r["final"]["baseline"] = fix(r["final"]["baseline"])
        r["final"]["winner"] = fix(r["final"]["winner"])
        if r["final"].get("seed"):
            r["final"]["seed"]["depths"] = fix(r["final"]["seed"].get("depths"))
    meta = {"run_id": run_id, "mode": mode, "power_plan": plan,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "params": params, "build": f"b{BUILD.get('build', '?')}", "gpu": BUILD.get("gpu", "?")}
    (run_dir / "tuning.json").write_text(json.dumps(results, indent=2, default=list), encoding="utf-8")
    write_report(run_dir, results, meta, args)
    write_proposals(run_dir, results, mode)
    mj = json.loads(meta_path.read_text(encoding="utf-8"))
    mj.update(completed=True, finished=datetime.now().isoformat(timespec="seconds"),
              build=meta["build"], gpu=meta["gpu"])
    meta_path.write_text(json.dumps(mj, indent=2), encoding="utf-8")
    log(f"\nreport: {run_dir / 'tuning.md'}\nproposals: {run_dir / 'proposals.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
