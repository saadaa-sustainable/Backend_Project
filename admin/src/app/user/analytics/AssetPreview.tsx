"use client";

import Image from "next/image";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { getAdPopupTheme, type AdPopupAppearance } from "@/lib/adPopupTheme";
import { getAssetPreview, type AssetPreview, type AssetPreviewSource } from "@/lib/assetPreview";

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

export function PreviewDialog({ item, preview, onClose, appearance = "creative" }: {
  item: { id: string; media: string | null; label: "Asset" | "Ad" };
  preview: AssetPreview;
  onClose: () => void;
  appearance?: AdPopupAppearance;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [failed, setFailed] = useState(false);
  const theme = getAdPopupTheme(appearance);
  const colors = {
    "--preview-bg": theme.bg,
    "--preview-surface": theme.surface,
    "--preview-border": theme.border,
    "--preview-text": theme.text,
    "--preview-muted": theme.muted,
    "--preview-accent": theme.accent,
    "--preview-accent-hover": theme.accentHover,
    "--preview-on-accent": theme.onAccent,
    "--preview-focus": theme.focus,
  } as CSSProperties;

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  return createPortal(
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onKeyDown={(event) => { if (event.key === "Escape") event.stopPropagation(); }}
      onClick={(event) => { event.stopPropagation(); if (event.target === event.currentTarget) onClose(); }}
      style={colors}
      className="fixed inset-0 m-auto max-h-[92dvh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-xl border border-[var(--preview-border)] bg-[var(--preview-bg)] p-0 text-[var(--preview-text)] shadow-2xl backdrop:bg-black/60"
    >
      <div className="flex items-center justify-between gap-3 border-b border-[var(--preview-border)] px-4 py-3">
        <div>
          <h2 id={titleId} className="font-semibold">{item.label} preview · {item.id}</h2>
          <p className="text-xs text-[var(--preview-muted)]">{preview.provider}{item.media ? ` · ${item.media}` : ""}</p>
        </div>
        <button type="button" autoFocus onClick={onClose} aria-label={`Close ${item.label.toLowerCase()} preview`} className="rounded-md border border-[var(--preview-border)] px-3 py-1.5 hover:bg-[var(--preview-surface)] focus-visible:outline-2 focus-visible:outline-[var(--preview-focus)]">✕</button>
      </div>

      <div className="p-4">
        <div className="relative flex min-h-56 items-center justify-center overflow-hidden rounded-lg border border-[var(--preview-border)] bg-[var(--preview-surface)]">
          {!failed && preview.src && preview.kind === "embed" ? (
            <iframe
              src={preview.src}
              title={`Preview of ${item.id}`}
              className="h-[60dvh] min-h-72 w-full border-0"
              allow="fullscreen; encrypted-media"
              allowFullScreen
              onError={() => setFailed(true)}
            />
          ) : !failed && preview.src && preview.kind === "video" ? (
            // Captions are not supplied by the asset register.
            <video src={preview.src} poster={preview.thumbnail ?? undefined} controls playsInline preload="none" aria-label={`Preview of ${item.id}`} className="max-h-[60dvh] w-full" onError={() => setFailed(true)} />
          ) : !failed && preview.src && preview.kind === "image" ? (
            <div className="relative h-[60dvh] w-full">
              <PreviewImage src={preview.src} alt={`Creative ${item.label.toLowerCase()} ${item.id}`} sizes="(max-width: 672px) 90vw, 640px" className="object-contain" onError={() => setFailed(true)} />
            </div>
          ) : (
            <p className="max-w-sm px-6 py-12 text-center text-sm text-[var(--preview-muted)]">
              {failed ? "This preview could not be loaded." : `This ${item.label.toLowerCase()} opens on its source website.`} Use the preview link below to view it.
            </p>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-[var(--preview-muted)]">If the preview doesn’t load, open the original {item.label.toLowerCase()}.</p>
          <a href={preview.href!} target="_blank" rel="noopener noreferrer" className="rounded-md bg-[var(--preview-accent)] px-3 py-2 text-sm font-medium text-[var(--preview-on-accent)] hover:bg-[var(--preview-accent-hover)]">Open preview ↗</a>
        </div>
      </div>
    </dialog>,
    document.body,
  );
}

export function AssetPreviewCell({ asset }: { asset: Asset }) {
  const preview = getAssetPreview(asset);
  const [open, setOpen] = useState(false);
  const [failedThumbnail, setFailedThumbnail] = useState<string | null>(null);
  const showThumbnail = preview.thumbnail && failedThumbnail !== preview.thumbnail;

  return (
    <div className="flex w-24 flex-col items-center gap-1.5" onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        disabled={!preview.href}
        onClick={() => setOpen(true)}
        aria-label={`Preview asset ${asset.asset_id}`}
        title={preview.href ? `Preview ${asset.asset_id}` : "No preview link available"}
        className="group relative flex h-16 w-24 items-center justify-center overflow-hidden rounded-md border border-[#E0DCD2] bg-[#F9F8F6] text-[#8E6608] transition-colors hover:border-[#8E6608] focus-visible:outline-2 focus-visible:outline-[#8E6608] disabled:cursor-default disabled:text-[#716D64] disabled:hover:border-[#E0DCD2]"
      >
        {showThumbnail ? (
          <PreviewImage src={preview.thumbnail!} alt="" sizes="96px" className="object-cover" onError={() => setFailedThumbnail(preview.thumbnail)} />
        ) : (
          <span aria-hidden="true" className="text-xl">{asset.media === "graphic" ? "▧" : "▶"}</span>
        )}
        <span className="absolute inset-x-0 bottom-0 bg-[#14120E]/75 py-0.5 text-[9px] font-medium text-white">{preview.href ? "Preview" : "Unavailable"}</span>
      </button>
      {preview.href ? (
        <a href={preview.href} target="_blank" rel="noopener noreferrer" aria-label={`Open preview for ${asset.asset_id}`} className="whitespace-nowrap text-[11px] font-medium text-[#8E6608] underline underline-offset-2 hover:text-[#8E6608]">Open preview ↗</a>
      ) : (
        <span className="text-[11px] text-[#716D64]">No preview link</span>
      )}
      {open && preview.href && <PreviewDialog key={`${asset.asset_id}:${preview.src}`} item={{ id: asset.asset_id, media: asset.media, label: "Asset" }} preview={preview} onClose={() => setOpen(false)} />}
    </div>
  );
}
