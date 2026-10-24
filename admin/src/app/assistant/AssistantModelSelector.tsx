import type { AssistantModel } from "@/lib/api";

const PROVIDERS = [
  ["openai", "GPT · OpenAI"], ["anthropic", "Claude · Anthropic"],
  ["chatgpt", "ChatGPT account"], ["cloudflare", "Cloudflare Workers AI"],
] as const;

export function AssistantModelSelector({ id, models, selected, disabled, onSelect, onRefresh, refreshing = false }: {
  id: string;
  models: AssistantModel[];
  selected: string;
  disabled: boolean;
  onSelect: (model: string) => void;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  const note = models.find(model => model.id === selected)?.note;
  return <div className="border-b border-border-primary px-4 py-2.5">
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor={id} className="text-xs font-medium text-text-secondary">Model</label>
      <select id={id} disabled={disabled} value={selected} aria-describedby={note ? `${id}-note` : undefined}
        onChange={event => onSelect(event.target.value)}
        className="min-w-0 max-w-full rounded-md border border-border-primary bg-white px-2 py-1.5 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-text-primary disabled:opacity-50">
        {PROVIDERS.map(([provider, label]) => {
          const choices = models.filter(model => model.provider === provider);
          return choices.length > 0 ? <optgroup key={provider} label={label}>
            {choices.map(model => <option key={model.id} value={model.id} disabled={model.available === false}>
              {model.label}{model.available === false ? " — not connected" : ""}
            </option>)}
          </optgroup> : null;
        })}
      </select>
      {onRefresh && <button type="button" onClick={onRefresh} disabled={disabled}
        className="rounded px-2 py-1.5 text-sm text-text-secondary underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-text-primary disabled:opacity-50">
        {refreshing ? "Refreshing models…" : "Refresh models"}
      </button>}
    </div>
    {note && <p id={`${id}-note`} className="mt-1.5 text-xs text-text-secondary">{note}</p>}
  </div>;
}
