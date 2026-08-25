"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ApiError,
  AssistantModel,
  ChatMessage,
  ContextDocument,
  fetchAssistantModels,
  fetchContextDocuments,
  sendChatMessage,
  uploadContextDocument,
} from "@/lib/api";

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto">
            <table className="border-collapse text-xs">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-slate-200/70">{children}</thead>,
        th: ({ children }) => (
          <th className="border border-slate-300 px-2 py-1 text-left font-medium text-slate-700">{children}</th>
        ),
        td: ({ children }) => <td className="border border-slate-300 px-2 py-1 text-slate-800">{children}</td>,
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        ul: ({ children }) => <ul className="mb-2 list-disc pl-5 last:mb-0">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 list-decimal pl-5 last:mb-0">{children}</ol>,
        code: ({ children }) => (
          <code className="rounded bg-slate-200/70 px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
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

export function ChatAssistant() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<ContextDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [models, setModels] = useState<AssistantModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    fetchContextDocuments()
      .then(setDocuments)
      .catch(() => {
        // Context documents are optional context, not core functionality --
        // silently leaving the panel empty is fine if this fails.
      });
    fetchAssistantModels()
      .then((res) => {
        setModels(res);
        setSelectedModel((prev) => prev || res[0]?.id || "");
      })
      .catch(() => {
        // Falls back to the backend's own default model if this fails --
        // the dropdown just won't show.
      });
  }, []);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const res = await sendChatMessage(nextMessages, selectedModel || undefined);
      setMessages((prev) => [...prev, { role: "assistant", content: res.message }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
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
    <div className="flex h-[calc(100vh-14rem)] flex-col gap-4 lg:flex-row">
      <div className="flex flex-1 flex-col rounded-lg border border-slate-200 bg-white">
        {models.length > 0 && (
          <div className="border-b border-slate-200 px-4 py-2.5">
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-slate-500">Model</label>
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-800 focus:border-sky-500 focus:outline-none"
              >
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
              </select>
            </div>
            {(() => {
              const note = models.find((m) => m.id === selectedModel)?.note;
              return note ? (
                <p className="mt-1.5 text-[11px] text-amber-700">⚠ {note}</p>
              ) : null;
            })()}
          </div>
        )}
        <div className="flex-1 overflow-y-auto p-5">
          {messages.length === 0 && (
            <p className="text-sm text-slate-500">
              Ask about the data -- e.g. &ldquo;How many Instagram posts does saadaadesigns have?&rdquo; This
              assistant is read-only: it can query the database and read uploaded context documents, but it
              cannot create, alter, or delete anything.
            </p>
          )}

          <div className="flex flex-col gap-4">
            {messages.map((message, messageIndex) => (
              <div
                key={messageIndex}
                className={`flex flex-col gap-2 ${message.role === "user" ? "items-end" : "items-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                    message.role === "user"
                      ? "whitespace-pre-wrap bg-sky-600 text-white"
                      : "bg-slate-100 text-slate-900"
                  }`}
                >
                  {message.role === "user" ? (
                    message.content
                  ) : (
                    <AssistantMarkdown content={message.content} />
                  )}
                </div>
              </div>
            ))}

            {loading && <p className="text-sm text-slate-500">Thinking…</p>}
            {error && <p className="text-sm text-red-600">{error}</p>}
          </div>
          <div ref={bottomRef} />
        </div>

        <div className="flex gap-2 border-t border-slate-200 p-4">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask about the data…"
            rows={2}
            className="flex-1 resize-none rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:outline-none"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="self-end rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>

      <div className="flex w-full flex-col rounded-lg border border-slate-200 bg-white p-4 lg:w-72">
        <h2 className="text-sm font-medium text-slate-900">Context documents</h2>
        <p className="mt-1 text-xs text-slate-500">
          Upload .md or .pptx files with business context -- the assistant can read these when answering.
        </p>

        <label className="mt-3 flex cursor-pointer items-center justify-center rounded-md border border-dashed border-slate-300 px-3 py-4 text-xs text-slate-500 hover:border-sky-400 hover:text-slate-700">
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
        {uploadError && <p className="mt-2 text-xs text-red-600">{uploadError}</p>}

        <ul className="mt-4 flex flex-col gap-2 overflow-y-auto">
          {documents.map((doc) => (
            <li key={doc.id} className="rounded-md border border-slate-200 bg-slate-50 p-2">
              <p className="truncate text-xs font-medium text-slate-800">{doc.filename}</p>
              <p className="mt-0.5 text-[11px] text-slate-500">{doc.char_count.toLocaleString()} chars</p>
            </li>
          ))}
          {documents.length === 0 && <p className="text-xs text-slate-400">No documents uploaded yet.</p>}
        </ul>
      </div>
    </div>
  );
}
