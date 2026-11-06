#!/usr/bin/env python3
"""Model-bench task runner.

Sends every task prompt to every configured preset through the llama-server
router's OpenAI-compatible API, and records the answer plus timing/usage.
Stdlib only (urllib) so it runs under plain python or `uv run`.

Presets that use speculative decoding (spec-type set, e.g. draft-mtp) also get
draft statistics per answer (accept rate, mean accepted length) and a per-model
summary in results/<run>/speed.json.

Grading is NOT done here. This produces results/<run>/answers/*.json and
extracted code under results/<run>/code/. autograde.py scores the code; the
Claude session scores the vuln reasoning (see SKILL.md).

Usage:
  python bench.py                      # new run, all configured models
  python bench.py --models A B         # only these presets
  python bench.py --tasks v01 c03      # only these task ids
  python bench.py --run 2026-11-05_01  # reuse/append to an existing run dir
  python bench.py --dry-run            # parse tasks, print plan, send nothing
"""
import argparse, json, re, statistics, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
import rigger

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
RESULTS_DIR = ROOT / "results"

EXT = {"c": "c", "cpp": "cpp", "csharp": "cs"}
FENCE = {"c": ("c",), "cpp": ("cpp", "c++", "cxx", "c"), "csharp": ("csharp", "cs", "c#")}


LOCAL_CONFIG = rigger.LOCAL / "benchmark-config.json"


def load_config():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if LOCAL_CONFIG.exists():  # private overrides (model list etc.)
        cfg.update(json.loads(LOCAL_CONFIG.read_text(encoding="utf-8")))
    cfg.setdefault("base_url", rigger.base_url())   # the router on LLAMA_PORT
    cfg.setdefault("request_timeout_s", 1800)
    cfg.setdefault("max_tokens", 8192)
    cfg.setdefault("warmup", True)
    return cfg


def load_tasks(only=None):
    tasks = []
    for tj in sorted(TASKS_DIR.glob("*/task.json")):
        t = json.loads(tj.read_text(encoding="utf-8"))
        t["_dir"] = tj.parent
        if only and t["id"] not in only:
            continue
        tasks.append(t)
    return tasks


def build_messages(task):
    d = task["_dir"]
    prompt = (d / task["prompt_file"]).read_text(encoding="utf-8")
    parts = [prompt, ""]
    for fn in task.get("files", []):
        code = (d / fn).read_text(encoding="utf-8")
        lang = task.get("lang", "")
        parts.append(f"File `{fn}`:\n```{lang}\n{code}\n```")
    user = "\n".join(parts)
    system = (
        "You are a careful senior engineer. Answer precisely. When asked for "
        "code, return it in a single fenced code block with the correct language "
        "tag and nothing omitted. Do not add commentary inside the code block."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extract_code(text, lang):
    """Return the last fenced block whose tag matches lang, else the last block."""
    blocks = re.findall(r"```([^\n`]*)\n(.*?)```", text, flags=re.S)
    if not blocks:
        return None
    tags = FENCE.get(lang, (lang,))
    matched = [b for (tag, b) in blocks if tag.strip().lower() in tags]
    if matched:
        return matched[-1].strip("\n")
    return blocks[-1][1].strip("\n")


def post_chat(cfg, model, messages):
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": cfg["max_tokens"],
        "stream": False,
        "timings_per_token": True,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        cfg["base_url"].rstrip("/") + "/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=cfg["request_timeout_s"]) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    wall = time.time() - t0
    return payload, wall


def available_models(cfg):
    try:
        req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/v1/models")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {m["id"] for m in data.get("data", [])}
    except Exception as e:
        print(f"  ! could not query /v1/models: {e}", file=sys.stderr)
        return None


def spec_settings(cfg):
    """Per preset: {"spec_type", "n_max"} from the router's GET /models arguments.

    Only presets that actually use speculative decoding are returned. n_max is the
    preset's --spec-draft-n-max (3 if the flag is absent, the build's default).
    """
    out = {}
    try:
        req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/models")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ! could not read preset arguments from /models: {e}", file=sys.stderr)
        return out
    for m in data.get("data", []):
        args = (m.get("status") or {}).get("args") or []

        def val(flag):
            return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None
        st = val("--spec-type")
        if st and st != "none":
            try:
                n_max = int(val("--spec-draft-n-max") or 3)
            except ValueError:
                n_max = 3
            out[m["id"]] = {"spec_type": st, "n_max": n_max}
    return out


