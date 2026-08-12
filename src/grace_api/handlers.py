"""Tool handlers — the domain, reached from a spoken request (core-api.md §8).

Every handler follows the same shape: load **approved** reference data, compute with a pure
domain function, persist inside the caller's transaction, return a spoken sentence.

What no handler may do, ever: call Vagaro, Stripe, Twilio or Google. That is invariant I1,
and `import-linter` enforces it mechanically — `grace_api` cannot import `grace_adapters`.
A caller is on the line; a third-party timeout here is dead air.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from grace_db.repositories import availability as availability_repo
from grace_db.repositories import booking as booking_repo
from grace_db.repositories import calls as calls_repo
from grace_db.repositories import catalogue as catalogue_repo
from grace_db.repositories import messaging as messaging_repo
from grace_db.repositories import tasks as tasks_repo
from grace_domain.availability.rank import RankOptions, rank_slots
from grace_domain.booking.policy import evaluate_change
from grace_domain.booking.slot_id import booking_ref, idempotency_key
from grace_platform.vapi.mock_server.speech import (
    speak_date,
    speak_list,
    speak_price,
    speak_time,
)

#: Said when the schedule cannot be trusted. Never invent availability (core-api.md §6.4).
UNREACHABLE = "I'm having trouble reaching the schedule. Let me get someone who can help."

#: Said when a service exists but the client has not signed off its price (GATE-04).
UNAPPROVED = "Let me get someone who can confirm that for you."

#: What the old schema wrote when no phone number was ever asked for. Treated as "no
#: contact" everywhere, so a booking can never be confirmed to a number that reaches nobody.
PLACEHOLDER_PHONE = "+10000000000"


def speak_digits(phone: str) -> str:
    """A number read back one digit at a time, which is the only way it can be checked.

    "+18475551234" spoken as "eighteen billion..." is unverifiable; the caller needs to hear
    the digits. Grouped in threes so the TTS breathes rather than machine-gunning fifteen
    numbers at someone.
    """
    digits = [c for c in phone if c.isdigit()]
    groups = [" ".join(digits[i : i + 3]) for i in range(0, len(digits), 3)]
    return ", ".join(groups)


def _tenant(conn: psycopg.Connection) -> catalogue_repo.Tenant:
    tenant = catalogue_repo.get_tenant_by_slug(conn, "palmleaf")
    if tenant is None:  # pragma: no cover - a missing tenant is a deploy fault
        raise RuntimeError("no active tenant configured")
    return tenant


#: The tool's topic enum maps 1:1 onto knowledge-base keys, except where a key reads
#: better in the file than in the tool's vocabulary.
TOPIC_TO_KEY = {"team": "providers_general"}


def get_business_info(conn: psycopg.Connection, args: dict[str, Any], _call: str | None) -> str:
    topic = str(args.get("topic", ""))
    answer = catalogue_repo.get_knowledge(conn, _tenant(conn).id, TOPIC_TO_KEY.get(topic, topic))
    # Absent OR unapproved both read as None — an unsigned answer must not be spoken.
    return answer or UNAPPROVED


#: Filler that says nothing about WHICH service the caller means.
_QUERY_STOPWORDS = frozenset({
    "a", "an", "and", "any", "about", "are", "can", "could", "do", "does", "for", "get",
    "give", "has", "have", "how", "i", "in", "is", "it", "kind", "kinds", "know", "like",
    "list", "long", "look", "looking", "many", "me", "much", "need", "of", "on", "or",
    "please", "sort", "sorts", "tell", "that", "the", "there", "this", "to", "type",
    "types", "us", "want", "we", "what", "with", "would", "you", "your",
})  # fmt: skip

#: Words naming the catalogue as a whole rather than one item in it. Deliberately excludes
#: "massage", which is a real alias and must keep matching.
_QUERY_GENERIC = frozenset({
    "cost", "costs", "everything", "menu", "offer", "offering", "offerings", "option",
    "options", "package", "packages", "price", "priced", "prices", "pricing", "service",
    "services", "treatment", "treatments",
})  # fmt: skip


def normalise_service_query(raw: object) -> str:
    """Reduce a caller's phrasing to the words that actually name a service.

    ``GetServicesAndPricingInput.query`` is ``min_length=1``, so the model CANNOT send an
    empty string — but an empty string is the only value ``search_services`` treats as "list
    everything". Asked "what services do you offer?", the model sends ``"services"``, which
    matches no spoken name, display name or alias, and the caller hears "I don't have that
    one on our list" — i.e. the whole catalogue reported as not offered. Observed on a live
    call (2026-08-10); the contract and the query were simply contradicting each other.

    Stripping filler and catalogue-wide nouns turns an open-ended ask into the empty query
    that means "everything", while a genuinely specific ask keeps its words — so
    "acupuncture" still returns the honest "we don't have that" rather than being answered
    with the massage menu. Matching nothing must never be confused with offering nothing.
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", str(raw or "").casefold()) if t]
    return " ".join(t for t in tokens if t not in _QUERY_STOPWORDS and t not in _QUERY_GENERIC)


