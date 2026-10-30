"use client";

/**
 * The four bands every analytics section is built from.
 *
 * One file, because the sections drifted: Ads Analyse used custom card
 * selects, Last Click UTM used native <select>s, CPIS used a third
 * shape, and each grew its own KPI treatment. Three control styles on
 * one surface is three things to learn.
 *
 * The grammar is the surface brief's, not mine:
 *
 *   "Rules, never boxes: hairlines separate rows and sections, and
 *    nothing on the surface carries both a border and a shadow."
 *   "Filters sit on one rule above the table as labelled cells, not
 *    floating selects."
 *   "the verdict band -- SCALE / PAUSE / MONITOR as flat colour fields
 *    carrying counts, spanning the content width, not cards."
 *   "Isotype's own label register: small caps, tracked out, above every
 *    column and field."
 *
 * So: no card wrappers, no rounded tiles, no shadows. A section is a
 * title on a rule, a filter rule, a figure band, and the table.
 */

import { useState } from "react";
import { MarkHelp, MarkChevron } from "./Pictograms";

/* ── labels ──────────────────────────────────────────────────────── */

/** The label register: small caps, tracked out, above the thing. */
export function FieldLabel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`block text-[10px] font-semibold uppercase tracking-[0.08em] text-text-tertiary ${className}`}>
      {children}
    </span>
  );
}

/* ── band 1: the section's name on a rule ────────────────────────── */

export function SectionHeader({
  title,
  helpId,
  children,
}: {
  title: string;
  /** Article in the Help section this title's `?` opens. */
  helpId?: string;
  /** Controls that belong to the title rather than the filters -- a
   *  level toggle, a view switch. Right-aligned. */
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-primary pb-2.5">
      <div className="flex items-center gap-2">
        <h2 className="m-0 text-[18px] font-semibold tracking-[-0.02em] text-text-primary">{title}</h2>
        {helpId && (
          <a
            href={`#help`}
            aria-label={`Help for ${title}`}
            title={`Help for ${title}`}
            className="inline-flex text-text-tertiary transition-colors hover:text-text-primary"
          >
            <MarkHelp />
          </a>
        )}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/**
 * A choice between two or three views of the same data.
 *
 * Distinct from a filter: a segmented control never refetches and never
 * narrows the rows -- it swaps which cells of the response are shown
 * (Ads-that-name-it against Its-share-of-spend, Equal against
 * Value-weighted, Ads against Ad Sets). Filters narrow; these reframe.
 * Keeping them out of the filter rule is what makes the rule's own
 * count of set filters honest.
 */
export function Segmented({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: string; title?: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-0.5" role="group">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            title={o.title}
            aria-pressed={on}
            onClick={() => onChange(o.value)}
            className={`px-2.5 py-1 text-[12.5px] transition-colors ${
              on
                ? "bg-text-primary font-medium text-bg-white"
                : "text-text-secondary hover:bg-bg-surface hover:text-text-primary"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* ── band 2: filters, as labelled cells on one rule ──────────────── */

export function FilterRule({
  children,
  extra,
  extraCount = 0,
  actions,
}: {
  /** Always-visible cells. Keep to four or five; the rest go in `extra`. */
  children: React.ReactNode;
  /** Cells revealed by "More filters". */
  extra?: React.ReactNode;
  /** How many of the hidden filters are currently set, shown on the toggle. */
  extraCount?: number;
  /** Export, column picker, inspector -- right-aligned, never wrapping
   *  into the filter cells. */
  actions?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  /* The approved design draws this as one bordered bar of rounded pill
     controls, not as underlined cells on a hairline. An earlier pass
     followed the surface brief's "rules, never boxes" and produced the
     underlined version; the design the user signed off is the bar, and
     it wins. The bar carries a border and NO shadow, so the one rule
     the brief is unambiguous about still holds. */
  return (
    <div className="flex flex-col">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-bg-white px-3.5 py-2.5">
        {children}
        {extra && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[13px] transition-colors ${
              extraCount > 0
                ? "border-accent-yellow bg-accent-yellow-bg font-medium text-accent-yellow"
                : "border-border-primary bg-bg-white text-text-secondary hover:text-text-primary"
            }`}
          >
            More filters{extraCount > 0 ? ` · ${extraCount}` : ""}
            <span className={`transition-transform ${open ? "rotate-180" : ""}`}>
              <MarkChevron size={11} />
            </span>
          </button>
        )}
        {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {extra && open && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-bg-white px-3.5 py-2.5">{extra}</div>
      )}
    </div>
  );
}

/** One labelled filter cell. The label sits above the control; the cell
 *  itself has no border -- the rule under the row is the only structure.
 *
 *  A DIV, not a LABEL. Wrapping the children in a <label> looks tidier
 *  and breaks the cells that hold a button: a label forwards its clicks
 *  to the control it labels, so the date picker's trigger stopped
 *  opening and the account select stopped being reachable. The filter
 *  harness caught both. The cell this replaces was a div with a caption
 *  div, so this is the prior behaviour, not a concession.
 *
 *  Pass `htmlFor` with a matching `id` on the control to get the
 *  association back where the cell holds exactly one labelable field. */