def spec_stats(timings, n_max):
    """Speculative-decoding statistics for one response, or None if it didn't draft.

    draft_n / draft_n_accepted come from the server's `timings` block.
    steps ~ draft_n / n_max (each decode step drafts up to n_max tokens; the last
    step of an answer may draft fewer, so this is approximate), and
    mean accepted length = tokens per decode step = (accepted + steps) / steps.
    """
    d = timings.get("draft_n") or 0
    a = timings.get("draft_n_accepted") or 0
    if not d:
        return None
    steps = d / max(n_max, 1)
    return {"draft_n": d, "accepted": a, "n_max": n_max,
            "accept_rate": round(a / d, 4),
            "mean_accepted_len": round((a + steps) / steps, 3)}


def summarise(records):
    """Per-model speed and speculative-decoding summary from the answer records."""
    by = {}
    for r in records:
        by.setdefault(r["model"], []).append(r)
    out = {}
    for model, rs in by.items():
        tps = [r["timings"]["predicted_per_second"] for r in rs
               if r["timings"].get("predicted_per_second")]
        row = {"answers": len(rs),
               "decode_tps_median": round(statistics.median(tps), 1) if tps else None,
               "wall_s_median": round(statistics.median(r["wall_s"] for r in rs), 1)}
        sp = [r["spec"] for r in rs if r.get("spec")]
        if sp:
            d, a = sum(x["draft_n"] for x in sp), sum(x["accepted"] for x in sp)
            steps = sum(x["draft_n"] / x["n_max"] for x in sp)
            row["spec"] = {"n_max": sp[0]["n_max"], "draft_n": d, "accepted": a,
                           "accept_rate": round(a / d, 4),
                           "mean_accepted_len": round((a + steps) / steps, 3),
                           "by_kind": {}}
            for kind in sorted({r["kind"] for r in rs if r.get("spec")}):
                ks = [r["spec"] for r in rs if r.get("spec") and r["kind"] == kind]
                kd, ka = sum(x["draft_n"] for x in ks), sum(x["accepted"] for x in ks)
                kst = sum(x["draft_n"] / x["n_max"] for x in ks)
                row["spec"]["by_kind"][kind] = {
                    "accept_rate": round(ka / kd, 4),
                    "mean_accepted_len": round((ka + kst) / kst, 3)}
        out[model] = row
    return out


