"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  EntityMatch,
  HypothesisCreate,
  createMetaHypothesis,
  searchHypothesisEntity,
} from "@/lib/api";

/**
 * Recording a test from the dashboard instead of the sheet.
 *
 * The register's weak point is the entity column: it is typed from
 * memory, and only 32 of the sheet's 102 tests resolve to anything in
 * Meta -- so the other 70 can never be measured, however carefully they
 * were written. This form fixes that at the source. The campaign or ad
 * set is PICKED from Meta's own roster and its id is stored, so a test
 * entered here is measurable the moment it is saved.
 *
 * Everything but the hypothesis, category and KPI is optional, matching
 * how the sheet is actually filled in. A form that demanded all 25
 * fields would simply send the team back to the sheet, and the register
 * would fork.
 */

const STATUSES = ["Ongoing", "Done", "Dropped", "Planned"];

/** The field styling here is stacked label-over-input rather than the
 *  filter bar's inline pills: these are things you type, not things you
 *  pick between, and a caption above the box is what makes a long form
 *  scannable. */
const inputClass =
  "w-full rounded-md border border-border-primary bg-bg-white px-2.5 py-1.5 " +
  "text-[13px] text-text-primary outline-none placeholder:text-text-tertiary " +
  "focus:border-text-link";

function Field({
  label,
  hint,
  className = "",
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 ${className}`}>
      <span className="text-[11px] uppercase tracking-wide text-text-tertiary">
        {label}
        {hint ? <span className="ml-1 normal-case tracking-normal">· {hint}</span> : null}
      </span>
      {children}
    </div>
  );
}

/** The entity picker: type a few letters, pick the real campaign or ad
 *  set. Searching Meta's roster rather than accepting free text is the
 *  whole point of entering a test here. */
function EntityPicker({
  chosen,
  onChoose,
}: {
  chosen: EntityMatch | null;
  onChoose: (m: EntityMatch | null) => void;
}) {
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<EntityMatch[]>([]);
  const [searching, setSearching] = useState(false);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const term = q.trim();
    if (chosen || term.length < 2) return;
    // Debounced: the roster query is an ILIKE over two tables, and firing
    // it per keystroke would queue a request behind every letter.
    //
    // Every setState sits inside the timeout or the promise rather than
    // in the effect body, so typing does not cascade a render per
    // keystroke before the request has even been sent.
    let cancelled = false;
    const t = setTimeout(() => {
      setSearching(true);
      searchHypothesisEntity(term, 15)
        .then((r) => {
          if (!cancelled) {
            setMatches(r.matches);
            setOpen(true);
          }
        })
        .catch(() => { if (!cancelled) setMatches([]); })
        .finally(() => { if (!cancelled) setSearching(false); });
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q, chosen]);

  //: What is on screen must never outlive the text it came from: an
  //: emptied box shows no stale list, and the previous matches are gone
  //: the moment the query stops being the one that produced them.
  const shown = q.trim().length < 2 || chosen ? [] : matches;

  // Clicking away closes the list without choosing.
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  if (chosen) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-success-border bg-success-bg px-2.5 py-1.5">
        <span className="shrink-0 rounded bg-bg-white px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-text-secondary">
          {chosen.level}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px] text-text-primary" title={chosen.name}>
          {chosen.name}
        </span>
        <button
          type="button"
          onClick={() => { onChoose(null); setQ(""); }}
          className="shrink-0 text-[12px] text-text-link underline underline-offset-2"
        >
          Change
        </button>
      </div>
    );
  }

  return (
    <div ref={boxRef} className="relative">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => shown.length && setOpen(true)}
        placeholder="Type part of the campaign or ad set name…"
        className={inputClass}
      />
      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded-md border border-border-primary bg-bg-white shadow-lg">
          {searching && !shown.length ? (
            <p className="px-3 py-2 text-[12px] text-text-tertiary">Searching Meta…</p>
          ) : !shown.length ? (
            <p className="px-3 py-2 text-[12px] text-text-tertiary">
              Nothing in Meta matches that. Check the name in Ads Manager — a test saved
              without a real entity can never be measured.
            </p>
          ) : (
            shown.map((m) => (
              <button
                key={`${m.level}-${m.id}`}
                type="button"
                onClick={() => { onChoose(m); setOpen(false); }}
                className="flex w-full items-start gap-2 border-b border-border-soft px-3 py-2 text-left last:border-b-0 hover:bg-bg-muted/60"
              >
                <span className="mt-0.5 shrink-0 rounded bg-bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-text-secondary">
                  {m.level}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block break-words text-[12.5px] text-text-primary">{m.name}</span>
                  <span className="block text-[11px] text-text-tertiary">
                    {m.account_name ?? "—"}
                    {m.status ? ` · ${m.status}` : ""}
                  </span>
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

const EMPTY: HypothesisCreate = {
  hypothesis: "",
  test_category: "",
  primary_kpi: "",
  test_status: "Ongoing",
  hypothesis_code: "",
  success_criteria: "",
  test_threshold: "",
  confidence_interval: "",
  supporting_metrics: "",
  budget_per_day: "",
  ad_account: "",
  launch_date: "",
  completion_date: "",
};

export function AddHypothesis({
  categories,
  kpis,
  onSaved,
}: {
  /** Categories already in the register, so a new test joins an existing
   *  bucket instead of inventing a near-duplicate of one. */
  categories: string[];
  kpis: string[];
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<HypothesisCreate>(EMPTY);
  const [entity, setEntity] = useState<EntityMatch | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  //: Bumped on save, to remount the entity picker and clear its query.
  const [resetKey, setResetKey] = useState(0);

  const set = useCallback(
    (k: keyof HypothesisCreate, v: string) => {
      setSaved(null);
      setForm((f) => ({ ...f, [k]: v }));
    },
    [],
  );

  const ready =
    form.hypothesis.trim().length >= 5 &&
    form.test_category.trim().length >= 2 &&
    form.primary_kpi.trim().length >= 1;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready || saving) return;
    setSaving(true);
    setError(null);
    try {
      // Blank optional fields go as null, not "", so an unfilled box
      // reads as a dash in the table like every other missing cell
      // rather than as an empty string that silently sorts first.
      const blanked = Object.fromEntries(
        Object.entries(form).map(([k, v]) =>
          [k, typeof v === "string" && !v.trim() ? null : v]),
      );
      const body = blanked as HypothesisCreate;
      body.hypothesis = form.hypothesis.trim();
      body.test_category = form.test_category.trim();
      body.primary_kpi = form.primary_kpi.trim();
      body.test_status = form.test_status || "Ongoing";
      body.matched_level = entity?.level ?? null;
      body.matched_id = entity?.id ?? null;
      body.matched_name = entity?.name ?? null;

      const r = await createMetaHypothesis(body);
      setSaved(
        r.matched_name
          ? `Saved, linked to ${r.matched_name}.`
          : "Saved. No Meta entity linked, so this test will carry no metrics.",
      );
      setForm(EMPTY);
      setEntity(null);
      setResetKey((n) => n + 1);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => { setOpen(true); setSaved(null); }}
          className="rounded-md border border-border-primary bg-bg-white px-3 py-1.5 text-[13px] font-medium text-text-primary hover:bg-bg-muted/60"
        >
          + Add a test
        </button>
        {saved && <span className="text-[12px] text-success-text">{saved}</span>}
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-4 rounded-md border border-border-primary bg-bg-white p-4"
    >
      <div className="flex items-baseline justify-between">
        <h3 className="text-[14px] font-medium text-text-primary">Add a test</h3>
        <button
          type="button"
          onClick={() => { setOpen(false); setError(null); }}
          className="text-[12px] text-text-link underline underline-offset-2"
        >
          Close
        </button>
      </div>

      <Field
        label="Campaign or ad set in Meta"
        hint="pick it, don't type it — this is what makes the test measurable"
      >
        {/* Keyed on the save counter: the picker owns its query text, so
            remounting is what clears the old search along with the rest
            of the form. */}
        <EntityPicker key={resetKey} chosen={entity} onChoose={setEntity} />
      </Field>

      <Field label="Hypothesis & objective" hint="required">
        <textarea
          value={form.hypothesis}
          onChange={(e) => set("hypothesis", e.target.value)}
          rows={3}
          placeholder="Narrowing the exclusion window from 30 days to 1 click will lift purchase rate, because…"
          className={inputClass}
        />
      </Field>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Test category" hint="required">
          <input
            list="h-cat-list"
            value={form.test_category}
            onChange={(e) => set("test_category", e.target.value)}
            placeholder="Audience, Creative…"
            className={inputClass}
          />
          <datalist id="h-cat-list">
            {categories.map((c) => <option key={c} value={c} />)}
          </datalist>
        </Field>

        <Field label="Primary KPI" hint="required">
          <input
            list="h-kpi-list"
            value={form.primary_kpi}
            onChange={(e) => set("primary_kpi", e.target.value)}
            placeholder="CPP, ROAS, CTR…"
            className={inputClass}
          />
          <datalist id="h-kpi-list">
            {kpis.map((k) => <option key={k} value={k} />)}
          </datalist>
        </Field>

        <Field label="Status">
          <select
            value={form.test_status ?? "Ongoing"}
            onChange={(e) => set("test_status", e.target.value)}
            className={inputClass}
          >
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>

        <Field label="Hypothesis code">
          <input
            value={form.hypothesis_code ?? ""}
            onChange={(e) => set("hypothesis_code", e.target.value)}
            placeholder="H-042"
            className={inputClass}
          />
        </Field>

        <Field label="Success criteria" className="sm:col-span-2">
          <input
            value={form.success_criteria ?? ""}
            onChange={(e) => set("success_criteria", e.target.value)}
            placeholder="CPP below ₹450 over 7 days"
            className={inputClass}
          />
        </Field>

        <Field label="Test threshold">
          <input
            value={form.test_threshold ?? ""}
            onChange={(e) => set("test_threshold", e.target.value)}
            placeholder="≥ 50 purchases"
            className={inputClass}
          />
        </Field>

        <Field label="Confidence interval">
          <input
            value={form.confidence_interval ?? ""}
            onChange={(e) => set("confidence_interval", e.target.value)}
            placeholder="95%"
            className={inputClass}
          />
        </Field>

        <Field label="Supporting metrics" className="sm:col-span-2">
          <input
            value={form.supporting_metrics ?? ""}
            onChange={(e) => set("supporting_metrics", e.target.value)}
            placeholder="CTR, ATC rate, frequency"
            className={inputClass}
          />
        </Field>

        <Field label="Budget allocated / day">
          <input
            value={form.budget_per_day ?? ""}
            onChange={(e) => set("budget_per_day", e.target.value)}
            placeholder="2000"
            className={inputClass}
          />
        </Field>

        <Field label="Ad account">
          <input
            value={form.ad_account ?? ""}
            onChange={(e) => set("ad_account", e.target.value)}
            placeholder={entity?.account_name ?? "Fourth Ad Account - SD"}
            className={inputClass}
          />
        </Field>

        <Field label="Launch date" hint="the day it went live in Meta">
          <input
            type="date"
            value={form.launch_date ?? ""}
            onChange={(e) => set("launch_date", e.target.value)}
            className={inputClass}
          />
        </Field>

        <Field label="Completion date" hint="leave blank while running">
          <input
            type="date"
            value={form.completion_date ?? ""}
            onChange={(e) => set("completion_date", e.target.value)}
            className={inputClass}
          />
        </Field>
      </div>

      {error && (
        <p className="rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-[12.5px] text-warning-text">
          {error}
        </p>
      )}

      {saved && !error && (
        <p className="rounded-md border border-success-border bg-success-bg px-3 py-2 text-[12.5px] text-success-text">
          {saved} It is in the register below — sorted by launch date, so a test
          saved without one sits at the bottom.
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={!ready || saving}
          className="rounded-md bg-text-primary px-4 py-1.5 text-[13px] font-medium text-bg-white disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save test"}
        </button>
        {!ready && (
          <span className="text-[12px] text-text-tertiary">
            Hypothesis, category and primary KPI are needed.
          </span>
        )}
        {!entity && ready && (
          <span className="text-[12px] text-text-tertiary">
            No Meta entity picked — the test will be recorded but carries no metrics.
          </span>
        )}
      </div>
    </form>
  );
}
