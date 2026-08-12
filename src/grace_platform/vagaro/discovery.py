"""Find out what Vagaro's API can actually do, before writing code that assumes.

    make vagaro-discover

**Read-only. This script never writes to Vagaro.** It authenticates, probes each endpoint
we might use, and records what came back — status codes, response shapes, rate-limit
headers, pagination style — into `platform/vagaro/discovery/`.

Why a discovery step at all: the public documentation confirms read endpoints and webhooks,
but whether appointment *creation* is available on this account is unverified. Secondary
sources say it exists; the account's own responses are the only evidence worth building on.
This is what answers GATE-01 and GATE-03 with facts instead of hope, and it is what sets
`PmsCapabilities` truthfully — every write flag defaults False until something here proves
otherwise.

Same pattern as the RingCentral snapshot: probe, record, commit the evidence, then design
against observed reality.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

OUT = Path(__file__).resolve().parents[3] / "platform" / "vagaro" / "discovery"

#: Keys whose values must never reach a committed file.
SECRET_KEYS = {"access_token", "refresh_token", "authorization", "client_secret", "password"}

#: Every probe is a GET. A POST would create real data in a live salon's calendar.
PROBES: list[tuple[str, str]] = [
    ("business", "/api/v2/businesses"),
    ("locations", "/api/v2/locations"),
    ("employees", "/api/v2/employees"),
    ("services", "/api/v2/services"),
    ("customers", "/api/v2/customers"),
    ("appointments", "/api/v2/appointments"),
]


def scrub(value: Any) -> Any:
    """Strip anything credential-shaped before it touches disk."""
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if k.lower() in SECRET_KEYS else scrub(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value[:3]]  # shape, not the salon's customer list
    return value


def token(client: httpx.Client, base: str) -> str:
    """OAuth 2.0 client-credentials. Path is config, not a constant — Vagaro's token
    endpoint is not published and may differ per region (assumption A-03)."""
    path = os.environ.get("GRACE_VAGARO_TOKEN_PATH", "/api/v2/oauth/token")
    response = client.post(
        path,
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["GRACE_VAGARO_CLIENT_ID"],
            "client_secret": os.environ["GRACE_VAGARO_CLIENT_SECRET"],
        },
    )
    if response.status_code // 100 != 2:
        sys.exit(
            f"✗ token request failed: {response.status_code} {response.text[:300]}\n"
            f"  Tried {base}{path}. If Vagaro's activation email names a different token\n"
            f"  URL, set GRACE_VAGARO_TOKEN_PATH and re-run."
        )
    payload = response.json()
    value = payload.get("access_token") or payload.get("accessToken")
    if not value:
        sys.exit(f"✗ no access_token in the response: {list(payload)}")
    return str(value)


def probe(client: httpx.Client, name: str, path: str, bearer: str) -> dict[str, Any]:
    try:
        response = client.get(path, headers={"Authorization": f"Bearer {bearer}"}, timeout=20.0)
    except httpx.HTTPError as exc:
        return {"path": path, "reachable": False, "error": str(exc)}

    record: dict[str, Any] = {
        "path": path,
        "status": response.status_code,
        "reachable": response.status_code // 100 == 2,
        # These decide the token bucket's real limits (GATE-03) rather than our guess.
        "rate_limit_headers": {
            k: v for k, v in response.headers.items() if "ratelimit" in k.lower()
        },
    }
    if record["reachable"]:
        try:
            body = response.json()
        except ValueError:
            record["note"] = "200 but not JSON"
            return record
        record["shape"] = scrub(body)
        if isinstance(body, dict):
            record["pagination_keys"] = [
                k for k in body if k.lower() in {"nextpage", "next", "cursor", "offset", "total"}
            ]
    else:
        record["body"] = response.text[:300]
    return record


def main() -> int:
    missing = [
        v for v in ("GRACE_VAGARO_CLIENT_ID", "GRACE_VAGARO_CLIENT_SECRET") if not os.environ.get(v)
    ]
    if missing:
        sys.exit(
            f"✗ {' and '.join(missing)} not set.\n"
            "  These arrive with Vagaro's API activation email (7 business days from the\n"
            "  request). Nothing else in the integration is blocked on them — the adapter,\n"
            "  the mirror and the webhook receiver are already built and tested."
        )

    base = os.environ.get("GRACE_VAGARO_BASE_URL", "https://api.vagaro.com")
    OUT.mkdir(parents=True, exist_ok=True)

    print(f"\nVagaro discovery — {base}\n")
    with httpx.Client(base_url=base, timeout=30.0) as client:
        bearer = token(client, base)
        print("  ✓ authenticated\n")

        results = {}
        for name, path in PROBES:
            record = probe(client, name, path, bearer)
            results[name] = record
            mark = "✓" if record.get("reachable") else "·"
            print(f"  {mark} {name:14} {path:34} {record.get('status', 'error')}")
            (OUT / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    # The capability matrix is the actual deliverable: it is what PmsCapabilities becomes.
    matrix = {
        "probed_at": None,
        "base_url": base,
        "read_appointments": results.get("appointments", {}).get("reachable", False),
        "read_customers": results.get("customers", {}).get("reachable", False),
        "read_employees": results.get("employees", {}).get("reachable", False),
        "read_services": results.get("services", {}).get("reachable", False),
        # Deliberately unset by a read-only probe. Confirming a write endpoint means
        # creating a real appointment in a live salon, which is a manual, supervised test
        # against a designated test customer and a far-future slot — never this script.
        "write_appointments": "UNVERIFIED — needs a supervised live write test",
        "rate_limit_headers_seen": any(
            r.get("rate_limit_headers") for r in results.values() if isinstance(r, dict)
        ),
    }
    (OUT / "capabilities.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")

    reachable = sum(1 for r in results.values() if r.get("reachable"))
    print(f"\n✓ {reachable}/{len(PROBES)} endpoints reachable — evidence in {OUT}")
    print("  Next: set PmsCapabilities from capabilities.json, then build the read adapter.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
