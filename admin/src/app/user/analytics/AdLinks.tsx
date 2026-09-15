"use client";

import { useState } from "react";
import { getAssetPreview, webUrl } from "@/lib/assetPreview";
import { PreviewDialog } from "./AssetPreview";

type AdLinkProps = {
  adId: string | null | undefined;
  url: string | null | undefined;
};

export function AdPreviewLinks({ adId, url, inline = false }: AdLinkProps & { inline?: boolean }) {
  const preview = getAssetPreview({ preview_url: url });
  const [open, setOpen] = useState(false);
  if (!preview.href) return <span className="text-xs text-[#9A9384]">No ad preview</span>;

  return (
    <div className="flex flex-wrap items-center gap-2" onClick={(event) => event.stopPropagation()}>
      {!inline && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label={`Preview ad ${adId ?? ""}`.trim()}
          className="whitespace-nowrap rounded-md border border-[#E8E2D5] bg-[#FAF8F3] px-2 py-1.5 text-xs font-medium text-[#B07E12] hover:border-[#B07E12] focus-visible:outline-2 focus-visible:outline-[#B07E12]"
        >
          Preview ad
        </button>
      )}
      <a
        href={preview.href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Open ad preview for ${adId ?? "this ad"}`}
        className="whitespace-nowrap text-xs font-medium text-[#B07E12] underline underline-offset-2 hover:text-[#93680E]"
      >
        Open ad ↗
      </a>
      {open && (
        <PreviewDialog
          key={`${adId}:${preview.src}`}
          item={{ id: adId ?? "Ad", media: null, label: "Ad" }}
          preview={preview}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

export function DestinationLink({ adId, url }: AdLinkProps) {
  const destination = webUrl(url);
  if (!destination) return <span className="text-xs text-[#9A9384]">No destination link</span>;

  return (
    <a
      href={destination.href}
      target="_blank"
      rel="noopener noreferrer"
      title={destination.href}
      aria-label={`Open website destination for ${adId ?? "this ad"}`}
      onClick={(event) => event.stopPropagation()}
      className="inline-block max-w-60 truncate align-middle text-xs font-medium text-[#B07E12] underline underline-offset-2 hover:text-[#93680E]"
    >
      {destination.host}{destination.pathname === "/" ? "" : destination.pathname} ↗
    </a>
  );
}
