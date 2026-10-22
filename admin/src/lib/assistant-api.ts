import type { AssistantModel, ChatMessage, ChatResponse } from "./api";

export interface AssistantAPIStatus {
  available: boolean;
  connected: boolean;
  chat_enabled: boolean;
  auth_required: boolean;
  message?: string;
  user?: { name: string };
  mcp_url?: string;
}

export class AssistantAPIError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function assistantAPIRequest<T>(action: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/assistant/api/${action}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin", cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
      // Backend chat has a 240s budget; allow its timeout response to reach the UI.
      signal: AbortSignal.timeout(action === "chat" ? 260_000 : 15_000),
    });
  } catch {
    throw new AssistantAPIError("Could not reach the API assistant. Stopped without retrying.", 503);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new AssistantAPIError(typeof data.detail === "string" ? data.detail : "The API assistant request failed. Check your connection and try again.", response.status);
  return data as T;
}

export const assistantAPITransport = {
  models: () => assistantAPIRequest<AssistantModel[]>("models"),
  send: (messages: ChatMessage[], model?: string) => assistantAPIRequest<ChatResponse>("chat", {
    messages: messages.map(({ role, content }) => ({ role, content })), model, mode: "analytics",
  }),
};
