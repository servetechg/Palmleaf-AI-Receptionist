"""Vapi config-as-code deploy (03-vapi-layer §8).

    python -m grace_platform.vapi.deploy --env dev --diff     show drift, change nothing
    python -m grace_platform.vapi.deploy --env dev --apply    upsert tools, outputs, assistant

Order matters: tools and structured outputs must exist before the assistant can reference
their ids, and the assistant must exist before a phone number can bind to it.
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

#: Phone numbers resolved from the environment AT DEPLOY TIME, mirroring the n8n deployer's
#: ``__URL__:`` pass. They are deliberately NOT committed: the numbers are not issued yet
#: (GATE-11/RingCentral), and a placeholder string in the file would fail Vapi's own schema —
#: ``transferToHuman.json`` therefore keeps ``destinations: []``, which validate.py enforces.
PHONE_VARS: dict[str, str] = {
    "transfer-target": "GRACE_TRANSFER_NUMBER",
    "main-line": "GRACE_MAIN_LINE_NUMBER",
}


def transfer_destinations() -> list[dict[str, Any]]:
    """The transfer destination, or none at all when the number is not configured yet.

    Never substitute a stand-in. An invalid number makes Vapi attempt a real transfer to
    garbage mid-call; an empty list keeps today's behaviour, where the tool's request-start
    message plays and the escalation flow takes over.

    **L11 — static vs dynamic transfer config.** ``validate.py`` requires
    ``transferToHuman.json`` to ship ``destinations: []`` so that Vapi asks our server for a
    destination at transfer time (``transfer-destination-request``). That server-driven path
    is AUTHORITATIVE whenever a server is live: only it can attach the per-call whisper the
    prompt primes via ``flagEscalation``, and only it can pick a destination based on what
    the call was actually about. What this function injects is the NO-SERVER FALLBACK — the
    same shape the mock returns (``mock_server/server.py``), frozen at deploy time, so a
    transfer still reaches a human if the events endpoint is unreachable.

    Every field below is checked against ``platform/vapi/.vapi-openapi.json``:
    ``TransferDestinationNumber`` (``callerId``, ``transferPlan``) and ``TransferPlan``
    (``mode`` enum includes ``warm-transfer-experimental``, ``sipVerb`` enum includes
    ``dial``, ``dialTimeout`` ≤ 600, ``fallbackPlan`` → ``TransferFallbackPlan``).
    """
    number = os.environ.get(PHONE_VARS["transfer-target"], "").strip()
    if not number:
        return []
    return [
        {
            "type": "number",
            "number": number,
            # A-04: without this the transfer target sees Grace's number, not the caller's,
            # so the front desk cannot tell who is being handed to them or call them back.
            "callerId": "{{customer.number}}",
            "message": "Transferring you now.",
            "transferPlan": {
                # Puts the caller on hold, dials, and only bridges if a human answers —
                # so a transfer into a voicemail box does not silently strand the caller.
                "mode": "warm-transfer-experimental",
                "message": "Transferring a caller from the PalmLeaf line.",
                "sipVerb": "dial",
                "dialTimeout": 25,
                "fallbackPlan": {
                    "message": "I'm sorry — nobody's picking up right now. Let me take a message.",
                    # Grace keeps the call rather than hanging up on a failed transfer.
                    "endCallEnabled": False,
                },
            },
        }
    ]


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
    # I7, deploy-side. Mirrors validate.py's check — both exist because a deploy can be
    # run without a validate, and this is the last gate before a real caller hears it.
    #
    # RECORDING: required. Illinois is all-party consent (720 ILCS 5/14-2), a criminal
    # statute. Wording is free, presence is not.
    if not re.search(r"recorded", greeting, re.I):
        sys.exit("✗ I7: first-message.txt is missing the recording disclosure")

    # AI LABEL: deliberately NOT required (reviewed 2026-08-08 — no enacted Illinois
    # bot-disclosure law; SB 3368 / SB 317 pending). What IS required is that she never
    # claims to be a person, and that the prompt keeps her honest when asked.
    # See 05-security-and-compliance.md §12.
    if re.search(r"\b(human|real person)\b", greeting, re.I):
        sys.exit("✗ I7: first-message.txt implies Grace is a person")

    system_prompt = (HERE / "prompts" / "system.md").read_text("utf-8")
    if "Never imply you are human" not in system_prompt:
        sys.exit('✗ I7: system.md must contain "Never imply you are human"')


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
        if path.name == "transferToHuman.json":
            destinations = transfer_destinations()
            if destinations:
                tool["destinations"] = destinations
            else:
                print(
                    f"  ⚠ transferToHuman has no destination — {PHONE_VARS['transfer-target']} "
                    f"is unset (waiting on configuration, GATE-11). Deploying with an empty "
                    f"destination list; a transfer falls through to escalation."
                )
        out[tool_identity(tool)] = tool
    return out


def locked_assistant_id() -> str:
    """The assistant id from ``.lock.json`` — the deployed assistant, not an env guess.

    Phone numbers bind to an assistant by id, and the only id that is certainly real is the
    one the last apply recorded. Reading it from the environment instead would let a stale
    or hand-typed value bind a live number to somebody else's assistant.
    """
    if not LOCK_PATH.exists():
        sys.exit(
            "✗ platform/vapi/.lock.json is missing — a phone number binds to an assistant id,\n"
            "  and that id comes from a completed assistant deploy. Run:\n"
            "      make vapi-apply ENV=dev\n"
            "  then deploy phone numbers."
        )
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assistant_id = str(lock.get("assistantId", "")).strip()
    if not assistant_id:
        sys.exit("✗ .lock.json has no assistantId — re-run `make vapi-apply ENV=dev` first.")
    return assistant_id


#: Vars whose absence prunes only the block that uses them, instead of blocking the file.
#: ``fallbackDestination`` is a safety net (L4): a number without one still works, so an
#: unconfigured front desk must not stop the number being created.
OPTIONAL_PHONE_VARS = frozenset({"GRACE_FRONT_DESK_NUMBER"})

#: Declared at create time and absent from ``UpdateVapiPhoneNumberDTO`` — Vapi has no way to
#: report them back and no way to change them, so comparing them against an existing number
#: would produce drift that can never converge (the same lesson as the n8n ``webhookId``).
PHONE_CREATE_ONLY = frozenset({"numberDesiredAreaCode"})


def local_phone_numbers(assistant_id: str) -> dict[str, dict[str, Any]]:
    """Every ``phone-numbers/*.json``, resolved. Files blocked on configuration are skipped.

    Skip, do not fail — the same philosophy as the n8n deployer's blocked-workflow handling.
    ``main.json`` (the BYO/RingCentral-trunk path) has no SIP trunk credential yet and is
    expected to skip; that must not hold back the numbers that are ready.
    """
    directory = HERE / "phone-numbers"
    if not directory.exists():
        return {}

    out: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        raw = path.read_text(encoding="utf-8").replace("${GRACE_ASSISTANT_ID}", assistant_id)

        blocking = sorted(
            {
                name
                for name in _ENV_VAR.findall(raw)
                if name not in OPTIONAL_PHONE_VARS and not os.environ.get(name, "").strip()
            }
        )
        if blocking:
            print(
                f"\n  ⚠ SKIPPED phone-numbers/{path.name} — waiting on configuration: "
                f"{', '.join(blocking)}"
            )
            print("      set it in .env and re-run; nothing is half-created on the Vapi side.")
            continue

        body = prune_empty(json.loads(substitute(raw, [])))
        if not isinstance(body, dict):
            continue

        # `prune_empty` drops the empty `number` key but leaves the enclosing object, and
        # `TransferDestinationNumber` requires `number` — so a destination that lost it is
        # not a partial destination, it is no destination.
        fallback = body.get("fallbackDestination")
        if isinstance(fallback, dict) and not str(fallback.get("number", "")).strip():
            body.pop("fallbackDestination")
            print(
                f"  ⚠ phone-numbers/{path.name}: no fallbackDestination — "
                f"GRACE_FRONT_DESK_NUMBER is unset, so a Vapi/server failure has no human to "
                f"fall back to (L4)."
            )

        name = str(body.get("name") or path.stem)
        out[name] = body
    return out


def deploy_phone_numbers(client: VapiClient, apply: bool) -> tuple[dict[str, str], int]:
    """Upserts ``platform/vapi/phone-numbers/*.json``, matching remote numbers by ``name``.

    Returns ``({name: id}, change_count)`` — the ids for the lock file, the count for the
    run summary. Diff/apply semantics match the rest of this deployer: ``+`` create,
    ``~`` change, ``=`` unchanged, and nothing is written without ``--apply``.
    """
    local = local_phone_numbers(locked_assistant_id())
    if not local:
        return {}, 0

    print()
    changes = 0
    ids: dict[str, str] = {}
    remote_by_name = {str(p.get("name") or ""): p for p in client.list_phone_numbers()}

    for name, desired in local.items():
        remote = remote_by_name.get(name)
        if remote is None:
            if apply:
                created = client.create_phone_number(desired)
                ids[name] = str(created["id"])
                print(f"  + phone-number {name} → {created.get('number', created['id'])}")
            else:
                print(f"  + phone-number {name} (would create)")
            changes += 1
            continue

        ids[name] = str(remote["id"])
        # Create-only fields are invisible to a PATCH, so they are invisible to the diff too.
        comparable = {k: v for k, v in desired.items() if k not in PHONE_CREATE_ONLY}
        drift = compute_drift(remote, comparable)
        if not drift:
            print(f"  = phone-number {name}")
            continue
        changes += 1
        print(f"  ~ phone-number {name}")
        for d in drift:
            print(f"      · {d.path}")
            print(f"          remote:  {json.dumps(d.remote)[:70]}")
            print(f"          desired: {json.dumps(d.desired)[:70]}")
        if apply:
            client.update_phone_number(str(remote["id"]), comparable)

    return ids, changes


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

        # 4. phone numbers ────────────────────────────────────────────────────
        # Last: a number binds to an assistant id, so the assistant has to exist first.
        phone_ids, phone_changes = deploy_phone_numbers(client, apply)
        changes += phone_changes

    # 5. lock file ────────────────────────────────────────────────────────────
    if apply and assistant_id:
        LOCK_PATH.write_text(
            json.dumps(
                {
                    "env": env,
                    "assistantId": assistant_id,
                    "toolIds": dict(sorted(tool_ids.items())),
                    "structuredOutputIds": dict(sorted(so_ids.items())),
                    "phoneNumberIds": dict(sorted(phone_ids.items())),
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
