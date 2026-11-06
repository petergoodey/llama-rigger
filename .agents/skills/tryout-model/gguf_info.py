#!/usr/bin/env python3
"""Read a GGUF file's metadata header, locally or straight from Hugging Face.

For a URL only the header is fetched (HTTP Range requests, a few MB), not the
weights, so a model can be sized before it is downloaded. For a sharded model
give the first shard (-00001-of-0000N): it holds the metadata.

Prints the architecture facts that matter for sizing and the matching fit.py
arguments:
  kv_layers  = layers that keep a KV cache (full attention; hybrid/recurrent
               layers and MTP layers excluded where the header says so)
  kv_heads   = KV heads per such layer
  kv_dim     = key head dim + value head dim
plus context length, expert counts, MTP (nextn) layers and sliding-window info.

Standard library only. Usage:
  python gguf_info.py models/<file>.gguf
  python gguf_info.py https://huggingface.co/<org>/<repo>/resolve/main/<file>.gguf
  python gguf_info.py <path-or-url> --json
"""
import argparse, json, os, struct, sys, urllib.request

CHUNK = 4 * 2**20
UA = {"User-Agent": "tryout-model-gguf-info/1.0"}


class Source:
    """Byte source over a local file or an HTTP URL (Range requests)."""

    def __init__(self, where):
        # buf holds bytes from file offset `base`; `pos` is the read cursor in buf.
        self.where, self.buf, self.base, self.pos = where, b"", 0, 0
        self.remote = where.startswith(("http://", "https://"))
        if self.remote:
            token = os.environ.get("HF_TOKEN")
            self.headers = dict(UA, **({"Authorization": f"Bearer {token}"} if token else {}))
        else:
            self.f = open(where, "rb")
        self.fetched = 0

    def _more(self, need):
        if len(self.buf) - self.pos >= need:
            return
        # drop consumed bytes once, then append whole chunks (no per-read copying)
        self.base += self.pos
        self.buf, self.pos = self.buf[self.pos:], 0
        while len(self.buf) < need:
            start = self.base + len(self.buf)
            size = max(CHUNK, need - len(self.buf))
            if self.remote:
                req = urllib.request.Request(self.where, headers=dict(
                    self.headers, Range=f"bytes={start}-{start + size - 1}"))
                with urllib.request.urlopen(req, timeout=60) as r:
                    # Read at most `size` bytes either way: a server that ignores Range
                    # answers 200 with the whole (multi-GB) file, which we must not pull.
                    data = r.read(size)
                    if r.status != 206 and start > 0:
                        raise ValueError("server ignored the Range request; download the "
                                         "file and run gguf_info.py on the local copy")
            else:
                self.f.seek(start)
                data = self.f.read(size)
            if not data:
                raise EOFError("unexpected end of GGUF header")
            self.fetched += len(data)
            self.buf += data

    def read(self, n):
        self._more(n)
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out


def parse(where, max_bytes=256 * 2**20):
    s = Source(where)
    u = lambda fmt: struct.unpack("<" + fmt, s.read(struct.calcsize(fmt)))[0]
    if s.read(4) != b"GGUF":
        raise ValueError("not a GGUF file")
    version = u("I")
    n_tensors, n_kv = u("Q"), u("Q")
    SCALAR = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}

    def string():
        return s.read(u("Q")).decode("utf-8", "replace")

    def value(t):
        if t in SCALAR:
            return u(SCALAR[t])
        if t == 8:
            return string()
        if t == 9:
            it, n = u("I"), u("Q")
            if it in SCALAR and n > 4096:   # big numeric arrays (token types, scores): skip
                s.read(struct.calcsize(SCALAR[it]) * n)
                return f"<array of {n}>"
            if it == 8 and n > 4096:        # the vocabulary: skip the strings
                for _ in range(n):
                    s.read(u("Q"))
                return f"<{n} strings>"
            return [value(it) for _ in range(n)]
        raise ValueError(f"unknown GGUF value type {t}")

    meta = {}
    for _ in range(n_kv):
        k = string()
        meta[k] = value(u("I"))
        if s.fetched > max_bytes:
            raise ValueError("header larger than expected; stopping")
    return {"version": version, "tensors": n_tensors, "meta": meta, "header_bytes_read": s.fetched}


