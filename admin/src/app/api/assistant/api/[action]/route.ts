/** Fixed same-origin proxy. Provider credentials remain on FastAPI. */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ action: string }> };
const methods: Record<string, string> = {
  status: "GET", connect: "POST", models: "GET", chat: "POST", disconnect: "POST",
};
const cookieName = "saadaa_assistant_api";
const visitorCookie = "saadaa_assistant_visitor";
const noStore = { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" };

function dashboardOrigin(): string | null {
  // Use server configuration, never browser-controlled Host/forwarded headers.
  // Render terminates HTTPS before Next.js, so the internal request URL differs.
  const configured = process.env.ASSISTANT_API_PUBLIC_ORIGIN ?? process.env.RENDER_EXTERNAL_URL
    ?? (process.env.NODE_ENV !== "production" ? "http://localhost:3000" : "");
  try {
    const value = configured.trim().replace(/\/+$/, "");
    const url = new URL(value);
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (url.username || url.password || url.search || url.hash || url.pathname !== "/"
      || (url.protocol !== "https:" && !(url.protocol === "http:" && local))) return null;
    return url.origin;
  } catch { return null; }
}

async function forward(request: Request, context: Context) {
  const { action } = await context.params;
  if (!Object.hasOwn(methods, action) || request.method !== methods[action]) {
    return Response.json({ detail: "Unknown assistant action." }, { status: 404, headers: noStore });
  }
  const origin = dashboardOrigin();
  if (!origin) {
    return Response.json({ detail: "Assistant dashboard URL is not configured. Set ASSISTANT_API_PUBLIC_ORIGIN on the frontend and backend to the dashboard's public URL." },
      { status: 503, headers: noStore });
  }
  if (request.method === "POST" && request.headers.get("origin") !== origin) {
    return Response.json({ detail: "This action must start from the dashboard." }, { status: 403, headers: noStore });
  }
  const backend = process.env.ASSISTANT_BACKEND_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8002";
  const headers = new Headers({ Accept: "application/json" });
  const cookie = (request.headers.get("cookie") ?? "").split(";")
    .map(value => value.trim()).find(value => value.split("=", 1)[0] === cookieName);
  if (cookie) headers.set("Cookie", cookie);
  // A visitor ID only groups usage limits; it grants no permissions and is not a login.
  const existingVisitor = (request.headers.get("cookie") ?? "").split(";")
    .map(value => value.trim()).find(value => value.startsWith(`${visitorCookie}=`))?.slice(visitorCookie.length + 1);
  const visitor = existingVisitor && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(existingVisitor)
    ? existingVisitor : crypto.randomUUID();
  headers.set("X-Assistant-Visitor", visitor);
  let body: string | undefined;
  if (request.method === "POST") {
    headers.set("Origin", origin);
    headers.set("Content-Type", "application/json");
    // Count streamed bytes so a missing Content-Length cannot bypass the cap.
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader) {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 256_000) {
          await reader.cancel();
          return Response.json({ detail: "Conversation is too long." }, { status: 413, headers: noStore });
        }
        chunks.push(value);
      }
    }
    body = new TextDecoder().decode(Buffer.concat(chunks));
  }
  try {
    const upstream = await fetch(new URL(`/admin/assistant/api/${action}`, backend), {
      method: request.method, headers, body, redirect: "manual", cache: "no-store",
      signal: AbortSignal.timeout(action === "chat" ? 250_000 : 12_000),
    });
    if (upstream.status >= 300 && upstream.status < 400) {
      return Response.json({ detail: "Unexpected assistant redirect." }, { status: 502, headers: noStore });
    }
    const outgoing = new Headers(noStore);
    outgoing.set("Content-Type", upstream.headers.get("content-type") ?? "application/json");
    if (visitor !== existingVisitor) {
      outgoing.append("Set-Cookie", `${visitorCookie}=${visitor}; Path=/api/assistant/api; Max-Age=28800; HttpOnly; SameSite=Strict${origin.startsWith("https://") ? "; Secure" : ""}`);
    }
    for (const value of upstream.headers.getSetCookie()) {
      if (value.split("=", 1)[0] === cookieName) outgoing.append("Set-Cookie", value);
    }
    return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: outgoing });
  } catch {
    return Response.json({ detail: "Could not reach the assistant backend. Stopped without retrying." },
      { status: 503, headers: noStore });
  }
}

export const GET = forward;
export const POST = forward;
