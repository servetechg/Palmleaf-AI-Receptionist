"""Generates platform/vapi/tools/*.json from the Pydantic registry in grace_contracts.

Runs in CI. If a generated file differs from what is committed, CI fails — the tool schema
published to Vapi and the schema the handler validates against cannot drift (doc 08 §2).

    python -m grace_platform.vapi.generate_tools           write files
    python -m grace_platform.vapi.generate_tools --check   exit 1 if anything would change
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from grace_contracts import HAND_AUTHORED_TOOLS, TOOL_REGISTRY, ToolSpec

TOOLS_DIR = Path(__file__).resolve().parents[3] / "platform" / "vapi" / "tools"

# Env placeholders, substituted by deploy.py. Never a literal URL in a committed file.
TOOLS_URL = "${GRACE_TOOLS_URL}"
TOOLS_CREDENTIAL_ID = "${VAPI_TOOLS_CREDENTIAL_ID}"

# Read tools may be retried; write tools may not — a retried booking is a real duplicate.
READ_BACKOFF: dict[str, Any] = {
    "type": "fixed",
    "maxRetries": 1,
    "baseDelaySeconds": 1,
    "excludedStatusCodes": [400, 401, 409, 422],
}

# Pydantic emits snake_case field names; Vapi tools and the prompt use camelCase.
_CAMEL_EXCEPTIONS: dict[str, str] = {}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return _CAMEL_EXCEPTIONS.get(name, head + "".join(w.capitalize() for w in rest))


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Resolves every ``$ref`` against ``$defs`` and inlines it.

    Pydantic hoists enums into ``$defs`` and references them. Vapi has no ``$ref``
    resolver for tool parameters, so anything left behind is a deploy-time 400.
    """
    if isinstance(node, list):
        return [_inline_refs(n, defs) for n in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        ref = str(node["$ref"])
        key = ref.rsplit("/", 1)[-1]
        target = defs.get(key)
        if target is None:
            raise ValueError(f"unresolvable $ref {ref}")
        merged = {**_inline_refs(target, defs)}
        # Preserve any siblings of the $ref (Pydantic puts `default`/`description` there).
        for k, v in node.items():
            if k != "$ref":
                merged[k] = _inline_refs(v, defs)
        # An inlined enum brings its class name as `title` and its class docstring as
        # `description`. Both are internal. The field's own description (a sibling of the
        # $ref, applied below) is the deliberate, model-facing text.
        merged.pop("title", None)
        if "description" in node:
            merged["description"] = _inline_refs(node["description"], defs)
        else:
            merged.pop("description", None)
        return merged

    return {k: _inline_refs(v, defs) for k, v in node.items()}


def _strip_docstring_noise(schema: dict[str, Any]) -> dict[str, Any]:
    """Removes everything Pydantic adds that the model should not read.

    Two kinds of noise, and the second is a real hazard:

    * ``title`` — Pydantic titles every field ("Medical Screen Passed"). Pure token cost;
      the field name and description already say it.
    * ``description`` on the parameters object itself — Pydantic uses the **class
      docstring** for this. Our docstrings contain implementation notes ("``bool`` rather
      than ``Literal[True]``: a single-value literal renders as a scalar ``const``…"),
      which would be fed to the model verbatim as instructions. Field-level descriptions
      are deliberate and are kept; class docstrings are not.
    """
    schema.pop("title", None)
    schema.pop("description", None)

    props = schema.get("properties")
    if isinstance(props, dict):
        for prop in props.values():
            if isinstance(prop, dict):
                prop.pop("title", None)
    return schema


def _to_camel_case_props(schema: dict[str, Any]) -> dict[str, Any]:
    """Renames properties (and `required`) to camelCase for the model-facing schema."""
    props = schema.get("properties")
    if isinstance(props, dict):
        schema["properties"] = {_camel(k): v for k, v in props.items()}
    req = schema.get("required")
    if isinstance(req, list):
        schema["required"] = [_camel(str(k)) for k in req]
    return schema


def _assert_vapi_compatible(tool_name: str, node: Any, path: str = "") -> None:
    """Vapi requires every parameter to carry a plain ``type``.

    It rejects ``anyOf`` with ``400 function.parameters.properties.X.type must be one of…``
    and rejects a scalar ``const``. Both were verified against the live API on 2026-08-03,
    after ``str | None`` and ``Literal[True]`` each broke a deploy. Catching them here turns
    a deploy-time 400 into an offline failure with a fix instruction.
    """
    if isinstance(node, list):
        for i, n in enumerate(node):
            _assert_vapi_compatible(tool_name, n, f"{path}[{i}]")
        return
    if not isinstance(node, dict):
        return

    for combinator in ("anyOf", "oneOf", "allOf"):
        if combinator in node:
            raise ValueError(
                f'{tool_name}: parameter "{path}" renders as `{combinator}`, which Vapi rejects.\n'
                f"    Cause: an optional field with constraints, e.g. `str | None` or `X | None`.\n"
                f'    Fix:   use a plain type with a default (e.g. `str = ""`) on tool INPUT models.'
            )
    if "const" in node and not isinstance(node["const"], dict | list):
        raise ValueError(
            f'{tool_name}: parameter "{path}" emits a scalar `const`, which Vapi rejects.\n'
            f"    Cause: Literal[...] with a single value on a tool INPUT model.\n"
            f"    Fix:   use the plain type and enforce the value in the handler."
        )
    if "$ref" in node:
        raise ValueError(f'{tool_name}: parameter "{path}" still contains a $ref after inlining.')

    for k, v in node.items():
        _assert_vapi_compatible(tool_name, v, f"{path}.{k}" if path else k)


def build_tool_json(spec: ToolSpec) -> dict[str, Any]:
    raw = spec.input_model.model_json_schema()
    defs = raw.pop("$defs", {})
    parameters = _inline_refs(raw, defs)
    parameters.pop("$schema", None)
    parameters = _strip_docstring_noise(parameters)
    parameters = _to_camel_case_props(parameters)
    _assert_vapi_compatible(spec.name, parameters)

    messages: list[dict[str, Any]] = []
    if spec.request_start:
        messages.append(
            {
                "type": "request-start",
                "content": spec.request_start,
                # Async tools never deliver a result to the model, so the filler IS the answer.
                "blocking": spec.is_async,
            }
        )
    if spec.request_failed:
        messages.append({"type": "request-failed", "content": spec.request_failed})

    server: dict[str, Any] = {
        "url": TOOLS_URL,
        "credentialId": TOOLS_CREDENTIAL_ID,
        "timeoutSeconds": 10,
    }
    if not spec.is_write:
        server["backoffPlan"] = READ_BACKOFF

    tool: dict[str, Any] = {
        "type": "function",
        "async": spec.is_async,
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": parameters,
        },
        "server": server,
    }
    if messages:
        tool["messages"] = messages
    return tool


