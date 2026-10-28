# docketbell

Deadline and reminder engine for patent and trademark matters. A missed deadline here can mean lost rights, so reminders must reach the right people, on a UK working day, exactly once.

## Run it

```bash
docker compose up --build
```

That starts Postgres, Redis, the API (`:8000`), a Celery worker, Celery beat and a fake messaging provider (`:8001`). On start the API migrates, loads UK bank holidays from a bundled GOV.UK snapshot, and seeds demo data. No keys or accounts needed.

Demo users (token auth, `Authorization: Token <token>`):

| User | Role on the demo matter | Token |
|---|---|---|
| alice | responsible attorney | `demo-alice-token` |
| bob | assistant | `demo-bob-token` |
| carol | supervisor (gets escalations) | `demo-carol-token` |
| dave | not a member | `demo-dave-token` |

Admin: http://localhost:8000/admin/, login `admin` / `admin` (created by `seed_demo`, so dev only). Matters and deadlines are editable there, and every save goes through the same services as the API, so moving, completing or cancelling a deadline, or adding a member, re-plans reminders. Reminders, webhook events, bank holidays and sandbox messages are read-only, because the dispatcher, webhooks and holiday refresh own those rows.

Then run the guided demo: `./scripts/demo.sh`. Example requests for every endpoint are in `requests.http`.

Tests: `docker compose run --rm api pytest`. Lint: `docker compose run --rm api ruff check .`

## Track and data source

Track 03, deadline and reminder engine, with the GOV.UK bank holidays feed (`www.gov.uk/bank-holidays.json`): free, keyless, official, and the only source that matters for UK working days. I chose this track because its hard parts are the ones that bite in production: delivery that must not duplicate, retries that must be safe, and dates that must be right.

## How it works

```
POST deadline ──► due date rolled past weekends/holidays ──► Reminder rows planned (Postgres)
                                                                   │
beat, every 30s ──► dispatcher claims due rows (FOR UPDATE SKIP LOCKED, 2-min lease)
                                                                   │
worker ──► send task ──► provider.send(payload, idempotency_key) ──► sandbox provider
                                                                   │
sandbox ──► signed webhook (delivered / failed) ──► reminder status moves forward
```

## Key decisions and trade-offs

- **Reminder rows plus a dispatcher, not Celery ETA tasks.** ETA tasks sit in Redis for days; Redis re-delivers them after its visibility timeout (duplicates), loses them on a flush, and they are hard to cancel when a deadline moves. Rows in Postgres are queryable, survive a Redis loss, and are cancelled with one UPDATE.
- **At-least-once sending, made exactly-once by the provider.** A worker can die after the provider accepted the message but before we recorded it. The lease lets another worker reclaim the row, and the per-reminder idempotency key makes the provider return the original message instead of sending again.
- **The payload is frozen on the first attempt.** The provider rejects a reused key with a different body (as Stripe does), so a title edit between retries must not change what we resend.
- **Every state change is conditional** (`WHERE status = 'sending'`), so a slow, stale worker can never overwrite a newer state.
- **Retries go back through the dispatcher** with backoff (30s, 2m, 8m, 30m, ±20% jitter, `Retry-After` respected), so there is one send path and every retry is visible in the table.
- **Webhooks:** HMAC-SHA256 over `timestamp.body`, constant-time compare, 5-minute replay window, de-duplicated by `event_id`, matched by our idempotency key (known before sending, so a webhook that beats our own `accepted` write still applies), and status only moves forward. A `delivered` event also applies to a reminder waiting in backoff after a timeout, because the provider did get that message.
- **Catch-up rule:** if a deadline is entered late, missed reminders collapse into one sent now instead of several stale ones.
- **`for_due_date` on each reminder:** moving a deadline plans a fresh set; changing only the offsets does not resend what was already delivered for the same date.
- **Bank holidays:** bundled snapshot so the first start works offline; daily refresh validates the payload and never deletes on bad data; newly announced holidays (like the 2023 coronation) re-roll open deadlines.
- **Visibility:** you only see matters you belong to; others' objects return 404 rather than 403, so IDs are not confirmed to outsiders.

