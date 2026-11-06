#!/usr/bin/env python3
"""List the GGUF variants in a Hugging Face repo, from any link form.

Accepts:
  https://huggingface.co/<org>/<repo>[/tree/<rev>[/<dir>]]
  https://huggingface.co/<org>/<repo>/blob|resolve/<rev>/<file>.gguf
  hf.co/<org>/<repo>[:<quant>]        <org>/<repo>[:<quant>]
Groups shards (-00001-of-0000N) into one variant, lists mmproj (vision
projector) files separately, and for each variant gives its size, the download
command and the URL of its first file (for gguf_info.py). Also reports what is
already on disk under the models folder and the free disk space there.

Standard library only; uses HF_TOKEN for gated/private repos if set. Usage:
  python hf_gguf.py <link> [--models-dir DIR] [--json]
"""
import argparse, json, os, re, shutil, sys, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
import rigger

API = "https://huggingface.co/api/models/"
UA = {"User-Agent": "tryout-model-hf-gguf/1.0"}
SHARD = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)
QUANT = re.compile(r"(UD-)?(IQ\d_[A-Z]+(?:_[A-Z]+)?|Q\d_K(?:_[A-Z]+)?(?:_XL)?|Q\d_\d|Q\d_K|"
                   r"TQ\d_\d|MXFP4(?:_MOE)?|BF16|F16|F32)", re.I)
# a revision is a branch/tag/sha, or a ref with slashes such as refs/pr/12 (URL-encoded or not)
REV = r"refs(?:/|%2F)[^/%]+(?:/|%2F)[^/%]+|[^/]+"


def parse_link(link):
    """-> (repo, revision, file_or_dir_hint, quant_hint)"""
    s = link.strip()
    s = re.sub(r"^(https?://)?(www\.)?(huggingface\.co|hf\.co)/", "", s)
    s = s.split("?")[0].split("#")[0].strip("/")
    m = re.match(rf"^([^/\s]+)/([^/:\s]+)(?::([^/\s]+))?(?:/(tree|blob|resolve)/({REV})(?:/(.*))?)?$", s)
    if not m:
        raise ValueError(f"not a Hugging Face repo link: {link}")
    org, name, quant, kind, rev, path = m.groups()
    rev = urllib.parse.unquote(rev) if rev else "main"
    return f"{org}/{name}", rev, urllib.parse.unquote(path) if path else None, quant


def _get(url):
    token = os.environ.get("HF_TOKEN")
    headers = dict(UA, **({"Authorization": f"Bearer {token}"} if token else {}))
    r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
    with r:
        return json.loads(r.read().decode()), r.headers.get("Link", "")


def get_json(url):
    return _get(url)[0]


def get_all(url):
    """A paginated list endpoint (the tree API pages big repos), following the
    Link: <...>; rel="next" headers until the last page."""
    out = []
    while url:
        page, link = _get(url)
        out += page
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out


def quant_of(fname):
    hits = QUANT.findall(Path(fname).stem)
    return ("".join(hits[-1]).upper()) if hits else Path(fname).stem


def variants(files):
    groups, mmproj = {}, []
    for f in files:
        p, size = f["path"], f.get("lfs", {}).get("size") or f.get("size") or 0
        if not p.lower().endswith(".gguf"):
            continue
        if "mmproj" in Path(p).name.lower():
            mmproj.append({"file": p, "gib": round(size / 2**30, 2)})
            continue
        key = SHARD.sub(".gguf", p)
        g = groups.setdefault(key, {"quant": quant_of(key), "files": [], "bytes": 0})
        g["files"].append(p)
        g["bytes"] += size
    out = []
    for key, g in sorted(groups.items(), key=lambda kv: kv[1]["bytes"]):
        g["files"].sort()
        g["gib"] = round(g.pop("bytes") / 2**30, 2)
        g["shards"] = len(g["files"])
        out.append(g)
    return out, mmproj


