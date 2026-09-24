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

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { theme } from "@/lib/theme";

/**
 * The earliest date any metric on this dashboard can honestly describe.
 *
 * Shopify order history is effectively 2026-only -- 376,348 of 377,215
 * orders fall in 2026, against 794 in all of 2025 -- while Meta's
 * lifetime spend and conversion value reach back years. Pairing them
 * produced ads showing real Meta revenue against zero Shopify revenue:
 * 2,751 ads carrying 36.9 Cr of conversion value and no orders at all.
 * That reads as catastrophic performance; it is a coverage gap.
 *
 * `insights_daily_by_ad` begins 2025-12-29, so 2026-01-01 is the first
 * date on which Meta daily AND Shopify both have real coverage. Below
 * it we have neither, so "all time" was never a thing this dashboard
 * could show.
 */
export const DATA_FLOOR = "2026-01-01";

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
  // Just "Lifetime". The floor date used to be spelled out here and
  // again in the summary line below, which repeated on every screen
  // what DataFloorNotice already says once, in the place built to
  // say it.
  { key: "lifetime", label: "Lifetime" },
  { key: "custom", label: "Custom Range" },
];

/** App tokens. `gold`/`goldSoft` keep their names for readability but
 *  now carry the app's primary accent and its tint, so the calendar
 *  matches every other control in the panel. */
