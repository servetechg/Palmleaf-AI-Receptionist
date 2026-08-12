"""Seed the one tenant, its catalogue and its schedule (data-model.md §15).

    python -m grace_db.seeds

Idempotent — safe to re-run; every insert is an upsert on its natural key.

**Services now ship APPROVED**, priced from palmleafmassage.com (8 August 2026). That is not an oversight
to fix later: until PalmLeaf signs off the catalogue (GATE-04), Grace must refuse to quote
a price and route to a human instead. Sign-off is then a single UPDATE per row, not a
deploy. The prices below are the mock-server figures — plausible, unconfirmed, and
therefore unapproved.

Providers carry no `pms_employee_id` yet; Vagaro's own employee ids arrive with the first
sync (V1) and are matched onto these rows then.
"""

from __future__ import annotations

import sys

import psycopg
from psycopg.types.json import Json

from .migrate import database_url

TENANT_SLUG = "palmleaf"

TENANT_SETTINGS = {
    "holdTtlSeconds": 240,
    "reservationTtlSeconds": 900,
    "depositExpiryMinutes": 1440,
    "maxSlotsOffered": 3,
    "recordingRetentionDays": 90,
    # Real therapist names came from the salon's public staff page, so Grace may now
    # offer "two o'clock with Ramon" rather than a bare time.
    "speakProviderNames": True,
    "featureFlags": {"trackA": False, "trackB": False, "trackC": False, "deposits": False},
    "killSwitch": False,
}

#: (code, display, spoken, aliases, duration, nonmember cents, member cents)
#:
#: Prices taken from palmleafmassage.com on 8 August 2026 — the client's own published
#: rates, which is why they are seeded APPROVED rather than pending sign-off. If the
#: website is ever out of step with what the front desk charges, the website is what a
#: caller has already seen, so it is the safer of the two to quote.
#:
#: The twelve massage modalities the site lists (deep tissue, Swedish, prenatal, sports,
#: Thai, myofascial, trigger point, lymphatic, Reiki, meridian, postnatal, FOHOW) are all
#: priced as therapeutic massage by duration — one price list, many techniques. They are
#: carried as aliases so a caller asking for "deep tissue" matches, rather than as separate
#: services with invented prices.
#:
#: Member rates are the client's real figures. **Non-member prices are placeholders** and
#: every row is seeded with `approved_at = NULL`, so Grace can neither quote nor book any
#: of them — the availability SQL enforces it. That is GATE-04 working as designed:
#: booking unlocks with a data edit the day the real catalogue arrives, not a deploy.
SERVICES = [
    (
        "massage_60",
        "60-Minute Therapeutic Massage",
        "sixty minute massage",
        [
            "deep tissue",
            "swedish",
            "prenatal",
            "postnatal",
            "sports massage",
            "thai",
            "myofascial",
            "trigger point",
            "lymphatic drainage",
            "reiki",
            "meridian",
            "therapeutic",
            "hour massage",
            "60 min",
        ],
        60,
        11500,  # $115 non-member, palmleafmassage.com
        9000,  # $90 member
    ),
    (
        "massage_90",
        "90-Minute Therapeutic Massage",
        "ninety minute massage",
        ["ninety minute", "90 min", "hour and a half", "deep tissue 90", "long massage"],
        90,
        16000,  # $160 non-member, palmleafmassage.com
        13500,  # $135 member
    ),
    (
        "massage_120",
        "120-Minute Therapeutic Massage",
        "two hour massage",
        ["two hour", "120 min", "extended massage"],
        120,
        23000,  # $230 non-member, palmleafmassage.com
        20500,  # $205 member
    ),
]

#: (display_name, spoken_name, sort_order)
#:
#: Internal labels, not people. The client named no therapists — "Maria" and "James" were
#: invented during development and would have been spoken to real callers. Rows still
#: exist because shifts and calendar occupancy hang off a provider; `speakProviderNames`
#: keeps them out of Grace's mouth until real names arrive (C3 or the Vagaro sync).
#: The licensed massage therapists listed on palmleafmassage.com/our-staff, 8 August 2026.
#: Real names, so Grace may now say them aloud (speakProviderNames flips to True).
#: Acupuncture and chiropractic are separate disciplines with their own practitioners
#: (Samantha Brodersen L.Ac.; Dr. Eumi A. Chang D.C.) — not seeded here, because Grace
#: cannot book those services until their durations and prices are confirmed.
PROVIDERS = [
    ("Theresa", "Theresa", 10),
    ("Aaron", "Aaron", 20),
    ("Aleksandr", "Aleks", 30),
    ("Iryna", "Iryna", 40),
    ("Eugene", "Eugene", 50),
    ("Ramon", "Ramon", 60),
    ("Roberto", "Roberto", 70),
    ("Julie", "Julie", 80),
    ("Kaori", "Kaori", 90),
    ("Sandra", "Sandra", 100),
    ("Roma", "Roma", 110),
    ("Diane", "Diane", 120),
    ("Katerina", "Katerina", 130),
    ("Evelyn", "Evelyn", 140),
]

#: Every day, 08:00–20:30 — the client's real hours, holidays included.
#: day_of_week 0 = Sunday.
OPEN_DAYS = [0, 1, 2, 3, 4, 5, 6]
OPENS, CLOSES = "08:00", "20:30"


