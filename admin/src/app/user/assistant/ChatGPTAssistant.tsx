"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatAssistant } from "@/app/assistant/ChatAssistant";
import { ChatGPTError, ChatGPTStatus, chatgptRequest, chatgptTransport } from "@/lib/chatgpt";

export default function ChatGPTAssistant() {
  const [status, setStatus] = useState<ChatGPTStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [sessionVersion, setSessionVersion] = useState(0);
  const callbackErrorRef = useRef<string | null>(null);
  const statusRequest = useRef<{ attempt: number; result: Promise<ChatGPTStatus> } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const url = new URL(window.location.href);
    const callbackError = url.searchParams.get("chatgpt_error");
    if (callbackError) {
      callbackErrorRef.current = callbackError === "access_denied"
        ? "This ChatGPT account has not been granted access. Contact your dashboard administrator."
        : "Sign-in did not complete. Continue with ChatGPT to try again.";
      url.searchParams.delete("chatgpt_error");
      window.history.replaceState({}, "", url);
    }
    if (!statusRequest.current || statusRequest.current.attempt !== attempt) {
      statusRequest.current = { attempt, result: chatgptRequest<ChatGPTStatus>("status") };
    }
    statusRequest.current.result.then(result => {
      if (!cancelled) {
        setStatus(result);
        if (callbackErrorRef.current) {
          setError(callbackErrorRef.current);
          callbackErrorRef.current = null;
        }
      }
    }).catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [attempt]);

  const accessError = useCallback((err: unknown) => {
    if (err instanceof ChatGPTError && [401, 403].includes(err.status)) {
      setStatus(previous => previous ? { ...previous, connected: false, plan_enabled: false, user: undefined } : previous);
      setSessionVersion(n => n + 1);
      setError(err.message);
    }
  }, []);

  async function connect() {
    setConnecting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await chatgptRequest<{ url: string }>("start", {});
      const target = new URL(result.url);
      if (target.origin !== "https://auth.openai.com") throw new Error("Could not verify the ChatGPT sign-in address.");
      window.location.assign(target.href);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start sign-in.");
      setConnecting(false);
    }
  }

  async function disconnect() {
    setConnecting(true);
    setError(null);
    try {
      const result = await chatgptRequest<{ message: string }>("disconnect", {});
      setStatus({ available: true, connected: false, plan_enabled: false });
      setSessionVersion(n => n + 1);
      setNotice(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect. Try again.");
    } finally { setConnecting(false); }
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <section aria-label="ChatGPT connection" className="rounded-lg border border-border-primary bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-text-primary">{status?.connected ? "Connected to ChatGPT" : "Use your ChatGPT account"}</h2>
            <p className="mt-1 max-w-2xl break-words text-sm text-text-secondary">
              {status?.connected ? status.user?.email : "Ask about ads, assets, revenue, and sessions using your account. Only approved team members can access analytics."}
            </p>
            {status?.connected && <p className="mt-2 text-sm text-text-secondary">
              {status.plan_enabled ? "Read-only analytics. Questions use your authorized ChatGPT plan; returned analytics are shared with OpenAI to answer them."
                : "You’re signed in. ChatGPT plan usage still needs to be enabled for this connection before you can ask questions."}
            </p>}
            {status && !status.available && <p className="mt-2 text-sm text-text-secondary">{status.message}</p>}
            {!status && !error && <p role="status" className="mt-2 text-sm text-text-secondary">Checking connection…</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {status?.connected && <button type="button" disabled={busy || connecting} onClick={disconnect}
              className="rounded-md border border-border-primary px-3 py-2 text-sm text-text-primary hover:bg-bg-muted focus-visible:outline-2 focus-visible:outline-text-primary disabled:opacity-50">Disconnect</button>}
            {status && (!status.connected || !status.plan_enabled) && <button type="button" onClick={connect}
              disabled={!status.available || connecting || busy}
              className="rounded-md bg-text-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-text-primary disabled:opacity-50">
              {connecting ? "Connecting…" : "Continue with ChatGPT"}
            </button>}
          </div>
        </div>
        {notice && <p role="status" className="mt-3 text-sm text-text-secondary">{notice}</p>}
        {error && <p role="alert" className="mt-3 text-sm text-error-text">{error}</p>}
        {!status && error && <button type="button" onClick={() => { setError(null); setAttempt(n => n + 1); }}
          className="mt-3 rounded text-sm text-text-primary underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-text-primary">Check connection again</button>}
      </section>
      {status?.connected && status.plan_enabled && <ChatAssistant key={sessionVersion} allowUpload={false}
        transport={chatgptTransport} onBusyChange={setBusy} onAccessError={accessError} />}
    </div>
  );
}
