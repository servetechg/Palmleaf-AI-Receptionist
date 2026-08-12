"""RingCentral platform login — READ-ONLY phase.

847.961.4800 is PalmLeaf's only business number. Everything in this module today issues
GET requests and nothing else: the account's pre-Grace state has to be captured, in git,
before any code is allowed to change it (plan Phase 0b).

Phase 2 adds the write path (``pilot.py`` — custom answering rules that forward whitelisted
callers to Grace). Two rules bind whoever implements it:

* **L7 — only ``grace-*`` rules may ever be written.** Write code must refuse, with a hard
  exit, to create, modify, enable, disable or delete any answering rule whose name does not
  start with ``grace-``. The account's own ``business-hours-rule`` and ``after-hours-rule``
  are what customers hit today; touching them is an outage, not a bug.
* **Snapshot before write is unconditional.** ``snapshot.py`` runs first, every time, so the
  rollback reference is current at the moment of the change.

Auth: a Private JWT app on the production platform. The JWT does not expire in any practical
horizon (exp ≈ 2094), so there is no refresh dance — but the client secret and JWT live in
``.env`` only and must never be echoed, logged, or written into a snapshot file.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

from ringcentral import SDK

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ringcentral.platform.platform import Platform

#: Production, not sandbox. The sandbox account is a different tenant with different
#: extensions, so a snapshot taken there would be a convincing but useless rollback reference.
SERVER_URL = "https://platform.ringcentral.com"

ENV_CLIENT_ID = "GRACE_RINGCENTRAL_CLIENT_ID"
ENV_CLIENT_SECRET = "GRACE_RINGCENTRAL_CLIENT_SECRET"
ENV_JWT = "GRACE_RINGCENTRAL_JWT"


def login() -> Platform:
    """Authenticates the Private JWT app and returns the SDK platform handle.

    Exits with an actionable message rather than raising when the credentials are absent:
    this is operator tooling, and a stack trace about an empty string is not a useful
    instruction.
    """
    client_id = os.environ.get(ENV_CLIENT_ID, "").strip()
    client_secret = os.environ.get(ENV_CLIENT_SECRET, "").strip()
    jwt = os.environ.get(ENV_JWT, "").strip()

    missing = [
        name
        for name, value in (
            (ENV_CLIENT_ID, client_id),
            (ENV_CLIENT_SECRET, client_secret),
            (ENV_JWT, jwt),
        )
        if not value
    ]
    if missing:
        sys.exit(
            f"✗ RingCentral credentials missing: {', '.join(missing)}\n"
            f"  Set them in .env (see .env.example) — they come from the Private JWT app in\n"
            f"  the RingCentral developer console. Docs/plans/06-platform-setup.md has the walkthrough."
        )

    sdk = SDK(client_id, client_secret, SERVER_URL)
    platform: Platform = sdk.platform()
    platform.login(jwt=jwt)
    return platform


def get_json(platform: Platform, path: str) -> Any:
    """One GET, decoded. The only verb this module knows (see the module docstring)."""
    return platform.get(path).json_dict()
