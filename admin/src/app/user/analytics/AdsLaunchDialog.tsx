"use client";

/**
 * AdsLaunchDialog — the popup the Ads Analyse "Analytics" button opens.
 *
 * A shell, deliberately. It owns opening, closing and focus; the chart
 * inside it owns everything about the chart. That split is why the chart
 * needed no changes to move in here, and why anything else can be added
 * to the popup later without touching this file.
 *
 * Native <dialog> via showModal(), the same approach AssetAdsModal takes:
 * the browser supplies the backdrop, the focus trap, Escape-to-close and
 * inert-ing of the page behind. None of that is worth reimplementing.
 *
 * Rendered through a portal so it escapes the table's overflow and
 * stacking contexts. Inside them a fixed-position dialog clips against
 * the scroll container instead of the viewport.
 */

import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

export function AdsLaunchDialog({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    // Remember who opened it, so focus returns there on close rather
    // than to the top of the document.
    const previousFocus = document.activeElement as HTMLElement | null;
    if (!dialog.open) dialog.showModal();
    // showModal() alone does not stop the page behind from scrolling.
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  return createPortal(
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      // The Escape key fires `cancel`. Without preventDefault the dialog
      // closes itself while React still thinks it is open, and the next
      // open() call is a no-op on an element the browser already closed.
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      // Clicks INSIDE the chart bubble up to the dialog element, so the
      // target check is what separates "clicked the backdrop" from
      // "clicked a bar". Without it the popup shuts on every interaction.
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      className="fixed inset-0 m-auto max-h-[88dvh] w-[calc(100%-2rem)] max-w-6xl overflow-y-auto rounded-xl border border-border-primary bg-white p-0 shadow-2xl backdrop:bg-black/50"
    >
      <div className="flex items-center justify-between gap-3 border-b border-border-primary px-5 py-3">
        <div>
          <h2 id={titleId} className="text-sm font-semibold text-text-primary">
            Analytics
          </h2>
          <p className="text-[11px] text-text-secondary">
            Across every ad matching the current filters, not just the rows in the table
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close analytics"
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs text-text-secondary hover:bg-bg-muted"
        >
          ✕
        </button>
      </div>
      <div className="p-4">{children}</div>
    </dialog>,
    document.body,
  );
}
