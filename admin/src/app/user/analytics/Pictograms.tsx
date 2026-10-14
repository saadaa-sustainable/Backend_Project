"use client";

/**
 * Drawn marks for the analytics surface.
 *
 * The surface brief is explicit: "Drawn pictograms, never glyphs or
 * emoji." Before this file the toolbar carried `⚙`, `▤`, `▾` and `✕`
 * typed as characters, which means every one of them rendered in
 * whatever the user's font stack happened to resolve -- different
 * weights, different baselines, different sizes between macOS and
 * Windows, and none of them matching Geist's stroke.
 *
 * Isotype's grammar: flat fills, one weight, no outline-and-fill mix,
 * built from a small set of geometric primitives. These are drawn on a
 * 16x16 field with a 1.5px stroke so they sit beside 13px label text
 * without optical correction.
 *
 * `currentColor` throughout, so a mark inherits the colour of whatever
 * it labels and never needs a variant.
 */

interface MarkProps {
  /** Rendered size in px. Default matches a 13px label's cap height. */
  size?: number;
  className?: string;
}

function frame(size: number, className: string | undefined, children: React.ReactNode) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {children}
    </svg>
  );
}

/** Help. A disc with the question's stem and point, not a "?" glyph. */
export function MarkHelp({ size = 14, className }: MarkProps) {
  return frame(size, className, (
    <>
      <circle cx="8" cy="8" r="6.25" />
      <path d="M6.2 6.1a1.85 1.85 0 1 1 1.85 1.95v1.1" strokeLinecap="round" />
      <path d="M8.05 11.3v.9" strokeLinecap="round" />
    </>
  ));
}

/** Filters. Three rules of decreasing length -- a narrowing. */
export function MarkFilter({ size = 14, className }: MarkProps) {
  return frame(size, className, (
    <>
      <path d="M2.25 4.25h11.5" />
      <path d="M4.25 8h7.5" />
      <path d="M6.25 11.75h3.5" />
    </>
  ));
}

/** Columns. The table's own grammar: a field divided into tracks. */
export function MarkColumns({ size = 14, className }: MarkProps) {
  return frame(size, className, (
    <>
      <rect x="2.25" y="2.75" width="11.5" height="10.5" />
      <path d="M6.1 2.75v10.5" />
      <path d="M9.9 2.75v10.5" />
    </>
  ));
}

/** Export. A sheet with the mark leaving it, downward. */
export function MarkExport({ size = 14, className }: MarkProps) {
  return frame(size, className, (
    <>
      <path d="M8 2.5v7.5" />
      <path d="M5 7.25 8 10.25l3-3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2.75 11.5v2h10.5v-2" />
    </>
  ));
}

/** Disclosure. One stroke, rotated by the caller when open. */
export function MarkChevron({ size = 12, className }: MarkProps) {
  return frame(size, className, (
    <path d="M4 6.25 8 10.25l4-4" strokeLinecap="round" strokeLinejoin="round" />
  ));
}

/** Dismiss. */
export function MarkClose({ size = 14, className }: MarkProps) {
  return frame(size, className, (
    <>
      <path d="M3.75 3.75 12.25 12.25" strokeLinecap="round" />
      <path d="M12.25 3.75 3.75 12.25" strokeLinecap="round" />
    </>
  ));
}

/** Search. */
export function MarkSearch({ size = 14, className }: MarkProps) {
  return frame(size, className, (
    <>
      <circle cx="7.1" cy="7.1" r="4.35" />
      <path d="M10.4 10.4 13.5 13.5" strokeLinecap="round" />
    </>
  ));
}

/** The date window: a bounded span, not a calendar page. */
export function MarkDateRange({ size = 14, className }: MarkProps) {
  return frame(size, className, (
    <>
      <path d="M3 3.25v9.5" strokeLinecap="round" />
      <path d="M13 3.25v9.5" strokeLinecap="round" />
      <path d="M3 8h10" />
    </>
  ));
}
