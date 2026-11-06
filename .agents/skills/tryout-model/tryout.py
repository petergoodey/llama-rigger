#!/usr/bin/env python3
"""tryout-model: run a candidate GGUF on a private router, smoke-test it, promote it.

The trial never touches the main router or local/models.ini until `promote
--apply`. It runs a second llama-server router on its own port (default 9947)
from local/tryout.ini, a preset file holding the main ini's [*] defaults plus
the one trial section, so the preset is validated exactly as models.ini would
validate it.

Subcommands:
  draft    write local/tryout.ini: [*] from local/models.ini + one trial section
  memory   what the main router has loaded right now (memory competition)
  serve    start the trial router in the background (logs: results/tryout/router.log)
  status   is it up, which presets it offers, their state
  smoke    load the model and run quick checks: load time, chat, tool call,
           long-prompt prefill, decode t/s, MTP acceptance; writes results/tryout/<name>-smoke.json
  stop     stop the trial router (and the model process it started)
  promote  show the diff that adds the trial section to local/models.ini;
           --apply writes it (backup first)
  record   add facts to the trial record (source, quant, fit.py estimate,
           comparison, benchmark run, decision) and re-render the trial report

The trial report is local/tryouts/<preset>.md (record: <preset>.json beside it).
draft, smoke and record update it, so it is current after every step.

Standard library only. Examples:
  python tryout.py draft --name GLM-OCR-Q8_0 --model C:/Models/models/GLM-OCR/GLM-OCR-Q8_0.gguf \\
      --mmproj C:/Models/models/GLM-OCR/mmproj-GLM-OCR-Q8_0.gguf --ctx 16384 \\
      --source "ggml-org/GLM-OCR-GGUF Q8_0"
  python tryout.py serve && python tryout.py smoke --name GLM-OCR-Q8_0
  python tryout.py promote --name GLM-OCR-Q8_0            # diff only
  python tryout.py promote --name GLM-OCR-Q8_0 --apply
  python tryout.py stop
"""
import argparse, difflib, json, re, shutil, sys, time, urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
import hostplat, rigger

HERE = Path(__file__).resolve().parent
REPO, LOCAL = rigger.REPO, rigger.LOCAL
TRY_INI = LOCAL / "tryout.ini"
STATE_DIR = HERE / "results" / "tryout"
STATE = STATE_DIR / "state.json"
PORT, MAIN_PORT = rigger.TRYOUT_PORT, rigger.ROUTER_PORT


# ------------------------------------------------------------------ http
def http(port, path, body=None, timeout=30):
    return rigger.http_json(rigger.base_url(port), path, body, timeout)


def up(port):
    try:
        http(port, "/health", timeout=3)
        return True
    except Exception:
        return False


def models(port):
    try:
        return http(port, "/models", timeout=10).get("data", [])
    except Exception:
        return None


# ------------------------------------------------------------------ ini helpers
def ini_sections(text):
    """[(name, start_line, end_line)] for each [section], end exclusive, trailing
    blank/comment lines left to the next section (they usually describe it)."""
    lines = text.splitlines(keepends=True)
    heads = [(i, m.group(1)) for i, l in enumerate(lines) if (m := re.match(r"^\s*\[([^\]]+)\]\s*$", l))]
    out = []
    for n, (i, name) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        while end > i + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith(";")):
            end -= 1
        out.append((name, i, end))
    return lines, out


def section_text(path, name):
    lines, secs = ini_sections(path.read_text(encoding="utf-8"))
    for n, s, e in secs:
        if n == name:
            return "".join(lines[s:e]).rstrip() + "\n"
    return None


# ------------------------------------------------------------------ trial record + report
# One record per trial in local/tryouts/<preset>.json (machine-readable) and its
# rendering local/tryouts/<preset>.md (the trial report). Every step that learns
# something merges it into the record and re-renders the report, so a trial that
# stops half-way still leaves a report.
REPORTS = LOCAL / "tryouts"
BENCH_RESULTS = HERE.parent / "benchmark-model" / "results"


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def load_record(name):
    p = REPORTS / f"{_safe(name)}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {
        "name": name, "started": datetime.now().isoformat(timespec="seconds")}


