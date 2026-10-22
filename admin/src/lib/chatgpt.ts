import type { AssistantModel, ChatMessage, ChatResponse } from "./api";

export interface ChatGPTStatus {
  available: boolean;
  connected: boolean;
  plan_enabled: boolean;
  message?: string;
  user?: { name: string | null; email: string };
}

export class ChatGPTError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function chatgptRequest<T>(action: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/assistant/chatgpt/${action}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin", cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(action === "chat" ? 260_000 : 45_000),
    });
  } catch {
    throw new ChatGPTError("Could not reach the assistant. Stopped without retrying.", 503);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ChatGPTError(typeof data.detail === "string" ? data.detail : "The assistant request failed. Try again.", response.status);
  return data as T;
}

export const chatgptTransport = {
  models: () => chatgptRequest<AssistantModel[]>("models"),
  send: (messages: ChatMessage[], model?: string) => chatgptRequest<ChatResponse>("chat", {
    messages: messages.map(({ role, content }) => ({ role, content })), model, mode: "analytics",
  }),
};
