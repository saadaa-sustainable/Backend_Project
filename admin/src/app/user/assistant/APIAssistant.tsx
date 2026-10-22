"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatAssistant } from "@/app/assistant/ChatAssistant";
import { AssistantAPIError, AssistantAPIStatus, assistantAPIRequest, assistantAPITransport } from "@/lib/assistant-api";

export default function APIAssistant() {
  const [status, setStatus] = useState<AssistantAPIStatus | null>(null);
  const [accessKey, setAccessKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const statusRequest = useRef<{ attempt: number; result: Promise<AssistantAPIStatus> } | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!statusRequest.current || statusRequest.current.attempt !== attempt) {
      statusRequest.current = { attempt, result: assistantAPIRequest<AssistantAPIStatus>("status") };
    }
    statusRequest.current.result.then(value => { if (!cancelled) setStatus(value); })
      .catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [attempt]);

  const accessError = useCallback((err: unknown) => {
    if (err instanceof AssistantAPIError && err.status === 401) {
      setStatus(previous => previous ? { ...previous, connected: false, user: undefined, mcp_url: undefined } : previous);
      setVersion(n => n + 1);
      setError(err.message);
    }
  }, []);

  async function connect(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setConnecting(true);
    setError(null);
    try {
      const connection = await assistantAPIRequest<AssistantAPIStatus>("connect", { access_key: accessKey.trim() });
      setStatus(connection);
      setVersion(n => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect.");
    } finally { setAccessKey(""); setConnecting(false); }
  }

  async function disconnect() {
    setConnecting(true);
    setError(null);
    try {
      await assistantAPIRequest("disconnect", {});
      setStatus(previous => previous ? { ...previous, connected: false, user: undefined, mcp_url: undefined } : previous);
      setVersion(n => n + 1);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not disconnect."); }
    finally { setConnecting(false); }
  }

  return <div className="flex min-w-0 flex-col gap-4">
    <section aria-label="API connection" className="rounded-lg border border-border-primary bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-text-primary">{status?.auth_required ? (status.connected ? `Connected as ${status.user?.name}` : "Connect to team analytics") : "Ask your analytics"}</h2>
          <p className="mt-1 max-w-2xl text-sm text-text-secondary">
            Explore metrics, ads, assets, data freshness, refresh runs, and table schemas.
            Read-only answers use the team’s OpenAI API account. Questions and relevant data are sent to OpenAI.
          </p>
        </div>
        {status?.auth_required && status.connected && <button type="button" onClick={disconnect} disabled={connecting || busy}
          className="rounded-md border border-border-primary px-3 py-2 text-sm text-text-primary hover:bg-bg-muted focus-visible:outline-2 focus-visible:outline-text-primary disabled:opacity-50">Disconnect API</button>}
      </div>
      {!status && !error && <p role="status" className="mt-3 text-sm text-text-secondary">Checking API connection…</p>}
      {status && !status.available && <p className="mt-3 text-sm text-text-secondary">{status.message}</p>}
      {status?.auth_required && status.available && !status.connected && <form onSubmit={connect} className="mt-4 max-w-lg">
        <label htmlFor="assistant-access-key" className="block text-sm font-medium text-text-primary">Your assistant access key</label>
        <p id="assistant-access-help" className="mt-1 text-xs text-text-secondary">Use the key issued by your dashboard administrator.</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <input id="assistant-access-key" type="password" value={accessKey} onChange={event => setAccessKey(event.target.value)}
            autoComplete="off" spellCheck={false} aria-describedby="assistant-access-help" required minLength={47} maxLength={47}
            disabled={connecting} className="min-w-0 flex-1 rounded-md border border-border-primary px-3 py-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-text-primary" />
          <button type="submit" disabled={!accessKey.trim() || connecting}
            className="rounded-md bg-text-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-text-primary disabled:opacity-50">
            {connecting ? "Connecting…" : "Connect API"}
          </button>
        </div>
      </form>}
      {status?.connected && !status.chat_enabled && <p role="status" className="mt-3 text-sm text-text-secondary">
        Your administrator needs to configure the OpenAI API key and model to enable chat here.
      </p>}
      {status?.auth_required && status.connected && status.mcp_url && <details className="mt-4 border-t border-border-primary pt-3 text-sm">
        <summary className="w-fit cursor-pointer rounded text-text-primary focus-visible:outline-2 focus-visible:outline-text-primary">Connect an MCP client</summary>
        <div className="mt-3 space-y-2 text-text-secondary">
          <p>Use Streamable HTTP with this server address:</p>
          <code className="block break-all rounded bg-bg-muted px-3 py-2 text-xs text-text-primary">{status.mcp_url}</code>
          <p>Set the Authorization header to <code className="text-xs">Bearer YOUR_ASSISTANT_ACCESS_KEY</code>. Your key grants the same read-only analytics access.</p>
        </div>
      </details>}
      {error && <p role="alert" className="mt-3 text-sm text-error-text">{error}</p>}
      {!status && error && <button type="button" onClick={() => { setError(null); setAttempt(n => n + 1); }}
        className="mt-3 rounded text-sm text-text-primary underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-text-primary">Check API connection again</button>}
    </section>
    {status?.connected && status.chat_enabled && <ChatAssistant key={version} allowUpload={false}
      transport={assistantAPITransport} onBusyChange={setBusy} onAccessError={accessError} />}
  </div>;
}
