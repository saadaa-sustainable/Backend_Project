"use client";

import Image from "next/image";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { getAdPopupTheme, type AdPopupAppearance } from "@/lib/adPopupTheme";
import { getAssetPreview, type AssetPreview, type AssetPreviewSource } from "@/lib/assetPreview";
import { useAnalyticsSectionVisible } from "@/lib/analyticsSectionVisibility";
import { lockBodyScroll } from "@/lib/bodyScrollLock";
import { instagramThumbUrl } from "@/lib/api";
import { MarkClose } from "./Pictograms";

type Asset = AssetPreviewSource & { asset_id: string; media: string | null };

function PreviewImage({ src, alt, sizes, className, onError }: {
  src: string;
  alt: string;
  sizes: string;
  className: string;
  onError: () => void;
}) {
  // Provider URLs may be signed or require the viewer's browser session.
  return <Image src={src} alt={alt} fill sizes={sizes} unoptimized loading="lazy" className={className} onError={onError} />;
}

export function PreviewDialog({ item, preview, alternatives = [], onClose, appearance = "creative" }: {
  item: { id: string; media: string | null; label: "Asset" | "Ad" };
  preview: AssetPreview;
  alternatives?: AssetPreview[];
  onClose: () => void;
  appearance?: AdPopupAppearance;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [selected, setSelected] = useState(0);
  const [failedSources, setFailedSources] = useState<Set<string>>(() => new Set());
  const sources = [preview, ...alternatives];
  // Existing asset callers also recover to their thumbnail if direct playback fails.
  if (preview.thumbnail && !sources.some((source) => source.src === preview.thumbnail)) {
    sources.push({ ...preview, kind: "image", src: preview.thumbnail, provider: "Image" });
  }
  const current = sources[selected] ?? preview;
  const failed = !!current.src && failedSources.has(current.src);
  function failSource() {
    if (!current.src) return;
    const nextFailed = new Set(failedSources).add(current.src);
    setFailedSources(nextFailed);
    const next = sources.findIndex((source) => !!source.src && !nextFailed.has(source.src));
    if (next >= 0) setSelected(next);
  }
  const visible = useAnalyticsSectionVisible();
  const theme = getAdPopupTheme(appearance);
  const colors = {
    "--preview-bg": theme.bg,
    "--preview-surface": theme.surface,
    "--preview-border": theme.border,
    "--preview-text": theme.text,
    "--preview-muted": appearance === "creative" ? "#716D64" : theme.muted,
    "--preview-accent": appearance === "creative" ? "#8E6608" : theme.accent,
    "--preview-accent-hover": theme.accentHover,
    "--preview-on-accent": theme.onAccent,
    "--preview-focus": theme.focus,
  } as CSSProperties;

  useEffect(() => {
    if (!visible) onClose();
  }, [visible, onClose]);

  useEffect(() => {
    if (!visible) return;
    const dialog = dialogRef.current;
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();
    const unlock = lockBodyScroll();
    return () => {
      dialog?.close();
      unlock();
      if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    };
  }, [visible]);

  if (!visible) return null;

  return createPortal(
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); event.stopPropagation(); onClose(); }}
      onKeyDown={(event) => { if (event.key === "Escape") event.stopPropagation(); }}
      onClick={(event) => { event.stopPropagation(); if (event.target === event.currentTarget) onClose(); }}
      style={colors}
      className="fixed inset-0 m-auto max-h-[92dvh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-xl border border-[var(--preview-border)] bg-[var(--preview-bg)] p-0 text-[var(--preview-text)] backdrop:bg-black/60"
    >
      <div className="flex items-center justify-between gap-3 border-b border-[var(--preview-border)] px-4 py-3">
        <div className="min-w-0">
          <h2 id={titleId} className="break-words font-semibold">{item.label} preview · {item.id}</h2>
          <p className="text-xs text-[var(--preview-muted)]">{current.provider}{item.media ? ` · ${item.media}` : ""}</p>
        </div>
        <button type="button" autoFocus onClick={onClose} aria-label={`Close ${item.label.toLowerCase()} preview`} className="shrink-0 rounded-md border border-[var(--preview-border)] px-3 py-1.5 hover:bg-[var(--preview-surface)] focus-visible:outline-2 focus-visible:outline-[var(--preview-focus)]"><MarkClose /></button>
      </div>

      <div className="p-4">
        {sources.length > 1 && (
          <div role="group" aria-label="Preview source" className="mb-3 flex flex-wrap gap-2">
            {sources.map((source, index) => (
              <button
                key={`${source.src}:${source.href}`}
                type="button"
                aria-pressed={selected === index}
                disabled={!!source.src && failedSources.has(source.src)}
                onClick={() => setSelected(index)}
                className="rounded-md border border-[var(--preview-border)] px-3 py-1.5 text-xs aria-pressed:bg-[var(--preview-surface)] aria-pressed:font-semibold disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-[var(--preview-focus)]"
              >
                {source.provider}{sources.findIndex((other) => other.provider === source.provider) !== index ? ` ${index + 1}` : ""}
              </button>
            ))}
          </div>
        )}
        <div className="relative flex min-h-56 items-center justify-center overflow-hidden rounded-lg border border-[var(--preview-border)] bg-[var(--preview-surface)]">
          {!failed && current.src && current.kind === "embed" ? (
            <iframe
              key={current.src}
              src={current.src}
              title={`Preview of ${item.id}`}
              className="h-[60dvh] min-h-72 w-full border-0"
              allow="fullscreen; encrypted-media"
              allowFullScreen
              onError={failSource}
            />
          ) : !failed && current.src && current.kind === "video" ? (
            // Captions are not supplied by the asset register.
            <video key={current.src} src={current.src} poster={current.thumbnail ?? undefined} controls playsInline preload="metadata" aria-label={`Preview of ${item.id}`} className="max-h-[60dvh] w-full" onError={failSource} />
          ) : !failed && current.src && current.kind === "image" ? (
            <div className="relative h-[60dvh] w-full">
              <PreviewImage key={current.src} src={current.src} alt={`Creative ${item.label.toLowerCase()} ${item.id}`} sizes="(max-width: 672px) 90vw, 640px" className="object-contain" onError={failSource} />
            </div>
          ) : (
            <p className="max-w-sm px-6 py-12 text-center text-sm text-[var(--preview-muted)]">
              {failed ? "This preview could not be loaded." : `This ${item.label.toLowerCase()} opens on its source website.`} Use the preview link below to view it.
            </p>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-sm text-xs text-[var(--preview-muted)]">If the preview doesn’t load, {sources.length > 1 ? "choose another source or " : ""}open the original {item.label.toLowerCase()}.</p>
          {current.href && <a href={current.href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-md bg-[var(--preview-accent)] px-3 py-2 text-sm font-medium text-[var(--preview-on-accent)] hover:bg-[var(--preview-accent-hover)]">
            Open preview
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 3h4v4M13 3l-7 7M7 3H3v10h10V9" /></svg>
          </a>}
        </div>
      </div>
    </dialog>,
    document.body,
  );
}

export function AssetPreviewCell({ asset, variant = "table", appearance = "creative" }: {
  asset: Asset;
  variant?: "table" | "compact" | "card";
  appearance?: AdPopupAppearance;
}) {
  const preview = getAssetPreview(asset);
  // An expired stored thumbnail must not hide a usable Drive file or post.
  const original = getAssetPreview({ preview_url: asset.preview_url });
  const shortcode = original.provider === "Instagram"
    ? original.src?.match(/\/(?:p|reel|tv)\/([\w-]+)\//)?.[1] : null;
  const thumbnails = [...new Set([
    preview.thumbnail, original.thumbnail, shortcode ? instagramThumbUrl(shortcode) : null,
  ].filter((url): url is string => !!url))];
  const [open, setOpen] = useState(false);
  const [failedThumbnails, setFailedThumbnails] = useState<Set<string>>(() => new Set());
  const thumbnail = thumbnails.find((url) => !failedThumbnails.has(url));
  const alternatives: AssetPreview[] = thumbnails
    .filter((url) => url !== preview.src && !failedThumbnails.has(url))
    .map((url) => ({ ...preview, kind: "image", src: url, thumbnail: url, provider: "Thumbnail" }));
  const theme = getAdPopupTheme(appearance);
  const colors = {
    "--asset-preview-bg": theme.mutedSurface,
    "--asset-preview-border": theme.border,
    "--asset-preview-accent": appearance === "creative" ? "#8E6608" : theme.accent,
    "--asset-preview-text": theme.text,
    "--asset-preview-focus": theme.focus,
  } as CSSProperties;
  const card = variant === "card";
  const compact = variant === "compact";

  return (
    <div style={colors} className={`flex shrink-0 flex-col ${card ? "w-full" : compact ? "w-16" : "w-24 items-center gap-1.5"}`} onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        disabled={!preview.href}
        onClick={() => setOpen(true)}
        aria-label={`Preview asset ${asset.asset_id}`}
        title={preview.href ? `Preview ${asset.asset_id}` : "No preview link available"}
        className={`group relative flex items-center justify-center overflow-hidden border-[var(--asset-preview-border)] bg-[var(--asset-preview-bg)] text-[var(--asset-preview-text)] transition-colors hover:border-[var(--asset-preview-accent)] focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--asset-preview-focus)] disabled:cursor-default ${card ? "aspect-[4/3] w-full border-b" : compact ? "h-12 w-16 rounded border" : "h-16 w-24 rounded-md border"}`}
      >
        {thumbnail ? (
          <PreviewImage key={thumbnail} src={thumbnail} alt="" sizes={card ? "(min-width: 1280px) 25vw, (min-width: 768px) 33vw, 50vw" : compact ? "64px" : "96px"} className="object-cover" onError={() => setFailedThumbnails((failed) => new Set(failed).add(thumbnail))} />
        ) : (
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-6 w-6">
            {asset.media === "video" || preview.kind === "video" ? <path d="m9 5 11 7-11 7V5Z" /> : <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8" cy="8" r="1.5" /><path d="m3 17 5-5 4 4 4-6 5 7" /></>}
          </svg>
        )}
        <span className={`absolute inset-x-0 bottom-0 bg-[#14120E]/75 font-medium text-white ${card ? "py-1.5 text-xs" : "py-0.5 text-[9px]"}`}>{preview.href ? "Preview" : "Unavailable"}</span>
      </button>
      {!compact && (preview.href ? (
        <a href={preview.href} target="_blank" rel="noopener noreferrer" aria-label={`Open original asset ${asset.asset_id}`} className={`text-[11px] font-medium text-[var(--asset-preview-accent)] underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-[var(--asset-preview-focus)] ${card ? "px-3 py-1.5" : "whitespace-nowrap"}`}>Open original</a>
      ) : <span className={`text-[11px] text-[var(--asset-preview-text)] ${card ? "px-3 py-1.5" : ""}`}>No preview link</span>)}
      {open && preview.href && <PreviewDialog key={`${asset.asset_id}:${preview.src}`} item={{ id: asset.asset_id, media: asset.media, label: "Asset" }} preview={preview} alternatives={alternatives} appearance={appearance} onClose={() => setOpen(false)} />}
    </div>
  );
}
