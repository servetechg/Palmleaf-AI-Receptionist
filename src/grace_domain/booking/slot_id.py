"""Public slot identifiers — the ids Grace is allowed to say out loud.

availability-engine.md §5.1, reconciled with `grace_contracts.tools.shared`: the committed
contract is `hold-XXX` (the engine doc's `'h' + base32` form is the outlier, and two of the
three specifications agree on this one).

**Never expose a UUID to a language model.** It will mangle it, and a mangled id is a
booking against the wrong slot. Short, unambiguous, and spoken-safe: Crockford base32 drops
I, L, O and U precisely because they are misheard and mistyped.
"""

from __future__ import annotations

import hashlib

#: Crockford base32 without I, L, O, U — the characters that get confused when spoken.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIX = "hold-"
LENGTH = 3


def public_slot_id(occupancy_id: str) -> str:
    """Deterministic short id for an occupancy row. Same input, same id, always."""
    digest = hashlib.blake2b(occupancy_id.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    chars = []
    for _ in range(LENGTH):
        chars.append(ALPHABET[value % len(ALPHABET)])
        value //= len(ALPHABET)
    return PREFIX + "".join(chars)


def booking_ref(booking_id: str) -> str:
    """`bk-XXXX`, matching the BookingRef contract in grace_contracts.tools.shared."""
    digest = hashlib.blake2b(booking_id.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    chars = []
    for _ in range(4):
        chars.append(ALPHABET[value % len(ALPHABET)])
        value //= len(ALPHABET)
    return "bk-" + "".join(chars)


def idempotency_key(call_id: str, slot_public_id: str) -> str:
    """`{callId}:{slotPublicId}` — invariant I3's database-level key.

    Keyed on the SLOT, not the tool-call id, because it must also collapse the case where
    the model calls createBooking twice in one conversation for the same slot. A Vapi
    retry and a chatty model are the same problem to the database.
    """
    return f"{call_id}:{slot_public_id}"
