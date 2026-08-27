import { ChatAssistant } from "./ChatAssistant";

export default function AssistantPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">AI Assistant</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Ask about the data in plain language — it can browse the schema, discover JSONB fields,
          and run read-only SQL queries. It has no write access at all: there is no tool it can
          use to create, alter, or delete anything.
        </p>
      </div>
      <ChatAssistant />
    </div>
  );
}