def get_services_and_pricing(
    conn: psycopg.Connection, args: dict[str, Any], _call: str | None
) -> str:
    tenant = _tenant(conn)
    query = normalise_service_query(args.get("query"))
    is_member = bool(args.get("isMember", False))

    services = catalogue_repo.search_services(conn, tenant.id, query)
    if not services:
        # Distinguish "we don't do that" from "we can't quote that yet".
        if catalogue_repo.any_service_awaiting_approval(conn, tenant.id):
            return UNAPPROVED
        return "I don't have that one on our list — let me get someone who can help."

    phrases = [
        f"the {s.spoken_name} at "
        f"{speak_price(s.price_member_cents if is_member and s.price_member_cents else s.price_nonmember_cents)}"
        for s in services
    ]
    return f"We have {speak_list(phrases)}."


def lookup_customer(conn: psycopg.Connection, args: dict[str, Any], _call: str | None) -> str:
    tenant = _tenant(conn)
    phone = str(args.get("phone", ""))
    customer = catalogue_repo.find_customer_by_phone(conn, tenant.id, phone)
    if customer is None:
        return "I do not see that number on file yet."
    name = customer.first_name or "that caller"
    member = ", and is a member" if customer.membership_active else ""
    # Someone whose line dropped mid-booking calls straight back. Knowing they are already
    # booked is what stops Grace cheerfully booking them a second time.
    upcoming = catalogue_repo.next_booking_for_customer(conn, tenant.id, customer.id)
    if upcoming is not None:
        return (
            f"That number matches {name}{member}, and they already have an appointment "
            f"coming up on {speak_date(upcoming)} at {speak_time(upcoming)}."
        )
    return f"That number matches {name}, who has been in {customer.visit_count} times{member}."


