/** Shared popup colors, including previews rendered in a separate portal. */
export type AdPopupAppearance = "creative" | "standard";

const creative = {
  bg: "#FAF8F3",
  surface: "#FFFFFF",
  border: "#E8E2D5",
  text: "#3A362E",
  muted: "#9A9384",
  accent: "#B07E12",
  accentHover: "#93680E",
  selected: "#FDF8E8",
  onAccent: "#FFFFFF",
  hover: "#FFFFFF",
  mutedSurface: "#F2F0EA",
  focus: "#B07E12",
};

const standard: typeof creative = {
  bg: "var(--bg-white)",
  surface: "var(--bg-white)",
  border: "var(--border-primary)",
  text: "var(--text-primary)",
  muted: "var(--text-secondary)",
  accent: "var(--accent-yellow)",
  accentHover: "var(--accent-yellow-hover)",
  selected: "var(--accent-yellow-bg)",
  onAccent: "#FFFFFF",
  hover: "var(--bg-muted)",
  mutedSurface: "var(--bg-surface)",
  focus: "var(--accent-yellow)",
};

export function getAdPopupTheme(appearance: AdPopupAppearance = "creative") {
  return appearance === "standard" ? standard : creative;
}
