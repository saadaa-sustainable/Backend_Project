"use client";

import { useState, type CSSProperties } from "react";
import { getAdPopupTheme, type AdPopupAppearance } from "@/lib/adPopupTheme";
import { getAssetPreview, webUrl } from "@/lib/assetPreview";
import { PreviewDialog } from "./AssetPreview";

type AdLinkProps = {
  adId: string | null | undefined;
  url: string | null | undefined;
  appearance?: AdPopupAppearance;
};

function linkColors(appearance: AdPopupAppearance): CSSProperties {
  const theme = getAdPopupTheme(appearance);
  return {
    "--ad-link-bg": theme.bg,
    "--ad-link-border": theme.border,
    "--ad-link-accent": theme.accent,
    "--ad-link-accent-hover": theme.accentHover,
    "--ad-link-focus": theme.focus,
    "--ad-link-muted": theme.muted,
  } as CSSProperties;
}

export function AdPreviewLinks({ adId, url, inline = false, appearance = "creative" }: AdLinkProps & { inline?: boolean }) {
  const preview = getAssetPreview({ preview_url: url });
  const [open, setOpen] = useState(false);
  const colors = linkColors(appearance);
  if (!preview.href) return <span style={colors} className="text-xs text-[var(--ad-link-muted)]">No ad preview</span>;

  return (
    <div style={colors} className="flex flex-wrap items-center gap-2" onClick={(event) => event.stopPropagation()}>
      {!inline && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label={`Preview ad ${adId ?? ""}`.trim()}
          className="whitespace-nowrap rounded-md border border-[var(--ad-link-border)] bg-[var(--ad-link-bg)] px-2 py-1.5 text-xs font-medium text-[var(--ad-link-accent)] hover:border-[var(--ad-link-accent)] focus-visible:outline-2 focus-visible:outline-[var(--ad-link-focus)]"
        >
          Preview ad
        </button>
      )}
      <a
        href={preview.href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Open ad preview for ${adId ?? "this ad"}`}
        className="whitespace-nowrap text-xs font-medium text-[var(--ad-link-accent)] underline underline-offset-2 hover:text-[var(--ad-link-accent-hover)]"
      >
        Open ad ↗
      </a>
      {open && (
        <PreviewDialog
          key={`${adId}:${preview.src}`}
          item={{ id: adId ?? "Ad", media: null, label: "Ad" }}
          preview={preview}
          onClose={() => setOpen(false)}
          appearance={appearance}
        />
      )}
    </div>
  );
}

export function DestinationLink({ adId, url, appearance = "creative" }: AdLinkProps) {
  const destination = webUrl(url);
  const colors = linkColors(appearance);
  if (!destination) return <span style={colors} className="text-xs text-[var(--ad-link-muted)]">No destination link</span>;

  return (
    <a
      href={destination.href}
      target="_blank"
      rel="noopener noreferrer"
      title={destination.href}
      aria-label={`Open website destination for ${adId ?? "this ad"}`}
      onClick={(event) => event.stopPropagation()}
      style={colors}
      className="inline-block max-w-60 truncate align-middle text-xs font-medium text-[var(--ad-link-accent)] underline underline-offset-2 hover:text-[var(--ad-link-accent-hover)]"
    >
      {destination.host}{destination.pathname === "/" ? "" : destination.pathname} ↗
    </a>
  );
}