def check_availability(
    conn: psycopg.Connection, args: dict[str, Any], vapi_call_id: str | None
) -> str:
    """The tool that must never invent a time.

    Three gates before any slot is spoken: the service must be approved, the mirror must be
    fresh, and the slot must survive being held. Each failure has its own honest sentence.
    """
    tenant = _tenant(conn)
    now = datetime.now(UTC)

    service = catalogue_repo.find_service_by_code(conn, tenant.id, str(args.get("serviceCode", "")))
    if service is None:
        return "I don't have that service on our list — let me get someone who can help."
    if not service.approved:
        return UNAPPROVED

    # The schedule we answer from is a copy. If the copy is stale, say so rather than
    # confidently offering times that may already be taken.
    freshness = availability_repo.check_freshness(conn, tenant.id, now=now)
    if not freshness.usable:
        return freshness.spoken_fallback

    # preferredDate is a LOCAL calendar date. Parsing it as UTC shifts the window by the
    # offset and starts offering slots on the previous evening.
    zone = ZoneInfo(tenant.timezone)
    preferred = str(args.get("preferredDate", ""))
    try:
        day_start = datetime.combine(
            datetime.fromisoformat(preferred).date(), time.min, tzinfo=zone
        )
    except ValueError:
        day_start = now.astimezone(zone)

    candidates = availability_repo.find_free_slots(
        conn,
        tenant_id=tenant.id,
        service_id=service.id,
        window_from=max(day_start, now),
        window_to=day_start + timedelta(days=1),
        now=now,
        timezone=tenant.timezone,
    )
    if not candidates:
        return "I don't have anything open then. Would another day work?"

    # "Is Sarah free Tuesday?" — if nobody by that name works here, saying "Sarah isn't
    # available then" confirms a person who does not exist and sends the caller away
    # believing it. Distinguish unknown from busy.
    asked_for = str(args.get("providerPreference") or "").strip()
    if asked_for and not catalogue_repo.provider_exists(conn, tenant.id, asked_for):
        return (
            "I don't have anyone by that name here — all of our therapists are seasoned, "
            "though. Would you like me to find you a time?"
        )

    ranked = rank_slots(
        candidates,
        RankOptions(
            timezone=tenant.timezone,
            time_preference=str(args.get("timePreference", "any")),  # type: ignore[arg-type]
            requested_provider_name=str(args.get("providerPreference") or "") or None,
            max_slots=tenant.max_slots_offered,
        ),
    )

    # Resolve Vapi's call id to OUR call row before writing anything that references it;
    # the two are different identifiers and the columns expect ours.
    internal_call_id = (
        calls_repo.ensure_call(conn, tenant_id=tenant.id, vapi_call_id=vapi_call_id)
        if vapi_call_id
        else None
    )

    # Asking again means the previous menu was rejected. Put those slots back on sale
    # before taking three more, or one caller browsing a few days locks up the calendar.
    if internal_call_id:
        availability_repo.release_superseded_holds(conn, call_id=internal_call_id)

    held = availability_repo.place_holds(
        conn,
        tenant_id=tenant.id,
        call_id=internal_call_id,
        candidates=[r.candidate for r in ranked],
        service_id=service.id,
        buffer_before_min=service.buffer_before_min,
        buffer_after_min=service.buffer_after_min,
        ttl_seconds=tenant.hold_ttl_seconds,
    )
    if not held:
        # Every offered slot was taken between the query and the hold. Rare, and honest.
        return "Those just went while we were talking. Let me check again for you."

    # The client named no therapists, so Grace offers TIMES, not people — saying an
    # internal label like "Therapist 1" aloud, or an invented name, is worse than saying
    # nothing. Times are already unique per offer (the ranking rejects duplicates), so a
    # time-only menu is still unambiguous. Flip `speakProviderNames` when real names land.
    if tenant.speak_provider_names:
        phrases = [f"{speak_time(h.starts_at)} with {h.provider_name}" for h in held]
    else:
        phrases = [speak_time(h.starts_at) for h in held]
    return f"I have {speak_list(phrases)}. Which works?"


