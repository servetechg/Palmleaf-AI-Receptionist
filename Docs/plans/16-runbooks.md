# 16 — Operational Runbooks

**Every alert in [12](12-observability-and-slo.md) §6 links to a section here.** Written to be followed
at 2am by someone who did not write the code.

**Standing rule for every incident:** if callers are affected and the cause is not obvious within
5 minutes, **pull the carrier kill switch (§1) first, then debug.** A phone line routing to staff is a
minor inconvenience; a phone line mishandling customers is a business problem.

---

## 1. THE KILL SWITCH — do this first when in doubt

### Layer 1 — carrier (works even if all our systems are down)

1. Log in to RingCentral admin (credentials in the shared vault; the manager also has them).
2. **Phone System → Auto-Receptionist → Call Handling** (or the forwarding rule for 847.961.4800).
3. Disable the forwarding rule to the Twilio DID.
4. Save. Place a test call from a mobile — confirm it rings the front desk.
5. Post in `#palmleaf-alerts`: what you did, when, why.

**Target: under 60 seconds. Drilled with the manager in Phase D (AC-10.5).**
Screenshots of every click: `docs/runbooks/killswitch-screenshots/`.

### Layer 2 — application

```bash
curl -X POST https://api.grace.<domain>/internal/tenants/palmleaf/kill-switch \
  -H "Authorization: Bearer $GRACE_INTERNAL_API_TOKEN" -d '{"enabled":true}'
```
Or the Slack command `/grace-kill palmleaf` (WF-14). Grace then transfers every caller on the first
tool call. Use this when the system is up but behaving wrongly.

**Re-enabling:** only after the cause is understood and a test call passes. Announce it.

---

## 2. Core API down

**Alert:** `/healthz` failing 2 consecutive probes. **Sev:** P1.

1. Check the load balancer — is it one instance or both? One instance: it should have been removed from
   rotation; verify and let it restart.
2. Both down → **kill switch layer 1 immediately.**
3. `docker compose ps` / ECS service events. Look for OOM, crash loop, failed health check.
4. Logs: `level=error` in the last 15 minutes. Common causes: bad deploy, DB unreachable, migration
   mismatch, config error after a secret rotation.
5. Bad deploy → roll back to the previous image tag (§14 §6.2). ~2 minutes.
6. DB unreachable → §10.
7. Once healthy: test call, then restore forwarding, then post a summary.

---

## 3. Tool error rate > 2%

**Sev:** P1.

1. Dashboard 5.1 → which tool, which error code.
2. `validation_error` spike → the model is sending malformed arguments. Usually follows a prompt or
   schema change. Check the last `platform/vapi` deploy. Roll back the assistant if so.
3. `internal` spike → check DB pool saturation, then adapter circuit states, then recent deploys.
4. `slot_taken` spike → not an error. Real contention, or the sweeper has stopped (§7).
5. `service_unapproved` / `policy_unapproved` → the client changed data, or a seed regressed. Check
   `approved_at` values. Grace is degrading correctly; fix the data.

---

## 4. Latency or deadline breach

**Alert:** tool p95 > 1.5s, or deadline rate > 5%. **Sev:** P1.

Diagnose in this order — it is almost always #1 or #2:

1. **Database.** `grace_db_pool_waiting > 0`? Pool saturation. Check for a long-running query
   (`pg_stat_activity` where `state='active'` and `now()-query_start > '1s'`). Kill it if it is a
   report or an ad-hoc query.
2. **Query plan regression.** Run `EXPLAIN ANALYZE` on the free-slot query with production-shaped
   parameters. Expect a GiST anti-join. Seq scan → `ANALYZE calendar_occupancy`; check whether an index
   was dropped by a migration.
3. **Occupancy table bloat.** Millions of non-ACTIVE rows still slow planning. Archive per §06 §11.
4. **Redis** slow or down → tenant cache misses hit the DB every request.
5. **Instance CPU** saturated → scale out (§14 §7).
6. Only then look at Vapi/network.

**If it cannot be fixed in 15 minutes:** kill switch layer 1. Slow Grace is worse than no Grace.

---

## 5. Webhook authentication failures

**Alert:** >10 in 5 min. **Sev:** P1.

1. All from one source? Check whether a secret was rotated on one side only — the most common cause.
2. Verify the current and previous secret are both in the verifier (24h dual-accept window, §11 §9).
3. Random sources → probing. Confirm the WAF/rate limit is active; no action beyond monitoring, since
   requests are rejected.
