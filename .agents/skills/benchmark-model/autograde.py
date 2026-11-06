#!/usr/bin/env python3
"""Automated grading of benchmark-model code answers.

Scores the parts a machine can judge deterministically:
  coding tasks  -> compile the model's function with the hidden test driver,
                   run it; PASS if it builds and all asserts pass.
  vuln tasks    -> compile the model's corrected function with the task's
                   exploit driver under AddressSanitizer; PASS if the benign
                   case is correct AND the malicious case runs clean (no ASan
                   report, no crash). Tasks flagged "judge_only" are compiled
                   for a build check only.

Writes results/<run>/auto_scores.json. The vuln *reasoning* grade (did the
model find the bug, explain root cause/impact, and — for traps — correctly say
it is safe) is added by the Claude session; see SKILL.md.

Usage: python autograde.py --run <run_id> [--tasks v01 c03]
"""
import argparse, json, os, platform, shutil, subprocess, sys, tempfile
from pathlib import Path

from _vcenv import vc_env, tool_path

IS_WIN = os.name == "nt"

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
RESULTS_DIR = ROOT / "results"
BUILD_TIMEOUT = 120
RUN_TIMEOUT = 30


def load_task(tid):
    tj = next(TASKS_DIR.glob(f"{tid}*/task.json"), None) or \
        next((p for p in TASKS_DIR.glob("*/task.json")
              if json.loads(p.read_text())["id"] == tid), None)
    if not tj:
        return None
    t = json.loads(tj.read_text(encoding="utf-8"))
    t["_dir"] = tj.parent
    return t


def run(cmd, cwd, env=None, timeout=RUN_TIMEOUT):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except Exception as e:
        return 1, f"spawn error: {e}"


def toolchain():
    """The C/C++ compiler to grade with: MSVC on Windows, clang/gcc elsewhere.

    Returns {"kind": "msvc"|"gnu", "cc", "cxx", "env"} or None. On Linux/macOS
    $CC / $CXX win, then clang, then gcc. AddressSanitizer must be available
    (selftest_setup.py + autograde.py --run _selftest confirms it links).
    """
    if IS_WIN:
        env = vc_env()
        return {"kind": "msvc", "cc": tool_path("cl.exe") or "cl", "cxx": tool_path("cl.exe") or "cl",
                "env": env} if env else None
    cc = os.environ.get("CC") or shutil.which("clang") or shutil.which("gcc") or shutil.which("cc")
    cxx = os.environ.get("CXX") or shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
    if not (cc and cxx):
        return None
    env = dict(os.environ)
    # MSVC's ASan has no leak checker; match it so leaks alone don't fail an answer
    # (LeakSanitizer also breaks under ptrace/some containers).
    env["ASAN_OPTIONS"] = "detect_leaks=0:" + env.get("ASAN_OPTIONS", "")
    # Older ASan runtimes (e.g. clang 14) crash at random under recent kernels' high
    # mmap randomisation; running with ASLR off is the standard workaround (Linux).
    setarch = shutil.which("setarch") if sys.platform.startswith("linux") else None
    wrap = [setarch, platform.machine(), "-R"] if setarch else []
    return {"kind": "gnu", "cc": cc, "cxx": cxx, "env": env, "wrap": wrap}


def compile_c(tc, work, srcs, out, asan=False, cpp=False):
    if tc["kind"] == "msvc":
        flags = ["/nologo", "/EHsc" if cpp else "/TC", "/Zi", "/Od", "/MT"]
        if cpp:
            flags = ["/nologo", "/EHsc", "/std:c++17", "/Zi", "/Od", "/MT"]
        if asan:
            flags.append("/fsanitize=address")
        cmd = [tc["cc"]] + flags + [str(s) for s in srcs] + [f"/Fe:{out}"]
    else:
        flags = ["-g", "-O0", "-std=c++17" if cpp else "-std=c11", "-D_GNU_SOURCE"]
        if asan:
            flags += ["-fsanitize=address", "-fno-omit-frame-pointer"]
        cmd = [tc["cxx"] if cpp else tc["cc"]] + flags + [str(s) for s in srcs] + ["-o", str(out)]
    return run(cmd, work, env=tc["env"], timeout=BUILD_TIMEOUT)


