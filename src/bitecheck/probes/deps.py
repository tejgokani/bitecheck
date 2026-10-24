"""The dependency probe: new dependencies an agent added, and whether they're real.

Agents hallucinate package names, and attackers register them
("slopsquatting"). Offline, bitecheck flags new dependencies whose names are
one edit away from a popular package. With --online it also asks the registry
whether the package exists and how old it is. Only PyPI, npm and crates.io
are queried, and only for names that newly appear in your manifests.
"""

from __future__ import annotations

import gzip
import json
import re
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from functools import cache
from importlib import resources

from ..core import git
from ..evidence import ERROR, INFO, WARN, Finding, ProbeResult
from ..plan import Plan

NAME = "deps"
NEW_PACKAGE_DAYS = 30


def F(code, sev, msg, items=None, hint=None) -> Finding:
    return Finding(NAME, code, sev, msg, items or [], hint=hint)


# --- manifest parsing ------------------------------------------------------------------

def _norm_py(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def deps_from(path: str, data: bytes | None) -> set[tuple[str, str]]:
    """(ecosystem, name) pairs declared in one manifest file."""
    if data is None:
        return set()
    text = data.decode("utf-8", errors="replace")
    name = path.rsplit("/", 1)[-1]
    out: set[tuple[str, str]] = set()
    try:
        if name == "package.json":
            doc = json.loads(text)
            for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
                for dep, spec in (doc.get(key) or {}).items():
                    if isinstance(spec, str) and spec.startswith(("file:", "link:", "workspace:", "git", "http")):
                        continue
                    out.add(("npm", dep))
        elif name == "pyproject.toml":
            doc = tomllib.loads(text)
            proj = doc.get("project", {})
            reqs = list(proj.get("dependencies", []))
            for group in (proj.get("optional-dependencies") or {}).values():
                reqs += list(group)
            for group in (doc.get("dependency-groups") or {}).values():
                reqs += [r for r in group if isinstance(r, str)]
            poetry = doc.get("tool", {}).get("poetry", {})
            reqs += [k for k in (poetry.get("dependencies") or {}) if k.lower() != "python"]
            for r in reqs:
                m = _REQ_NAME.match(r)
                if m:
                    out.add(("pypi", _norm_py(m.group(1))))
        elif re.match(r"requirements.*\.(txt|in)$", name):
            for line in text.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line or line.startswith(("-", "git+", "http")) or "://" in line:
                    continue
                m = _REQ_NAME.match(line)
                if m:
                    out.add(("pypi", _norm_py(m.group(1))))
        elif name == "Cargo.toml":
            doc = tomllib.loads(text)
            for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                for dep, spec in (doc.get(key) or {}).items():
                    if isinstance(spec, dict) and ("path" in spec or "git" in spec):
                        continue
                    pkg = spec.get("package", dep) if isinstance(spec, dict) else dep
                    out.add(("crates", pkg))
        elif name == "go.mod":
            for m in re.finditer(r"^\s*(?:require\s+)?([a-z0-9.-]+\.[a-z]{2,}/[^\s]+)\s+v[0-9]", text, re.M):
                out.add(("go", m.group(1)))
        elif name == "Gemfile":
            for m in re.finditer(r"^\s*gem\s+['\"]([^'\"]+)['\"]", text, re.M):
                out.add(("rubygems", m.group(1)))
    except (ValueError, tomllib.TOMLDecodeError, AttributeError, TypeError):
        return set()
    return out


MANIFEST = re.compile(r"(^|/)(package\.json|pyproject\.toml|requirements[^/]*\.(?:txt|in)|Cargo\.toml|go\.mod|Gemfile)$")


# --- popularity / typosquatting ---------------------------------------------------------

@cache
def popular(ecosystem: str) -> frozenset[str]:
    files = {"npm": "npm-top.txt.gz", "pypi": "pypi-top.txt", "crates": "crates-top.txt"}
    fname = files.get(ecosystem)
    if not fname:
        return frozenset()
    raw = resources.files("bitecheck.data").joinpath(fname).read_bytes()
    if fname.endswith(".gz"):
        raw = gzip.decompress(raw)
    names = set()
    for line in raw.decode().splitlines():
        if line.startswith("#"):
            continue
        names.update(line.split())
    if ecosystem == "pypi":
        names = {_norm_py(n) for n in names}
    return frozenset(names)


def _dl1(a: str, b: str) -> bool:
    """True if a and b are within Damerau-Levenshtein distance 1 (and differ)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    skipped = False
    while i < len(a) and j < len(b):
        if a[i] != b[j]:
            if skipped:
                return False
            skipped = True
            j += 1
            continue
        i += 1
        j += 1
    return True


def lookalike(ecosystem: str, name: str) -> str | None:
    pop = popular(ecosystem)
    if not pop or name in pop:
        return None
    key = name.lower()
    squashed = re.sub(r"[-_.]", "", key)
    for p in pop:
        if len(p) < 4:
            continue
        if _dl1(key, p) or (squashed == re.sub(r"[-_.]", "", p) and key != p):
            return p
    return None


# --- registry (opt-in network) ----------------------------------------------------------

def registry_info(ecosystem: str, name: str, timeout: float = 8.0) -> dict:
    """{'exists': bool|None, 'created': datetime|None, 'error': str|None}"""
    q = urllib.parse.quote(name, safe="@")
    url = {"npm": f"https://registry.npmjs.org/{q.replace('/', '%2F')}",
           "pypi": f"https://pypi.org/pypi/{q}/json",
           "crates": f"https://crates.io/api/v1/crates/{q}"}.get(ecosystem)
    if not url:
        return {"exists": None, "created": None, "error": "registry not supported"}
    req = urllib.request.Request(url, headers={"User-Agent": "bitecheck (https://github.com/tejgokani/bitecheck)",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read(5_000_000))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"exists": False, "created": None, "error": None}
        return {"exists": None, "created": None, "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return {"exists": None, "created": None, "error": str(exc)[:80]}
    created = None
    try:
        if ecosystem == "npm":
            created = doc.get("time", {}).get("created")
        elif ecosystem == "pypi":
            uploads = [f["upload_time_iso_8601"] for rel in doc.get("releases", {}).values() for f in rel]
            created = min(uploads) if uploads else None
        elif ecosystem == "crates":
            created = doc.get("crate", {}).get("created_at")
        if created:
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        created = None
    return {"exists": True, "created": created, "error": None}


# --- probe ------------------------------------------------------------------------------

def run(plan: Plan, online: bool = False) -> ProbeResult:
    start = time.monotonic()
    added: dict[tuple[str, str], str] = {}
    for ch in plan.changes:
        if not MANIFEST.search(ch.path) or ch.status == "D":
            continue
        before = deps_from(ch.path, git.show_file(plan.repo, plan.base, ch.path))
        after = deps_from(ch.path, git.read_head_file(plan.repo, plan.head, ch.path))
        for dep in sorted(after - before):
            added[dep] = ch.path
    findings: list[Finding] = []
    if not added:
        return ProbeResult(NAME, "ran", "no new dependencies", [], elapsed=time.monotonic() - start)
    squats, missing, young, unknown, new = [], [], [], [], []
    for (eco, name), path in sorted(added.items()):
        label = f"{name} ({eco}, {path})"
        new.append(label)
        near = lookalike(eco, name)
        if near:
            squats.append(f"{label}: one edit away from popular package '{near}'")
        if online and eco in ("npm", "pypi", "crates"):
            info = registry_info(eco, name)
            if info["exists"] is False:
                missing.append(label)
            elif info["exists"] and info["created"]:
                age = (datetime.now(UTC) - info["created"]).days
                if age < NEW_PACKAGE_DAYS:
                    young.append(f"{label}: first published {age} day(s) ago")
            elif info["error"]:
                unknown.append(f"{label}: {info['error']}")
    findings.append(F("NEW_DEPENDENCIES", INFO, f"{len(new)} new dependenc{'y' if len(new) == 1 else 'ies'} added", new))
    if missing:
        findings.append(F("DEPENDENCY_NOT_FOUND", ERROR, "dependencies that do not exist on their registry "
                          "(hallucinated package names; an attacker can register them)", missing,
                          hint="replace with the real package name"))
    if squats:
        findings.append(F("TYPOSQUAT_SUSPECT", WARN, "new dependencies whose names are one edit away from a popular "
                          "package", squats, hint="check the spelling of the package name"))
    if young:
        findings.append(F("DEPENDENCY_VERY_NEW", WARN, f"dependencies first published less than {NEW_PACKAGE_DAYS} "
                          "days ago", young, hint="confirm this is the intended, trustworthy package"))
    if unknown:
        findings.append(F("REGISTRY_UNREACHABLE", INFO, "could not check some packages", unknown))
    if not online:
        findings.append(F("DEPS_OFFLINE", INFO, "registry existence was not checked (run with --online)"))
    return ProbeResult(NAME, "ran", f"{len(new)} new", findings, elapsed=time.monotonic() - start)
