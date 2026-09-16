"use client";

/**
 * Multi-Filter rule builder for Ads Analyse.
 *
 * Rows of (field, operator, value) combined by a join. Nothing is sent
 * until Apply — the same discipline as the date picker, because every
 * keystroke would otherwise be a request against an endpoint whose cold
 * path is measured in seconds.
 *
 * The rules are compiled and evaluated SERVER-side (see
 * `_multi_filter_sql` in app/api/routers/analytics.py). Filtering the
 * already-loaded rows here would narrow one page while appearing to
 * narrow the dataset — the defect that had the category tiles reading
 * "P2 analysis 3" against a real 1,768.
 *
 * The join deserves a word. AND and OR are obvious; NAND is the
 * complement of AND — "anything except ads matching all of these" —
 * which is how you exclude a combination rather than a single value.
 * Verified against live data: AND 63 + NAND 19,721 = 19,784 total.
 */

import { useState } from "react";
import { theme } from "@/lib/theme";

export type MultiFilterJoin = "and" | "or" | "nand";

export interface MultiFilterRule {
  field: string;
  op: string;
  value: string;
}

export interface MultiFilterState {
  join: MultiFilterJoin;
  rules: MultiFilterRule[];
}

const FIELDS: { key: string; label: string }[] = [
  { key: "ad_name", label: "Ad Name" },
  { key: "campaign_name", label: "Campaign" },
  { key: "adset_id", label: "Adset ID" },
  { key: "ad_id", label: "Ad ID" },
  { key: "category", label: "Category" },
  { key: "status", label: "Status" },
  { key: "account_name", label: "Account" },
];

const OPS: { key: string; label: string; keywordy: boolean }[] = [
  { key: "contains_all", label: "contains all of", keywordy: true },
  { key: "contains_any", label: "contains any of", keywordy: true },
  { key: "contains_none", label: "contains none of", keywordy: true },
  { key: "equals", label: "is exactly", keywordy: false },
  { key: "not_equals", label: "is not", keywordy: false },
  { key: "starts_with", label: "starts with", keywordy: false },
  { key: "ends_with", label: "ends with", keywordy: false },
];

const JOINS: { key: MultiFilterJoin; label: string; hint: string }[] = [
  { key: "and", label: "AND", hint: "Every rule must match" },
  { key: "or", label: "OR", hint: "At least one rule must match" },
  { key: "nand", label: "NAND", hint: "Everything EXCEPT ads matching all rules" },
];

/** App tokens. This started on the legacy dashboard's cream/gold, which
 *  made Ads Analyse the only tab not matching the rest of the panel. */
const AE = {
  cream: theme.bgMuted,
  border: theme.borderPrimary,
  muted: theme.textTertiary,
  ink: theme.textPrimary,
  brick: theme.accentYellow,
};

const EMPTY_RULE: MultiFilterRule = { field: "ad_name", op: "contains_all", value: "" };

export function MultiFilter({
  applied,
  onApply,
}: {
  applied: MultiFilterState | null;
  onApply: (state: MultiFilterState | null) => void;
}) {
  const [join, setJoin] = useState<MultiFilterJoin>(applied?.join ?? "and");
  const [rules, setRules] = useState<MultiFilterRule[]>(
    applied?.rules?.length ? applied.rules : [{ ...EMPTY_RULE }],
  );

  const dirtyCount = rules.filter((r) => r.value.trim()).length;
  const appliedCount = applied?.rules.length ?? 0;

  function update(i: number, patch: Partial<MultiFilterRule>) {
    setRules((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }

  return (
    <div className="rounded-lg border p-3" style={{ backgroundColor: AE.cream, borderColor: AE.border }}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: AE.muted }}>
            Multi-filter
          </span>
          {appliedCount > 0 && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ backgroundColor: theme.infoBg, color: theme.infoText }}
            >
              {appliedCount} rule{appliedCount === 1 ? "" : "s"} active
            </span>
          )}
          <div className="inline-flex overflow-hidden rounded-md border" style={{ borderColor: AE.border }}>
            {JOINS.map((j) => (
              <button
                key={j.key}
                onClick={() => setJoin(j.key)}
                title={j.hint}
                className="px-2.5 py-1 text-[11px] font-medium"
                style={{
                  backgroundColor: join === j.key ? AE.ink : "#FFFFFF",
                  color: join === j.key ? "#FFFFFF" : AE.ink,
                }}
              >
                {j.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => onApply(dirtyCount ? { join, rules: rules.filter((r) => r.value.trim()) } : null)}
            className="rounded-md px-4 py-1.5 text-sm font-medium text-white"
            style={{ backgroundColor: AE.brick }}
          >
            Apply
          </button>
          <button
            onClick={() => {
              setRules([{ ...EMPTY_RULE }]);
              setJoin("and");
              onApply(null);
            }}
            className="rounded-md border bg-white px-4 py-1.5 text-sm"
            style={{ borderColor: AE.border, color: AE.ink }}
          >
            Clear
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {rules.map((r, i) => {
          const op = OPS.find((o) => o.key === r.op);
          return (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <select
                value={r.field}
                onChange={(e) => update(i, { field: e.target.value })}
                className="w-44 rounded-md border bg-white px-2 py-2 text-sm"
                style={{ borderColor: AE.border, color: AE.ink }}
              >
                {FIELDS.map((f) => (
                  <option key={f.key} value={f.key}>{f.label}</option>
                ))}
              </select>
              <select
                value={r.op}
                onChange={(e) => update(i, { op: e.target.value })}
                className="w-44 rounded-md border bg-white px-2 py-2 text-sm"
                style={{ borderColor: AE.border, color: AE.ink }}
              >
                {OPS.map((o) => (
                  <option key={o.key} value={o.key}>{o.label}</option>
                ))}
              </select>
              <input
                value={r.value}
                onChange={(e) => update(i, { value: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && dirtyCount) {
                    onApply({ join, rules: rules.filter((x) => x.value.trim()) });
                  }
                }}
                placeholder={op?.keywordy ? "Keywords separated by space" : "Exact value"}
                className="min-w-[220px] flex-1 rounded-md border bg-white px-3 py-2 text-sm"
                style={{ borderColor: AE.border, color: AE.ink }}
              />
              <button
                onClick={() =>
                  setRules((rs) => (rs.length === 1 ? [{ ...EMPTY_RULE }] : rs.filter((_, j) => j !== i)))
                }
                title="Remove this rule"
                className="rounded-md border bg-white px-2 py-1.5 text-sm"
                style={{ borderColor: AE.border, color: AE.muted }}
              >
                ×
              </button>
            </div>
          );
        })}
      </div>

      <div className="mt-2 text-center">
        <button
          onClick={() => setRules((rs) => [...rs, { ...EMPTY_RULE }])}
          className="text-sm font-medium"
          style={{ color: AE.brick }}
        >
          + Add Rule
        </button>
      </div>

      <p className="mt-2 text-[11px]" style={{ color: AE.muted }}>
        {JOINS.find((j) => j.key === join)?.hint}. Keyword operators split the value on spaces.
        Rules are evaluated server-side across every matching ad, not just the rows in view.
      </p>
    </div>
  );
}

export default MultiFilter;