## Data model

- `Matter`, `MatterMember` (responsible, assistant or supervisor)
- `Deadline`: `nominal_date` as entered, `due_date` rolled, offsets, status, acknowledgement
- `Reminder`: one row per recipient, offset and type (reminder or escalation), with status, lease, attempts, idempotency key and frozen payload
- `WebhookEvent`: de-duplication
- `BankHoliday`
- Indexes:
  - partial index on `send_at` for pending reminders (the dispatcher's query)
  - partial index on `locked_until` for reminders in `sending` (lease reclaim)
  - partial index on `due_date` for open deadlines

## API

All under `/api/v1/`, token auth, cursor pagination on lists, errors always shaped as `{"error": {"code", "message", "details"}}`.

| Method | Path | |
|---|---|---|
| GET, POST | `/matters/` | |
| GET | `/matters/{id}/` | |
| POST | `/matters/{id}/members/` | responsible or supervisor |
| GET, POST | `/matters/{id}/deadlines/` | POST: responsible or supervisor |
| GET | `/deadlines/?status=&due_before=&due_after=` | across your matters |
| GET, PATCH | `/deadlines/{id}/` | PATCH: responsible or supervisor |
| POST | `/deadlines/{id}/acknowledge/` | responsible or assistant |
| GET | `/deadlines/{id}/reminders/` | |
| POST | `/webhooks/provider/` | signature auth |

## Testing and QA

The tests cover what would cause damage if it broke:

- working-day maths, including Easter, Christmas and Boxing Day substitutes, and the March clock change
- the planner, including the catch-up rule and replanning without re-sending
- two dispatchers never claiming the same row, against real Postgres row locks
- the "timed out, but the provider stored it" case ending with exactly one message
- webhook signature, replay, duplicate and out-of-order handling
- permissions and the error shape
- the deadline list query count staying flat as rows grow, so there are no N+1 queries

### Manual test plan

| # | Do | Expect |
|---|---|---|
| 1 | `docker compose up`, then `curl localhost:8000/healthz` | `{"status": "ok"}` |
| 2 | Create a deadline on a Saturday | `due_date` is the next working day, `rolled: true` |
| 3 | Create a deadline due in 2 days | One catch-up reminder per recipient goes out within ~30s |
| 4 | Watch `/reminders/` for a minute | Some rows retry (`attempts > 1`); all end `delivered` or `failed` |
| 5 | Sandbox inbox | At most one message per idempotency key |
| 6 | Acknowledge as bob | Escalation `cancelled`, reminders still pending |
| 7 | PATCH the date | Old pending rows `cancelled`, new ones planned |
| 8 | Complete the deadline | All pending rows `cancelled` |
| 9 | `docker compose stop worker` for 2 min, then start | Due reminders go out late but once |
| 10 | As dave, GET alice's deadline | 404 |
| 11 | POST a webhook with a wrong signature | 401, nothing changes |

### What I would check next

- A soak run with the fault rates raised to 50%, to confirm nothing ends up duplicated or stuck.
- Killing the worker with `kill -9` mid-send, to confirm the lease reclaims the row.
- Clock-skew behaviour of the webhook replay window.

## Query plan

The dispatcher's due-reminder query against 100,000 reminders (`python manage.py seed_load`):

```
Limit  (cost=0.28..242.72 rows=100 width=424) (actual time=0.010..0.084 rows=100 loops=1)
  ->  Index Scan using reminder_due_idx on reminders_reminder  (cost=0.28..5881.72 rows=2426 width=424) (actual time=0.010..0.079 rows=100 loops=1)
        Index Cond: (send_at <= '2026-10-28 05:05:24.590897+00'::timestamp with time zone)
Planning Time: 0.434 ms
Execution Time: 0.098 ms
```

This is a plain SELECT of the same filter and order. The dispatcher adds `FOR UPDATE SKIP LOCKED` and selects only ids. So this output shows that the partial index is used, not the exact timing of the locked query.

## Known limitations

- If a deadline is completed while a send is already in flight, that one message may still go out.
- The sandbox shares the Postgres server with the app (separate tables), unlike a real external provider.
- There's one bank-holiday region per deployment, with no per-matter jurisdiction.
- Each API process caches holidays for up to an hour, so a just-refreshed holiday may take that long to affect new deadlines there.
- Holidays removed from the GOV.UK feed are not removed here.
- There's no per-attempt history; each reminder keeps only a counter and its last error.
- One channel only; no user preferences, quiet hours or per-user time zones.
- **Re-planning during a retry can send twice.** Say a send times out after the provider stored the message, so the reminder waits in `pending` to retry. If the offsets change in that window, re-planning cancels it and creates a new row with a new idempotency key. The provider can't link the two, so the person may get the message twice. The fix is to keep rows that have already been attempted when re-planning.
- **A late `delivered` webhook can't undo `failed`.** If the last allowed attempt times out after the provider stored the message, the reminder is marked `failed`. A later `delivered` webhook is recorded but doesn't change it, because status only moves forward.
- **A new holiday can be missed if the worker crashes mid-refresh.** The holiday is saved before open deadlines are recalculated. If the worker crashes in between, the next refresh sees nothing new and never recalculates.
- **Paging stops working past about 1,000 deadlines on the same date.** DRF's cursor only uses `due_date` for the cursor position, and caps the offset within one date at 1,000.
- **The sandbox can lose a webhook.** A message stored right before a crash, or before Redis is lost, never gets its delivery webhook, and the reminder stays `accepted`. The reconciliation job under "Before production" covers this for a real provider.
- **Two webhook tasks for one sandbox message can report opposite outcomes.** The sandbox doesn't lock the message while choosing an outcome, so two tasks can each pick a different result.
- **Postgres data is lost on `docker compose down`.** It has no named volume, so the next `up` starts with an empty database.

## Before production

- **Real provider.** Implement `MessagingProvider` for SendGrid or a similar service, with its own webhook verification. Switch it with `MESSAGING_PROVIDER`.
- **Secrets.** Load secrets from a secret manager; startup already refuses dev defaults when `DEBUG` is off. Rotate the webhook secret by accepting two secrets during the overlap.
- **Monitoring.** Add metrics for:
  - due-but-unclaimed reminders (dispatcher lag)
  - failures by reason
  - webhook rejections
  - age of the oldest `accepted` reminder (missing webhooks)
  Alert on all of them.
- **Missing webhooks.** Add a reconciliation job that asks the provider for the status of reminders stuck in `accepted`.
- **Audit trail.** Keep per-attempt history for legal auditability, and record who acknowledged what and when.
- **Infrastructure.** Run gunicorn and Celery under proper process supervision, use a managed Postgres with backups, and make Redis persistence optional (Redis holds no state we can't rebuild).
- **API protection.** Add rate limiting and request size limits on the API, and an IP allow-list for webhooks if the provider publishes one.

## How I used AI

I used Claude Code (desktop app, model Claude Opus 5.5) for the whole project, in three phases.

**1. Planning: one conversation, about an hour**

- **Choosing the track.** I gave it the brief and asked which track would best show senior back-end experience while still being easy to explain. It compared the three tracks. I picked Track 03 because its hard parts are the ones that hurt in production: duplicate sends, unsafe retries and wrong dates.
- **Settling the design, one decision at a time.** We worked through these in order:
  1. Domain: patent and trademark deadlines, because a missed deadline can mean lost rights.
  2. The one extra feature: acknowledge, then escalate to the supervisor.
  3. The core architecture. It laid out three options:
     - reminder rows in Postgres with a `SKIP LOCKED` dispatcher
     - Celery ETA tasks
     - a separate outbox relay

     I chose the rows and dispatcher. The reasons are under "Key decisions" above.
- **Spec, then plan.** It wrote a design spec, which I reviewed and approved. It then turned the spec into a 12-task, test-first implementation plan with the code and tests written out.
- **Gaps found before any code was written.** While writing the plan at code level, the AI found four gaps in the design we had agreed. All four were fixed before implementation started:
  - Moving a deadline would have clashed with reminders already delivered. Fixed with `for_due_date`.
  - A title edit between retries would have turned a retry into a permanent 422. Fixed by freezing the payload on the first attempt.
  - A delivery webhook arriving during the backoff after a timeout would have left the reminder stuck. Webhooks now also apply to `pending` reminders.
  - A reminder that keeps crashing the worker would have looped forever. Fixed with an attempts cap checked at claim time.

**2. Implementation: a separate Claude Code session**

A fresh session carried out the plan task by task:
- It wrote each test first, saw it fail, then wrote the code.
- It ran pytest and ruff inside Docker after every task.
- It finished by running the full stack, the demo script and the query-plan check.

It was told not to weaken tests to make them pass, and to record every place it had to change the plan. Those changes are below.

**What changed from the plan during the build**

The build hit three places where the plan's own code was wrong. Each was fixed minimally, and no test was weakened or removed.

- **The tests were quietly using the real Redis.** The test setup overrode Celery's `broker_url`. But the app reads Celery settings under the `CELERY_` namespace, so `CELERY_BROKER_URL` won and the override did nothing. The session caught it when the live worker started picking up tasks for reminders that only existed in the test database. Fixed by overriding the namespaced keys. The suite now passes with Redis unreachable.
- **Lint could never pass on generated migrations.** Django's migration files break the import-order and line-length rules. Migrations are now excluded from ruff. All hand-written code is still linted with the full rule set.
- **Long lines.** 14 lines of the plan's code were over the 110-character limit. They were wrapped. This was formatting only, with no logic changes.

**3. Follow-up: an admin and a check before submitting**

A third session, after the build was finished:

- **Django admin.** I asked for an admin for operators. Every deadline and member save goes through `matters/services.py`, so an admin edit re-plans reminders exactly as the API does. Reminders, webhook events, bank holidays and sandbox messages are read-only, because background jobs own those rows and a manual status edit could cause a duplicate send. Adding the admin's CSRF middleware would have broken the sandbox's POST endpoint; the AI caught this and exempted that view, which authenticates with a bearer key. The Unfold theme was added on top at my request.
- **Checking the repo against the brief.** It found what was still missing for submission: a `.gitignore`, the empty "What I verified myself" section below, and a broken reference to design notes that were never committed.
- **Checking that the review fixes are really guarded.** I had it put each of the four review bugs below back into a scratch copy of the code and run the matching test. All four tests fail against the bug. For the catch-up bug, the test fails only on the exact original mistake, not on every edit to that condition.

**Where I overruled or steered it**

- **How often to send.** The first plan sent the day's reminders in a single daily run. I had it changed to a dispatcher that runs every 30 seconds and claims due reminders in batches of 100. Not every send time is 09:00: catch-up reminders go out at once, a worker that died mid-send must have its row reclaimed within minutes, and a single daily run would leave everything past the first batch for the next day. This also moved retries off Celery's built-in retry. A failed send goes back to `pending` with a backoff `send_at`, and a later dispatcher run picks it up. There is one send path, and every retry is visible in the table.
- **An independent review before sending.** All tests passed, but I didn't take that as proof. I asked for a review against the spec: one pass by Claude and a separate one by Codex, a different model. Together they found four bugs the tests missed, and each was confirmed with a failing test before it was fixed:
  - members added through the API got no reminders;
  - planning a deadline again brought back reminders the catch-up rule had merged;
  - a reminder already picked up for sending still went out with the old date after the deadline moved;
  - a webhook signature with non-ASCII characters caused a 500 instead of a 401.

  The risks we chose not to fix are listed under "Known limitations".

**What I verified myself**

- Ran `scripts/demo.sh` against the full stack and followed the reminders through retries to delivery.
- Checked access from outside a matter: requests with dave's token for alice's matter and deadlines return 404.
- Used the Django admin to inspect the data by hand: reminder statuses, attempts and last errors, deadlines with their reminder schedule, webhook events and the sandbox inbox. This made it much quicker to check that each state change matched what the API and the logs said.