def save_record(name, rec):
    REPORTS.mkdir(parents=True, exist_ok=True)
    rec["updated"] = datetime.now().isoformat(timespec="seconds")
    (REPORTS / f"{_safe(name)}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    (REPORTS / f"{_safe(name)}.md").write_text(render(rec), encoding="utf-8")


def measured_memory():
    """MiB figures from the trial router's log since `serve`: KV cache, model and
    compute buffers per device (needs verbosity >= 4, which `draft` sets)."""
    log_path = STATE_DIR / "router.log"
    if not log_path.exists():
        return None
    with open(log_path, "rb") as f:
        f.seek(_state().get("log_offset", 0))
        text = f.read().decode("utf-8", "replace")
    # only the most recent load (the model may have slept and reloaded)
    starts = [m.start() for m in re.finditer(r"llama_model_loader: loaded meta data", text)]
    text = text[starts[-1]:] if starts else text
    out = {}
    # Every cache of this load adds up: sliding-window models log two, and a
    # draft-mtp model's draft context logs its own 1-layer cache after the main one
    # (measured: Qwen3.8-27B, 16 + 1 layers). The draft context reuses the loaded
    # model, so it does not start a new "loaded meta data" block.
    caches = re.findall(r"llama_kv_cache: size =\s*([\d.]+) MiB \(\s*(\d+) cells,\s*(\d+) layers", text)
    if caches:
        out["kv_mib"] = round(sum(float(c[0]) for c in caches), 2)
        out["kv_cells"] = int(caches[0][1])
        out["kv_layers"] = sum(int(c[2]) for c in caches)
        out["kv_caches"] = len(caches)
    for kind in ("model", "compute"):
        per = {}
        for dev, mib in re.findall(rf"(\S+) {kind} buffer size =\s*([\d.]+) MiB", text):
            per[dev] = round(per.get(dev, 0) + float(mib), 2)   # several buffers per device add up
        if per:
            out[f"{kind}_mib"] = per
    return out or None


def benchmark_summary(run, model):
    """Scoreboard for one model from a benchmark-model run: auto_scores.json
    (autograde), judge_scores.json (the session's 0-2 found/rootcause/fix grades)
    and speed.json (bench.py)."""
    d = BENCH_RESULTS / run
    load = lambda f: json.loads((d / f).read_text(encoding="utf-8")) if (d / f).exists() else {}
    auto, judge, speed = load("auto_scores.json").get(model, {}), load("judge_scores.json").get(model, {}), \
        load("speed.json").get(model, {})
    code = {t: r for t, r in auto.items() if t.startswith("c")}
    vuln = {t: r for t, r in auto.items() if t.startswith("v")}
    # judge-only tasks are only compile-checked: the judge grades them, so they are
    # left out of the auto-pass count whatever their build result
    judge_only = set()
    for tj in (HERE.parent / "benchmark-model" / "tasks").glob("*/task.json"):
        t = json.loads(tj.read_text(encoding="utf-8"))
        if t.get("grading", {}).get("judge_only"):
            judge_only.add(t["id"])
    graded = [r for tid, r in vuln.items() if tid not in judge_only]
    out = {"run": run, "report": str(d / "report.md") if (d / "report.md").exists() else None,
           "coding_pass": f"{sum(r['auto'] == 'PASS' for r in code.values())}/{len(code)}" if code else None,
           "vuln_auto_pass": f"{sum(r['auto'] == 'PASS' for r in graded)}/{len(graded)}" if vuln else None,
           "decode_tps_median": speed.get("decode_tps_median"), "wall_s_median": speed.get("wall_s_median")}
    if judge:
        pts = [sum(int(j.get(k, 0)) for k in ("found", "rootcause", "fix")) for j in judge.values()]
        out["reasoning"] = f"{sum(pts)}/{6 * len(pts)}"
        traps = [t for t, r in vuln.items() if r.get("trap")]
        out["trap_false_positives"] = sum(1 for t in traps if int(judge.get(t, {}).get("found", 1)) == 0)
    if speed.get("spec"):
        out["mtp_mean_accepted_len"] = speed["spec"].get("mean_accepted_len")
    return out


def render(rec):
    t, sm, mem = rec.get("trial", {}), rec.get("smoke", {}), rec.get("memory_measured") or {}
    C = sm.get("checks", {})
    L = [f"# Trial: {rec['name']}", ""]
    dec = rec.get("decision")
    L.append(f"**Decision:** {dec['verdict'].upper()} ({dec.get('date')}): {dec.get('reason', '')}" if dec
             else "**Decision:** pending")
    L += ["", "| | |", "|---|---|"]
    for k, label in (("source", "Source"), ("quant", "Quant"), ("license", "Licence"),
                     ("download_gib", "Download (GiB)"), ("model_path", "File"), ("mmproj", "mmproj"),
                     ("c", "Context (c)"), ("parallel", "parallel"), ("mtp_n_max", "MTP spec-draft-n-max"),
                     ("extra", "Other settings"), ("power_mode", "Power mode")):
        if t.get(k) not in (None, "", []):
            L.append(f"| {label} | {t[k]} |")
    L.append(f"| Started / updated | {rec.get('started')} / {rec.get('updated')} |")

    fit = rec.get("fit")
    if fit or mem:
        L += ["", "## Memory: estimate vs measured", "", "| | fit.py estimate | measured (load log) |",
              "|---|---|---|"]
        mm = lambda d: round(sum(d.values()) / 1024, 2) if isinstance(d, dict) and d else None
        L.append(f"| weights GiB | {(fit or {}).get('weights_gib', '')} | {mm(mem.get('model_mib')) or ''} |")
        kv_meas = round(mem["kv_mib"] / 1024, 2) if mem.get("kv_mib") is not None else ""
        L.append(f"| KV cache GiB | {(fit or {}).get('kv_gib', '')} | {kv_meas}"
                 + (f" ({mem['kv_layers']} layers, {mem['kv_cells']} cells"
                    + (f", {mem['kv_caches']} caches" if mem.get("kv_caches", 1) > 1 else "") + ")"
                    if mem.get("kv_layers") else "") + " |")
        L.append(f"| compute GiB | {(fit or {}).get('compute_gib', '')} | {mm(mem.get('compute_mib')) or ''} |")
        L.append(f"| footprint GiB | {(fit or {}).get('footprint_gib', '')} | "
                 f"{round(sum(x for x in (mm(mem.get('model_mib')), mem.get('kv_mib', 0) / 1024 if mem.get('kv_mib') else 0, mm(mem.get('compute_mib'))) if x), 2) if mem else ''} |")
        if fit and "headroom_alone_gib" in fit:
            L.append(f"| headroom vs budget GiB | {fit['headroom_alone_gib']} | |")

    if C:
        L += ["", f"## Smoke test ({sm.get('date')})", "", "| check | result |", "|---|---|"]
        ok = lambda c: "ok" if c.get("ok") else ("**failed**" + (f": {c['error']}" if c.get("error") else ""))
        if "load" in C:
            L.append(f"| load (first request) | {ok(C['load'])}"
                     + (f", {C['load'].get('seconds_incl_load')} s" if C['load'].get('ok') else "") + " |")
        if "basic" in C:
            b = C["basic"]
            extra = (f", MTP accept {b['accept_rate']:.0%} ({b['draft_accepted']}/{b['draft_n']})"
                     if b.get("draft_n") else "")
            L.append(f"| chat answer | {ok(b)}, decode **{b.get('decode_tps')} t/s**, {b.get('tokens')} tokens, "
                     f"reasoning {'yes' if b.get('reasoning') else 'no'}{extra} |")
        if "tool_call" in C:
            L.append(f"| tool call | {ok(C['tool_call'])}"
                     + (f" `{C['tool_call'].get('arguments')}`" if C['tool_call'].get('ok') else "") + " |")
        if "prefill" in C:
            p = C["prefill"]
            L.append(f"| prefill | {ok(p)}, **{p.get('prefill_tps')} t/s** at {p.get('prompt_tokens')} tokens |")
        if "settings" in C:
            s = C["settings"]
            L.append(f"| in effect (/props, /slots) | {ok(s)}"
                     + (f", {s.get('total_slots')} slot(s) x {s.get('n_ctx_per_slot')} ctx, build {s.get('build')}"
                        if s.get("ok") else "") + " |")

    if rec.get("compare"):
        L += ["", "## Compared with installed models", "", rec["compare"]]
    b = rec.get("benchmark")
    if b:
        L += ["", f"## Benchmark (benchmark-model run `{b['run']}`)", "", "| | |", "|---|---|"]
        for k, label in (("coding_pass", "coding tasks passed"), ("vuln_auto_pass", "vuln fixes auto-checked"),
                         ("reasoning", "vuln reasoning (found/rootcause/fix)"),
                         ("trap_false_positives", "trap false positives"),
                         ("decode_tps_median", "median decode t/s"), ("wall_s_median", "median s/answer"),
                         ("mtp_mean_accepted_len", "MTP mean accepted length")):
            if b.get(k) is not None:
                L.append(f"| {label} | {b[k]} |")
        if b.get("report"):
            L.append(f"\nFull report: `{b['report']}`")
    elif rec.get("benchmark_skipped"):
        L += ["", "## Benchmark", "", f"Skipped: {rec['benchmark_skipped']}"]
    if rec.get("notes"):
        L += ["", "## Notes", ""] + [f"- {n}" for n in rec["notes"]]
    return "\n".join(L) + "\n"


def cmd_record(a):
    rec = load_record(a.name)
    t = rec.setdefault("trial", {})
    for k in ("source", "quant", "license", "download_gib", "power_mode"):
        if getattr(a, k) is not None:
            t[k] = getattr(a, k)
    if a.fit:
        src = Path(a.fit)
        rec["fit"] = json.loads(src.read_text(encoding="utf-8") if src.exists() else a.fit)
    if a.compare:
        rec["compare"] = a.compare
    if a.note:
        rec.setdefault("notes", []).append(f"{datetime.now():%Y-%m-%d}: {a.note}")
    if a.benchmark_run:
        rec["benchmark"] = benchmark_summary(a.benchmark_run, a.name)
        rec.pop("benchmark_skipped", None)
    if a.benchmark_skipped:
        rec["benchmark_skipped"] = a.benchmark_skipped
    if a.decision:
        rec["decision"] = {"verdict": a.decision, "reason": a.reason or "",
                           "date": datetime.now().strftime("%Y-%m-%d")}
    save_record(a.name, rec)
    print(f"updated {REPORTS / (_safe(a.name) + '.md')}")
    return 0


# ------------------------------------------------------------------ commands
def cmd_draft(a):
    src = rigger.find_preset()   # [*] defaults as the launcher would read them
    if not src.exists():
        print(f"preset {src} does not exist (LLAMA_PRESET?)", file=sys.stderr)
        return 2
    star = section_text(src, "*")
    target = rigger.preset_target()
    if target.exists() and section_text(target, a.name):
        print(f"note: [{a.name}] already exists in {target}; promote would need --as <new name>",
              file=sys.stderr)
    body = [f"[{a.name}]",
            f"; tryout {datetime.now():%Y-%m-%d}" + (f" - {a.source}" if a.source else ""),
            f"model     = {a.model.replace(chr(92), '/')}"]
    if a.mmproj:
        body.append(f"mmproj    = {a.mmproj.replace(chr(92), '/')}")
    body += [f"parallel  = {a.parallel}", f"c         = {a.ctx}", f"cache-ram = {a.cache_ram}"]
    if a.mtp:
        body += ["spec-type        = draft-mtp", f"spec-draft-n-max = {a.mtp}"]
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        body.append(f"{k.strip():9} = {v.strip()}")
    star = (star or "[*]\nngl = 999\nfa = on\njinja = true\n").rstrip() + "\n"
    # trial only (promote copies just the model's section): log KV / buffer sizes
    star += "verbosity          = 4        ; tryout only: memory lines for the trial report\n"
    text = ("; tryout-model trial preset: [*] copied from models.ini + one trial section.\n"
            "; Rewritten by `tryout.py draft`; edit freely, then `tryout.py serve`.\n\n"
            "version = 1\n\n" + star + "\n\n" + "\n".join(body) + "\n")
    rec = load_record(a.name)
    rec.setdefault("trial", {}).update({k: v for k, v in {
        "preset": a.name, "model_path": a.model.replace("\\", "/"), "mmproj": a.mmproj,
        "c": a.ctx, "parallel": a.parallel, "mtp_n_max": a.mtp, "extra": a.set,
        "source": a.source}.items() if v is not None})
    save_record(a.name, rec)
    LOCAL.mkdir(parents=True, exist_ok=True)
    TRY_INI.write_text(text, encoding="utf-8")
    print(f"wrote {TRY_INI}\n\n{text}")
    return 0


def cmd_memory(a):
    ms = models(MAIN_PORT)
    if ms is None:
        print(f"main router (port {MAIN_PORT}): not running")
        return 0
    loaded = [m["id"] for m in ms if (m.get("status") or {}).get("value") == "loaded"]
    print(f"main router (port {MAIN_PORT}): {len(ms)} presets, loaded now: {', '.join(loaded) or 'none'}")
    print("The trial router's memory is NOT counted by the main router's margin, and vice versa:"
          " check the trial model fits next to what is loaded, or free memory first.")
    return 0


def _state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def cmd_serve(a):
    if not TRY_INI.exists():
        print(f"no {TRY_INI}; run `tryout.py draft` first", file=sys.stderr)
        return 2
    if up(PORT):
        print(f"port {PORT} already answers; `tryout.py stop` first, or set TRYOUT_PORT", file=sys.stderr)
        return 3
    exe = shutil.which("llama-server")
    if not exe:
        print("llama-server not on PATH", file=sys.stderr)
        return 2
    # --models-memory-margin is left at llama-server's default on purpose: the trial
    # router only ever holds one model, and memory is checked by hand (see `memory`).
    cmd = [exe, "--models-preset", str(TRY_INI), "--host", "127.0.0.1", "--port", str(PORT),
           "--models-max", "1"] + (a.extra or [])
    log_path = STATE_DIR / "router.log"
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    p = hostplat.popen_detached(cmd, log_path)
    STATE.write_text(json.dumps({"pid": p.pid, "port": PORT, "ini": str(TRY_INI), "log_offset": log_offset,
                                 "started": datetime.now().isoformat(timespec="seconds"), "cmd": cmd}),
                     encoding="utf-8")
    for _ in range(60):
        if up(PORT):
            print(f"trial router up on 127.0.0.1:{PORT} (pid {p.pid}); log {STATE_DIR / 'router.log'}")
            return 0
        if p.poll() is not None:
            break
        time.sleep(1)
    print(f"trial router did not come up (exit {p.poll()}); see {STATE_DIR / 'router.log'}", file=sys.stderr)
    return 1


def cmd_status(a):
    st = _state()
    ms = models(PORT)
    print(f"trial router: {'up' if ms is not None else 'down'} on port {PORT}"
          + (f" (pid {st.get('pid')}, since {st.get('started')})" if st else ""))
    for m in ms or []:
        print(f"  {m['id']}: {(m.get('status') or {}).get('value')}")
    return 0


def cmd_stop(a):
    st = _state()
    if not st:
        print("no trial router recorded" + (f"; but port {PORT} answers - stop it by hand" if up(PORT) else ""))
        return 0
    hostplat.kill_tree(st["pid"])
    for _ in range(20):
        if not up(PORT):
            break
        time.sleep(1)
    STATE.unlink(missing_ok=True)
    print(f"trial router stopped (pid {st['pid']}); port {PORT} {'still answers!' if up(PORT) else 'free'}")
    return 0


TOOL = {"type": "function", "function": {
    "name": "get_weather", "description": "Get the current weather for a city.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}


def chat(name, messages, max_tokens, timeout, **extra):
    t0 = time.time()
    r = http(PORT, "/v1/chat/completions", dict(
        {"model": name, "messages": messages, "max_tokens": max_tokens, "seed": 1}, **extra), timeout=timeout)
    return r, time.time() - t0


def cmd_smoke(a):
    if not up(PORT):
        print(f"trial router not up on {PORT}; `tryout.py serve` first", file=sys.stderr)
        return 2
    res = {"name": a.name, "date": datetime.now().isoformat(timespec="seconds"), "checks": {}}
    C = res["checks"]

    def run(label, fn):
        try:
            C[label] = fn()
        except Exception as e:  # a failed check is a result, not a crash
            C[label] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}
        print(f"{label:10} {json.dumps(C[label])[:300]}", flush=True)

    def load():
        r, s = chat(a.name, [{"role": "user", "content": "Say OK."}], 4, a.load_timeout)
        return {"ok": True, "seconds_incl_load": round(s, 1)}

    def basic():
        r, s = chat(a.name, [{"role": "user", "content":
                              "Write a short Python function that reverses a string, with a docstring."}],
                    a.max_tokens, 600)
        msg, t = r["choices"][0]["message"], r.get("timings", {})
        out = {"ok": bool(msg.get("content")), "finish": r["choices"][0].get("finish_reason"),
               "decode_tps": round(t.get("predicted_per_second", 0), 1),
               "tokens": t.get("predicted_n"), "reasoning": bool(msg.get("reasoning_content")),
               "answer_head": (msg.get("content") or "")[:160]}
        if t.get("draft_n"):
            out.update(draft_n=t["draft_n"], draft_accepted=t.get("draft_n_accepted"),
                       accept_rate=round(t.get("draft_n_accepted", 0) / t["draft_n"], 2))
        return out

    def tools():
        r, s = chat(a.name, [{"role": "user", "content": "What is the weather in Paris right now? Use the tool."}],
                    a.max_tokens, 600, tools=[TOOL], tool_choice="auto")
        calls = r["choices"][0]["message"].get("tool_calls") or []
        args = calls[0]["function"].get("arguments") if calls else None
        return {"ok": bool(calls) and calls[0]["function"]["name"] == "get_weather",
                "calls": len(calls), "arguments": args}

    def prefill():
        para = (REPO / "AGENTS.md").read_text(encoding="utf-8") if (REPO / "AGENTS.md").exists() \
            else "The quick brown fox jumps over the lazy dog. " * 200
        text = (para * (a.prefill_chars // max(1, len(para)) + 1))[:a.prefill_chars]
        r, s = chat(a.name, [{"role": "user", "content": text + "\n\nIn one sentence: what is this text about?"}],
                    64, 900)
        t = r.get("timings", {})
        return {"ok": True, "prompt_tokens": t.get("prompt_n"),
                "prefill_tps": round(t.get("prompt_per_second", 0), 1)}

    def settings():
        """What is actually in effect (AGENTS.md: trust /props and /slots, not the ini),
        plus the arguments the router spawned the model with."""
        q = "?model=" + urllib.parse.quote(a.name)
        props = http(PORT, "/props" + q, timeout=30)
        slots = http(PORT, "/slots" + q, timeout=30)
        gen = props.get("default_generation_settings", {})
        ms = models(PORT) or []
        m = next((x for x in ms if x["id"] == a.name), {})
        return {"ok": bool(props), "total_slots": props.get("total_slots"),
                "n_ctx_per_slot": gen.get("n_ctx"),
                "slots": len(slots) if isinstance(slots, list) else None,
                "model_path": props.get("model_path"), "build": props.get("build_info"),
                "args": (m.get("status") or {}).get("args")}

    run("load", load)
    if not C["load"].get("ok"):
        print(f"model did not load; see {STATE_DIR / 'router.log'} (the child's errors are there)")
    else:
        run("basic", basic)
        run("tool_call", tools)
        run("prefill", prefill)
    run("settings", settings)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = STATE_DIR / f"{_safe(a.name)}-smoke.json"
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    rec = load_record(a.name)
    rec["smoke"] = res
    rec["memory_measured"] = measured_memory()
    save_record(a.name, rec)
    print(f"wrote {out}\nreport: {REPORTS / (_safe(a.name) + '.md')}")
    return 0


def cmd_promote(a):
    sec = section_text(TRY_INI, a.name) if TRY_INI.exists() else None
    if not sec:
        print(f"[{a.name}] not found in {TRY_INI}", file=sys.stderr)
        return 2
    new_name = a.as_name or a.name
    if new_name != a.name:
        sec = sec.replace(f"[{a.name}]", f"[{new_name}]", 1)
    MAIN_INI = rigger.preset_target()   # never the shipped models.example.ini
    if not MAIN_INI.exists():
        print(f"{MAIN_INI} does not exist; copy models.example.ini there first", file=sys.stderr)
        return 2
    orig = MAIN_INI.read_text(encoding="utf-8")
    if section_text(MAIN_INI, new_name):
        print(f"[{new_name}] already exists in {MAIN_INI}; use --as <other name>", file=sys.stderr)
        return 2
    block = (f"\n; ---- {new_name} - added by tryout-model {datetime.now():%Y-%m-%d} "
             + "-" * max(3, 60 - len(new_name)) + "\n" + sec)
    lines, secs = ini_sections(orig)
    # before the trailing comment block (e.g. a residency table) if the file ends with one
    end_of_last = secs[-1][2] if secs else len(lines)
    new = "".join(lines[:end_of_last]).rstrip("\n") + "\n" + block + "".join(lines[end_of_last:])
    diff = "".join(difflib.unified_diff(orig.splitlines(True), new.splitlines(True),
                                        fromfile=str(MAIN_INI), tofile=str(MAIN_INI) + " (new)"))
    print(diff)
    if not a.apply:
        print("(dry run: nothing written; add --apply)")
        return 0
    bak = MAIN_INI.with_name(MAIN_INI.name + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(MAIN_INI, bak)
    MAIN_INI.write_text(new, encoding="utf-8")
    print(f"wrote {MAIN_INI} (backup {bak.name}). The main router reads presets only at start: "
          f"restart it to offer [{new_name}].")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--name", required=True, help="preset name: the GGUF file name without .gguf/shard suffix")
    d.add_argument("--model", required=True, help="absolute path of the .gguf (first shard)")
    d.add_argument("--mmproj")
    d.add_argument("--ctx", type=int, default=32768, help="c: total KV budget")
    d.add_argument("--parallel", type=int, default=1)
    d.add_argument("--cache-ram", type=int, default=2048)
    d.add_argument("--mtp", type=int, help="enable draft-mtp with this spec-draft-n-max")
    d.add_argument("--set", action="append", help="extra key=value (repeatable), e.g. n-cpu-moe=12")
    d.add_argument("--source", help="where it came from, recorded as a comment")
    sub.add_parser("memory")
    s = sub.add_parser("serve")
    s.add_argument("extra", nargs="*", help="extra llama-server args (after --)")
    sub.add_parser("status")
    sub.add_parser("stop")
    m = sub.add_parser("smoke")
    m.add_argument("--name", required=True)
    m.add_argument("--load-timeout", type=int, default=900, help="seconds for the first request (model load)")
    m.add_argument("--max-tokens", type=int, default=512)
    m.add_argument("--prefill-chars", type=int, default=16000, help="~4K tokens")
    r = sub.add_parser("record", help="add facts to the trial record and re-render the report")
    r.add_argument("--name", required=True)
    r.add_argument("--source")
    r.add_argument("--quant")
    r.add_argument("--license")
    r.add_argument("--download-gib", type=float)
    r.add_argument("--power-mode", help="power mode the numbers were measured in")
    r.add_argument("--fit", help="fit.py --json output: a file path or the JSON itself")
    r.add_argument("--compare", help="Markdown: how it compares with the closest installed model")
    r.add_argument("--note", help="append a dated note")
    r.add_argument("--benchmark-run", help="benchmark-model run id to summarise")
    r.add_argument("--benchmark-skipped", help="why the benchmark was skipped")
    r.add_argument("--decision", choices=["keep", "drop"])
    r.add_argument("--reason")
    p = sub.add_parser("promote")
    p.add_argument("--name", required=True)
    p.add_argument("--as", dest="as_name", help="section name to use in models.ini")
    p.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    return {"draft": cmd_draft, "memory": cmd_memory, "serve": cmd_serve, "status": cmd_status,
            "stop": cmd_stop, "smoke": cmd_smoke, "promote": cmd_promote, "record": cmd_record}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
