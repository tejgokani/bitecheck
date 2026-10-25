import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PY = sys.executable
PYTEST = f"{PY} -m pytest -q -p no:cacheprovider"

GIT_ENV = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")

CART_V1 = "def subtotal(items):\n    return sum(p * q for p, q in items)\n"
CART_TEST_V1 = "from cart import subtotal\n\n\ndef test_subtotal():\n    assert subtotal([(2, 3), (5, 1)]) == 11\n"
CART_FEATURE = (
    CART_V1 + "\n\ndef total(items, coupon=None):\n"
    "    amount = subtotal(items)\n"
    "    if coupon == \"HALF\":\n"
    "        amount = amount / 2\n"
    "    if amount < 0:\n"
    "        amount = 0\n"
    "    return round(amount, 2)\n"
)
WEAK_TEST = "\n\ndef test_total():\n    from cart import total\n    assert total([(2, 3)]) is not None\n"
STRONG_TEST = (
    "\n\ndef test_total():\n    from cart import total\n"
    "    assert total([(2, 3)]) == 6\n"
    "    assert total([(2, 3)], 'HALF') == 3\n"
    "    assert total([(-5, 1)]) == 0\n"
    "    assert total([(-5, 1)], 'HALF') == 0\n"
    "    assert total([(1, 1)], 'HALF') == 0.5\n"
    "    assert total([(0.333, 1)]) == 0.33\n"
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout


def make_repo(root: Path, files: dict[str, str], name: str = "proj") -> Path:
    r = root / name
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, {".gitignore": "__pycache__/\nreport.xml\nnode_modules/\n", **files})
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    return r


def write(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


@pytest.fixture
def cart(tmp_path):
    return make_repo(tmp_path, {"cart.py": CART_V1, "test_cart.py": CART_TEST_V1})


def run_bc(repo: Path, *args: str, stdin: str | None = None, env: dict | None = None,
           timeout: float = 300) -> subprocess.CompletedProcess:
    e = {**os.environ, "PYTHONPATH": str(SRC), "NO_COLOR": "1", "BITECHECK_HOME": str(repo.parent / "home")}
    if env:
        e.update(env)
    return subprocess.run([PY, "-m", "bitecheck", *args, "-C", str(repo)] if args and args[0] in (
        "check", "plan", "hook") else [PY, "-m", "bitecheck", "-C", str(repo), *args],
        capture_output=True, text=True, env=e, input=stdin, timeout=timeout)


def check_json(repo: Path, *args: str, cmd: str = PYTEST, **kw):
    proc = run_bc(repo, "--cmd", cmd, "--json", "--no-transcript", "--jobs", "2", *args, **kw)
    assert proc.stdout.strip(), proc.stderr
    return proc, json.loads(proc.stdout)


def probe(doc, name):
    return next(p for p in doc["probes"] if p["name"] == name)


def codes(doc) -> set[str]:
    return {f["code"] for p in doc["probes"] for f in p["findings"]}


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
needs_go = pytest.mark.skipif(shutil.which("go") is None, reason="go not installed")
