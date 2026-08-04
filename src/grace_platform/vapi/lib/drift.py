"""Merge-based drift detection (doc 08 §8.1).

A naive ``local`` vs ``remote`` diff is permanently red: Vapi materialises every server
default and adds new ones over time. Instead we compare ``remote`` against
``deep_merge(remote, local)`` — so drift is non-empty **iff a key we actually declare has
a different value remotely**. Keys the server adds and we do not declare are invisible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

VOLATILE = frozenset(
    {
        "id",
        "orgId",
        "createdAt",
        "updatedAt",
        "isServerUrlSecretSet",
        "credentialId",  # env-injected, instance-specific — masked, not compared
    }
)

SORT_ARRAYS_AT = frozenset({"toolIds", "structuredOutputIds", "serverMessages"})

FORBIDDEN_DRIFT: tuple[str, ...] = (
    "firstMessage",
    "serverMessages",
    "server.url",
    "model.messages.0.content",
    "compliancePlan.hipaaEnabled",
    "compliancePlan.pciEnabled",
    "artifactPlan.transcriptPlan.enabled",
)
"""Any drift here is a hard failure, never a warning: these carry compliance or routing
meaning (doc 08 §8.1)."""


def deep_merge(remote: Any, local: Any) -> Any:
    """``local`` overlays ``remote``. Arrays are replaced wholesale, never merged."""
    if not isinstance(remote, dict) or not isinstance(local, dict):
        return local
    out = dict(remote)
    for k, v in local.items():
        prev = out.get(k)
        out[k] = deep_merge(prev, v) if isinstance(prev, dict) and isinstance(v, dict) else v
    return out


def normalise(value: Any, key: str = "") -> Any:
    """Strips volatile keys, sorts unordered arrays, canonicalises for comparison."""
    if isinstance(value, list):
        items = [normalise(v) for v in value]
        if key in SORT_ARRAYS_AT:
            return sorted(items, key=lambda x: json.dumps(x, sort_keys=True))
        return items
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k in sorted(value):
            if k in VOLATILE:
                continue
            v = value[k]
            if v is None:  # null ≡ absent
                continue
            out[k] = normalise(v, k)
        return out
    if isinstance(value, str):
        return value.rstrip()
    # JSON has one number type; Python has two. `1.0` from a config file and `1` echoed
    # back by Vapi are the same value, but compare unequal — which made the drift check
    # permanently red on the very first Python run. Collapse integral floats to int.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


@dataclass(frozen=True, slots=True)
class DriftEntry:
    path: str
    remote: Any
    desired: Any
    forbidden: bool


def _is_forbidden(path: str) -> bool:
    return any(path == f or path.startswith(f + ".") for f in FORBIDDEN_DRIFT)


def diff(remote: Any, desired: Any, base: str = "") -> list[DriftEntry]:
    """Reports only paths present in ``desired`` — i.e. paths we declare."""
    out: list[DriftEntry] = []

    if isinstance(remote, dict) and isinstance(desired, dict):
        for k in desired:
            out.extend(diff(remote.get(k), desired.get(k), f"{base}.{k}" if base else k))
        return out

    if json.dumps(remote, sort_keys=True) != json.dumps(desired, sort_keys=True):
        out.append(DriftEntry(base, remote, desired, _is_forbidden(base)))
    return out


def compute_drift(remote_raw: Any, local_raw: Any) -> list[DriftEntry]:
    return diff(normalise(remote_raw), normalise(deep_merge(remote_raw, local_raw)))