4. **Never** disable signature verification to "get things working." That is the failure mode this
   alert exists to prevent.

---

## 6. Outbox lag or dead letters

**Alert:** lag >60s (P2) or any DEAD row (P1).

```sql
-- what is stuck?
SELECT event_type, status, count(*), min(created_at), max(last_error)
FROM outbox_events WHERE status IN ('PENDING','FAILED','DEAD','IN_FLIGHT')
GROUP BY 1,2 ORDER BY 3 DESC;
```

1. `IN_FLIGHT` with stale `locked_at` → a worker died. The reclaimer handles it in 5 minutes; verify.
2. All `FAILED` on one `event_type` → that adapter is broken. Check its circuit state and `last_error`.
3. `DEAD` rows → **read the payload and decide deliberately.** Never bulk-replay blindly; some events
   have already partially succeeded.
   ```sql
   UPDATE outbox_events SET status='PENDING', attempts=0, available_at=now()
   WHERE id = '<specific-id>';
   ```
4. Any `DEAD` row involving a booking → check whether the customer was told something we have not
   delivered. If so, that is a phone call from a human, today.
5. Workers down entirely → nothing is lost (ADR-0005). Restart, watch the backlog drain, verify no
   duplicates.

---

## 7. Booking stuck, or `NEEDS_STAFF` piling up

**Alert:** `WRITING_TO_PMS` >2h, or `NEEDS_STAFF` >4h in business hours. **Sev:** P2.

```sql
SELECT id, state, state_reason, track_b_status, track_b_attempts, track_b_last_error,
       starts_at, created_at
FROM bookings WHERE state IN ('WRITING_TO_PMS','NEEDS_STAFF') ORDER BY starts_at;
```

1. **Confirm the customer's slot is still held:**
   ```sql
   SELECT state, kind, expires_at FROM calendar_occupancy WHERE booking_id = '<id>';
   ```
   If it is not `ACTIVE` — that is a P1. A customer believes they are booked and they are not. Recreate
   the occupancy, then call them.
2. Many at once → the automation broke. Check the Track B canary (§11) and the write-path adapter.
3. Each open task: a human completes the booking in the PMS, then resolves the task, which sets
   `pms_appointment_id` and transitions to `SYNCED`.

---

## 8. PMS/Grace collision — someone booked over us

**Alert:** occupancy conflict during mirror sync. **Sev:** P1.

This means the front desk (or a customer on the public widget) booked a slot Grace had reserved.

1. Find both records — the staff task payload contains them.
2. **Call the affected customer.** Do not let them arrive to a double-booked room. This is the runbook's
   only mandatory human action.
3. Rebook whoever is easier to move, with an apology and, at the client's discretion, a goodwill gesture.
4. Root cause: is Massagebook still live alongside Vagaro (design brief §15 item 9)? Is the mirror lagging
   (§10)? Is a provider booking directly into their Google Calendar?
5. Repeated occurrences → the dual-system cutover has not happened. Escalate commercially, not technically.

---

## 9. Adapter circuit open

**Alert:** any adapter open >2 min. **Sev:** P2.

1. Which adapter? Check `last_error` on recent outbox rows and the adapter's error metrics.
2. Third-party outage → confirm on their status page. Post it in `#palmleaf-alerts` so nobody
   re-diagnoses it. Work queues and drains automatically when the breaker closes.
3. Auth failure (401/403) → a credential expired or was revoked. Rotate/reissue.
4. Rate limited (429) → lower the token bucket for that adapter and consider whether a poller is too
   aggressive.
5. **Calls keep working throughout.** Only the cold path is affected. Do not kill the phone line for this.

---

## 10. Mirror lag or drift

**Alert:** lag >15 min, or drift >5 records. **Sev:** P2.

1. `SELECT * FROM sync_state;` — which source, when did it last succeed, what is the error?
2. Webhooks stopped → check `inbound_webhooks` for recent rows. None → the PMS webhook registration may
   have been disabled. Re-register (their settings UI, desktop only).
3. Poller failing → adapter/circuit issue (§9).
4. Google watch channel expired → check the renewal cron; re-establish the channel manually if needed.
5. Force a resync:
   ```bash
   curl -X POST .../internal/sync/reconcile -d '{"tenant":"palmleaf","from":"-7d","to":"+60d"}'
   ```
6. **While drifting, availability may be wrong.** If drift is large or the cause is unknown, consider
   restricting Grace to information-only (kill switch layer 2) rather than booking against a stale mirror.

