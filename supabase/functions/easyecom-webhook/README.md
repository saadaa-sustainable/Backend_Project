# EasyEcom webhook → Supabase

Receives EasyEcom webhooks directly in Supabase and appends them to
`public.webhook_events`. No Render deploy involved, so this works
without waiting on the backend PR, and there is no cold start.

## Deploy

```bash
supabase login
supabase link --project-ref gtcdyfmlvglzpiwzklhx

# Same string you paste into EasyEcom's Webhook Settings.
supabase secrets set EASYECOM_WEBHOOK_TOKEN='<your-secret>'

# --no-verify-jwt is REQUIRED. Supabase would otherwise demand an
# `Authorization: Bearer <supabase jwt>` of its own, which EasyEcom
# cannot send alongside its own auth header. Auth is not skipped --
# the function checks EASYECOM_WEBHOOK_TOKEN itself.
supabase functions deploy easyecom-webhook --no-verify-jwt
```

## Configure in EasyEcom

Meatball menu → Account Settings → Other settings → Webhook Settings.
One row per event; the last path segment must match the event:

```
https://gtcdyfmlvglzpiwzklhx.supabase.co/functions/v1/easyecom-webhook/tracking
https://gtcdyfmlvglzpiwzklhx.supabase.co/functions/v1/easyecom-webhook/mark_return
https://gtcdyfmlvglzpiwzklhx.supabase.co/functions/v1/easyecom-webhook/manifested
https://gtcdyfmlvglzpiwzklhx.supabase.co/functions/v1/easyecom-webhook/rtd
```

Put the secret in the **webhook token** field (the one showing
*Required* in red), leave auth type as **Access Token**, toggle on.

## Do NOT point EasyEcom at PostgREST instead

`https://<ref>.supabase.co/rest/v1/webhook_events` would also accept a
POST, and it needs no function — but it needs a Supabase API key in
EasyEcom's settings. `anon` cannot write, and `service_role` grants
read and write on **every table in the project**, bypassing row-level
security, to a third party and to anyone with access to that EasyEcom
account.

This function holds the service key itself, where it never leaves
Supabase, and accepts a shared secret that authorises exactly one
thing: appending a row to `webhook_events`.

## Behaviour

| Case | Response |
|---|---|
| Correct token | 200, row inserted, `{received, event, id}` |
| Missing / wrong token | 401 |
| `EASYECOM_WEBHOOK_TOKEN` unset | 503 — refuses rather than waving calls through |
| Unknown event in the path | 422 |
| Empty body | 400 |
| Body is not JSON | 200, kept under `_unparsed` |
| Insert fails | 500, so EasyEcom records a failed delivery |

The token is compared in constant time, and is deliberately not among
the headers stored beside the payload.