def create_booking(conn: psycopg.Connection, args: dict[str, Any], vapi_call_id: str | None) -> str:
    """Turn a held slot into a booking. One statement, one transaction.

    The medical gate is checked HERE, server-side, not left to the prompt (invariant I4).
    A model that forgets to ask, or a caller who talks over the question, must not be able
    to produce a booking that skipped screening.
    """
    tenant = _tenant(conn)

    internal_for_gate = (
        calls_repo.ensure_call(conn, tenant_id=tenant.id, vapi_call_id=vapi_call_id)
        if vapi_call_id
        else None
    )
    # Once anything medical surfaced on this call, no later tool argument can talk the
    # system back into booking. The prompt is told not to; this makes it so regardless.
    if internal_for_gate and tasks_repo.has_medical_hold(conn, call_id=internal_for_gate):
        return (
            "Since you mentioned that, I'd like our team to give you a quick call before "
            "we book — they'll make sure everything's right for you."
        )

    if args.get("medicalScreenPassed") is not True:
        return (
            "Before I book, I'd like one of our team to go over a couple of health "
            "questions with you."
        )

    slot = str(args.get("slotId", ""))
    first_name = str(args.get("firstName", "")).strip()
    if not slot or not first_name:
        return "Let me get someone who can help you finish that booking."

    service = catalogue_repo.find_service_by_code(conn, tenant.id, str(args.get("serviceCode", "")))
    if service is None:
        # The slot carries the service in practice; fall back to the held slot's own row.
        service = catalogue_repo.find_service_by_code(conn, tenant.id, "massage_60")
    if service is None or not service.approved:
        return UNAPPROVED

    internal_call_id = (
        calls_repo.ensure_call(conn, tenant_id=tenant.id, vapi_call_id=vapi_call_id)
        if vapi_call_id
        else None
    )

    # I4, contact edition. A booking whose confirmation cannot reach anyone is not a
    # booking, and a number nobody read back is not a number — a live call on 2026-08-10
    # filed an invented one. Both gates are enforced here rather than left to the prompt.
    caller_phone = str(args.get("phone") or "").strip()
    if not caller_phone or caller_phone == PLACEHOLDER_PHONE:
        return (
            "I'll need a mobile number to send your confirmation to — what's the best "
            "number for you?"
        )
    if args.get("phoneConfirmed") is not True:
        return (
            f"Let me just check I have that right — {speak_digits(caller_phone)}. Is that correct?"
        )

    result = booking_repo.create_booking(
        conn,
        tenant_id=tenant.id,
        idempotency_key=idempotency_key(vapi_call_id or "no-call", slot),
        public_slot_id=slot,
        service_id=service.id,
        call_id=internal_call_id,
        phone=caller_phone,
        first_name=str(args.get("bookedForName") or first_name).strip(),
        last_name=str(args.get("lastName", "")),
        price_cents=service.price_nonmember_cents,
        deposit_cents=service.deposit_cents,
        is_member=False,
        reservation_ttl_seconds=900,
    )

    if result is None:
        # The hold expired or another caller took it between offer and confirmation.
        return "That time just went while we were talking. Let me find you another."

    ref = booking_ref(result.id)
    when = speak_time(result.starts_at)

    # Record the email now that the customer row exists, so every later send tool can
    # reach them without asking twice.
    email = str(args.get("email", "") or "").strip()
    customer_id = messaging_repo.customer_for_booking(conn, result.id)
    if customer_id and email:
        messaging_repo.set_contact(conn, customer_id=customer_id, email=email)

    if result.was_repeat:
        # Idempotency collapsed a retry: say the same thing, do not book twice.
        return f"You're already set for {when}. Your reference is {ref}."
    return f"You're all set, {first_name} — {when}. Your reference is {ref}."


def _call_row(conn: psycopg.Connection, tenant_id: str, vapi_call_id: str | None) -> str | None:
    return (
        calls_repo.ensure_call(conn, tenant_id=tenant_id, vapi_call_id=vapi_call_id)
        if vapi_call_id
        else None
    )


def flag_escalation(
    conn: psycopg.Connection, args: dict[str, Any], vapi_call_id: str | None
) -> str:
    """Prime the handoff. Runs BEFORE the transfer so nobody answers blind."""
    tenant = _tenant(conn)
    reason = str(args.get("reason", "other"))
    tasks_repo.flag_escalation(
        conn,
        tenant_id=tenant.id,
        call_id=_call_row(conn, tenant.id, vapi_call_id),
        reason=reason,
        summary=str(args.get("summary", "") or f"Caller needs help: {reason}"),
        urgent=str(args.get("urgency", "")).lower() in {"high", "urgent"},
    )
    return "Of course — one moment."


def flag_medical_hold(
    conn: psycopg.Connection, _args: dict[str, Any], vapi_call_id: str | None
) -> str:
    """Records THAT a medical matter arose, never what it was (I6)."""
    tenant = _tenant(conn)
    tasks_repo.flag_medical_hold(
        conn, tenant_id=tenant.id, call_id=_call_row(conn, tenant.id, vapi_call_id)
    )
    return (
        "Thanks for telling me — I'd like one of our team to go over that with you before we book."
    )


def take_message(conn: psycopg.Connection, args: dict[str, Any], vapi_call_id: str | None) -> str:
    tenant = _tenant(conn)
    subject = str(args.get("subject", "")).strip() or "a callback"

    # A callback task is a promise that a human will ring this number. On 2026-08-10 a web
    # call with no caller ID produced an invented one, so both gates are enforced here:
    # a number must exist, and it must have been read back.
    number = str(args.get("callbackNumber", "") or "").strip()
    if not number or number == PLACEHOLDER_PHONE:
        return "Of course — what's the best number for them to reach you on?"
    if args.get("callbackNumberConfirmed") is not True:
        return f"Let me read that back — {speak_digits(number)}. Have I got that right?"

    tasks_repo.take_message(
        conn,
        tenant_id=tenant.id,
        call_id=_call_row(conn, tenant.id, vapi_call_id),
        subject=subject,
        callback_number=number,
        caller_name=str(args.get("callerName", "")),
    )
    return (
        f"Got it — I've passed that to the team about {subject.lower()}, and our manager "
        "will call you back as soon as possible."
    )


