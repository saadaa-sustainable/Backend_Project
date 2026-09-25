// EasyEcom webhook receiver, running inside Supabase.
//
// Takes custody of the payload and returns 200. Nothing is parsed
// beyond confirming it is JSON: the body is written verbatim to
// webhook_events so that if a field is renamed upstream, or a payload
// differs from the docs, the rows are still there to re-read. A body
// that is not JSON is kept under _unparsed rather than rejected --
// an unreadable payload is still evidence, and EasyEcom only shows a
// delivery as failed, never what it tried to send.
//
// WHY NOT POINT EASYECOM AT PostgREST DIRECTLY
// A webhook's token is stored in EasyEcom's settings and travels to a
// third party. A Supabase service_role key there would hand EasyEcom --
// and anyone with access to that EasyEcom account -- read and write on
// every table in the project, bypassing row-level security. This
// function holds the service key itself, where it never leaves
// Supabase, and accepts only a shared secret that authorises exactly
// one thing: appending a row to webhook_events.
//
// DEPLOY WITH --no-verify-jwt. Supabase would otherwise demand an
// `Authorization: Bearer <jwt>` of its own, which EasyEcom cannot send
// alongside its own auth header. Auth is not skipped -- it is done
// below against EASYECOM_WEBHOOK_TOKEN.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// The 12 events EasyEcom can send, as its Webhook Settings screen names
// them. Rejecting anything else means a typo in a configured URL fails
// loudly at setup instead of quietly collecting rows nobody reads.
const EVENTS = new Set([
  "create_order", "confirm_order", "update_inventory", "manifested",
  "mark_return", "grn_details", "complete_grn", "rtd", "tracking",
  "confirm_order_start", "fetch_order", "cancel_order",
]);

/** Constant-time compare, so the secret cannot be probed a character
 *  at a time by timing the response. */
function tokensMatch(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  // .../functions/v1/easyecom-webhook/tracking
  const event = new URL(req.url).pathname.split("/").filter(Boolean).pop() ?? "";
  if (!EVENTS.has(event)) {
    return json({ error: `Unknown event '${event}'` }, 422);
  }

  const expected = Deno.env.get("EASYECOM_WEBHOOK_TOKEN");
  if (!expected) {
    // Refusing is the safe default: a public URL with the check
    // disabled is an open write path into the database.
    console.error("EASYECOM_WEBHOOK_TOKEN is not set");
    return json({ error: "Receiver not configured" }, 503);
  }
  // EasyEcom sends its token as Access-Token. Authorization is also
  // accepted because its auth-type dropdown offers both.
  const supplied = req.headers.get("Access-Token")
    ?? req.headers.get("authorization")?.replace(/^Bearer\s+/i, "")
    ?? "";
  if (!tokensMatch(supplied, expected)) {
    return json({ error: "Bad or missing Access-Token" }, 401);
  }

  const raw = await req.text();
  if (!raw) return json({ error: "Empty body" }, 400);
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    payload = { _unparsed: raw };
  }

  // Only headers worth keeping. Access-Token is deliberately absent:
  // storing the secret beside the data it protects undoes the point of
  // having one.
  const headers: Record<string, string> = {};
  for (const k of ["content-type", "user-agent", "x-forwarded-for"]) {
    const v = req.headers.get(k);
    if (v) headers[k] = v;
  }

  // SUPABASE_URL / SERVICE_ROLE_KEY are injected by the platform. The
  // key stays inside this function and is never sent to EasyEcom.
  const db = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );
  const { data, error } = await db
    .from("webhook_events")
    .insert({ source: "easyecom", event, payload, headers })
    .select("id")
    .single();

  if (error) {
    // 5xx so EasyEcom records a failed delivery and retries rather
    // than considering the event handed over.
    console.error("insert failed", error);
    return json({ error: "Could not store event" }, 500);
  }
  return json({ received: true, event, id: data.id }, 200);
});

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
