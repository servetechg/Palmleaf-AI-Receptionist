"""Structural lint for committed workflow JSON (doc 09 §8).

Runs on every PR. Catches the failure modes that are otherwise only discovered by a caller
hearing silence, or by a workflow that deploys green and throws on its first execution.

    python -m grace_platform.n8n.lint
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

DIR = Path(__file__).resolve().parents[3] / "platform" / "n8n" / "workflows"

ERROR_HANDLER = "WF-00"
"""WF-00 is the global error handler; it cannot point its errorWorkflow at itself."""

SECRET_PATTERNS = (
    re.compile(r"\bsk_[A-Za-z0-9]{10,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{10,}"),
    re.compile(r"\bxoxb-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAC[0-9a-f]{32}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
)

WEBHOOK_TYPES = {"n8n-nodes-base.webhook", "n8n-nodes-base.slackTrigger"}
CRED_PLACEHOLDER = re.compile(r"^__CRED__:[a-z0-9-]+$")

problems: list[str] = []


def bad(file: str, rule: int, msg: str) -> None:
    problems.append(f"{file}  [rule {rule}]  {msg}")


def _str(v: Any, fallback: str = "") -> str:
    """Node parameters are untyped; coerce only real primitives."""
    return str(v) if isinstance(v, str | int | float | bool) else fallback


def _every_path_responds(wf: dict[str, Any], start: str) -> bool:
    """Every path out of a webhook trigger must terminate in a Respond-to-Webhook node."""
    by_name = {n["name"]: n for n in wf["nodes"]}
    seen: set[str] = set()

    def walk(name: str) -> bool:
        if name in seen:  # a cycle cannot introduce a dead end
            return True
        seen.add(name)
        node = by_name.get(name)
        if node is None:
            return False
        if node["type"] == "n8n-nodes-base.respondToWebhook":
            return True
        branches = wf.get("connections", {}).get(name, {}).get("main", [])
        nxt = [c["node"] for branch in branches for c in branch]
        if not nxt:
            return False  # terminal, and not a respond node
        return all(walk(n) for n in nxt)

    return walk(start)


def lint_file(path: Path) -> None:
    file = path.name
    raw = path.read_text(encoding="utf-8")
    wf: dict[str, Any] = json.loads(raw)
    is_error_handler = file.startswith(ERROR_HANDLER)

    for pattern in SECRET_PATTERNS:
        if pattern.search(raw):
            bad(file, 3, f"contains something matching {pattern.pattern}")
    if re.search(r"localhost|127\.0\.0\.1|ngrok|trycloudflare", raw):
        bad(file, 4, "references localhost or a dev tunnel URL")

    name = str(wf.get("name", ""))
    if not file.removesuffix(".json").startswith(name.split(" ")[0]):
        bad(file, 7, f'workflow name "{name}" does not match filename')
    if re.match(r"^\[(dev|prod)\]", name):
        bad(file, 7, "committed name carries an env prefix; it is applied at deploy time")
    if "pinData" in wf:
        bad(file, 8, "contains pinData")

    settings: dict[str, Any] = wf.get("settings", {})
    if not is_error_handler and not isinstance(settings.get("errorWorkflow"), str):
        bad(file, 6, "settings.errorWorkflow is not set")
    ew = settings.get("errorWorkflow")
    if isinstance(ew, str) and not ew.startswith("__WF__:"):
        bad(file, 11, f'settings.errorWorkflow "{ew}" must be a __WF__:<alias> placeholder')

    nodes: list[dict[str, Any]] = wf.get("nodes", [])
    has_wait = any(n["type"] == "n8n-nodes-base.wait" for n in nodes)
    if has_wait and "executionTimeout" in settings:
        bad(file, 12, "has a Wait node and settings.executionTimeout, which would kill it mid-wait")

    for node in nodes:
        params: dict[str, Any] = node.get("parameters", {})
        ntype = node["type"]

        for cred_type, cred in (node.get("credentials") or {}).items():
            cred_id = cred.get("id", "")
            if not CRED_PLACEHOLDER.match(str(cred_id)):
                bad(
                    file,
                    10,
                    f'node "{node["name"]}" credential {cred_type}.id must be __CRED__:<alias>, '
                    f"got {cred_id} (n8n resolves credentials strictly by id — a name here "
                    f"deploys green and throws at runtime)",
                )

        if ntype == "n8n-nodes-base.httpRequest" and not isinstance(
            params.get("options", {}).get("timeout"), int
        ):
            bad(file, 5, f'HTTP node "{node["name"]}" has no timeout')

        if ntype == "n8n-nodes-base.wait":
            unit = _str(params.get("unit"), "seconds")
            amount = float(params.get("amount", 0) or 0)
            seconds = (
                amount * 60 if unit == "minutes" else amount * 3600 if unit == "hours" else amount
            )
            if 0 < seconds < 65:
                bad(
                    file,
                    13,
                    f'Wait node "{node["name"]}" is {seconds:g}s; under 65s it is lost on restart',
                )

        if ntype == "n8n-nodes-base.scheduleTrigger":
            tz = _str(params.get("timezone"))
            if tz != "America/Chicago":
                bad(
                    file,
                    15,
                    f'schedule node "{node["name"]}" must set timezone America/Chicago, got "{tz}"',
                )

        if ntype in WEBHOOK_TYPES and ntype == "n8n-nodes-base.webhook":
            if _str(params.get("httpMethod")) != "POST":
                bad(file, 1, f'webhook "{node["name"]}" must be POST')
            if _str(params.get("responseMode")) != "responseNode":
                bad(file, 1, f'webhook "{node["name"]}" must use responseMode "responseNode"')
            path_param = _str(params.get("path"))
            if not path_param.startswith("{{ENV}}/"):
                bad(
                    file,
                    9,
                    f'webhook "{node["name"]}" path must start with {{{{ENV}}}}/, got "{path_param}"',
                )
            if params.get("options", {}).get("rawBody") is not True:
                bad(
                    file,
                    14,
                    f'webhook "{node["name"]}" must enable Raw Body (signatures cover exact bytes)',
                )
            if not _every_path_responds(wf, node["name"]):
                bad(
                    file,
                    2,
                    f'not every path from "{node["name"]}" reaches a Respond to Webhook node',
                )


def main() -> int:
    files = sorted(DIR.glob("*.json"))
    if not files:
        print("  (no workflows yet)")
        return 0
    for path in files:
        lint_file(path)

    if problems:
        print(f"\n✗ {len(problems)} lint problem(s):\n", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        print(file=sys.stderr)
        return 1
    print(f"✓ {len(files)} workflow(s) pass all 15 lint rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
