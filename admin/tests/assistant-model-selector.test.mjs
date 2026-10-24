import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = await readFile(new URL("../src/app/assistant/AssistantModelSelector.tsx", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022, jsx: ts.JsxEmit.ReactJSX,
} }).outputText.replaceAll('"react/jsx-runtime"', JSON.stringify(import.meta.resolve("react/jsx-runtime")));
const { AssistantModelSelector } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

const models = [
  { id: "gpt", label: "GPT", provider: "openai", available: true, note: "OpenAI API account" },
  { id: "claude", label: "Claude Sonnet", provider: "anthropic", available: true, note: "Anthropic API credits" },
];
function render(props = {}) {
  return renderToStaticMarkup(createElement(AssistantModelSelector, {
    id: "model-choice", models, selected: "claude", disabled: false, onSelect() {}, ...props,
  }));
}
test("API selector renders Claude and GPT together with the chosen model and billing account", () => {
  const html = render();
  assert.match(html, /<label[^>]+for="model-choice"/);
  assert.match(html, /<optgroup label="GPT · OpenAI">/);
  assert.match(html, /<optgroup label="Claude · Anthropic">/);
  assert.match(html, /<option value="claude" selected="">Claude Sonnet<\/option>/);
  assert.match(html, /Anthropic API credits/);
  assert.doesNotMatch(html, /Cloudflare|ChatGPT account/);
});
test("unconfigured Claude stays visible but cannot be selected", () => {
  const html = render({ selected: "gpt", models: [models[0], { ...models[1], available: false }] });
  assert.match(html, /<option value="claude" disabled="">Claude Sonnet — not connected<\/option>/);
  assert.match(html, /OpenAI API account/);
});
test("model switching is disabled while the answer is running", () => {
  assert.match(render({ disabled: true }), /<select[^>]+disabled=""/);
});

test("manual model refresh is available and disabled while a request is running", () => {
  assert.match(render({ onRefresh() {} }), /<button[^>]+type="button"[^>]*>Refresh models<\/button>/);
  const busy = render({ onRefresh() {}, refreshing: true, disabled: true });
  assert.match(busy, /<button[^>]+disabled=""[^>]*>Refreshing models…<\/button>/);
});