def warmup(cfg, model):
    try:
        post_chat(cfg, model, [{"role": "user", "content": "Reply with: ok"}])
    except Exception as e:
        print(f"  ! warmup failed for {model}: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*")
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base-url", help="router URL, overriding config (e.g. the tryout-model "
                                       f"trial router {rigger.base_url(rigger.TRYOUT_PORT)})")
    args = ap.parse_args()

    cfg = load_config()
    if args.base_url:
        cfg["base_url"] = args.base_url
    models = args.models or cfg["models"]
    tasks = load_tasks(set(args.tasks) if args.tasks else None)
    if not tasks:
        print("no tasks found", file=sys.stderr)
        return 1

    run_id = args.run or datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = RESULTS_DIR / run_id
    (run_dir / "answers").mkdir(parents=True, exist_ok=True)
    (run_dir / "code").mkdir(parents=True, exist_ok=True)

    print(f"run: {run_dir}")
    print(f"models ({len(models)}): {', '.join(models)}")
    print(f"tasks ({len(tasks)}): {', '.join(t['id'] for t in tasks)}")

    if args.dry_run:
        for t in tasks:
            msgs = build_messages(t)
            print(f"  [{t['id']}] {t['kind']}/{t['lang']} prompt+code = "
                  f"{len(msgs[1]['content'])} chars")
        return 0

    present = available_models(cfg)
    if not models:  # empty list = everything the router offers
        if present is None:
            print("no models configured and /v1/models unreachable", file=sys.stderr)
            return 1
        models = sorted(present)
        print(f"models (from router, {len(models)}): {', '.join(models)}")
    if present is not None:
        skip = [m for m in models if m not in present]
        if skip:
            print(f"  skipping (not offered by router): {', '.join(skip)}")
        models = [m for m in models if m in present]

    spec_cfg = spec_settings(cfg)
    manifest, records = [], []
    for model in models:
        print(f"\n== {model}")
        if cfg["warmup"]:
            print("   warmup...")
            warmup(cfg, model)
        for t in tasks:
            tag = f"{model}__{t['id']}"
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", tag)
            try:
                payload, wall = post_chat(cfg, model, build_messages(t))
                choice = payload["choices"][0]["message"]
                content = choice.get("content") or ""
                reasoning = choice.get("reasoning_content") or ""
                usage = payload.get("usage", {})
                timings = payload.get("timings", {})
                code = extract_code(content, t.get("lang", ""))
                spec = spec_stats(timings, spec_cfg[model]["n_max"]) if model in spec_cfg else None
                rec = {
                    "model": model, "task": t["id"], "kind": t["kind"],
                    "lang": t["lang"], "trap": t.get("trap", False),
                    "wall_s": round(wall, 2), "usage": usage, "timings": timings,
                    "spec": spec,
                    "reasoning_chars": len(reasoning),
                    "content": content, "reasoning_content": reasoning,
                    "has_code": code is not None,
                }
                (run_dir / "answers" / f"{safe}.json").write_text(
                    json.dumps(rec, indent=2), encoding="utf-8")
                if code is not None:
                    (run_dir / "code" / f"{safe}.{EXT[t['lang']]}").write_text(
                        code, encoding="utf-8")
                records.append(rec)
                tps = timings.get("predicted_per_second")
                line = (f"   [{t['id']}] {wall:6.1f}s  "
                        f"{usage.get('completion_tokens','?')} tok"
                        + (f"  {tps:.1f} t/s" if tps else ""))
                if spec:
                    line += (f"  draft {spec['accepted']}/{spec['draft_n']} "
                             f"({spec['accept_rate']:.0%}) mean len {spec['mean_accepted_len']:.2f}")
                print(line)
                manifest.append({"model": model, "task": t["id"],
                                 "answer": f"answers/{safe}.json",
                                 "code": f"code/{safe}.{EXT[t['lang']]}" if code else None})
            except urllib.error.URLError as e:
                print(f"   [{t['id']}] ERROR {e}", file=sys.stderr)
                manifest.append({"model": model, "task": t["id"], "error": str(e)})
            except Exception as e:
                print(f"   [{t['id']}] ERROR {e}", file=sys.stderr)
                manifest.append({"model": model, "task": t["id"], "error": str(e)})

    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    speed = summarise(records)
    (run_dir / "speed.json").write_text(json.dumps(speed, indent=2), encoding="utf-8")
    for model, row in speed.items():
        sp = row.get("spec")
        if sp:
            print(f"   {model}: MTP/spec n-max {sp['n_max']}: accept {sp['accept_rate']:.0%}, "
                  f"mean accepted length {sp['mean_accepted_len']:.2f}, "
                  f"median decode {row['decode_tps_median']} t/s")
    print(f"\ndone. {run_dir / 'manifest.json'}")
    print("next: python autograde.py --run", run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
