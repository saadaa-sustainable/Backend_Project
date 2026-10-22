import AssistantConnections from "./AssistantConnections";

export default async function UserAssistantPage({ searchParams }: {
  searchParams: Promise<{ assistant?: string; chatgpt_error?: string }>;
}) {
  const query = await searchParams;
  const initialMode = query.assistant === "chatgpt" || query.chatgpt_error ? "chatgpt" : "api";
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">AI Assistant</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-secondary">
          Ask questions about your dashboard data. Answers include the reporting period, filters, and sources.
        </p>
      </div>
      <AssistantConnections initialMode={initialMode} />
    </div>
  );
}
