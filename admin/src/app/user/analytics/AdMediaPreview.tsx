"use client";

import Image from "next/image";
import { useState } from "react";
import { instagramThumbUrl, type AdsAnalyseRow } from "@/lib/api";
import { getAdPreviews } from "@/lib/assetPreview";
import { PreviewDialog } from "./AssetPreview";

/** Social embeds load only on demand, never once per visible table row. */
export function AdMediaPreview({ row, linkOnly = false }: { row: AdsAnalyseRow; linkOnly?: boolean }) {
  const sources = getAdPreviews(row);
  const [open, setOpen] = useState(false);
  const [failedThumbnails, setFailedThumbnails] = useState<Set<string>>(() => new Set());
  const instagram = sources.find((source) => source.provider === "Instagram");
  const shortcode = instagram?.src?.match(/\/(?:p|reel|tv)\/([\w-]+)\//)?.[1];
  const thumbnails = [sources.find((source) => source.kind === "image")?.src, shortcode ? instagramThumbUrl(shortcode) : null];
  const thumbnail = thumbnails.find((url) => !!url && !failedThumbnails.has(url));
  const href = sources.find((source) => source.kind === "embed")?.href ?? sources[0]?.href;
  const isVideo = sources.some((source) => source.kind === "video");

  if (linkOnly) return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()} className="text-text-link hover:underline" aria-label={`Open preview for ${row.ad_name ?? row.ad_id}`}>Open preview</a>
  ) : <span className="text-text-tertiary">—</span>;

  return (
    <>
      <button
        type="button"
        disabled={!sources.length}
        onClick={(event) => { event.stopPropagation(); setOpen(true); }}
        aria-label={`Preview ad ${row.ad_name ?? row.ad_id}`}
        title={sources.length ? "Open ad preview" : "No preview link available"}
        className="relative flex h-10 w-10 items-center justify-center overflow-hidden rounded border border-border-primary bg-bg-muted text-text-secondary hover:border-text-secondary focus-visible:outline-2 focus-visible:outline-text-primary disabled:cursor-default"
      >
        {thumbnail ? (
          <Image key={thumbnail} src={thumbnail} alt="" fill sizes="40px" unoptimized loading="lazy" className="object-cover" onError={() => setFailedThumbnails((failed) => new Set(failed).add(thumbnail))} />
        ) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
            {isVideo ? <path d="m9 5 11 7-11 7V5Z" /> : <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8" cy="8" r="1.5" /><path d="m3 17 5-5 4 4 4-6 5 7" /></>}
          </svg>
        )}
      </button>
      {open && sources.length > 0 && (
        <PreviewDialog
          key={`${row.ad_id}:${sources.map((source) => source.src).join("|")}`}
          item={{ id: row.ad_name ?? row.ad_id, media: isVideo ? "video" : null, label: "Ad" }}
          preview={sources[0]}
          alternatives={sources.slice(1)}
          appearance="standard"
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
