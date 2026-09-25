# Pointing EasyEcom straight at PostgREST

No Edge Function, no Render. EasyEcom POSTs directly to
`/rest/v1/webhook_events`.

The risk with this route is the key. `service_role` in a third party's
settings grants read and write on **every table in the project** and
bypasses row-level security. So instead we mint a key whose Postgres
role can do exactly one thing.

## 1. Create the role (already applied)

```bash
psql "$DATABASE_URL_SYNC" -f sql/easyecom_webhook_role.sql
```

Verified by switching into the role and trying each operation:

| Operation | Result |
|---|---|
| `INSERT` an easyecom webhook | **allowed** |
| `SELECT` webhook_events back | denied |
| `INSERT` forged as another source | denied (RLS) |
| `SELECT` shopify_order_attribution | denied |
| `SELECT` gokwik_orders | denied |
| `SELECT` ad_lifecycle (spend/revenue) | denied |
| `SELECT` the founder snapshot views | denied |
| `UPDATE` / `DELETE` / `DROP` | denied |

A leaked key buys junk rows in a landing table. Nothing readable.

## 2. Mint the key

```bash
./.venv/bin/python scripts/mint_easyecom_key.py
```

It asks for the **JWT Secret** from Supabase → Settings → API → JWT
Settings. That is the long random string with no dots — *not* the anon
or service_role key. It is read from a prompt, never stored.

## 3. Configure EasyEcom

URL, identical for every event:

```
https://gtcdyfmlvglzpiwzklhx.supabase.co/rest/v1/webhook_events
```

Token field: the minted key.

## Two things to verify on the first delivery

**Headers.** PostgREST on Supabase normally wants *two*:

```
apikey: <key>
Authorization: Bearer <key>
```

EasyEcom's UI shows one token field and an auth-type dropdown, so it
likely sends only one. `Authorization: Bearer` alone usually works;
`apikey` alone does not reach PostgREST's role switching. If deliveries
come back 401, that is why — and the Edge Function in
`supabase/functions/easyecom-webhook/` does not have this problem
because it reads whatever header arrives.

**Payload shape.** PostgREST inserts the JSON body *as a row*, so
EasyEcom's payload must match the table's columns. It will not: EasyEcom
sends its own order shape, and this table expects
`source, event, payload, headers`. Expect `400 PGRST204` naming an
unknown column on the first real delivery.

Fixing that needs a wrapper — either a `BEFORE INSERT` trigger that
folds unknown keys into `payload`, or a Postgres function exposed as an
RPC endpoint. Say which and it can be added; the Edge Function already
does this, which is the one real advantage it keeps.