def summarise(meta):
    arch = meta.get("general.architecture", "?")
    g = lambda k, d=None: meta.get(f"{arch}.{k}", d)
    n_layer = g("block_count")
    heads = g("attention.head_count")
    kv = g("attention.head_count_kv", heads)
    emb = g("embedding_length")
    head_dim = (emb // heads) if (emb and isinstance(heads, int) and heads) else None
    k_len, v_len = g("attention.key_length", head_dim), g("attention.value_length", head_dim)
    nextn = g("nextn_predict_layers", 0) or 0
    interval = g("full_attention_interval")
    notes = []

    # Which layers keep a KV cache?
    if isinstance(kv, list):                       # per-layer list; 0 = no attention
        # the last `nextn` entries are the MTP layers: left out here like everywhere
        # else, and added back by the draft-mtp hint below
        base_layers = kv[:len(kv) - nextn] if nextn else kv
        attn = [h for h in base_layers if h]
        kv_layers, kv_heads = len(attn), (max(attn) if attn else 0)
        if len(set(attn)) > 1:
            notes.append(f"KV heads vary per layer {sorted(set(attn))}; used the max")
    elif interval and n_layer:
        base = n_layer - nextn
        kv_layers, kv_heads = base // interval, kv
        notes.append(f"hybrid: 1 in {interval} layers is full attention")
    else:
        kv_layers, kv_heads = (n_layer - nextn) if n_layer else None, kv
    if nextn:
        # Measured (GLM-OCR, b12121): without speculative decoding the nextn layer is
        # ignored and gets no KV cache. With draft-mtp it runs too: count it then.
        notes.append(f"MTP head: {nextn} nextn layer(s). Excluded from kv_layers; with "
                     f"spec-type = draft-mtp use --kv-layers {(kv_layers or 0) + nextn}")
    if g("ssm.state_size") or g("ssm.conv_kernel"):
        notes.append("has recurrent/SSM layers: their state is small and fixed, not per token")
    sw = g("attention.sliding_window")
    if sw:
        notes.append(f"sliding-window attention ({sw} tokens) on some layers: real KV is lower "
                     "than kv_layers suggests at long context; check the load log")
    kv_dim = (k_len + v_len) if (k_len and v_len) else None
    out = {
        "architecture": arch, "name": meta.get("general.name"),
        "file_type": meta.get("general.file_type"), "size_label": meta.get("general.size_label"),
        "context_length": g("context_length"), "layers": n_layer,
        "experts": g("expert_count"), "experts_used": g("expert_used_count"),
        "kv_layers": kv_layers, "kv_heads": kv_heads, "kv_dim": kv_dim,
        "kv_kib_per_token_f16": round(kv_layers * kv_heads * kv_dim * 2 / 1024, 1)
        if (kv_layers and kv_heads and kv_dim) else None,
        "mtp_layers": nextn, "split_count": meta.get("split.count"),
        "has_chat_template": "tokenizer.chat_template" in meta, "notes": notes,
    }
    if kv_layers and kv_heads and kv_dim:
        out["fit_args"] = f"--kv-layers {kv_layers} --kv-heads {kv_heads} --kv-dim {kv_dim}"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("where", help="local .gguf path or https URL (first shard for split models)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--raw", action="store_true", help="also print every scalar metadata key")
    a = ap.parse_args()
    try:
        info = parse(a.where)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = summarise(info["meta"])
    out["header_bytes_read"] = info["header_bytes_read"]
    if a.raw:
        out["meta"] = {k: v for k, v in info["meta"].items() if not k.startswith("tokenizer.")}
    if a.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    for k, v in out.items():
        if k in ("notes", "meta"):
            continue
        print(f"{k:22} {v}")
    for n in out["notes"]:
        print(f"note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
