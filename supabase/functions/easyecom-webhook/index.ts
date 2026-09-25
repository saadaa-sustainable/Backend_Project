// EasyEcom webhook receiver, running inside Supabase.
//
// ONE URL FOR EVERY TRIGGER.
//
//   https://<project>.supabase.co/functions/v1/easyecom-webhook
//
// EasyEcom's dropdown carries ~30 triggers and grows. Routing on a path
// segment meant a new URL per trigger, a row in Webhook Settings that
// had to agree with it, and a code change here whenever EasyEcom added
// one. So the event is now worked out from the PAYLOAD, and every
// trigger can point at the same URL. Adding a trigger becomes a single
// paste with nothing to deploy.
//
// A path segment is still honoured when present and wins over
// detection, so one trigger can be pinned exactly without giving up
// the single URL for the rest:
//
//   .../easyecom-webhook/rtd     -> stored as 'rtd'
//   .../easyecom-webhook         -> stored as whatever detect() says
//
// The resolved label comes back in the 200 body, so a mislabelled row
// is visible the moment a trigger is tested rather than days later.
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

/** Customer PII, dropped before the row is written.
 *
 *  create_order and mark_return carry the full customer block: name,
 *  email, phone, both address lines, pincode, lat/long. None of it is
 *  needed to correct ROAS for returns, and webhook_events is append
 *  only -- anything landing here is kept indefinitely. City, state and
 *  pin-less geography stay, because RTO varies sharply by region.
 *
 *  This matches scripts/ingest_gokwik_orders.py and
 *  scripts/ingest_easyecom_orders.py, which drop the same set. */
const PII = new Set([
  "customer_name", "contact_num", "email",
  "address_line_1", "address_line_2", "pin_code", "latitude", "longitude",
  "billing_name", "billing_address_1", "billing_address_2",
  "billing_mobile", "billing_pin_code",
  "shipping_name", "warehouse_contact",
  "forward_shipment_customer_name", "forward_shipment_customer_email",
  "forward_shipment_customer_contact_num",
  "forward_shipment_customer_address_line_1",
  "forward_shipment_customer_address_line_2",
  "forward_shipment_customer_pin_code",
  "forward_shipment_billing_name", "forward_shipment_billing_mobile",
  "forward_shipment_billing_address_1", "forward_shipment_billing_address_2",
  "forward_shipment_billing_pin_code",
  // presigned links to the customer's own invoice PDFs
  "documents", "invoice_documents", "credit_note_documents",
]);

function scrub(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(scrub);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      if (!PII.has(k)) out[k] = scrub(val);
    }
    return out;
  }
  return v;
}

/** Reach the first order-shaped object, whatever it is wrapped in.
 *
 *  Three wrappings occur in practice and a trigger set to the wrong one
 *  must still be understood:
 *      V2 order events  [{...}]
 *      V2 mark_return   [[{...}]]      array of arrays
 *      V1 anything      {"orders": [{...}], "nextUrl": null}
 *                       {"credit_notes": [{...}], "nextUrl": null}
 *
 *  ENVELOPE is deliberately short. `items` is NOT in it: on a tracking
 *  payload that key holds formatted strings, and descending into it
 *  would lose the event. */
const ENVELOPE = ["orders", "credit_notes", "data"];

function firstObject(p: unknown): Record<string, unknown> | null {
  let cur: unknown = p;
  for (let depth = 0; depth < 5; depth++) {
    if (Array.isArray(cur)) { cur = cur[0]; continue; }
    if (!cur || typeof cur !== "object") return null;
    const o = cur as Record<string, unknown>;
    const key = ENVELOPE.find((k) => Array.isArray(o[k]));
    if (key) { cur = o[key]; continue; }
    return o;
  }
  return null;
}

/** Work out which trigger sent this from the shape of the body.
 *
 *  The order-lifecycle triggers -- create_order, confirm_order, rtd,
 *  manifested -- all share ONE ~95-field schema and differ only in
 *  which timestamps happen to be filled, so they are NOT reliably
 *  separable and collapse to 'order'. Everything the revenue and RTO
 *  work needs is separable: tracking, mark_return and cancel_order each
 *  have fields the others do not. Pin a path segment on the trigger if
 *  an exact lifecycle label is ever needed. */
function detect(p: unknown): string {
  const o = firstObject(p);
  if (!o) return "unknown";

  // credit note fields appear on returns and nowhere else
  if ("credit_note_id" in o || "credit_note_number" in o) return "mark_return";

  // tracking is the only camelCase schema
  if ("currentShippingStatus" in o || ("awbNumber" in o && "invoiceId" in o)) {
    return "tracking";
  }

  if ("invoice_id" in o && "order_id" in o) {
    const status = String(o.order_status ?? "").toLowerCase();
    if (status === "cancelled" || status === "canceled") return "cancel_order";
    return "order";
  }

  if ("available_inventory" in o || "inventory_status" in o) return "inventory";
  return "unknown";
}

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
    // An unreadable payload is still evidence, and EasyEcom's delivery
    // log shows only that a call failed, never what it tried to send.
    payload = { _unparsed: raw };
  }

  // .../easyecom-webhook            -> segment is the function name
  // .../easyecom-webhook/mark_return-> segment is the pinned event
  const seg = new URL(req.url).pathname.split("/").filter(Boolean).pop() ?? "";
  const pinned = seg && seg !== "easyecom-webhook"
    ? seg.toLowerCase().replace(/[^a-z0-9_]+/g, "_").slice(0, 40)
    : "";
  const event = pinned || detect(payload);

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
    .insert({ source: "easyecom", event, payload: scrub(payload), headers })
    .select("id")
    .single();

  if (error) {
    // 5xx so EasyEcom records a failed delivery and retries rather
    // than considering the event handed over.
    console.error("insert failed", error);
    return json({ error: "Could not store event" }, 500);
  }
  // `event` is echoed so a freshly configured trigger shows how it was
  // labelled at the moment it is tested.
  return json({ received: true, event, id: data.id }, 200);
});

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
