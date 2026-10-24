"""A minimal stdio MCP server, so any MCP-capable agent can verify its own work.

Tools:
  bitecheck_verify  run the probes on the working tree and return agent-facing feedback + JSON summary
  bitecheck_plan    show which changed lines would be mutated, without running anything

Protocol: newline-delimited JSON-RPC 2.0 over stdin/stdout. Nothing else is
ever written to stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import __version__

PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "bitecheck_verify",
        "description": ("Verify the current uncommitted change with execution evidence: deliberately break each "
                        "changed line and run the tests (lines no test notices are reported), run the original tests "
                        "against the new code, and flag shortcuts like skipped tests. Call this before saying a "
                        "task is done, and fix what it reports."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "repository directory (default: server cwd)"},
                "base": {"type": "string", "description": "base revision (default HEAD)"},
                "cmd": {"type": "string", "description": "test command (default: configured or auto-detected)"},
                "probes": {"type": "string", "description": "comma list: mutants,goalpost,tamper,deps"},
                "max_mutants": {"type": "integer", "minimum": 0},
            },
        },
    },
    {
        "name": "bitecheck_plan",
        "description": "List the changed files and lines bitecheck would verify, without running tests.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "base": {"type": "string"}}},
    },
]


def _respond(id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _call(name: str, args: dict) -> dict:
    from .. import check, config
    from ..cli import build_config
    from ..core import git
    from ..plan import make_plan
    from ..report import feedback, jsonout

    path = Path(args.get("path") or ".")
    repo = git.repo_root(path)
    base = args.get("base") or "HEAD"
    base_sha = git.resolve_commit(repo, base)

    class A:  # the subset of CLI args build_config reads
        cmd = args.get("cmd")
        test_pattern: list = []
        exclude: list = []

    cfg = build_config(A, repo, base_sha)
    if not cfg.mutant_cmd and cfg.test_cmd:
        cfg.mutant_cmd = config.fail_fast_variant(cfg.test_cmd)
    if isinstance(args.get("max_mutants"), int):
        cfg.max_mutants = args["max_mutants"]
    plan = make_plan(repo, base, None, cfg)
    if name == "bitecheck_plan":
        files = {p: sorted(v) for p, v in plan.code_lines.items()}
        return {"content": [{"type": "text", "text": json.dumps({"test_cmd": cfg.test_cmd, "code_lines": files,
                                                                  "tests": [c.path for c in plan.test_changes]},
                                                                 indent=2)}]}
    probes = [p for p in (args.get("probes") or "mutants,goalpost,tamper,deps").split(",") if p]
    bad = set(probes) - set(config.ALL_PROBES)
    if bad:
        raise ValueError(f"unknown probes: {', '.join(sorted(bad))}")
    verdict, _ = check.run(plan, cfg, probes=probes)
    summary = jsonout.to_dict(plan, verdict, cfg.test_cmd)
    for p in summary["probes"]:
        if "mutation" in p:
            p["mutation"]["mutants"] = [m for m in p["mutation"]["mutants"] if m["status"] == "survived"]
    text = feedback.render(plan, verdict)
    return {"content": [{"type": "text", "text": text},
                        {"type": "text", "text": json.dumps({"verdict": summary["verdict"], "score": summary["score"],
                                                             "probes": summary["probes"]}, indent=2)}],
            "isError": False}


def serve() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            _respond(None, error={"code": -32700, "message": "parse error"})
            continue
        if not isinstance(msg, dict):
            continue
        method, id_ = msg.get("method"), msg.get("id")
        if id_ is None:
            continue  # notification (e.g. notifications/initialized)
        if method == "initialize":
            _respond(id_, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                           "serverInfo": {"name": "bitecheck", "version": __version__}})
        elif method == "ping":
            _respond(id_, {})
        elif method == "tools/list":
            _respond(id_, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name not in ("bitecheck_verify", "bitecheck_plan"):
                _respond(id_, error={"code": -32602, "message": f"unknown tool: {name}"})
                continue
            try:
                _respond(id_, _call(name, params.get("arguments") or {}))
            except Exception as exc:  # report tool failures to the agent, never crash the server
                _respond(id_, {"content": [{"type": "text", "text": f"bitecheck error: {exc}"}], "isError": True})
        else:
            _respond(id_, error={"code": -32601, "message": f"method not found: {method}"})
    return 0