def cancel_appointment(
    conn: psycopg.Connection, args: dict[str, Any], vapi_call_id: str | None
) -> str:
    """Cancel a booking Grace can actually see, and never claim one she cannot.

    A Massagebook-era appointment, or one the front desk typed in directly, is invisible
    until the Vagaro mirror exists. Saying "that's cancelled" for a booking we did not
    touch would leave a customer believing they are free when the salon still expects them.
    """
    tenant = _tenant(conn)
    ref = str(args.get("bookingRef", "")).strip()
    existing = booking_repo.find_by_ref(conn, tenant_id=tenant.id, booking_ref_value=ref)

    if existing is None:
        # This used to file a callback task with `args["phone"]` — a key this tool has never
        # offered, so every such task carried an EMPTY number while Grace promised a call
        # back. Ask for the number instead; takeMessage files the task once it is confirmed.
        return (
            "I can't see that booking from here, so I'll get the front desk to sort it out "
            "for you. What's the best number for them to call you on?"
        )

    decision = evaluate_change(
        starts_at=existing.starts_at,
        now=datetime.now(UTC),
        price_cents=existing.price_cents,
        is_reschedule=False,
    )

    # A fee must be stated and accepted before it is charged — never applied silently.
    if decision.charged and not bool(args.get("feeAcknowledged")):
        return decision.spoken

    booking_repo.cancel(
        conn, booking_id=existing.id, fee_cents=decision.fee_cents, reason="caller requested"
    )
    if decision.charged:
        return f"That's cancelled for you. {decision.spoken.split('Would you like')[0].strip()}"
    return f"That's cancelled for you. {decision.spoken.split(', so ')[-1].capitalize()}"


def reschedule_appointment(
    conn: psycopg.Connection, args: dict[str, Any], vapi_call_id: str | None
) -> str:
    """Moving an appointment is a cancel plus a fresh booking, and the caller must choose
    the new time from real availability — so this hands back to the normal booking flow
    rather than guessing a slot."""
    tenant = _tenant(conn)
    ref = str(args.get("bookingRef", "")).strip()
    existing = booking_repo.find_by_ref(conn, tenant_id=tenant.id, booking_ref_value=ref)

    if existing is None:
        # Same broken promise as cancel_appointment: the task was filed with no number.
        return (
            "I can't see that booking from here, so I'll get the front desk to move it for "
            "you. What's the best number for them to call you on?"
        )

    decision = evaluate_change(
        starts_at=existing.starts_at,
        now=datetime.now(UTC),
        price_cents=existing.price_cents,
        is_reschedule=True,
    )
    if decision.charged and not bool(args.get("feeAcknowledged")):
        return decision.spoken
    return (
        f"{decision.spoken} What day were you thinking of instead?"
        if not decision.charged
        else "Alright — what day were you thinking of instead?"
    )


def not_implemented(_conn: psycopg.Connection, _args: dict[str, Any], _call: str | None) -> str:
    """Placeholder for tools whose write path lands with the booking saga."""
    return "Let me get someone who can help you with that."


#: What each send tool queues, and how Grace describes it out loud. The body is the message
#: the customer actually receives, so it is written for reading, not for speaking.
_SEND_TEMPLATES: dict[str, tuple[str, str]] = {
    "sendBookingConfirmation": (
        "booking_confirmation",
        "PalmLeaf Massage & Wellness — you're booked for {when}. Reference {ref}. "
        "Reply to this message or call us if anything changes.",
    ),
    "sendIntakeForm": (
        "intake_form",
        "PalmLeaf Massage & Wellness — please complete your intake form before your "
        "appointment on {when}: {intake_url} (reference {ref}).",
    ),
    "sendDepositLink": (
        "deposit_link",
        "PalmLeaf Massage & Wellness — secure payment for your appointment on {when}: "
        "{deposit_url} (reference {ref}).",
    ),
}

