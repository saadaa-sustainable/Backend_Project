"use client";

/**
 * Date-range picker matching the legacy Ads Analyse control: a preset
 * list on the left, two months side by side, range highlighting across
 * them, the resolved range echoed at the bottom, and Cancel / Apply.
 *
 * Deliberately uncommitted until Apply. The old control fired a fetch on
 * every `<input type=date>` keystroke, so typing a year walked through
 * 0002-, 0020-, 0202- and issued a request for each — against an
 * endpoint whose cold path is measured in seconds. Here the calendar
 * edits local state and only `onApply` reaches the caller.
 *
 * "Lifetime" yields ("", "") rather than some sentinel far-past date:
 * the callers treat an empty range as "no date filter at all" and skip
 * the window predicates entirely, which is both cheaper and honest —
 * there is no real lower bound to claim.
 */

import { useEffect, useMemo, useRef, useState } from "react";

export interface DateRange {
  from: string; // YYYY-MM-DD, "" = unbounded
  to: string;
}

type PresetKey =
  | "today" | "yesterday" | "last7" | "last30" | "thisMonth"
  | "lastMonth" | "last90" | "lifetime" | "custom";

const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last7", label: "Last 7 Days" },
  { key: "last30", label: "Last 30 Days" },
  { key: "thisMonth", label: "This Month" },
  { key: "lastMonth", label: "Last Month" },
  { key: "last90", label: "Last 90 Days" },
  { key: "lifetime", label: "Lifetime" },
  { key: "custom", label: "Custom Range" },
];

const CT = {
  border: "#E8E2D5",
  muted: "#9A9384",
  gold: "#C9A227",
  goldSoft: "#FBF3DC",
  goldMid: "#F4E4B8",
  ink: "#3A362E",
  brick: "#B4573A",
};

function iso(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}
function addDays(d: Date, n: number) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}
function startOfMonth(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}
function addMonths(d: Date, n: number) {
  return new Date(d.getFullYear(), d.getMonth() + n, 1);
}
function fmtDisplay(s: string) {
  if (!s) return "—";
  const [y, m, d] = s.split("-");
  return `${d}/${m}/${y}`;
}

export function resolvePreset(key: PresetKey): DateRange {
  const today = new Date();
  switch (key) {
    case "today":
      return { from: iso(today), to: iso(today) };
    case "yesterday": {
      const y = addDays(today, -1);
      return { from: iso(y), to: iso(y) };
    }
    case "last7":
      return { from: iso(addDays(today, -6)), to: iso(today) };
    case "last30":
      return { from: iso(addDays(today, -29)), to: iso(today) };
    case "last90":
      return { from: iso(addDays(today, -89)), to: iso(today) };
    case "thisMonth":
      return { from: iso(startOfMonth(today)), to: iso(today) };
    case "lastMonth": {
      const first = addMonths(startOfMonth(today), -1);
      const last = addDays(startOfMonth(today), -1);
      return { from: iso(first), to: iso(last) };
    }
    case "lifetime":
      return { from: "", to: "" };
    default:
      return { from: "", to: "" };
  }
}

export function presetLabel(key: string) {
  return PRESETS.find((p) => p.key === key)?.label ?? "Custom Range";
}

/** Month grid, Sunday-first, with leading/trailing days from the
 *  neighbouring months shown greyed so the grid never reflows. */
