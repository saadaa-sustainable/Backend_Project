import { ChatAssistant } from "@/app/assistant/ChatAssistant";

export default function UserAssistantPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">AI Assistant</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Ask questions about the data in plain language — read-only, backed by the live database.
        </p>
      </div>
      <ChatAssistant allowUpload={false} />
    </div>
  );
}
