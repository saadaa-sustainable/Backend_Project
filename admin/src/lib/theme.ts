/**
 * Design tokens as raw hex -- for SVG chart fills/strokes, which can't
 * read Tailwind's CSS custom properties directly. Kept in sync by hand
 * with globals.css's :root block (same values, same names).
 */
export const theme = {
  bgBase: "#F8FAFC",
  bgSurface: "#F1F5F9",
  bgWhite: "#FFFFFF",
  bgMuted: "#EEF2F6",
  textPrimary: "#0F172A",
  textSecondary: "#64748B",
  textTertiary: "#94A3B8",
  borderPrimary: "#E2E8F0",
  borderSoft: "#EDF1F5",
  accentYellow: "#2563EB",
  successText: "#15803D",
  successMid: "#16A34A",
  successBg: "#F0FDF4",
  warningText: "#B45309",
  warningMid: "#D97706",
  warningBg: "#FFFBEB",
  errorText: "#B91C1C",
  errorMid: "#DC2626",
  errorBg: "#FEF2F2",
  infoText: "#1D4ED8",
  infoMid: "#2563EB",
  infoBg: "#EFF6FF",
  accentPurple: "#7C3AED",
  accentPink: "#DB2777",
  accentIndigo: "#4F46E5",
} as const;

/**
 * Categorical chart series order -- validated CVD-safe (lightness band,
 * chroma floor, normal-vision floor >= 15, contrast >= 3:1 against the
 * #F8FAFC canvas; the one adjacent pair in the 6-8 CVD floor band is
 * covered by this project's charts always shipping direct labels/legend)
 * via the dataviz skill's validator (`validate_palette.js
 * "#2563EB,#16A34A,#B45309,#7C3AED,#DC2626,#0891B2" --mode light` -> ALL
 * CHECKS PASS). Fixed order -- never cycle/reassign per filter change; a
 * 7th series folds into "Other" rather than generating a new hue.
 */
export const CATEGORICAL_PALETTE = [
  "#2563EB", // blue
  theme.successMid, // green
  theme.warningText, // amber-brown
  theme.accentPurple, // purple
  theme.errorMid, // red
  "#0891B2", // cyan
] as const;