const CT = {
  border: theme.borderPrimary,
  muted: theme.textTertiary,
  gold: theme.accentYellow,
  goldSoft: theme.infoBg,
  ink: theme.textPrimary,
  brick: theme.accentYellow,
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

/** Parse an ISO date into a LOCAL Date.
 *
 *  `new Date("2026-09-23")` parses as UTC midnight, which is the
 *  previous day in any timezone behind UTC and would shift every
 *  preset by one more day. Building from the parts keeps it local, the
 *  same basis `iso()` writes with. */
function fromIso(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Resolve a preset to a concrete range.
 *
 *  `anchor` is the newest day the data actually covers. It matters:
 *  Meta lands its insights a day in arrears, so "Last 7 Days" measured
 *  off the clock asks for a window whose final day does not exist yet
 *  and quietly sums six days against Meta's seven.
 *
 *  Measured 2026-09-24 on NCP_ASC-7DC+1DEV_CP_Jan2025: Meta Ads
 *  Manager reported Rs 74,401 for its last 7 days; the clock-anchored
 *  window (18-24 Sep) summed Rs 64,425 because we hold nothing for the
 *  24th. Anchored on the data (17-23 Sep) it is Rs 75,062, which is the
 *  same seven days Meta counted.
 *
 *  The rolling 3D/7D decision columns already anchor this way. Falls
 *  back to the clock when the caller has no freshness figure yet. */
export function resolvePreset(key: PresetKey, anchor?: string | null): DateRange {
  const today = anchor ? fromIso(anchor) : new Date();
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
      // Was ("", "") -- an empty range makes every endpoint skip its
      // window predicates and fall back to LIFETIME columns, which is
      // exactly the mismatch above. A real bounded range routes this
      // through the same windowed path as every other preset, so spend,
      // conversion value and Shopify orders share one basis.
      return { from: DATA_FLOOR, to: iso(today) };
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
  accentSolid,
  accentSoft,
}: {
  month: Date;
  from: string;
  to: string;
  hover: string | null;
  onPick: (d: string) => void;
  onHover: (d: string | null) => void;
  accentSolid: string;
  accentSoft: string;
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
                color: isEnd ? "#FFFFFF" : outside ? CT.muted : inRange ? accentSolid : CT.ink,
                backgroundColor: isEnd ? accentSolid : inRange ? accentSoft : "transparent",
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
  align = "right",
  accent,
  anchor,
}: {
  value: DateRange;
  preset: string;
  onApply: (range: DateRange, preset: string) => void;
  /** Newest day the data actually covers. Presets resolve against it
   *  instead of the clock, because Meta lands its insights a day in
   *  arrears -- see resolvePreset. Omitted, the clock is used. */
  anchor?: string | null;
  /** Which edge the panel hangs from. The panel is ~500px wide, so a
   *  trigger near the LEFT of its container must open leftwards or the
   *  first month lands off-screen. Default keeps existing callers. */
  align?: "left" | "right";
  /** Section accent for the selected day and Apply. Defaults to the app
   *  token, which is blue (`accentYellow` is a misnomer -- #3B6BF5).
   *  A section with its own palette passes it so the picker does not
   *  arrive in a colour nothing around it uses. */
  accent?: { solid: string; soft: string };
}) {
  const ACCENT = accent?.solid ?? CT.gold;
  const ACCENT_SOFT = accent?.soft ?? CT.goldSoft;
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DateRange>(value);
  const [draftPreset, setDraftPreset] = useState<string>(preset);
  const [hover, setHover] = useState<string | null>(null);
  const [leftMonth, setLeftMonth] = useState<Date>(() =>
    addMonths(startOfMonth(value.to ? new Date(value.to) : new Date()), -1),
  );
  const box = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  // Horizontal offset of the panel from the trigger's left edge, in px.
  // Measured rather than declared: `align` is only a preference, and a
  // preference cannot know that this particular trigger sits 300px from
  // the left of a page whose sidebar covers the first 264. Twice now the
  // preset rail has ended up off-screen because a caller inherited the
  // wrong default, so the panel now places itself.
  const [offset, setOffset] = useState(0);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const trigger = box.current;
      const el = panel.current;
      if (!trigger || !el) return;
      const t = trigger.getBoundingClientRect();
      const w = el.offsetWidth;
      const GUTTER = 8;
      // Stay inside the scrollable content column when there is one --
      // clamping to the viewport alone would happily slide the panel
      // under a fixed sidebar, which is invisible to getBoundingClientRect.
      const host = trigger.closest("main")?.getBoundingClientRect();
      const lo = (host ? host.left : 0) + GUTTER;
      const hi = (host ? host.right : document.documentElement.clientWidth) - GUTTER;

      // Preferred edge first, then the opposite, then clamp.
      const preferred = align === "left" ? t.left : t.right - w;
      const flipped = align === "left" ? t.right - w : t.left;
      let x = preferred;
      if (preferred < lo || preferred + w > hi) {
        x = flipped >= lo && flipped + w <= hi ? flipped : Math.max(lo, Math.min(preferred, hi - w));
      }
      setOffset(x - t.left);
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, align]);

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
        style={{ borderColor: open ? ACCENT : CT.border, color: CT.ink }}
      >
        <span className="font-medium">{buttonLabel}</span>
        <span style={{ color: CT.muted }}>▾</span>
      </button>

      {open && (
        <div
          ref={panel}
          className="absolute left-0 z-50 mt-1 flex w-max overflow-hidden rounded-xl border bg-white shadow-2xl"
          style={{ borderColor: CT.border, transform: `translateX(${offset}px)` }}
        >
          {/* presets */}
          <div className="w-44 shrink-0 border-r py-2" style={{ borderColor: CT.border, backgroundColor: theme.bgMuted }}>
            {PRESETS.map((p) => {
              const active = draftPreset === p.key;
              return (
                <button
                  key={p.key}
                  onClick={() => {
                    setDraftPreset(p.key);
                    if (p.key !== "custom") {
                      const r = resolvePreset(p.key, anchor);
                      setDraft(r);
                      if (r.to) setLeftMonth(addMonths(startOfMonth(new Date(r.to)), -1));
                    }
                  }}
                  className="block w-full px-4 py-2.5 text-left text-sm transition-colors"
                  style={{
                    backgroundColor: active ? ACCENT_SOFT : "transparent",
                    color: active ? ACCENT : CT.ink,
                    fontWeight: active ? 600 : 400,
                    borderLeft: `3px solid ${active ? ACCENT : "transparent"}`,
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
                    accentSolid={ACCENT}
                    accentSoft={ACCENT_SOFT}
                  />
                </div>
              ))}
            </div>

            <div className="mt-3 flex items-center justify-between border-t pt-3" style={{ borderColor: CT.border }}>
              <div className="font-mono text-[13px]" style={{ color: CT.ink }}>
                {draftPreset === "lifetime"
                  ? "Lifetime"
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
                        ? resolvePreset("lifetime", anchor)
                        : draft.from && !draft.to
                          ? { from: draft.from, to: draft.from }
                          : draft;
                    onApply(r, draftPreset);
                    setOpen(false);
                  }}
                  className="rounded-md px-4 py-1.5 text-sm font-medium text-white"
                  style={{ backgroundColor: ACCENT }}
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