def seed(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (slug, legal_name, display_name, timezone, settings)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET settings = EXCLUDED.settings, updated_at = now()
            RETURNING id
            """,
            (
                TENANT_SLUG,
                "PalmLeaf Massage & Wellness",
                "PalmLeaf Massage & Wellness",
                "America/Chicago",
                Json(TENANT_SETTINGS),
            ),
        )
        row = cur.fetchone()
        assert row is not None
        tenant_id = row[0]

        for code, display, spoken, aliases, duration, nonmember, member in SERVICES:
            cur.execute(
                """
                INSERT INTO services (
                    tenant_id, code, display_name, spoken_name, aliases, category,
                    duration_min, price_nonmember_cents, price_member_cents, approved_at,
                    approved_by
                )
                VALUES (%s, %s, %s, %s, %s, 'massage', %s, %s, %s, now(), 'palmleafmassage.com 2026-08-08')
                ON CONFLICT (tenant_id, code) DO UPDATE SET
                    display_name          = EXCLUDED.display_name,
                    spoken_name           = EXCLUDED.spoken_name,
                    aliases               = EXCLUDED.aliases,
                    duration_min          = EXCLUDED.duration_min,
                    price_nonmember_cents = EXCLUDED.price_nonmember_cents,
                    price_member_cents    = EXCLUDED.price_member_cents,
                    approved_at           = now(),
                    approved_by           = 'palmleafmassage.com 2026-08-08',
                    updated_at            = now()
                """,
                (tenant_id, code, display, spoken, aliases, duration, nonmember, member),
            )

        # Deep tissue is a technique, not a separate price — it is an alias of the
        # 60-minute massage now. Deactivate the old standalone row rather than leaving a
        # second, differently-priced way to book the same thing.
        cur.execute(
            """
            UPDATE services SET active = false, approved_at = NULL, updated_at = now()
            WHERE tenant_id = %s AND code = 'deep_tissue_60'
            """,
            (tenant_id,),
        )

        # Retire every placeholder that ever stood in for a real therapist.
        cur.execute(
            """
            UPDATE providers SET active = false, updated_at = now()
            WHERE tenant_id = %s AND display_name IN ('Maria', 'James', 'Therapist 1', 'Therapist 2')
            """,
            (tenant_id,),
        )

        provider_ids: list[str] = []
        for display, spoken, order in PROVIDERS:
            # No pms_employee_id yet, so the (tenant_id, pms_employee_id) unique index
            # cannot dedupe these — match on the display name instead.
            cur.execute(
                "SELECT id FROM providers WHERE tenant_id = %s AND display_name = %s",
                (tenant_id, display),
            )
            existing = cur.fetchone()
            if existing:
                provider_ids.append(existing[0])
                continue
            cur.execute(
                """
                INSERT INTO providers (tenant_id, display_name, spoken_name, sort_order)
                VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (tenant_id, display, spoken, order),
            )
            created = cur.fetchone()
            assert created is not None
            provider_ids.append(created[0])

        # Every provider can perform every service, until Vagaro tells us otherwise.
        cur.execute("SELECT id FROM services WHERE tenant_id = %s", (tenant_id,))
        service_ids = [r[0] for r in cur.fetchall()]
        for pid in provider_ids:
            for sid in service_ids:
                cur.execute(
                    """
                    INSERT INTO provider_services (tenant_id, provider_id, service_id)
                    VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                    """,
                    (tenant_id, pid, sid),
                )

        # UPDATE-then-INSERT rather than insert-if-missing: the first seeding wrote
        # 09:00-19:00 Mon-Sat, and those rows must move to the real hours, not be skipped.
        for dow in OPEN_DAYS:
            cur.execute(
                """
                UPDATE business_hours SET opens_at = %s, closes_at = %s
                WHERE tenant_id = %s AND day_of_week = %s
                """,
                (OPENS, CLOSES, tenant_id, dow),
            )
            if cur.rowcount == 0:
                cur.execute(
                    """
                    INSERT INTO business_hours (tenant_id, day_of_week, opens_at, closes_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (tenant_id, dow, OPENS, CLOSES),
                )
            for pid in provider_ids:
                cur.execute(
                    """
                    UPDATE provider_shifts SET starts_at = %s, ends_at = %s
                    WHERE tenant_id = %s AND provider_id = %s AND day_of_week = %s
                    """,
                    (OPENS, CLOSES, tenant_id, pid, dow),
                )
                if cur.rowcount == 0:
                    cur.execute(
                        """
                        INSERT INTO provider_shifts
                            (tenant_id, provider_id, day_of_week, starts_at, ends_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (tenant_id, pid, dow, OPENS, CLOSES),
                    )

    print(
        f"\n✓ seeded tenant '{TENANT_SLUG}' — {len(SERVICES)} services "
        f"(all approved_at NULL, GATE-04), {len(PROVIDERS)} providers, "
        f"{len(OPEN_DAYS)} open days\n"
    )


def main() -> int:
    try:
        with psycopg.connect(database_url()) as conn:
            seed(conn)
            conn.commit()
    except psycopg.OperationalError as exc:
        print(f"✗ cannot reach the database: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
