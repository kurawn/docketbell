#!/usr/bin/env bash
# Walks through the reminder flow against a running `docker compose up`. Needs curl and python3.
set -euo pipefail

API="${API:-http://localhost:8000/api/v1}"
SANDBOX="${SANDBOX:-http://localhost:8001/sandbox/v1}"
ALICE="Authorization: Token demo-alice-token"
BOB="Authorization: Token demo-bob-token"
SANDBOX_AUTH="Authorization: Bearer sandbox-dev-key"

pretty() { python3 -m json.tool; }
pick() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }

MATTER_ID=$(curl -sf -H "$ALICE" "$API/matters/" | pick "['results'][0]['id']")
DUE=$(python3 -c "import datetime; print(datetime.date.today() + datetime.timedelta(days=2))")

echo "== Alice creates a deadline due $DUE; the 10- and 5-day reminders are already missed"
DEADLINE_ID=$(curl -sf -H "$ALICE" -H "Content-Type: application/json" \
  -d "{\"kind\": \"office_action_response\", \"title\": \"Demo: file response\", \"nominal_date\": \"$DUE\"}" \
  "$API/matters/$MATTER_ID/deadlines/" | pick "['id']")
curl -sf -H "$ALICE" "$API/deadlines/$DEADLINE_ID/reminders/" | pretty

echo "== Waiting 75s for the dispatcher, injected failures, retries and delivery webhooks"
sleep 75
curl -sf -H "$ALICE" "$API/deadlines/$DEADLINE_ID/reminders/" | pretty

echo "== Bob acknowledges; Carol's escalation is cancelled"
curl -sf -X POST -H "$BOB" "$API/deadlines/$DEADLINE_ID/acknowledge/" | pretty
curl -sf -H "$ALICE" "$API/deadlines/$DEADLINE_ID/reminders/" | python3 -c "
import json, sys
for r in json.load(sys.stdin):
    print(f\"{r['type']:<11} {r['recipient']:<6} offset={r['offset_days']:<3} {r['status']:<10} attempts={r['attempts']}\")
"

echo "== Sandbox inbox: exactly one message per idempotency key"
curl -sf -H "$SANDBOX_AUTH" "$SANDBOX/messages" | python3 -c "
import collections, json, sys
messages = json.load(sys.stdin)['messages']
per_key = collections.Counter(m['idempotency_key'] for m in messages)
print(f'{len(messages)} messages, {len(per_key)} keys, most per key: {max(per_key.values(), default=0)}')
"
