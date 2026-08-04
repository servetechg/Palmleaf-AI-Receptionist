"""T1 static gate (doc 08 §9.1).

Validates every local Vapi artefact OFFLINE against the Vapi OpenAPI spec plus our own
invariants. No calls to Vapi, no cost, under a second.

This is the tier that found four assistant fields that no longer exist. Run it before any
deploy; run it in CI with --refresh so it checks against current reality.

    python -m grace_platform.vapi.validate [--refresh]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

from grace_contracts import HAND_AUTHORED_TOOLS, TOOL_REGISTRY

HERE = Path(__file__).resolve().parents[3] / "platform" / "vapi"
SPEC_URL = "https://api.vapi.ai/api-json"
SPEC_CACHE = HERE / ".vapi-openapi.json"

problems: list[str] = []
warnings: list[str] = []

EXPECTED_TYPE = {"transferToHuman": "transferCall", "endCall": "endCall"}
STREAMING_MESSAGES = ("conversation-update", "transcript", "speech-update", "model-output")


def read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def load_spec(refresh: bool) -> dict[str, Any] | None:
    if not refresh and SPEC_CACHE.exists():
        return read_json(SPEC_CACHE)
    try:
        res = httpx.get(SPEC_URL, timeout=30.0)
        res.raise_for_status()
        spec = res.json()
        SPEC_CACHE.write_text(json.dumps(spec), encoding="utf-8")
        return dict(spec)
    except Exception as err:
        warnings.append(f"could not fetch the Vapi OpenAPI spec ({err}) — schema checks skipped")
        return read_json(SPEC_CACHE) if SPEC_CACHE.exists() else None


def _schema(spec: dict[str, Any], name: str) -> dict[str, Any]:
    schemas = spec.get("components", {}).get("schemas", {})
    return dict(schemas.get(name, {}))


def main() -> int:
    spec = load_spec("--refresh" in sys.argv)
    assistant = read_json(HERE / "assistants" / "grace.json")

    # ── assistant keys against the live schema ────────────────────────────────
    if spec:
        props = _schema(spec, "CreateAssistantDTO").get("properties", {})
        if not props:
            warnings.append("CreateAssistantDTO not found in spec — key check skipped")
        deprecated = {k for k, v in props.items() if v.get("deprecated")}
        for key in assistant:
            if props and key not in props:
                problems.append(f'grace.json: "{key}" is not a property of CreateAssistantDTO')
            if key in deprecated:
                problems.append(f'grace.json: "{key}" is DEPRECATED in the current Vapi API')

        server_props = _schema(spec, "Server").get("properties", {})
        for key in assistant.get("server", {}):
            if server_props and key not in server_props:
                problems.append(
                    f"grace.json: server.{key} is not a property of Server (did you mean credentialId?)"
                )

    # ── I7: the greeting must be injected, never inlined ──────────────────────
    first_message = assistant.get("firstMessage", "")
    if "injected from prompts/first-message.txt" not in str(first_message):
        problems.append("I7: grace.json must inject firstMessage, never inline it")

    greeting = (HERE / "prompts" / "first-message.txt").read_text(encoding="utf-8").lower()
    if "may be recorded" not in greeting:
        problems.append(
            'I7: first-message.txt is missing the recording disclosure ("may be recorded")'
        )
    if "virtual assistant" not in greeting and "ai assistant" not in greeting:
        problems.append("I7: first-message.txt is missing the AI disclosure")

    # ── serverMessages ────────────────────────────────────────────────────────
    server_messages = assistant.get("serverMessages", [])
    if "end-of-call-report" not in server_messages:
        problems.append(
            'serverMessages omits "end-of-call-report" — setting this field REPLACES the defaults, '
            "so the call-summary/QA/redaction pipeline would silently never run (doc 08 §3.2)"
        )
    if "transfer-destination-request" not in server_messages:
        problems.append(
            'serverMessages omits "transfer-destination-request" — transfers cannot resolve a destination'
        )
    for streaming in STREAMING_MESSAGES:
        if streaming in server_messages:
            problems.append(
                f'serverMessages includes "{streaming}" — that streams raw caller utterances before '
                f"redaction (I5/I6 risk, doc 08 §3.2). Remove it."
            )

    if "analysisPlan" in assistant:
        problems.append(
            "grace.json uses analysisPlan, which is deprecated in full. "
            "Use artifactPlan.structuredOutputIds"
        )
    if "endCallFunctionEnabled" in assistant:
        problems.append(
            "grace.json: endCallFunctionEnabled no longer exists — register tools/endCall.json instead"
        )

    # ── generated tools ───────────────────────────────────────────────────────
    for spec_tool in TOOL_REGISTRY:
        path = HERE / "tools" / f"{spec_tool.name}.json"
        if not path.exists():
            problems.append(f"tools/{spec_tool.name}.json is missing — run make vapi-generate")
            continue
        tool = read_json(path)
        server = tool.get("server", {})
        if not server.get("url"):
            problems.append(f"tools/{spec_tool.name}.json: server.url is missing")
        if "secret" in server:
            problems.append(
                f"tools/{spec_tool.name}.json: server.secret does not exist in the Vapi API — "
                f"use credentialId"
            )
        if tool.get("async") != spec_tool.is_async:
            problems.append(f"tools/{spec_tool.name}.json: async flag disagrees with the registry")
        # Async tools never deliver a result to the model, so they need a spoken filler —
        # unless the prompt guarantees the very next tool speaks (flagEscalation → transfer).
        if spec_tool.is_async and not spec_tool.acked_by_next_tool and "messages" not in tool:
            problems.append(
                f"tools/{spec_tool.name}.json is async but has no request-start message — the caller "
                f"would hear silence, because an async result never reaches the model (doc 08 §4.2)"
            )
        # Write tools must not retry: a retried booking is a real duplicate.
        if spec_tool.is_write and "backoffPlan" in server:
            problems.append(
                f"tools/{spec_tool.name}.json is a write tool and must not carry a backoffPlan"
            )
        # The parameters the model sees must contain no internal noise.
        params = tool.get("function", {}).get("parameters", {})
        if "description" in params:
            problems.append(
                f"tools/{spec_tool.name}.json: parameters carries a class docstring as `description` — "
                f"internal notes must never become model-facing text"
            )
        if any("title" in p for p in params.get("properties", {}).values() if isinstance(p, dict)):
            problems.append(
                f"tools/{spec_tool.name}.json: parameters contain Pydantic `title` noise"
            )

    # ── hand-authored tools ───────────────────────────────────────────────────
    for name in HAND_AUTHORED_TOOLS:
        path = HERE / "tools" / f"{name}.json"
        if not path.exists():
            problems.append(f"tools/{name}.json is missing (hand-authored, not generated)")
            continue
        tool = read_json(path)
        if tool.get("type") != EXPECTED_TYPE[name]:
            problems.append(
                f'tools/{name}.json must be type "{EXPECTED_TYPE[name]}", got "{tool.get("type")}"'
            )
        if "function" in tool:
            problems.append(
                f'tools/{name}.json has a "function" property. Its DTO has none, so the model '
                f"cannot pass arguments to it (doc 08 §7.1)"
            )
        if name == "transferToHuman" and tool.get("destinations") != []:
            problems.append(
                "tools/transferToHuman.json: destinations must be [] so Vapi asks our server for it"
            )

    # ── structured outputs ────────────────────────────────────────────────────
    so = read_json(HERE / "structured-outputs" / "call-outcome.json")
    for key, defn in so.get("schema", {}).get("properties", {}).items():
        # Free text in a structured output is a PHI route: an LLM summarising a transcript
        # that may contain health disclosures, written to a persisted column (I6).
        if (
            defn.get("type") == "string"
            and "enum" not in defn
            and not key.endswith("Ref")
            and not key.startswith("provider")
        ):
            warnings.append(f'structured-output "{key}" is free text — prefer an enum (I6)')

    for w in warnings:
        print(f"  ⚠ {w}")
    if problems:
        print(f"\n✗ {len(problems)} validation problem(s):\n", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        print(file=sys.stderr)
        return 1

    print(
        f"✓ grace.json, {len(TOOL_REGISTRY)} generated tools, "
        f"{len(HAND_AUTHORED_TOOLS)} hand-authored tool(s) and 1 structured output validated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