def stable_json(value: Any) -> str:
    """Deterministic output: sorted keys, trailing newline. Byte-identical across runs."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    generated = {f"{s.name}.json": stable_json(build_tool_json(s)) for s in TOOL_REGISTRY}

    protected = {"README.md", *(f"{n}.json" for n in HAND_AUTHORED_TOOLS)}
    on_disk = {p.name for p in TOOLS_DIR.iterdir() if p.name not in protected}
    problems: list[str] = []

    for filename, content in generated.items():
        path = TOOLS_DIR / filename
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == content:
            continue
        if check:
            problems.append(f"{'missing' if existing is None else 'stale  '}: {filename}")
        else:
            path.write_text(content, encoding="utf-8")
            print(f"{'created' if existing is None else 'updated'}  tools/{filename}")

    # A tool removed from the registry must not linger in Vapi.
    for filename in sorted(on_disk - generated.keys()):
        if check:
            problems.append(f"orphan : {filename} (no registry entry)")
        else:
            (TOOLS_DIR / filename).unlink()
            print(f"removed  tools/{filename}")

    if check and problems:
        print("\n✗ generated tool JSON is out of date:\n", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        print("\n  Run: make vapi-generate  and commit the result.\n", file=sys.stderr)
        return 1

    digest = hashlib.sha256(
        "".join(k + v for k, v in sorted(generated.items())).encode()
    ).hexdigest()[:12]
    verb = "up to date" if check else "wrote"
    print(f"✓ {len(generated)} tool schemas {verb} ({digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
