/**
 * The surface's icon set: drawn, not typed.
 *
 * Creative Testing carried 🎬 🖼 👤 and Instagram carried ♥ 💬 👁 as its
 * media and metric icons. Emoji are a different typeface on every
 * operating system, they ignore `currentColor`, and they arrive at
 * whatever weight the vendor drew them at -- so a row of them reads as
 * six unrelated pictures rather than one system.
 *
 * These are authored at one stroke weight (1.5 at a 24-unit grid,
 * rounded caps and joins) on one optical size, and they inherit
 * `currentColor`, so an icon beside a label is the same ink as the
 * label. Isotype's discipline is that a mark means one thing and is
 * drawn once; this is the same rule applied to the interface's own
 * marks.
 */

type IconProps = {
  /** Rendered size in px. Defaults to 14, the size that sits on a
   *  12-13px label without pushing the line box taller. */
  size?: number;
  className?: string;
  /** Decorative by default: these always sit beside a text label, so
   *  announcing them would just repeat it. Pass a title only when the
   *  icon is genuinely carrying meaning on its own. */
  title?: string;
};

function Svg({ size = 14, className, title, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
    >
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

/** Video asset. A film frame, not a clapperboard -- the perforations
 *  read at 14px where a hinged slate does not. */
export function IconVideo(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="2.5" y="5" width="19" height="14" rx="1.5" />
      <path d="M7 5v14M17 5v14M2.5 12h19" />
    </Svg>
  );
}

/** Graphic asset. A picture plane with a horizon and a sun. */
export function IconGraphic(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="2.5" y="4.5" width="19" height="15" rx="1.5" />
      <circle cx="8.5" cy="10" r="1.75" />
      <path d="M2.5 16.5l5-4 4.5 3.5 3.5-3 6 5" />
    </Svg>
  );
}

/** Influencer asset. A single figure -- Arntz drew people as a head and
 *  shoulders and so does this. */
export function IconInfluencer(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M4.5 20a7.5 7.5 0 0115 0" />
    </Svg>
  );
}

/** Likes. */
export function IconHeart(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M12 20.5C6.5 16.8 3 13.7 3 9.9A4.4 4.4 0 017.4 5.5c1.8 0 3.4 1 4.6 2.6 1.2-1.6 2.8-2.6 4.6-2.6A4.4 4.4 0 0121 9.9c0 3.8-3.5 6.9-9 10.6z" />
    </Svg>
  );
}

/** Comments. */
export function IconComment(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M21 11.5a7.5 7.5 0 01-10.9 6.7L4 20l1.8-5.1A7.5 7.5 0 1121 11.5z" />
    </Svg>
  );
}

/** Reach. Deliberately an eye and deliberately never summed. */
export function IconReach(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="2.75" />
    </Svg>
  );
}

/** Close. */
export function IconClose(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Svg>
  );
}

/** Column picker. */
export function IconColumns(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="3" y="4.5" width="18" height="15" rx="1.5" />
      <path d="M9 4.5v15M15 4.5v15" />
    </Svg>
  );
}
