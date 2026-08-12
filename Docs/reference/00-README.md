# 00 — Reference: what this folder is and when each file comes back

**Status:** Active — this README is maintained; everything it points at is frozen.
**Read before:** picking up work in a blocked area, or wondering where a document went.
**Last verified:** 2026-08-04 against the nine documents in this folder.

> **In one paragraph:** this folder holds the parts of the system that are **designed but not
> being built** — the database, Core API, the provider adapters, telephony, observability,
> infrastructure and the runbooks. Every document here has been rewritten for Python **before**
> being moved, so bringing one back into `plans/` is a `git mv` and nothing else. It deliberately
> holds nothing that is buildable today; that is [`Docs/plans/`](../plans/00-INDEX.md).

---

## 1. Why this folder exists

Roughly 3,200 lines of the original document set described work that could not start. It sat in
the same reading path as the two layers actually being built, which had two costs: `plans/` could
not be read in one sitting, and it was genuinely hard to tell which documents described the system
that exists versus the system that is coming.

Splitting them fixes both without losing anything. **Nothing here is abandoned or stale** — each
document was brought up to date with the Python decisions (ADR-0014 to ADR-0018) as part of the
move, precisely so that "unblocked" never means "and now rewrite the document too".

**Frozen means: not currently maintained against reality.** These documents were correct when
moved. As `plans/` evolves they will drift, so the `Last verified` date in each header is the one
to check before trusting a detail.

---

## 2. What unblocks each file

| Document | Unblocks when | Blocked by an *external* answer? |
|---|---|---|
| [data-model](data-model.md) | [08-roadmap](../plans/08-roadmap.md) task **C-02** | **No** — buildable today |
| [availability-engine](availability-engine.md) | task **C-03** | **No** — buildable today |
| [booking-write-path](booking-write-path.md) | task **C-04** (outbox); Phase D for the tracks | Partly — GATE-01, GATE-10 for Track B |
| [core-api](core-api.md) | task **C-05**, once **A-13** is answered | A-13 only — one captured signed request |
| [observability](observability.md) | Core API exists — most signals come from it | No |
| [infrastructure](infrastructure.md) | there is a running service to deploy (Phase C) | No |
| [provider-adapters](provider-adapters.md) | GATE-01, GATE-03, GATE-07, GATE-08, GATE-09 | **Yes** — except the fakes and resilient client (D-01, D-02), which are buildable today |
| [telephony](telephony.md) | GATE-09 (10DLC) and GATE-11 (RingCentral) | **Yes** |
| [runbooks](runbooks.md) | go-live | No, but most procedures need a running service |

> ⚠️ **Read that table carefully: five of these nine are not externally blocked at all.** They are
> frozen because Phase C has not started, not because anyone is waiting on Vagaro. Phase C is the
> entire remaining critical path and it can begin today — see
> [08-roadmap](../plans/08-roadmap.md) §4.
>
> Genuinely gated on someone else answering: **provider-adapters** and **telephony**, plus Track B
> inside booking-write-path. Everything else is waiting on us.

---

## 3. How to bring a document back

1. Confirm the unblocking condition in §2 has actually been met.
2. `git mv Docs/reference/<name>.md Docs/plans/NN-<name>.md`, taking the next free number.
3. Change `**Status:** Frozen — …` to `**Status:** Active` and refresh `**Last verified:**`.
4. Add it to the reading-order table in [00-INDEX](../plans/00-INDEX.md) §3 and to the old→new
   map in §4.
5. Re-run `make docs-lint`.

That is the whole procedure, and it is short by design — the expensive part (rewriting for Python)
was done up front, deliberately, so that unblocking a document is never a reason to delay starting
the work it describes.

---

## 4. Acceptance criteria

✅ **AC-RF.1** Every document in this folder carries `**Status:** Frozen` with a named unblocking
condition — never a bare "Frozen".
✅ **AC-RF.2** Every document here passes `make docs-lint`, exactly as `plans/` does. A frozen
document is still a maintained document.
✅ **AC-RF.3** No document here names the superseded stack except on a line explaining what
replaced it — the same bar `plans/` is held to.
✅ **AC-RF.4** The unblocking conditions in §2 match the gate and task IDs in
[09-open-decisions](../plans/09-open-decisions.md) and
[08-roadmap](../plans/08-roadmap.md).

## 5. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-RF.1** | Who checks whether an unblocking condition has been met? | Nothing watches §2. The weekly review in [09-open-decisions](../plans/09-open-decisions.md) §7 is the natural home for it, and it does not currently include the check. Without it, a document could sit frozen well after the thing blocking it cleared. | Engineering, weekly |
| **Q-RF.2** | How stale is too stale? | These are frozen, not maintained, so they drift as `plans/` moves. There is no policy for when a `Last verified` date is old enough to warrant a re-read before trusting the document. | Engineering |
