"""Vapi config-as-code deploy (doc 08 §8).

    python -m grace_platform.vapi.deploy --env dev --diff     show drift, change nothing
    python -m grace_platform.vapi.deploy --env dev --apply    upsert tools, outputs, assistant

Order matters: tools and structured outputs must exist before the assistant can reference
their ids.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grace_contracts import HAND_AUTHORED_TOOLS, TOOL_REGISTRY

from .lib.client import VapiClient, tool_identity
from .lib.drift import compute_drift

HERE = Path(__file__).resolve().parents[3] / "platform" / "vapi"
LOCK_PATH = HERE / ".lock.json"

_ENV_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


def substitute(text: str, required: list[str]) -> str:
    """Replaces ``${VAR}`` placeholders. Missing required vars fail loudly."""
    missing: list[str] = []

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        val = os.environ.get(name, "")
        if not val and name in required:
            missing.append(name)
        return val

    out = _ENV_VAR.sub(repl, text)
    if missing:
        sys.exit(f"✗ missing required environment variable(s): {', '.join(sorted(set(missing)))}")
    return out


def prune_empty(value: Any) -> Any:
    """Drops keys whose value became empty after substitution (e.g. an unset credentialId)."""
    if isinstance(value, list):
        return [prune_empty(v) for v in value]
    if isinstance(value, dict):
        return {k: prune_empty(v) for k, v in value.items() if v not in ("", None)}
    return value


def load_json(path: Path, required: list[str] | None = None) -> Any:
    return prune_empty(json.loads(substitute(path.read_text(encoding="utf-8"), required or [])))


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def assert_guard_rails(env: str, apply: bool) -> None:
    if not apply:
        return
    if env == "prod" and _git("status", "--porcelain"):
        sys.exit("✗ refusing to --apply to prod with a dirty git tree (AC-08.8)")

    assistant_raw = (HERE / "assistants" / "grace.json").read_text(encoding="utf-8")
    if "injected from prompts/first-message.txt" not in assistant_raw:
        sys.exit("✗ I7: grace.json must inject firstMessage, never inline it")

    greeting = (HERE / "prompts" / "first-message.txt").read_text(encoding="utf-8")
    if not re.search(r"may be recorded", greeting, re.I) or not re.search(
        r"virtual assistant|AI assistant", greeting, re.I
    ):
        sys.exit("✗ I7: first-message.txt is missing the recording or AI disclosure")


def build_assistant_body(env: str, tool_ids: list[str], so_ids: list[str]) -> dict[str, Any]:
    assistant = load_json(HERE / "assistants" / "grace.json", ["GRACE_EVENTS_URL"])
    assistant["firstMessage"] = (HERE / "prompts" / "first-message.txt").read_text("utf-8").strip()
    assistant["model"]["messages"] = [
        {"role": "system", "content": (HERE / "prompts" / "system.md").read_text("utf-8").strip()}
    ]
    assistant["model"]["toolIds"] = sorted(tool_ids)
    assistant["artifactPlan"]["structuredOutputIds"] = sorted(so_ids)
    if env == "dev":
        assistant["name"] = "Grace — PalmLeaf [dev]"
    return dict(assistant)


def local_tools() -> dict[str, Any]:
    wanted = {f"{t.name}.json" for t in TOOL_REGISTRY} | {f"{n}.json" for n in HAND_AUTHORED_TOOLS}
    hand = {f"{n}.json" for n in HAND_AUTHORED_TOOLS}
    out: dict[str, Any] = {}
    for path in sorted((HERE / "tools").iterdir()):
        if path.name not in wanted:
            continue
        tool = load_json(path, [] if path.name in hand else ["GRACE_TOOLS_URL"])
        out[tool_identity(tool)] = tool
    return out


def local_structured_outputs() -> dict[str, Any]:
    directory = HERE / "structured-outputs"
    if not directory.exists():
        return {}
    out: dict[str, Any] = {}
    for path in sorted(directory.glob("*.json")):
        so = load_json(path)
        name = so.get("name")
        out[name if isinstance(name, str) else path.stem] = so
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="vapi-deploy")
    parser.add_argument("--env", choices=("dev", "prod"), default="dev")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--diff", action="store_true")
    args = parser.parse_args()
    env, apply = args.env, args.apply

    assert_guard_rails(env, apply)
    print(f"\nVapi deploy — env={env} mode={'APPLY' if apply else 'DIFF'}\n")

    changes = 0
    forbidden = 0
    tool_ids: dict[str, str] = {}
    so_ids: dict[str, str] = {}

    with VapiClient(os.environ.get("VAPI_API_KEY", "")) as client:
        # 1. tools ────────────────────────────────────────────────────────────
        remote_by_name = {tool_identity(t): t for t in client.list_tools()}
        for name, local in local_tools().items():
            remote = remote_by_name.get(name)
            if remote is None:
                if apply:
                    created = client.create_tool(local)
                    tool_ids[name] = str(created["id"])
                    print(f"  + tool {name} → {created['id']}")
                else:
                    print(f"  + tool {name} (would create)")
                changes += 1
                continue

            tool_ids[name] = str(remote["id"])
            drift = compute_drift(remote, local)
            if not drift:
                print(f"  = tool {name}")
                continue
            changes += 1
            print(f"  ~ tool {name}")
            for d in drift:
                print(f"      {'⛔' if d.forbidden else '·'} {d.path}")
            if apply:
                client.update_tool(remote["id"], local)

        # 2. structured outputs ───────────────────────────────────────────────
        so_by_name = {str(s.get("name")): s for s in client.list_structured_outputs()}
        for name, local in local_structured_outputs().items():
            remote = so_by_name.get(name)
            if remote is None:
                if apply:
                    created = client.create_structured_output(local)
                    so_ids[name] = str(created["id"])
                    print(f"  + structured-output {name} → {created['id']}")
                else:
                    print(f"  + structured-output {name} (would create)")
                changes += 1
                continue
            so_ids[name] = str(remote["id"])
            if compute_drift(remote, local):
                changes += 1
                print(f"  ~ structured-output {name}")
                if apply:
                    client.update_structured_output(remote["id"], local)
            else:
                print(f"  = structured-output {name}")

        # 3. assistant ────────────────────────────────────────────────────────
        desired = build_assistant_body(env, list(tool_ids.values()), list(so_ids.values()))
        wanted_name = str(desired["name"])
        remote_assistant = next(
            (a for a in client.list_assistants() if a.get("name") == wanted_name), None
        )
        assistant_id = str(remote_assistant["id"]) if remote_assistant else ""

        if remote_assistant is None:
            if apply:
                created = client.create_assistant(desired)
                assistant_id = str(created["id"])
                print(f'  + assistant "{wanted_name}" → {assistant_id}')
            else:
                print(f'  + assistant "{wanted_name}" (would create)')
            changes += 1
        else:
            full = client.get_assistant(assistant_id)
            drift = compute_drift(full, desired)
            if not drift:
                print(f'  = assistant "{wanted_name}"')
            else:
                changes += 1
                print(f'  ~ assistant "{wanted_name}"')
                for d in drift:
                    forbidden += int(d.forbidden)
                    mark = "⛔" if d.forbidden else "·"
                    print(f"      {mark} {d.path}")
                    print(f"          remote:  {json.dumps(d.remote)[:70]}")
                    print(f"          desired: {json.dumps(d.desired)[:70]}")
                if apply:
                    client.update_assistant(assistant_id, desired)

    # 4. lock file ────────────────────────────────────────────────────────────
    if apply and assistant_id:
        LOCK_PATH.write_text(
            json.dumps(
                {
                    "env": env,
                    "assistantId": assistant_id,
                    "toolIds": dict(sorted(tool_ids.items())),
                    "structuredOutputIds": dict(sorted(so_ids.items())),
                    "lastAppliedSha": _git("rev-parse", "HEAD") or "unknown",
                    "lastAppliedAt": datetime.now(UTC).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\n  wrote .lock.json (assistant {assistant_id})")

    print()
    if apply:
        print(f"✓ applied — {changes} change(s)\n")
        return 0
    if changes == 0:
        print("✓ no drift\n")
        return 0
    if forbidden:
        print(f"✗ {forbidden} FORBIDDEN drift path(s) — a compliance-bearing field differs\n")
        return 1
    print(f"⚠ {changes} pending change(s). Re-run with --apply.\n")
    return 1 if os.environ.get("CI") else 0


if __name__ == "__main__":
    raise SystemExit(main())
