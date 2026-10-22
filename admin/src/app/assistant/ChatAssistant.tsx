"use client";

import { useEffect, useId, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ApiError,
  AssistantModel,
  ChatMessage,
  ChatResponse,
  ContextDocument,
  fetchAssistantModels,
  fetchContextDocuments,
  sendChatMessage,
  uploadContextDocument,
} from "@/lib/api";

export function AssistantMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto">
            <table className="border-collapse text-xs">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-bg-muted/70">{children}</thead>,
        th: ({ children }) => (
          <th className="border border-border-mid px-2 py-1 text-left font-medium text-text-primary">{children}</th>
        ),
        td: ({ children }) => <td className="border border-border-mid px-2 py-1 text-text-primary">{children}</td>,
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        ul: ({ children }) => <ul className="mb-2 list-disc pl-5 last:mb-0">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 list-decimal pl-5 last:mb-0">{children}</ol>,
        code: ({ children }) => (
          <code className="rounded bg-bg-muted/70 px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
        ),
        pre: ({ children }) => (
          <pre className="mb-2 overflow-x-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100 last:mb-0">
            {children}
          </pre>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

interface ChatTransport {
  models: () => Promise<AssistantModel[]>;
  send: (messages: ChatMessage[], model?: string) => Promise<ChatResponse>;
}

export function ChatAssistant({ allowUpload = true, transport, onBusyChange, onAccessError }: {
  allowUpload?: boolean;
  transport?: ChatTransport;
  onBusyChange?: (busy: boolean) => void;
  onAccessError?: (error: unknown) => void;
}) {
  const analyticsMode = !allowUpload;
  const modelId = useId();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<ContextDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [models, setModels] = useState<AssistantModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const modelRequestRef = useRef<{ load: () => Promise<AssistantModel[]>; result: Promise<AssistantModel[]> } | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    let cancelled = false;
    if (allowUpload) {
      fetchContextDocuments()
        .then((res) => { if (!cancelled) setDocuments(res); })
        .catch(() => {
          if (!cancelled) setUploadError("Context documents could not be loaded.");
        });
    }
    const loadModels = transport?.models ?? fetchAssistantModels;
    if (!modelRequestRef.current || modelRequestRef.current.load !== loadModels) {
      modelRequestRef.current = { load: loadModels, result: loadModels() };
    }
    modelRequestRef.current.result
      .then((res) => {
        if (cancelled) return;
        setModels(res);
        setSelectedModel((prev) => prev || res[0]?.id || "");
      })
      .catch((err) => {
        if (!cancelled) {
          setSetupError(err instanceof Error ? err.message : "Could not load assistant models. Reload this page to try again.");
          onAccessError?.(err);
        }
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });
    return () => { cancelled = true; };
  }, [allowUpload, transport, onAccessError]);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading || modelsLoading || setupError) return;
    if (messages.length >= 38) {
      setError("Start a new conversation to keep answers focused and responsive.");
      return;
    }

    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    onBusyChange?.(true);
    setError(null);

    try {
      const res = transport
        ? await transport.send(nextMessages, selectedModel || undefined)
        : await sendChatMessage(nextMessages, selectedModel || undefined, analyticsMode ? "analytics" : "database");
      setMessages((prev) => [...prev, { role: "assistant", content: res.message, sources: res.sources }]);
    } catch (err) {
      setMessages(nextMessages.slice(0, -1));
      setInput(text);
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
      onAccessError?.(err);
    } finally {
      setLoading(false);
      onBusyChange?.(false);
    }
  }

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      const doc = await uploadContextDocument(file);
      setDocuments((prev) => [doc, ...prev]);
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <div className={`flex min-h-[28rem] flex-col gap-4 lg:flex-row ${transport ? "lg:h-[calc(100dvh-22rem)]" : "lg:h-[calc(100vh-14rem)]"}`}>
      <div className="flex min-w-0 flex-1 flex-col rounded-lg border border-border-primary bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-border-primary px-4 py-2.5">
          <span className="text-sm text-text-secondary">{analyticsMode ? "Ask about your analytics" : "Explore your database"}</span>
          <button type="button" disabled={loading || messages.length === 0} onClick={() => { setMessages([]); setInput(""); setError(null); }}
            className="rounded px-2 py-1 text-sm text-text-secondary hover:bg-bg-muted focus-visible:outline-2 focus-visible:outline-accent-yellow disabled:opacity-50">
            New conversation
          </button>
        </div>
        {models.length > 0 && (
          <div className="border-b border-border-primary px-4 py-2.5">
            <div className="flex items-center gap-2">
              <label htmlFor={modelId} className="text-xs font-medium text-text-secondary">Model</label>
              <select
                id={modelId}
                disabled={loading}
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs text-text-primary focus:border-accent-yellow focus:outline-none"
              >
                {models.filter(m => m.provider === "chatgpt" || m.provider === "openai").map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                {!transport && <>
                <optgroup label="Cloudflare Workers AI">
                  {models
                    .filter((m) => m.provider === "cloudflare")
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                </optgroup>
                <optgroup label="Claude (extra cost — use sparingly)">
                  {models
                    .filter((m) => m.provider === "anthropic")
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                </optgroup>
                </>}
              </select>
            </div>
            {(() => {
              const note = models.find((m) => m.id === selectedModel)?.note;
              return note ? (
                <p className="mt-1.5 text-[11px] text-warning-text">⚠ {note}</p>
              ) : null;
            })()}
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {messages.length === 0 && (
            <p className="text-sm text-text-secondary">
              {analyticsMode
                ? "Ask about performance, data freshness, refresh runs, or tables. Answers include sources and filters. Try: “Is our data up to date?” or “Did the latest daily refresh succeed?”"
                : "Ask about the database or uploaded context documents. This assistant can read data but cannot change it."}
            </p>
          )}

          <div className="flex flex-col gap-4">
            {messages.map((message, messageIndex) => (
              <div
                key={messageIndex}
                className={`flex flex-col gap-2 ${message.role === "user" ? "items-end" : "items-start"}`}
              >
                <div
                  className={`max-w-[95%] break-words rounded-lg px-3 py-2 text-sm sm:max-w-[85%] ${
                    message.role === "user"
                      ? "whitespace-pre-wrap bg-accent-yellow text-white"
                      : "bg-bg-muted text-text-primary"
                  }`}
                >
                  {message.role === "user" ? (
                    message.content
                  ) : (
                    <AssistantMarkdown content={message.content} />
                  )}
                </div>
                {message.role === "assistant" && (message.sources?.length ?? 0) > 0 && (
                  <details className="max-w-full text-sm text-text-secondary">
                    <summary className="cursor-pointer rounded py-1 focus-visible:outline-2 focus-visible:outline-accent-yellow">Sources and filters ({message.sources!.length})</summary>
                    <ul className="mt-2 space-y-3">
                      {message.sources!.map((source, i) => (
                        <li key={`${source.url}-${i}`} className="break-words">
                          <a href={source.url.startsWith("/user/analytics#") ? source.url : "/user/analytics"}
                            className="font-medium text-text-primary underline underline-offset-2">{source.label}</a>
                          <p>{source.basis}</p>
                          <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                            {Object.entries(source.filters).filter(([, value]) => value !== null && value !== false).map(([key, value]) => (
                              <div key={key}><dt className="inline">{key.replace(/_/g, " ")}: </dt><dd className="inline text-text-primary">{String(value)}</dd></div>
                            ))}
                          </dl>
                          <p className="mt-1">{source.cache_note}</p>
                          <p>{source.link_note}</p>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            ))}

            {modelsLoading && <p role="status" className="text-sm text-text-secondary">Loading assistant…</p>}
            {loading && <p role="status" className="text-sm text-text-secondary">Checking your question and data…</p>}
            {setupError && <p role="alert" className="text-sm text-error-text">{setupError}</p>}
            {error && <p role="alert" className="text-sm text-error-text">{error}</p>}
          </div>
          <div ref={bottomRef} />
        </div>

        <div className="flex gap-2 border-t border-border-primary p-4">
          <textarea
            aria-label="Your question"
            disabled={loading || modelsLoading || !!setupError}
            maxLength={12000}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask about the data…"
            rows={2}
            className="min-w-0 flex-1 resize-none rounded-md border border-border-primary bg-white px-3 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus:border-accent-yellow focus:outline-none"
          />
          <button
            onClick={handleSend}
            disabled={loading || modelsLoading || !!setupError || !input.trim()}
            className="self-end rounded-md bg-accent-yellow px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-yellow-hover disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>

      {allowUpload && <div className="flex w-full flex-col rounded-lg border border-border-primary bg-white p-4 lg:w-72">
        <h2 className="text-sm font-medium text-text-primary">Context documents</h2>
        <p className="mt-1 text-xs text-text-secondary">
          Upload .md or .pptx files with business context -- the assistant can read these when answering.
        </p>

        {allowUpload && (
          <>
            <label className="mt-3 flex cursor-pointer items-center justify-center rounded-md border border-dashed border-border-mid px-3 py-4 text-xs text-text-secondary hover:border-accent-yellow hover:text-text-primary">
              {uploading ? "Uploading…" : "Choose a file…"}
              <input
                ref={fileInputRef}
                type="file"
                accept=".md,.txt,.pptx"
                className="hidden"
                disabled={uploading}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleUpload(file);
                }}
              />
            </label>
            {uploadError && <p className="mt-2 text-xs text-error-text">{uploadError}</p>}
          </>
        )}

        <ul className="mt-4 flex flex-col gap-2 overflow-y-auto">
          {documents.map((doc) => (
            <li key={doc.id} className="rounded-md border border-border-primary bg-bg-surface p-2">
              <p className="truncate text-xs font-medium text-text-primary">{doc.filename}</p>
              <p className="mt-0.5 text-[11px] text-text-secondary">{doc.char_count.toLocaleString()} chars</p>
            </li>
          ))}
          {documents.length === 0 && <p className="text-xs text-text-tertiary">No documents uploaded yet.</p>}
        </ul>
      </div>}
    </div>
  );
}