export function FilterCell({
  label,
  children,
  className = "",
  htmlFor,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
  htmlFor?: string;
}) {
  /* A pill, with its label inline and quiet in front of the control --
     "Media: all", "Account: all accounts". The approved design shows a
     row of these rather than stacked caption-over-field cells, which is
     what makes the bar read as one line of choices.

     Still a DIV, not a LABEL: a label forwards its clicks to the control
     it labels, which broke the date picker's trigger and made the
     account select unreachable. The filter harness caught it. */
  return (
    <div
      className={`flex min-w-0 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-border-primary bg-bg-white px-3 py-1.5 ${className}`}
    >
      <label htmlFor={htmlFor} className="shrink-0 text-[12px] text-text-tertiary">
        {label}
      </label>
      {children}
    </div>
  );
}

/** The control inside a filter pill. The pill carries the border, so the
 *  control itself is bare -- otherwise every filter reads as a box
 *  inside a box. */
export const filterControlClass =
  "min-w-0 border-0 bg-transparent p-0 text-[13px] font-medium text-text-primary " +
  "outline-none placeholder:font-normal placeholder:text-text-tertiary " +
  "focus:outline-none";

/* ── band 3: figures, no boxes ───────────────────────────────────── */

export interface Figure {
  label: string;
  /** Pre-formatted. The caller owns units, because only it knows them. */
  value: React.ReactNode;
  /** One line under the figure: its basis, its period, its caveat. */
  basis?: React.ReactNode;
  /** The definition, on hover. Keeps a sentence off the screen without
   *  losing it -- the same bargain the `?` makes with Help. */
  title?: string;
}

/**
 * `compact` is for a band that is subordinate to another band on the
 * same screen -- the name-miss worklist under the cascade, say. Same
 * grammar, one step down in the hierarchy, so the panel's figures do
 * not shout over the section's own.
 */
/** Literal class names, not `lg:grid-cols-${n}`.
 *
 *  Tailwind scans source statically and only emits classes it can see
 *  written out, so an interpolated name produces no CSS at all and the
 *  grid silently keeps its mobile column count. Spelling them out is
 *  what makes the class exist. */
const FIGURE_COLUMNS: Record<number, string> = {
  1: "lg:grid-cols-1",
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
  5: "lg:grid-cols-5",
  6: "lg:grid-cols-6",
};

export function FigureBand({
  figures,
  className = "",
  compact = false,
  singleRow = false,
}: {
  figures: Figure[];
  className?: string;
  compact?: boolean;
  /** Lay the figures out as equal columns on one row instead of letting
   *  them wrap.
   *
   *  The default is flex-wrap, where each figure is as wide as its own
   *  content — fine for three or four, but a long `basis` line makes one
   *  figure wide enough to push the rest onto a second row. Opt in where
   *  the set is meant to be read across, and keep the default for the
   *  nine other sections that rely on wrapping.
   *
   *  Still wraps at phone width: the columns collapse to two, because
   *  five 26px figures on a 400px screen would be unreadable. */
  singleRow?: boolean;
}) {
  if (singleRow) {
    return (
      <div
        className={`grid grid-cols-2 items-start border-b border-border-primary sm:grid-cols-3 ${
          FIGURE_COLUMNS[figures.length] ?? "lg:grid-cols-4"
        } ${compact ? "gap-x-6 gap-y-4 pb-3" : "gap-x-8 gap-y-5 pb-4"} ${className}`}
      >
        {figures.map((f) => (
          <div key={f.label} className="min-w-0" title={f.title}>
            <FieldLabel>{f.label}</FieldLabel>
            <div
              className={`mt-1 font-medium leading-none tracking-[-0.02em] text-text-primary tabular-nums ${
                compact ? "text-[20px]" : "text-[26px]"
              }`}
            >
              {f.value}
            </div>
            {f.basis && <div className="mt-1.5 text-[11.5px] text-text-tertiary">{f.basis}</div>}
          </div>
        ))}
      </div>
    );
  }
  return (
    <div
      className={`flex flex-wrap items-start border-b border-border-primary ${
        compact ? "gap-x-8 gap-y-4 pb-3" : "gap-x-10 gap-y-5 pb-4"
      } ${className}`}
    >
      {figures.map((f) => (
        <div key={f.label} className="min-w-0" title={f.title}>
          <FieldLabel>{f.label}</FieldLabel>
          <div
            className={`mt-1 font-medium leading-none tracking-[-0.02em] text-text-primary tabular-nums ${
              compact ? "text-[20px]" : "text-[26px]"
            }`}
          >
            {f.value}
          </div>
          {f.basis && <div className="mt-1.5 text-[11.5px] text-text-tertiary">{f.basis}</div>}
        </div>
      ))}
    </div>
  );
}

