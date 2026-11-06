"""Shared paths, ports and preset lookup for every skill script.

One source of truth, so the launcher and all skills agree:
  repo root     MODELS_DIR env, else the folder holding .agents/
  private dir   MODELS_LOCAL_DIR env, else <root>/local
  weights dir   <root>/models
  preset ini    LLAMA_PRESET, else local/models.ini, else models.example.ini
  router port   LLAMA_PORT, else 9931 (the launcher's default)
  trial port    TRYOUT_PORT, else 9947 (tryout-model's private router)

Import from a skill script with:
  sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_shared"))
  import rigger
Standard library only.
"""
import json, os, urllib.request
from pathlib import Path

REPO = Path(os.environ.get("MODELS_DIR") or Path(__file__).resolve().parents[3])  # <root>/.agents/skills/_shared/
LOCAL = Path(os.environ.get("MODELS_LOCAL_DIR") or REPO / "local")
WEIGHTS = REPO / "models"
EXAMPLE_INI = REPO / "models.example.ini"
ROUTER_PORT = int(os.environ.get("LLAMA_PORT") or 9931)
TRYOUT_PORT = int(os.environ.get("TRYOUT_PORT") or 9947)


def preset_target():
    """The ini that edits go to: LLAMA_PRESET, else local/models.ini (may not exist).
    Never the shipped example."""
    return Path(os.environ["LLAMA_PRESET"]) if os.environ.get("LLAMA_PRESET") else LOCAL / "models.ini"


def find_preset():
    """The ini to read, as the launcher picks it: LLAMA_PRESET, else
    local/models.ini, else models.example.ini. An explicit LLAMA_PRESET is
    returned even if missing, so the caller reports it instead of silently
    falling back."""
    if os.environ.get("LLAMA_PRESET"):
        return Path(os.environ["LLAMA_PRESET"])
    for p in (LOCAL / "models.ini", EXAMPLE_INI):
        if p.exists():
            return p
    return LOCAL / "models.ini"


def base_url(port=None):
    return f"http://127.0.0.1:{port or ROUTER_PORT}"


def http_json(base, path, body=None, timeout=30):
    """GET (body None) or POST JSON to base+path; returns the decoded JSON."""
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())