def grade_c_cpp(task, code_path, tc):
    env = tc["env"]
    d = task["_dir"]
    cpp = task["lang"] == "cpp"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ans = tmp / ("answer.cpp" if cpp else "answer.c")
        ans.write_text(code_path.read_text(encoding="utf-8"), encoding="utf-8")
        driver = d / task["grading"]["driver"]
        drv = tmp / driver.name
        drv.write_text(driver.read_text(encoding="utf-8"), encoding="utf-8")
        asan = task["kind"] == "vuln" and not task["grading"].get("judge_only")
        exe = tmp / ("t.exe" if IS_WIN else "t")
        rc, log = compile_c(tc, tmp, [ans, drv], exe, asan=asan, cpp=cpp)
        if rc != 0:
            return {"auto": "BUILD_FAIL", "detail": log[-1500:]}
        if task["kind"] == "vuln" and task["grading"].get("judge_only"):
            return {"auto": "BUILD_OK", "detail": "compile-only (judge grades fix)"}
        # run benign then malicious; driver takes a mode arg
        results = {}
        for mode in task["grading"].get("run_modes", ["benign", "malicious"]):
            rc, log = run(tc.get("wrap", []) + [str(exe), mode], tmp, env=env)
            clean = rc == 0 and "AddressSanitizer" not in log and "ERROR" not in log
            results[mode] = {"rc": rc, "clean": clean, "log": log[-600:]}
        if task["kind"] == "vuln":
            ok = results.get("benign", {}).get("clean") and \
                results.get("malicious", {}).get("clean")
            return {"auto": "PASS" if ok else "FAIL", "runs": results}
        ok = all(r["clean"] for r in results.values())
        return {"auto": "PASS" if ok else "FAIL", "runs": results}


def grade_csharp(task, code_path):
    d = task["_dir"]
    tmpl = d / task["grading"]["driver"]  # a full Program.cs with Main + asserts
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "model.cs").write_text(code_path.read_text(encoding="utf-8"),
                                      encoding="utf-8")
        (tmp / "Program.cs").write_text(tmpl.read_text(encoding="utf-8"),
                                        encoding="utf-8")
        (tmp / "app.csproj").write_text(
            "<Project Sdk=\"Microsoft.NET.Sdk\"><PropertyGroup>"
            "<OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework>"
            "<Nullable>disable</Nullable><ImplicitUsings>enable</ImplicitUsings>"
            "<AssemblyName>app</AssemblyName></PropertyGroup></Project>",
            encoding="utf-8")
        rc, log = run(["dotnet", "build", "-c", "Release", "-o", "bin"], tmp,
                      timeout=BUILD_TIMEOUT)
        if rc != 0:
            return {"auto": "BUILD_FAIL", "detail": log[-1500:]}
        rc, log = run(["dotnet", str(tmp / "bin" / "app.dll")], tmp)
        ok = rc == 0 and "FAIL" not in log
        return {"auto": "PASS" if ok else "FAIL", "detail": log[-800:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--tasks", nargs="*")
    args = ap.parse_args()

    run_dir = RESULTS_DIR / args.run
    code_dir = run_dir / "code"
    if not code_dir.exists():
        print(f"no code dir in {run_dir}", file=sys.stderr)
        return 1

    tc = toolchain()
    if not tc:
        print("! no C/C++ compiler found (MSVC on Windows; clang or gcc elsewhere); "
              "C/C++ tasks will be skipped", file=sys.stderr)
    else:
        print(f"C/C++ toolchain: {tc['kind']} ({tc['cc']})", file=sys.stderr)

    scores = {}
    for cf in sorted(code_dir.glob("*.*")):
        stem = cf.stem  # model__taskid
        if "__" not in stem:
            continue
        model, tid = stem.rsplit("__", 1)
        if args.tasks and tid not in args.tasks:
            continue
        task = load_task(tid)
        if not task:
            continue
        try:
            if task["lang"] in ("c", "cpp"):
                res = grade_c_cpp(task, cf, tc) if tc else {"auto": "SKIP_NO_COMPILER"}
            elif task["lang"] == "csharp":
                res = grade_csharp(task, cf)
            else:
                res = {"auto": "SKIP"}
        except Exception as e:
            res = {"auto": "ERROR", "detail": str(e)}
        res["trap"] = task.get("trap", False)
        res["kind"] = task["kind"]
        scores.setdefault(model, {})[tid] = res
        print(f"{model:40} {tid:5} {res['auto']}")

    (run_dir / "auto_scores.json").write_text(json.dumps(scores, indent=2),
                                              encoding="utf-8")
    print(f"\nwrote {run_dir / 'auto_scores.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