---

## 11. Track B failing / canary red

**Alert:** failure rate >10% (P2), canary red (P1).

A red canary almost always means **the PMS changed their booking UI.**

1. Open the latest failure screenshots (object storage, 7-day retention). They usually show it
   immediately — a new consent checkbox, a moved button, a new required field.
2. Update `selectors.ts`, bump the version stamp, add a test, deploy.
3. While broken: bookings land in `NEEDS_STAFF` and staff complete them. **Slots stay held.** Tell the
   client the same day — this is a known, budgeted maintenance event (design brief §16), not a surprise.
4. Log the hours spent. That number is the commercial argument for native API access.

---

## 12. Medical hold flagged

**Sev:** P2 (staff notification, not on-call).

1. Staff sees the task: "Caller disclosed a medical matter — please discuss before booking."
2. **Do not look for detail in the transcript. It is not there by design and must not be added.**
3. Staff calls the customer back, handles the conversation, books manually if appropriate.
4. Resolve the task with an outcome — never with clinical notes.

---

## 13. Card number detected in a transcript

**Sev:** P1. Counter `grace_card_number_detected_total` should never move.

1. The redactor caught it — no digits were persisted. Verify: query the stored transcript and summary for
   the call and confirm they are clean.
2. Listen to the recording to understand how it happened (Grace failed to interrupt fast enough).
3. Strengthen the prompt guardrail and add the phrasing to voice suite scenario 9.
4. **Purge the recording for that call early**, ahead of normal retention.
5. If digits *did* persist: this is a compliance incident. Purge, document, notify the client, and review
   the redactor.

---

## 14. SMS not delivering

**Alert:** >10% failures in 1h. **Sev:** P2.

1. Twilio error codes in `messages.error_code`.
   - `30007` filtered by carrier → 10DLC problem. Check campaign status.
   - `30003/30005` unreachable/invalid → data quality, not systemic.
   - `21610` opted out → correct behaviour, not a failure.
2. 10DLC campaign lapsed or suspended → re-register. Use email fallback meanwhile.
3. Check the message body — new template wording can trigger carrier filtering (links, all caps,
   "free"). Revert and reword.

---

## 15. Cost anomaly

**Alert:** daily spend >150% of the 7-day average. **Sev:** P2.

1. Dashboard 5.4 — which component?
2. Vapi/Twilio voice → check call volume and duration. A stuck call loop or a runaway `maxDuration`?
3. PMS API calls → a poller in a retry storm.
4. Unexpected inbound volume → possible robocall/spam wave. Consider carrier-level blocking.

---

## 16. Full disaster recovery

Rebuild from an empty account. **Test this once before go-live.**

1. Provision Postgres; restore the latest PITR snapshot. Verify row counts against the last known good
   reconciliation report.
2. Provision Redis (empty is fine — it is rebuildable by design).
3. Deploy images from the last known good tag via CI.
4. Restore secrets from the secret store.
5. `platform:vapi:apply` and `platform:n8n:deploy` from the matching commit.
6. Re-point telephony.
7. Test call. Verify a booking end to end.
8. Re-run reconciliation and inspect the integrity report before letting bookings resume.

**RTO 30 min · RPO 5 min.** Time the drill and record the actual numbers.

---

## 17. Routine operational procedures

| Procedure | Cadence | Steps |
|---|---|---|
| Weekly QA sample | Mon | §12 §8 |
| Recording purge verification | Weekly | Confirm the job ran and expired URIs are gone from storage |
| Restore drill | Quarterly | §16 |
| Secret rotation | Quarterly | §11 §10; dual-accept window makes it zero-downtime |
| Dependency updates | Weekly | Grouped PR, CI-gated |
| Track B canary review | Daily (automated) | Alert only on red |
| Client report | Weekly | Calls, containment, bookings, cost, open items |
| Kill-switch drill | Quarterly | With the manager, timed |

---

## 18. Subject access / deletion request

**Read:** [11](11-security-and-compliance.md) §7.4.

1. Verify the requester's identity (they must be reachable at the number on file).
2. **Access:** export `customers`, `bookings`, `messages`, `calls` metadata for that customer.
   Recordings only if still within retention.
3. **Deletion:** null name/email, hash the phone, delete recordings and transcripts, keep
   `booking_events`, `consent_log`, `audit_log` under the documented retention basis.
4. Record the request and the action in `audit_log`.
5. Confirm to the requester in writing within the applicable statutory window.
