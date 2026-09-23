import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

// A data: module cannot resolve a bare specifier, so react and the JSX
// runtime are rewritten to absolute file URLs before the source is
// encoded. Same trick the other suites use for their relative imports.
function asModule(source) {
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });
  const resolved = outputText.replace(
    /from "(react\/jsx-runtime|react)"/g,
    (_m, spec) => `from "${import.meta.resolve(spec)}"`,
  );
  return `data:text/javascript;base64,${Buffer.from(resolved).toString("base64")}`;
}

const infoDotSrc = await readFile(new URL("../src/app/user/analytics/InfoDot.tsx", import.meta.url), "utf8");
const { InfoDot } = await import(asModule(infoDotSrc));
const adsAnalyseSrc = await readFile(new URL("../src/app/user/analytics/AdsAnalyse.tsx", import.meta.url), "utf8");

test("the dot is not a button, so it can sit inside one", () => {
  const html = renderToStaticMarkup(createElement(InfoDot, { basis: "why this number" }));
  // Every tile that carries a dot is itself a <button>. A nested button
  // is invalid HTML; this is the assertion that keeps it a <span>.
  assert.equal(/<button/.test(html), false);
  assert.match(html, /cursor-help/);
  assert.match(html, /aria-label="What this number is based on"/);
});

test("the panel stays closed until hover or focus", () => {
  const html = renderToStaticMarkup(createElement(InfoDot, { basis: "why this number" }));
  assert.equal(html.includes("why this number"), false);
  assert.equal(/role="tooltip"/.test(html), false);
});

test("the open panel can never swallow a click meant for the tile", () => {
  // Rendered only on hover, so it cannot be asserted from static
  // markup -- checked at the source instead.
  const panel = infoDotSrc.slice(infoDotSrc.indexOf('role="tooltip"'));
  assert.match(panel, /pointer-events-none/);
});

test("every verdict tile states its basis", () => {
  const decl = adsAnalyseSrc.indexOf("const DECISION_TILES");
  const tiles = adsAnalyseSrc.slice(
    adsAnalyseSrc.indexOf("[", decl),          // past `basis: InfoBasis`, a type
    adsAnalyseSrc.indexOf("function DecisionBadge"),
  );
  const keys = [...tiles.matchAll(/key: "(\w+)"/g)].map((m) => m[1]);
  // OK and UNRATED have no tile: every tile names something to DO, and
  // those two name its absence. Both still exist on the rows and as a
  // `decision` filter value.
  assert.deepEqual(keys, ["SCALE", "PAUSE", "MONITOR", "REPORT"]);
  // One `basis:` per tile, and none left on the old free-text `hint:`.
  assert.equal([...tiles.matchAll(/\bbasis:/g)].length, keys.length);
  assert.equal(/\bhint:/.test(tiles), false);
});

test("every ad category states its basis", () => {
  const order = adsAnalyseSrc.slice(
    adsAnalyseSrc.indexOf("const CATEGORY_ORDER"),
    adsAnalyseSrc.indexOf("const CATEGORY_CLASS"),
  );
  const cats = [...order.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  const rules = adsAnalyseSrc.slice(
    adsAnalyseSrc.indexOf("const CATEGORY_RULE"),
    adsAnalyseSrc.indexOf("function categoryBasis"),
  );
  for (const cat of cats) {
    assert.ok(rules.includes(`"${cat}"`) || rules.includes(`\n  ${cat}:`),
      `no rule text for category ${cat}`);
  }
});

test("a category tile does not claim its spend covers the filter set", () => {
  const basis = adsAnalyseSrc.slice(
    adsAnalyseSrc.indexOf("function categoryBasis"),
    adsAnalyseSrc.indexOf("const CATEGORY_ICON: Record"),
  );
  // The count covers every matching ad; the spend only sums what is
  // loaded. Conflating them is the defect this text exists to stop, so
  // each line must say which set it describes. Matched on the meaning
  // rather than an exact sentence, so rewording the copy for clarity
  // does not fail the test that guards the distinction.
  assert.match(basis, /spend:[\s\S]*loaded so far/i);
  assert.match(basis, /count:[\s\S]*not only the ones visible/i);
});
