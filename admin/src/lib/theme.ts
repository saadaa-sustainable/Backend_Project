/**
 * Design tokens as raw hex -- for SVG chart fills/strokes, which can't
 * read Tailwind's CSS custom properties directly. Kept in sync by hand
 * with globals.css's :root block (same values, same names).
 *
 * The Vienna Method palette (2026-09-26). `accentYellow` is Vienna blue;
 * the name is historical and shared with the CSS var for the same reason
 * -- see the note in globals.css.
 */
export const theme = {
  bgBase: "#F9F8F6",
  bgSurface: "#F2F0EB",
  bgWhite: "#FFFFFF",
  bgMuted: "#EFEDE7",
  textPrimary: "#14120E",
  textSecondary: "#57534A",
  textTertiary: "#716D64",
  borderPrimary: "#E0DCD2",
  borderSoft: "#EBE8E0",
  accentYellow: "#1D4E89",
  accentYellowBg: "#E7EDF5",
  successText: "#2F6B3A",
  successMid: "#16A34A",
  successBg: "#E7EDE2",
  warningText: "#7A5206",
  warningMid: "#B45309",
  warningBg: "#F4EBD8",
  errorText: "#9E0C24",
  errorMid: "#C8102E",
  errorBg: "#F6E3E4",
  infoText: "#1D4E89",
  infoMid: "#2563EB",
  infoBg: "#E4EAF2",
  accentPurple: "#7C3AED",
  accentPink: "#B02A6B",
  accentIndigo: "#3F3BB0",
} as const;

/**
 * Categorical chart series order -- validated CVD-safe (lightness band,
 * chroma floor, normal-vision floor >= 15, contrast >= 3:1 against the
 * #F8FAFC canvas; the one adjacent pair in the 6-8 CVD floor band is
 * covered by this project's charts always shipping direct labels/legend)
 * via the dataviz skill's validator (`validate_palette.js
 * "#2563EB,#16A34A,#B45309,#7C3AED,#DC2626,#0891B2" --mode light` -> ALL
 * CHECKS PASS). Re-checked 2026-09-26 against the Vienna ground
 * #F9F8F6: weakest ink #16A34A clears at 3.11:1, every other ink above
 * 3.4:1, and the palette is UNCHANGED -- the ground was lightened to
 * keep it so, rather than darkening a series off its validated
 * lightness band. Fixed order -- never cycle/reassign per filter change; a
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
