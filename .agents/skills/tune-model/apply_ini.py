#!/usr/bin/env python3
"""Apply a tuning run's proposals.json to models.ini.

Safe by default: prints a unified diff and changes nothing unless --apply.
--apply writes a timestamped backup next to the ini first.

Edits only the primary preset of each model (the section named after its GGUF).
Existing keys are updated in place (trailing ; comments kept); missing keys are
appended to the end of that section's key block. Line endings are preserved.

Usage:
  python apply_ini.py --run <run_id>                 # show diff only
  python apply_ini.py --run <run_id> --apply
  python apply_ini.py --run <run_id> --models GLM-OCR-Q8_0 --apply
  python apply_ini.py --run <run_id> --ini C:\\path\\copy.ini   # test on a copy
"""
import argparse, difflib, json, re, shutil, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEYLINE = re.compile(r"^(?P<lead>\s*)(?P<key>[A-Za-z0-9_-]+)(?P<eq>\s*=\s*)(?P<val>[^;\r\n]*?)(?P<cmt>\s*;.*)?$")


def edit_section(lines, section, changes, stamp):
    """Return (new_lines, applied:{key:(old,new)}) or raise KeyError."""
    start = next((i for i, l in enumerate(lines) if l.strip() == f"[{section}]"), None)
    if start is None:
        raise KeyError(section)
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip().startswith("[") and lines[i].strip().endswith("]")),
               len(lines))
    applied, pending = {}, dict(changes)
    last_key = start
    for i in range(start + 1, end):
        m = KEYLINE.match(lines[i].rstrip("\r\n"))
        if m and not lines[i].lstrip().startswith(";"):
            last_key = i
            k = m["key"]
            if k in pending:
                old, new = m["val"].strip(), str(pending.pop(k))
                eol = lines[i][len(lines[i].rstrip("\r\n")):]
                lines[i] = f"{m['lead']}{k}{m['eq']}{new}{m['cmt'] or ''}{eol}"
                applied[k] = (old, new)
    # insert missing keys after the last key line and its comment continuations
    ins = last_key + 1
    while ins < end and lines[ins].lstrip().startswith(";") and lines[ins][:1].isspace():
        ins += 1
    eol = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    pad = next((KEYLINE.match(l.rstrip("\r\n"))["lead"] for l in lines[start + 1:end]
                if KEYLINE.match(l.rstrip("\r\n"))), "")
    new_lines = []
    for k, v in pending.items():
        new_lines.append(f"{pad}{k:<16} = {v}   ; tune-model {stamp}{eol}")
        applied[k] = (None, str(v))
    lines[ins:ins] = new_lines
    return lines, applied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--models", nargs="*")
    ap.add_argument("--ini")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    pj = ROOT / "results" / args.run / "proposals.json"
    if not pj.exists():
        print(f"no proposals at {pj}", file=sys.stderr)
        return 1
    props = json.loads(pj.read_text(encoding="utf-8"))
    ini = Path(args.ini or props["ini"])
    print(f"Proposals from run {args.run}, tuned for power mode: "
          f"{props.get('mode', '(not recorded)')}")
    print("models.ini holds ONE set of settings. If the other power mode's optimum "
          "differs, see `python compare_modes.py`.\n")
    raw = ini.read_bytes().decode("utf-8")
    lines = raw.splitlines(keepends=True)
    orig = list(lines)
    stamp = datetime.now().strftime("%Y-%m-%d")

    todo = props["models"]
    if args.models:
        want = [w.lower() for w in args.models]
        todo = {k: v for k, v in todo.items() if any(w in k.lower() for w in want)}
    if not todo:
        print("nothing to apply (no proposals, or filter matched nothing)")
        return 0

    for name, p in todo.items():
        try:
            lines, applied = edit_section(lines, p["preset"], p["changes"], stamp)
        except KeyError:
            print(f"! section [{p['preset']}] not found in {ini}; skipped {name}")
            continue
        print(f"[{p['preset']}]  ({p['gain_pct']:+.1f}% at scored depth)")
        for k, (old, new) in applied.items():
            print(f"    {k}: {old if old is not None else '(unset)'} -> {new}")
        if p.get("other_presets"):
            print(f"    note: other presets using this GGUF are untouched: "
                  f"{', '.join(p['other_presets'])}")

    diff = "".join(difflib.unified_diff(orig, lines, fromfile=str(ini), tofile=str(ini) + " (new)"))
    print("\n" + (diff or "(no textual change)"))
    if not args.apply:
        print("dry run: nothing written. Re-run with --apply to write.")
        return 0
    if diff:
        bak = ini.with_name(ini.name + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(ini, bak)
        ini.write_bytes("".join(lines).encode("utf-8"))
        print(f"applied. backup: {bak}")
        print("Edits take effect when each preset next cold-starts; unload or restart the router.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
