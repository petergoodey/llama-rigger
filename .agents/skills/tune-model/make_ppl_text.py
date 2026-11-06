#!/usr/bin/env python3
"""Build ppl_text.txt: a fixed code+prose corpus for the KV-quant perplexity guard.

Run once per machine; the output goes to local/ppl_text.txt (the private repo,
since it embeds your preset ini) so every tuning run scores the same text.
Source = benchmark-model task sources/keys + AGENTS.md + the active preset ini.
Rebuilding it changes the corpus: perplexity numbers from before and after are
not comparable.
"""
from tune import INI_PATH, MODELS_DIR, PPL_TEXT

BENCH_TASKS = MODELS_DIR / ".agents" / "skills" / "benchmark-model" / "tasks"

parts = []
for p in (MODELS_DIR / "AGENTS.md", INI_PATH):
    if p.exists():
        parts.append(f"=== {p.name} ===\n" + p.read_text(encoding="utf-8", errors="replace"))

if BENCH_TASKS.exists():
    for f in sorted(BENCH_TASKS.rglob("*")):
        if f.is_file() and f.suffix in (".c", ".cpp", ".cs", ".md"):
            parts.append(f"=== {f.relative_to(BENCH_TASKS)} ===\n"
                         + f.read_text(encoding="utf-8", errors="replace"))

text = "\n\n".join(parts) + "\n"
PPL_TEXT.parent.mkdir(parents=True, exist_ok=True)
PPL_TEXT.write_text(text, encoding="utf-8")
print(f"wrote {PPL_TEXT} ({len(text):,} chars, {len(parts)} sources)")
