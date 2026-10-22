"use client";

import { useState } from "react";
import ChatGPTAssistant from "./ChatGPTAssistant";
import APIAssistant from "./APIAssistant";

export default function AssistantConnections({ initialMode = "api" }: { initialMode?: "chatgpt" | "api" }) {
  const [mode, setMode] = useState<"chatgpt" | "api">(initialMode);
  const [apiOpened, setAPIOpened] = useState(initialMode === "api");
  const [chatGPTOpened, setChatGPTOpened] = useState(initialMode === "chatgpt");
  return <div className="flex min-w-0 flex-col gap-4">
    <fieldset className="flex flex-wrap gap-2">
      <legend className="sr-only">Assistant connection</legend>
      {([ ["api", "API chat"], ["chatgpt", "ChatGPT account"] ] as const).map(([value, label]) =>
        <label key={value} className="cursor-pointer">
          <input type="radio" name="assistant-connection" value={value} checked={mode === value} className="peer sr-only"
            onChange={() => { setMode(value); if (value === "chatgpt") setChatGPTOpened(true); else setAPIOpened(true); }} />
          <span className="block rounded-md border border-border-primary px-4 py-2 text-sm text-text-primary hover:bg-bg-muted peer-checked:bg-text-primary peer-checked:text-white peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-text-primary">{label}</span>
        </label>)}
    </fieldset>
    {/* Keep each conversation mounted when switching; only the chosen provider handles a send. */}
    {chatGPTOpened && <div hidden={mode !== "chatgpt"}><ChatGPTAssistant /></div>}
    {apiOpened && <div hidden={mode !== "api"}><APIAssistant /></div>}
  </div>;
}