def local_dir_for(repo, variant, with_mmproj):
    """Repo convention: a single file goes in models/, anything else in a subfolder."""
    if variant["shards"] == 1 and not with_mmproj:
        return ""
    return re.sub(r"-GGUF$", "", repo.split("/")[1], flags=re.I)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("link")
    ap.add_argument("--models-dir", default=os.environ.get("TRYOUT_MODELS_DIR", str(rigger.WEIGHTS)))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    try:
        repo, rev, hint, quant_hint = parse_link(a.link)
        info = get_json(f"{API}{repo}?expand[]=gguf&expand[]=cardData&expand[]=gated&expand[]=downloads&expand[]=lastModified")
        tree = get_all(f"{API}{repo}/tree/{urllib.parse.quote(rev, safe='')}?recursive=true")
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    vs, mmproj = variants(tree)
    if hint and hint.lower().endswith(".gguf"):
        key = SHARD.sub(".gguf", hint)
        vs = [v for v in vs if SHARD.sub(".gguf", v["files"][0]) == key] or vs
    elif hint:
        vs = [v for v in vs if v["files"][0].startswith(hint.rstrip("/") + "/")] or vs
    if quant_hint:
        vs = [v for v in vs if v["quant"].lower() == quant_hint.lower()
              or quant_hint.lower() in v["files"][0].lower()] or vs

    models_dir = Path(a.models_dir)
    have = {}
    if models_dir.exists():
        for p in models_dir.rglob("*.gguf"):
            have.setdefault(p.name.lower(), str(p).replace("\\", "/"))

    def pick_mmproj(v):
        """The projector to pair with a variant: same quant if there is one, else F16, else smallest."""
        if not mmproj:
            return None
        same = [m for m in mmproj if quant_of(m["file"]) == v["quant"].replace("UD-", "")]
        f16 = [m for m in mmproj if "f16" in m["file"].lower()]
        return (same or f16 or sorted(mmproj, key=lambda m: m["gib"]))[0]

    for v in vs:
        v["on_disk"] = all(Path(f).name.lower() in have for f in v["files"])
        v["first_file_url"] = f"https://huggingface.co/{repo}/resolve/{rev}/{urllib.parse.quote(v['files'][0])}"
        sub = local_dir_for(repo, v, bool(mmproj))
        target = models_dir / sub if sub else models_dir
        pats = ([str(Path(v["files"][0]).parent).replace("\\", "/") + "/*"]
                if v["shards"] > 1 and "/" in v["files"][0] else list(v["files"]))
        mp = pick_mmproj(v)
        if mp:
            pats.append(mp["file"])
            v["mmproj"] = mp["file"]
            v["mmproj_path"] = have.get(Path(mp["file"]).name.lower(),
                                        str(target / mp["file"]).replace("\\", "/"))
        include = " ".join(f'--include "{p}"' for p in pats)
        v["download"] = f'hf download {repo} {include} --revision {rev} --local-dir "{target}"'
        # where it is now if already downloaded, else where the download puts it
        v["model_path"] = have.get(Path(v["files"][0]).name.lower(),
                                   str(target / v["files"][0]).replace("\\", "/"))
        v["download_gib"] = round(v["gib"] + (mp["gib"] if mp and not
                                  Path(mp["file"]).name.lower() in have else 0), 2) if not v["on_disk"] else 0
    for m in mmproj:
        m["on_disk"] = Path(m["file"]).name.lower() in have

    g = info.get("gguf") or {}
    free = shutil.disk_usage(models_dir if models_dir.exists() else models_dir.anchor or ".").free
    out = {
        "repo": repo, "revision": rev, "gated": info.get("gated"),
        "downloads": info.get("downloads"), "last_modified": info.get("lastModified"),
        "license": (info.get("cardData") or {}).get("license"),
        "architecture": g.get("architecture"), "context_length": g.get("context_length"),
        "total_params_b": round(g["total"] / 1e9, 2) if g.get("total") else None,
        "mtp_in_name": "mtp" in repo.lower(),
        "variants": vs, "mmproj": mmproj,
        "models_dir": str(models_dir), "free_disk_gib": round(free / 2**30, 1),
    }
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"{repo}@{rev}  arch={out['architecture']}  ctx={out['context_length']}  "
          f"params={out['total_params_b']}B  license={out['license']}  gated={out['gated']}")
    print(f"free disk in {models_dir}: {out['free_disk_gib']} GiB")
    print(f"{'quant':16} {'GiB':>7} {'shards':>6}  on disk  file")
    for v in vs:
        print(f"{v['quant']:16} {v['gib']:7.2f} {v['shards']:6}  {'yes' if v['on_disk'] else '-':7}  {v['files'][0]}")
    for m in mmproj:
        print(f"{'mmproj':16} {m['gib']:7.2f} {'':6}  {'yes' if m['on_disk'] else '-':7}  {m['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
