"use client";

/**
 * InfoDot — the (i) on a KPI card, answering "where does this number
 * come from?".
 *
 * Every tile on this page shows a count and a rupee sub-line, and the
 * two do NOT always share a basis: a category tile's count is a
 * server-side figure over every matching ad while its spend only sums
 * the rows currently paged in. That difference is invisible on the
 * card, so each tile states it rather than leaving the reader to assume
 * the two agree.
 *
 * `title` was the obvious implementation and is the wrong one here: the
 * native tooltip takes about a second to appear, collapses newlines, and
 * truncates at a length these explanations exceed. This renders a real
 * panel instead.
 *
 * The dot is deliberately NOT a <button>. Four of the six verdict tiles
 * and all seven category tiles are themselves buttons, and a button
 * inside a button is invalid HTML that React will warn about and that
 * browsers resolve inconsistently. A focusable <span> gets the same
 * keyboard reach without nesting interactive elements, and the panel
 * carries `pointer-events-none` so it can never swallow a click meant
 * for the tile underneath.
 */

import { useState } from "react";

/** The three questions a KPI card should answer about itself. Structured
 *  rather than free text so no tile can quietly skip one. */
export interface InfoBasis {
  /** What the big number counts, and over what population. */
  count: string;
  /** What the ₹ sub-line sums, and over what window. */
  spend?: string;
  /** The rule that puts an entity in this bucket. */
  rule?: string;
  /** Anything else that would otherwise mislead. */
  note?: string;
}

function BasisBody({ basis }: { basis: InfoBasis }) {
  const lines: [string, string | undefined][] = [
    ["Counts", basis.count],
    ["Spend", basis.spend],
    ["Rule", basis.rule],
  ];
  return (
    <>
      {lines.map(([k, v]) =>
        v ? (
          <div key={k} className="mb-1.5 last:mb-0">
            <span className="font-semibold text-white">{k}: </span>
            <span className="text-slate-300">{v}</span>
          </div>
        ) : null,
      )}
      {basis.note && (
        <div className="mt-2 border-t border-slate-700 pt-1.5 text-slate-400">
          {basis.note}
        </div>
      )}
    </>
  );
}

export function InfoDot({ basis }: { basis: string | InfoBasis }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      className="relative inline-flex shrink-0"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <span
        tabIndex={0}
        role="note"
        aria-label="What this number is based on"
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        // The dot sits on top of a tile that filters the table when
        // clicked. Reaching for the explanation should not also change
        // what the table shows.
        onClick={(e) => e.stopPropagation()}
        className={
          "flex h-4 w-4 cursor-help items-center justify-center rounded-full border text-[9px] font-semibold leading-none transition " +
          (open
            ? "border-slate-700 bg-slate-800 text-white"
            : "border-border-primary text-text-tertiary hover:border-slate-500 hover:text-text-secondary")
        }
      >
        i
      </span>
      {open && (
        <span
          role="tooltip"
          // right-0 so the panel opens leftward from a dot that always
          // sits at the tile's top-right -- the last column of a
          // six-wide grid would otherwise run off the viewport.
          className="pointer-events-none absolute right-0 top-5 z-30 w-64 rounded-lg bg-slate-900 p-2.5 text-left text-[11px] font-normal normal-case leading-snug tracking-normal text-slate-300 shadow-lg"
        >
          {typeof basis === "string" ? basis : <BasisBody basis={basis} />}
        </span>
      )}
    </span>
  );
}