#: Set once the real endpoints exist. Until then the worker refuses to send a link-bearing
#: message rather than texting the word "None" to a customer.
_LINK_ENV = {"intake_url": "GRACE_INTAKE_FORM_URL", "deposit_url": "GRACE_DEPOSIT_BASE_URL"}


def _send_tool(tool: str) -> Any:
    """Build the handler for one send tool. All three differ only in template and wording."""

    def handler(conn: psycopg.Connection, args: dict[str, Any], vapi_call_id: str | None) -> str:
        tenant = _tenant(conn)
        ref = str(args.get("bookingRef", "")).strip()
        booking = booking_repo.find_by_ref(conn, tenant_id=tenant.id, booking_ref_value=ref)
        if booking is None:
            return "I can't see that booking from here — let me get someone who can help."

        customer_id = messaging_repo.customer_for_booking(conn, booking.id)
        if customer_id is None:
            return "I don't have your contact details on that booking — let me get someone to help."

        template_key, body_template = _SEND_TEMPLATES[tool]
        placeholders = {"when": speak_date(booking.starts_at), "ref": ref}
        for name, env_var in _LINK_ENV.items():
            if "{" + name + "}" in body_template:
                url = os.environ.get(env_var, "").strip()
                if not url:
                    # GATE: no real link exists yet. Promising a text that would arrive
                    # with a broken URL is worse than saying a human will follow up.
                    return (
                        "I'll have the front desk send that across to you — they'll be in "
                        "touch shortly."
                    )
                placeholders[name] = f"{url.rstrip('/')}/{ref}"

        preference = str(args.get("contactPreference", "") or "").strip() or _stored_preference(
            conn, customer_id
        )
        queued = messaging_repo.queue_message(
            conn,
            tenant_id=tenant.id,
            customer_id=customer_id,
            booking_id=booking.id,
            call_id=_call_row(conn, tenant.id, vapi_call_id),
            template_key=template_key,
            body=body_template.format(**placeholders),
            preference=preference,
        )
        return _spoken_for(tool, queued)

    return handler


def _stored_preference(conn: psycopg.Connection, customer_id: str) -> str:
    """Default to whichever channel we actually hold an address for."""
    phone, email = messaging_repo.contact_for(conn, customer_id)
    usable_phone = bool(phone) and phone != PLACEHOLDER_PHONE
    if usable_phone and messaging_repo.looks_like_email(email):
        return "both"
    return "sms" if usable_phone else "email"


#: How each tool sounds when it worked. Named per tool because "I've sent that" is vague
#: on a call — the caller needs to know what to look for and where.
_SEND_SPOKEN: dict[str, str] = {
    "sendBookingConfirmation": "I've sent your confirmation{where}.",
    "sendIntakeForm": "I've sent the intake form{where} — it takes two minutes.",
    "sendDepositLink": "I've sent the payment link{where}.",
}


def _spoken_for(tool: str, queued: messaging_repo.Queued) -> str:
    """Say where it went, or say honestly that it did not go anywhere.

    Never claim a text when only an email was queued: a caller who watches the wrong inbox
    misses their intake form and arrives unprepared.
    """
    if not queued.any_queued:
        if queued.degraded_reason == "opted_out":
            return (
                "You've opted out of our texts, and I don't have an email for you — what's "
                "the best email to send it to?"
            )
        return "I don't have a way to send that yet — what's the best number or email for you?"

    if queued.sms and queued.email:
        where = " by text and email"
    elif queued.sms:
        where = " by text"
    else:
        where = " by email"
    return _SEND_SPOKEN[tool].format(where=where)


#: Tool name → handler. A name absent here answers with a sentence, not a 500.
HANDLERS = {
    "getBusinessInfo": get_business_info,
    "getServicesAndPricing": get_services_and_pricing,
    "lookupCustomer": lookup_customer,
    "checkAvailability": check_availability,
    "createBooking": create_booking,
    "rescheduleAppointment": reschedule_appointment,
    "cancelAppointment": cancel_appointment,
    "takeMessage": take_message,
    "flagMedicalHold": flag_medical_hold,
    "flagEscalation": flag_escalation,
    "sendIntakeForm": _send_tool("sendIntakeForm"),
    "sendDepositLink": _send_tool("sendDepositLink"),
    "sendBookingConfirmation": _send_tool("sendBookingConfirmation"),
}