function MonthGrid({
  month,
  from,
  to,
  hover,
  onPick,
  onHover,
}: {
  month: Date;
  from: string;
  to: string;
  hover: string | null;
  onPick: (d: string) => void;
  onHover: (d: string | null) => void;
}) {
  const first = startOfMonth(month);
  const start = addDays(first, -first.getDay());
  const days = Array.from({ length: 42 }, (_, i) => addDays(start, i));
  // While picking the second end, preview against the hovered day so the
  // range reads as continuous before it is committed.
  const effEnd = to || hover || "";
  const lo = from && effEnd ? (from <= effEnd ? from : effEnd) : from;
  const hi = from && effEnd ? (from <= effEnd ? effEnd : from) : from;

  return (
    <div>
      <div className="mb-1 grid grid-cols-7 text-center text-[10px] font-semibold uppercase" style={{ color: CT.muted }}>
        {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => (
          <div key={d} className="py-1">{d}</div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const s = iso(d);
          const outside = d.getMonth() !== month.getMonth();
          const isEnd = s === from || s === to;
          const inRange = !!lo && !!hi && s >= lo && s <= hi;
          return (
            <button
              key={s}
              onClick={() => onPick(s)}
              onMouseEnter={() => onHover(s)}
              className="relative h-8 text-[12px] tabular-nums transition-colors"
              style={{
                color: isEnd ? CT.ink : outside ? "#CFC8B8" : inRange ? CT.gold : CT.ink,
                backgroundColor: isEnd ? CT.gold : inRange ? CT.goldSoft : "transparent",
                fontWeight: isEnd ? 700 : 400,
                borderRadius: isEnd ? 999 : 0,
              }}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function DateRangePicker({
  value,
  preset,
  onApply,
}: {
  value: DateRange;
  preset: string;
  onApply: (range: DateRange, preset: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DateRange>(value);
  const [draftPreset, setDraftPreset] = useState<string>(preset);
  const [hover, setHover] = useState<string | null>(null);
  const [leftMonth, setLeftMonth] = useState<Date>(() =>
    addMonths(startOfMonth(value.to ? new Date(value.to) : new Date()), -1),
  );
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setDraft(value);
    setDraftPreset(preset);
    setLeftMonth(addMonths(startOfMonth(value.to ? new Date(value.to) : new Date()), -1));
  }, [open, value, preset]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function pick(day: string) {
    setDraftPreset("custom");
    // First click, or restarting after a complete range, sets the anchor.
    if (!draft.from || (draft.from && draft.to)) {
      setDraft({ from: day, to: "" });
      return;
    }
    setDraft(day < draft.from ? { from: day, to: draft.from } : { from: draft.from, to: day });
  }

  const buttonLabel = useMemo(() => {
    if (preset !== "custom") return presetLabel(preset);
    if (value.from && value.to) return `${fmtDisplay(value.from)} – ${fmtDisplay(value.to)}`;
    return "Custom Range";
  }, [preset, value]);

  return (
    <div className="relative" ref={box}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-md border bg-white px-3 py-2 text-sm"
        style={{ borderColor: open ? CT.gold : CT.border, color: CT.ink }}
      >
        <span className="font-medium">{buttonLabel}</span>
        <span style={{ color: CT.muted }}>▾</span>
      </button>

      {open && (
        <div
          className="absolute right-0 z-50 mt-1 flex overflow-hidden rounded-xl border bg-white shadow-2xl"
          style={{ borderColor: CT.border }}
        >
          {/* presets */}
          <div className="w-44 shrink-0 border-r py-2" style={{ borderColor: CT.border, backgroundColor: "#FCFAF5" }}>
            {PRESETS.map((p) => {
              const active = draftPreset === p.key;
              return (
                <button
                  key={p.key}
                  onClick={() => {
                    setDraftPreset(p.key);
                    if (p.key !== "custom") {
                      const r = resolvePreset(p.key);
                      setDraft(r);
                      if (r.to) setLeftMonth(addMonths(startOfMonth(new Date(r.to)), -1));
                    }
                  }}
                  className="block w-full px-4 py-2.5 text-left text-sm transition-colors"
                  style={{
                    backgroundColor: active ? CT.goldSoft : "transparent",
                    color: active ? CT.gold : CT.ink,
                    fontWeight: active ? 600 : 400,
                    borderLeft: `3px solid ${active ? CT.gold : "transparent"}`,
                  }}
                >
                  {p.label}
                </button>
              );
            })}
          </div>

          {/* calendars */}
          <div className="p-3" onMouseLeave={() => setHover(null)}>
            <div className="mb-1 flex items-center justify-between px-1">
              <button
                onClick={() => setLeftMonth(addMonths(leftMonth, -1))}
                className="rounded px-2 py-0.5 text-base hover:bg-bg-muted"
                style={{ color: CT.muted }}
                aria-label="Previous month"
              >
                ‹
              </button>
              <div className="flex flex-1 justify-around text-sm font-semibold" style={{ color: CT.ink }}>
                <span>
                  {leftMonth.toLocaleString("en-US", { month: "long", year: "numeric" })}
                </span>
                <span>
                  {addMonths(leftMonth, 1).toLocaleString("en-US", { month: "long", year: "numeric" })}
                </span>
              </div>
              <button
                onClick={() => setLeftMonth(addMonths(leftMonth, 1))}
                className="rounded px-2 py-0.5 text-base hover:bg-bg-muted"
                style={{ color: CT.muted }}
                aria-label="Next month"
              >
                ›
              </button>
            </div>

            <div className="flex gap-5">
              {[leftMonth, addMonths(leftMonth, 1)].map((m, i) => (
                <div key={i} className="w-[232px]">
                  <MonthGrid
                    month={m}
                    from={draft.from}
                    to={draft.to}
                    hover={hover}
                    onPick={pick}
                    onHover={setHover}
                  />
                </div>
              ))}
            </div>

            <div className="mt-3 flex items-center justify-between border-t pt-3" style={{ borderColor: CT.border }}>
              <div className="font-mono text-[13px]" style={{ color: CT.ink }}>
                {draftPreset === "lifetime"
                  ? "All time"
                  : `${fmtDisplay(draft.from)}  -  ${fmtDisplay(draft.to)}`}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setOpen(false)}
                  className="rounded-md border px-4 py-1.5 text-sm"
                  style={{ borderColor: CT.border, color: CT.ink }}
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    // An anchor with no second end is not a range; treat a
                    // single click as that one day rather than applying a
                    // half-open window the server would read as unbounded.
                    const r =
                      draftPreset === "lifetime"
                        ? { from: "", to: "" }
                        : draft.from && !draft.to
                          ? { from: draft.from, to: draft.from }
                          : draft;
                    onApply(r, draftPreset);
                    setOpen(false);
                  }}
                  className="rounded-md px-4 py-1.5 text-sm font-medium text-white"
                  style={{ backgroundColor: CT.brick }}
                >
                  Apply
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default DateRangePicker;
