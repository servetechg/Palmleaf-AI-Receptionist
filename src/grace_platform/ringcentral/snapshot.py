"""RingCentral read-only snapshot + drift detection (plan Phase 0b).

    python -m grace_platform.ringcentral.snapshot     # make rc-snapshot

Captures the live account's routing configuration into ``platform/ringcentral/snapshot/``
so that:

1. the **exact pre-Grace state** of a real business phone line is in git before any write
   code exists — this is the rollback reference (plan Phase 0b);
2. the answering-rule JSON shapes Phase 2 must produce are observed rather than guessed —
   RingCentral's public guides do not publish the full schemas;
3. re-running reports drift, the same way ``n8n-diff`` does, so a change somebody makes in
   the RingCentral admin UI shows up here instead of surprising us mid-pilot.

**Where the routing actually lives (observed 2026-08-06, not assumed).** This account has the
``NewCallHandlingAndForwarding`` feature enabled, which makes the per-extension answering-rule
API return ``403 This API is not available with enabled feature [NewCallHandlingAndForwarding]``.
The COMPANY-level endpoint ``/account/~/answering-rule`` still works, and that is where the
rules for +1 847 961 4800 live — every one of them keyed on ``calledNumbers``. So the pilot's
whitelist rule is a company answering rule, not an extension one. The failed extension-level
call is snapshotted anyway (``extension-answering-rules.json``) because "this endpoint is
closed to us" is itself a fact Phase 2 depends on.

Every request is a GET. There is no write path in this module and there must not be one —
see ``client.py`` for the rules Phase 2 inherits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .client import get_json, login

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ringcentral.platform.platform import Platform

SNAPSHOT_DIR = Path(__file__).resolve().parents[3] / "platform" / "ringcentral" / "snapshot"

#: Keys stripped from every snapshot before it touches disk, at any depth. The snapshot is
#: committed, so a credential that reaches a file here reaches the repository history.
#: Phone numbers are deliberately NOT scrubbed — they are business data the docs already
#: carry, and the whole point of the snapshot is knowing which number routes where.
SECRET_KEYS = frozenset(
    {
        "token",
        "accesstoken",
        "refreshtoken",
        "access_token",
        "refresh_token",
        "password",
        "authorization",
        "clientsecret",
        "client_secret",
    }
)

#: A URI carrying a session token in its query string would smuggle a credential past the
#: key-name scrub, so values are checked too, not just key names.
_TOKEN_IN_URI = ("access_token=", "accessToken=", "token=")


def scrub(value: Any) -> Any:
    """Recursively removes credential-bearing fields."""
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k.lower().replace("-", "").replace("_", "") in SECRET_KEYS:
                continue
            if isinstance(v, str) and any(marker in v for marker in _TOKEN_IN_URI):
                out[k] = "<redacted: embedded credential>"
                continue
            out[k] = scrub(v)
        return out
    return value


def _error_note(exc: Exception) -> str:
    """A safe one-line description of a failed GET.

    Deliberately does not use the SDK's own ``error()``: it appends the full prepared
    request, Authorization header included, which is exactly what must never be printed or
    written to a file.
    """
    response = getattr(getattr(exc, "api_response", lambda: None)(), "response", lambda: None)()
    status = getattr(response, "status_code", None)
    reason = ""
    try:
        body = response.json() if response is not None else {}
        if isinstance(body, dict):
            reason = str(body.get("message") or body.get("errorCode") or "")
    except Exception:
        reason = ""
    if status is None:
        return f"request failed: {type(exc).__name__}"
    return f"{status} {reason}".strip()


def fetch(platform: Platform, path: str) -> Any:
    """GET, scrubbed. A 403/404 on one endpoint records itself instead of aborting the run.

    Partial visibility is normal — an app scope may be missing, or the account's feature set
    may have closed an endpoint (see the module docstring) — and a snapshot that captures
    twelve endpoints and names the thirteenth is far more useful than one that dies on it.
    """
    try:
        return scrub(get_json(platform, path))
    except Exception as exc:
        return {"_unavailable": _error_note(exc), "_path": path}


def _canonical(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def _records(payload: Any) -> list[dict[str, Any]]:
    """The ``records`` array of a RingCentral list response, or [] when unavailable."""
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [r for r in records if isinstance(r, dict)]
    return []


def main_extension_id(account: Any, extensions: Any) -> str:
    """The extension that owns the main company number.

    Preference order, most authoritative first: the account's declared ``operator``; an
    extension numbered 0; a ``Main``/``Site`` extension; otherwise ``~`` (the extension the
    JWT itself authenticates as), which is always valid but may not be the one customers reach.
    """
    if isinstance(account, dict):
        operator = account.get("operator")
        if isinstance(operator, dict) and operator.get("id"):
            return str(operator["id"])

    for record in _records(extensions):
        if str(record.get("extensionNumber", "")) == "0":
            return str(record.get("id", "~"))
    for record in _records(extensions):
        if str(record.get("type", "")) in {"Main", "Site"}:
            return str(record.get("id", "~"))
    return "~"


class Snapshot:
    """Accumulates files, reporting per-file drift against what is already committed."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.first_run = not any(self.dir.glob("*.json"))
        self.drifted: list[str] = []
        self.written: set[str] = set()

    def record(self, name: str, payload: Any) -> Any:
        path = self.dir / name
        body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if _canonical(previous) == _canonical(payload):
                print(f"  = {name}")
            else:
                print(f"  ~ {name}")
                self.drifted.append(name)
        else:
            print(f"  + {name}")
        path.write_text(body, encoding="utf-8")
        self.written.add(name)
        return payload

    def prune(self) -> None:
        """Deletes snapshot files no longer produced — a stale file is a false rollback reference."""
        for path in sorted(self.dir.glob("*.json")):
            if path.name not in self.written:
                print(f"  - {path.name} (no longer captured)")
                path.unlink()


