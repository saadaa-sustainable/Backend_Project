/** Same-origin BFF: tokens stay on FastAPI; the browser only receives HttpOnly session cookies. */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ action: string }> };
const methods: Record<string, string> = {
  status: "GET", start: "POST", callback: "GET", models: "GET", chat: "POST", disconnect: "POST",
};
const cookieNames = new Set(["saadaa_chatgpt_session", "saadaa_chatgpt_signin"]);
const noStore = { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" };

async function forward(request: Request, context: Context) {
  const { action } = await context.params;
  if (!Object.hasOwn(methods, action) || request.method !== methods[action]) {
    return Response.json({ detail: "Unknown assistant action." }, { status: 404, headers: noStore });
  }
  const publicOrigin = process.env.CHATGPT_PUBLIC_ORIGIN ?? "http://localhost:3000";
  if (request.method === "POST" && request.headers.get("origin") !== publicOrigin) {
    return Response.json({ detail: "This action must start from the dashboard." }, { status: 403, headers: noStore });
  }
  const backend = process.env.ASSISTANT_BACKEND_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8002";
  const headers = new Headers({ "Accept": "application/json" });
  const cookies = (request.headers.get("cookie") ?? "").split(";")
    .map(c => c.trim()).filter(c => cookieNames.has(c.split("=", 1)[0])).join("; ");
  if (cookies) headers.set("Cookie", cookies);
  if (request.method === "POST") {
    headers.set("Origin", publicOrigin);
    headers.set("Content-Type", "application/json");
  }
  // No arbitrary proxy targets or caller-supplied authorization headers.
  const url = new URL(`/admin/assistant/chatgpt/${action}`, backend);
  if (action === "callback") url.search = new URL(request.url).search;
  let body: string | undefined;
  if (request.method === "POST") {
    const contentLength = Number(request.headers.get("content-length") ?? "0");
    if (contentLength > 256_000) {
      return Response.json({ detail: "Conversation is too long." }, { status: 413, headers: noStore });
    }
    body = await request.text();
    if (body.length > 256_000) return Response.json({ detail: "Conversation is too long." }, { status: 413, headers: noStore });
  }
  try {
    const upstream = await fetch(url, {
      method: request.method, headers, body, redirect: "manual", cache: "no-store",
      signal: AbortSignal.timeout(action === "chat" ? 250_000 : 40_000),
    });
    const outgoing = new Headers(noStore);
    outgoing.set("Content-Type", upstream.headers.get("content-type") ?? "application/json");
    const location = upstream.headers.get("location");
    if (location) {
      const target = new URL(location, publicOrigin);
      if (target.origin !== publicOrigin || target.pathname !== "/user/assistant") {
        return Response.json({ detail: "Invalid sign-in redirect." }, { status: 502, headers: noStore });
      }
      outgoing.set("Location", target.href);
    }
    for (const value of upstream.headers.getSetCookie()) {
      if (cookieNames.has(value.split("=", 1)[0])) outgoing.append("Set-Cookie", value);
    }
    return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: outgoing });
  } catch {
    return Response.json({ detail: "Could not reach the assistant backend. Stopped without retrying." },
      { status: 503, headers: noStore });
  }
}

export const GET = forward;
export const POST = forward;