/* ── the verdict band ────────────────────────────────────────────── */

export interface Verdict {
  key: string;
  label: string;
  count: number;
  /** Second line -- spend behind the verdict, usually. */
  under?: React.ReactNode;
  tone: "scale" | "pause" | "monitor" | "report";
  selected?: boolean;
  onSelect?: () => void;
}

const TONE: Record<Verdict["tone"], string> = {
  // Flat colour fields. Signal red is reserved by law for a fired rule,
  // which is exactly what PAUSE is.
  scale: "bg-success-bg text-success-text",
  pause: "bg-error-bg text-error-text",
  monitor: "bg-warning-bg text-warning-text",
  report: "bg-bg-muted text-text-secondary",
};

export function VerdictBand({ verdicts }: { verdicts: Verdict[] }) {
  const total = verdicts.reduce((n, v) => n + v.count, 0) || 1;
  return (
    <div className="flex w-full flex-wrap border-b border-border-primary">
      {verdicts.map((v) => {
        const body = (
          <>
            <FieldLabel className="!text-current opacity-80">{v.label}</FieldLabel>
            <div className="mt-1 text-[24px] font-medium leading-none tabular-nums">
              {v.count.toLocaleString("en-IN")}
            </div>
            {v.under && <div className="mt-1 text-[11.5px] opacity-80 tabular-nums">{v.under}</div>}
          </>
        );
        // Width carries the count: one mark, one unit. A verdict holding
        // four fifths of the ads occupies four fifths of the band.
        const grow = Math.max(v.count / total, 0.08);
        const cls = `flex min-w-[140px] flex-col px-4 py-3 text-left transition-opacity ${TONE[v.tone]} ${
          v.selected ? "" : v.onSelect ? "opacity-90 hover:opacity-100" : ""
        } ${v.selected ? "ring-1 ring-inset ring-text-primary" : ""}`;
        return v.onSelect ? (
          <button
            key={v.key}
            type="button"
            onClick={v.onSelect}
            aria-pressed={v.selected}
            className={cls}
            style={{ flexGrow: grow, flexBasis: 0 }}
          >
            {body}
          </button>
        ) : (
          <div key={v.key} className={cls} style={{ flexGrow: grow, flexBasis: 0 }}>
            {body}
          </div>
        );
      })}
    </div>
  );
}

/* ── ranked list: what the colour-topped tiles become ────────────── */

export interface RankedRow {
  key: string;
  label: React.ReactNode;
  value: React.ReactNode;
  /** 0..1. Drives the bar and, with `share`, the right-hand percentage. */
  fraction: number;
  share?: React.ReactNode;
  onSelect?: () => void;
  selected?: boolean;
}

/**
 * A ranked list with a bar, replacing a grid of tiles.
 *
 * Ten channels as ten colour-topped cards spent a whole screen and gave
 * the hue of each card a meaning it did not have. Rank answers "which",
 * the bar answers "by how much", and one monochrome ramp means the
 * colour is not pretending to be a category.
 */
export function RankedList({ rows, labelWidth = 150 }: { rows: RankedRow[]; labelWidth?: number }) {
  return (
    <div className="flex flex-col">
      {rows.map((r, i) => {
        const inner = (
          <>
            <div className="shrink-0 truncate text-[13px] text-text-primary" style={{ width: labelWidth }}>
              {r.label}
            </div>
            <div className="h-1.5 min-w-[40px] flex-1 bg-bg-muted">
              <div
                className="h-full bg-text-primary"
                style={{ width: `${Math.max(Math.min(r.fraction, 1), 0) * 100}%`, opacity: 1 - Math.min(i, 5) * 0.13 }}
              />
            </div>
            <div className="w-[96px] shrink-0 text-right text-[13px] text-text-primary tabular-nums">{r.value}</div>
            {r.share !== undefined && (
              <div className="w-[52px] shrink-0 text-right text-[12px] text-text-tertiary tabular-nums">{r.share}</div>
            )}
          </>
        );
        const cls = `flex items-center gap-3 border-t border-border-soft py-2 first:border-t-0 ${
          r.onSelect ? "cursor-pointer hover:bg-bg-surface" : ""
        } ${r.selected ? "bg-bg-surface" : ""}`;
        return r.onSelect ? (
          <button key={r.key} type="button" onClick={r.onSelect} aria-pressed={r.selected} className={`${cls} text-left`}>
            {inner}
          </button>
        ) : (
          <div key={r.key} className={cls}>
            {inner}
          </div>
        );
      })}
    </div>
  );
}

/* ── the table's frame ───────────────────────────────────────────── */

/**
 * Full bleed to the content column, hairline rules between rows, no
 * container -- the brief's first viewport, exactly. Horizontal scroll
 * lives here so a 74-column table never widens the page.
 */
export function TableFrame({ children, footer }: { children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <div className="-mx-1 overflow-x-auto px-1">{children}</div>
      {footer && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-primary pt-2.5">
          {footer}
        </div>
      )}
    </div>
  );
}
