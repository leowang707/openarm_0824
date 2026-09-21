"""Offline checks. Default mode REQUIRES real dependencies; --mock-only is limited."""
from __future__ import annotations
import argparse
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
SKIP={".git",".venv","venv","__pycache__","node_modules"}

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mock-only",action="store_true",help="Only syntax and isolated contract tests; not release approval")
    args=p.parse_args()
    count=0
    for f in ROOT.rglob("*.py"):
        if any(part in SKIP for part in f.relative_to(ROOT).parts): continue
        ast.parse(f.read_text(encoding="utf-8"),filename=str(f))
        count+=1
    print(f"Syntax PASS: {count} Python files; interpreter={sys.executable}",flush=True)
    subprocess.run([sys.executable,str(ROOT/"tests/refactor_contract_checks.py")],cwd=ROOT,check=True)
    if args.mock_only:
        print("MOCK-ONLY PASS. Real dependency integration and hardware remain unverified.")
        return 0
    missing=[name for name in ("can","serial","damiao_motor","flask") if importlib.util.find_spec(name) is None]
    if missing:
        print("MISSING DEPENDENCIES: "+", ".join(missing),file=sys.stderr)
        print("Install the project's requirements using this interpreter, then rerun.",file=sys.stderr)
        return 2
    subprocess.run([sys.executable,str(ROOT/"tests/refactor_dependency_checks.py")],cwd=ROOT,check=True)
    subprocess.run(["git","--no-pager","diff","--check"],cwd=ROOT,check=True)
    print("OFFLINE CHECKS PASS. No physical USB/CAN/motor operation has been validated here.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