def _rule_line(rule: dict[str, Any], extension_names: dict[str, str]) -> str:
    target = rule.get("extension")
    target_id = str(target.get("id", "")) if isinstance(target, dict) else ""
    called = ", ".join(
        str(c.get("phoneNumber", "?"))
        for c in (rule.get("calledNumbers") or [])
        if isinstance(c, dict)
    )
    bits = [
        f"{rule.get('id', '?')}",
        f"{rule.get('name') or rule.get('type', '(unnamed)')!r}",
        "enabled" if rule.get("enabled") else "DISABLED",
        f"action={rule.get('callHandlingAction', '?')}",
    ]
    if target_id:
        bits.append(f"→ ext {target_id} ({extension_names.get(target_id, 'unknown')})")
    if called:
        bits.append(f"called={called}")
    return "    · " + "  ".join(bits)


def main() -> int:
    snap = Snapshot(SNAPSHOT_DIR)

    print("\nRingCentral snapshot — READ ONLY\n")
    platform = login()

    # ── account ───────────────────────────────────────────────────────────────
    account = snap.record("account.json", fetch(platform, "/restapi/v1.0/account/~"))
    service_info = snap.record(
        "service-info.json", fetch(platform, "/restapi/v1.0/account/~/service-info")
    )
    snap.record(
        "phone-numbers.json", fetch(platform, "/restapi/v1.0/account/~/phone-number?perPage=100")
    )
    extensions = snap.record(
        "extensions.json", fetch(platform, "/restapi/v1.0/account/~/extension?perPage=100")
    )
    snap.record(
        "account-business-hours.json", fetch(platform, "/restapi/v1.0/account/~/business-hours")
    )

    # The routing layer that actually answers +1 847 961 4800 (see module docstring).
    rules = snap.record(
        "answering-rules.json",
        fetch(platform, "/restapi/v1.0/account/~/answering-rule?perPage=100"),
    )

    rule_ids = [str(r["id"]) for r in _records(rules) if r.get("id")]
    for known in ("business-hours-rule", "after-hours-rule"):
        if known not in rule_ids:
            rule_ids.append(known)

    details: dict[str, Any] = {}
    for rule_id in rule_ids:
        detail = fetch(platform, f"/restapi/v1.0/account/~/answering-rule/{rule_id}")
        details[rule_id] = detail
        snap.record(f"answering-rule-{rule_id}.json", detail)

    # Where the rules send calls: every `callHandlingAction: Bypass` names an extension id,
    # and those are IVR menus, call queues and voicemail boxes rather than phones.
    snap.record(
        "call-queues.json", fetch(platform, "/restapi/v1.0/account/~/call-queues?perPage=100")
    )
    snap.record("ivr-menus.json", fetch(platform, "/restapi/v1.0/account/~/ivr-menus"))

    # ── the operator extension ────────────────────────────────────────────────
    ext_id = main_extension_id(account, extensions)
    base = f"/restapi/v1.0/account/~/extension/{ext_id}"
    snap.record("extension.json", fetch(platform, base))
    snap.record("extension-business-hours.json", fetch(platform, f"{base}/business-hours"))
    snap.record(
        "extension-answering-rules.json",
        fetch(platform, f"{base}/answering-rule?view=Detailed&enabledOnly=false"),
    )
    snap.record("forwarding-numbers.json", fetch(platform, f"{base}/forwarding-number?perPage=100"))

    snap.prune()

    # ── findings ──────────────────────────────────────────────────────────────
    extension_names = {
        str(r.get("id")): f"{r.get('type', '?')} {r.get('extensionNumber') or '-'} "
        f"{r.get('name', '')}".strip()
        for r in _records(extensions)
    }

    print("\nFindings\n")
    if isinstance(account, dict):
        print(f"  main number:      {account.get('mainNumber', '(no mainNumber field)')}")
    print(f"  operator ext:     {ext_id} ({extension_names.get(ext_id, 'unknown')})")
    print(f"  extensions:       {len(extension_names)}")

    print(f"\n  company answering rules: {len(rule_ids)}")
    for rule_id in rule_ids:
        detail = details.get(rule_id, {})
        if not isinstance(detail, dict) or "_unavailable" in detail:
            note = detail.get("_unavailable") if isinstance(detail, dict) else "unreadable"
            print(f"    · {rule_id} — unavailable ({note})")
            continue
        print(_rule_line(detail, extension_names))

    # L3 — does RingCentral voicemail race the forward? The ring/timeout config of whatever
    # rule is in force decides it. `Bypass` hands the call straight to another extension, so
    # the timing lives in that extension, not the rule.
    print("\n  L3 (ring / voicemail timing):")
    for rule_id in rule_ids:
        detail = details.get(rule_id, {})
        forwarding = detail.get("forwarding") if isinstance(detail, dict) else None
        if not isinstance(forwarding, dict):
            continue
        print(f"    {rule_id}: ringingMode={forwarding.get('ringingMode', '?')}")
        for ruleset in forwarding.get("rules") or []:
            if isinstance(ruleset, dict):
                targets = [
                    str(f.get("phoneNumber", f.get("label", "?")))
                    for f in (ruleset.get("forwardingNumbers") or [])
                    if isinstance(f, dict)
                ]
                print(
                    f"      ring {ruleset.get('ringCount', '?')}× → {', '.join(targets) or '(none)'}"
                )
    if not any(isinstance(details.get(r, {}).get("forwarding"), dict) for r in rule_ids):
        print("    no rule declares `forwarding` — every rule uses callHandlingAction to hand")
        print("    the call to another extension, so ring counts live on those extensions.")

    # L9 — concurrent-call limits, verbatim from whatever service-info reports.
    print("\n  L9 (service limits / concurrent calls):")
    if isinstance(service_info, dict) and "_unavailable" not in service_info:
        limits = service_info.get("limits")
        if isinstance(limits, dict):
            for key, value in sorted(limits.items()):
                print(f"    {key}: {value}")
        plan = service_info.get("servicePlan")
        if isinstance(plan, dict):
            print(f"    servicePlan: {plan.get('name', '?')}")
        if not isinstance(limits, dict) or not any("all" in k.lower() for k in limits):
            print("    service-info publishes NO concurrent-call figure — L9 stays empirical.")
    elif isinstance(service_info, dict):
        print(f"    unavailable — {service_info.get('_unavailable')}")

    print()
    if snap.first_run:
        print("✓ first snapshot written to platform/ringcentral/snapshot/")
        print("  Commit it: this is the rollback reference for every RingCentral change.\n")
        return 0
    if snap.drifted:
        print(f"⚠ {len(snap.drifted)} file(s) drifted from the committed snapshot:")
        for name in snap.drifted:
            print(f"    ~ {name}")
        print("  Review the diff — someone changed the account outside this repository.\n")
        return 0
    print("✓ no drift\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
