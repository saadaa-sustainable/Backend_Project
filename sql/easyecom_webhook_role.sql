-- ---------------------------------------------------------------------
-- A PostgREST role that can do exactly one thing: append a webhook.
--
-- Lets EasyEcom POST straight to
--   https://<ref>.supabase.co/rest/v1/webhook_events
-- with no Edge Function in between, WITHOUT handing it service_role.
--
-- service_role in a third party's settings grants read and write on
-- every table in the project and bypasses row-level security. This role
-- can INSERT into one table and cannot SELECT it back, so a leaked key
-- cannot be used to read orders, spend, revenue or anything else -- the
-- worst it buys is junk rows in a landing table.
--
-- PostgREST switches to the role named in the JWT's `role` claim, so a
-- token minted with role=easyecom_webhook lands here.
-- ---------------------------------------------------------------------

-- NOLOGIN: this role is only ever reached by PostgREST switching into
-- it, never by connecting directly.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'easyecom_webhook') THEN
    CREATE ROLE easyecom_webhook NOLOGIN NOINHERIT;
  END IF;
END
$$;

-- `authenticator` is the role PostgREST logs in as; it must be allowed
-- to SET ROLE into ours or every request fails with "unable to switch".
GRANT easyecom_webhook TO authenticator;

GRANT USAGE ON SCHEMA public TO easyecom_webhook;

-- INSERT only. Deliberately no SELECT: PostgREST would otherwise let a
-- leaked key read the table back, and webhook payloads carry customer
-- detail. It also means no `Prefer: return=representation`.
GRANT INSERT ON public.webhook_events TO easyecom_webhook;

-- id is bigserial, so inserting needs the sequence.
GRANT USAGE ON SEQUENCE public.webhook_events_id_seq TO easyecom_webhook;

-- Nothing else in the schema, now or later.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM easyecom_webhook;

-- Row-level security, so the grant above cannot be widened by accident
-- and the role is confined to appending EasyEcom rows.
ALTER TABLE public.webhook_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS easyecom_webhook_insert ON public.webhook_events;
CREATE POLICY easyecom_webhook_insert
    ON public.webhook_events
    FOR INSERT TO easyecom_webhook
    -- source is pinned: this key cannot be used to forge rows
    -- attributed to any other integration.
    WITH CHECK (source = 'easyecom');

-- The app connects as the table owner and is unaffected by RLS, but
-- service_role is used by other tooling and must keep full access.
DROP POLICY IF EXISTS service_role_all ON public.webhook_events;
CREATE POLICY service_role_all
    ON public.webhook_events FOR ALL TO service_role
    USING (true) WITH CHECK (true);
