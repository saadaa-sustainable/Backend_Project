"use client";

/**
 * Per-asset ad drill-down, shared by Creative Testing and Untested Assets.
 *
 * A NEW asset normally has one ad, so the modal just shows it. An
 * ITERATED asset has several — the same creative put back in market more
 * than once — and those are stepped through with a toggle: Original,
 * 1st iteration, 2nd iteration, and so on in launch order.
 *
 * That ordering is the point of the view. The same asset can be running
 * in several ads at once and can perform completely differently each
 * time, so "how did this creative do, and how is it doing now" is only
 * answerable per outing. Real example, GAD-Sep-340: the original was a
 * P1 at ROAS 1.62, its 1st iteration became a Winner on Rs 10.7L at
 * 2.76, and five later copies ranged from Discarded to ROAS 13.
 */

import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import {
  ApiError,
  CreativeTestingAdRow,
  fetchCreativeTestingAds,
} from "@/lib/api";
import { AdPreviewLinks, DestinationLink } from "./AdLinks";
import { getAdPopupTheme, type AdPopupAppearance } from "@/lib/adPopupTheme";

const CAT_COLOR: Record<string, string> = {
  "Incremental Winner": "#2F6B3A",
  Winner: "#2F6B3A",
  "P0 analysis": "#1D4E89",
  "P1 analysis": "#B45309",
  "P2 analysis": "#8E6608",
  "Result Awaited": "#8E6608",
  Discarded: "#9E0C24",
};

const STATUS_COLOR: Record<string, string> = {
  ACTIVE: "#2F6B3A",
  PAUSED: "#B45309",
  ADSET_PAUSED: "#B45309",
  CAMPAIGN_PAUSED: "#B45309",
  ARCHIVED: "#716D64",
  DELETED: "#9E0C24",
};

function money(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return "₹" + Math.round(n).toLocaleString("en-IN");
}
function compact(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  // Full figures, Indian grouping -- see the note in AdsAnalyse.tsx.
  return Math.round(n).toLocaleString("en-IN");
}
function num(n: number | null | undefined, d = 2) {
  if (n === null || n === undefined) return "—";
  return n.toFixed(d);
}
function iterLabel(i: number) {
  if (i === 0) return "Original";
  if (i === 1) return "1st iteration";
  if (i === 2) return "2nd iteration";
  if (i === 3) return "3rd iteration";
  return `${i}th iteration`;
}

function Flag({ label, on, appearance }: {
  label: string; on: boolean | null; appearance: AdPopupAppearance;
}) {
  const colors = getAdPopupTheme(appearance);
  return (
    <span
      className="rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{
        backgroundColor: on ? "#E7EDE2" : colors.mutedSurface,
        color: on ? "#2F6B3A" : colors.muted,
        border: `1px solid ${on ? "#E7EDE2" : colors.border}`,
      }}
    >
      {label} {on ? "✓" : "✕"}
    </span>
  );
}

type AssetAdsModalProps = {
  assetId: string;
  assetName?: string;
  appearance?: AdPopupAppearance;
  requestTimeoutMs?: number;
  onClose: () => void;
};

export function AssetAdsModal(props: AssetAdsModalProps) {
  return <AssetAdsDialog key={props.assetId} {...props} />;
}

function AssetAdsDialog({
  assetId,
  assetName,
  appearance = "creative",
  requestTimeoutMs,
  onClose,
}: AssetAdsModalProps) {
  const colors = getAdPopupTheme(appearance);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const selectedAdId = useId();
  const [ads, setAds] = useState<CreativeTestingAdRow[]>([]);
  const [media, setMedia] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchCreativeTestingAds(assetId, requestTimeoutMs)
      .then((res) => {
        if (cancelled) return;
        setAds(res.ads);
        setMedia(res.media);
        setSel(0);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof ApiError ? e.message : "Could not load this asset's ads.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [assetId, requestTimeoutMs, attempt]);

  useEffect(() => {
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    dialog?.showModal();
    document.body.style.overflow = "hidden";
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, []);

  function retry() {
    setError(null);
    setLoading(true);
    setAttempt((value) => value + 1);
  }

  const ad = ads[sel];
  const totalSpend = ads.reduce((a, x) => a + (x.spend ?? 0), 0);
  const totalConv = ads.reduce((a, x) => a + (x.conv_value ?? 0), 0);

  return createPortal(
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onCancel={(event) => {
        if (event.target !== event.currentTarget) return;
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => { if (event.key === "Escape") event.stopPropagation(); }}
      onClick={(event) => { event.stopPropagation(); if (event.target === event.currentTarget) onClose(); }}
      className="fixed inset-0 m-auto max-h-[88dvh] w-[calc(100%-2rem)] max-w-5xl overflow-y-auto rounded-xl border p-0 shadow-2xl backdrop:bg-black/50"
      style={{ backgroundColor: colors.bg, borderColor: colors.border, color: colors.text, "--asset-ad-focus": colors.focus } as CSSProperties}
    >
      <div>
        {/* header */}
        <div
          className="flex items-start justify-between gap-3 border-b px-5 py-4"
          style={{ borderColor: colors.border }}
        >
          <div className="min-w-0">
            <h2 id={titleId} className="break-words text-lg font-semibold tracking-tight">
              Asset · {assetName?.trim() || assetId}
            </h2>
            <div className="mt-1 break-all font-mono text-xs" style={{ color: colors.muted }}>
              Asset ID: {assetId}
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {loading ? "Loading matched ads…" : error ? "Matched ads unavailable" : (
                <>
                  {ads.length} matched ad{ads.length === 1 ? "" : "s"}
                  {media ? ` · ${media}` : ""} · lifetime spend {money(totalSpend)} · blended ROAS{" "}
                  {totalSpend > 0 ? num(totalConv / totalSpend) : "—"}
                </>
              )}
            </div>
          </div>
          <button
            type="button"
            autoFocus
            onClick={onClose}
            aria-label="Close matched ads"
            className="rounded-md border px-2 py-1 text-sm focus-visible:outline-2 focus-visible:outline-[var(--asset-ad-focus)]"
            style={{ borderColor: colors.border, color: colors.muted }}
          >
            ✕
          </button>
        </div>

        {loading && (
          <div role="status" className="px-5 py-10 text-center text-sm" style={{ color: colors.muted }}>
            Loading ads…
          </div>
        )}
        {error && (
          <div className="px-5 py-6 text-sm">
            <p role="alert" className="text-rose-700">{error}</p>
            <button type="button" onClick={retry} className="mt-3 rounded-md border px-3 py-1.5 focus-visible:outline-2 focus-visible:outline-[var(--asset-ad-focus)]" style={{ borderColor: colors.border, backgroundColor: colors.surface, color: colors.accent }}>
              Retry loading ads
            </button>
          </div>
        )}

        {!loading && !error && ads.length > 0 && (
          <div className="px-5 py-4">
            {/* iteration toggle — only meaningful when there's more than one */}
            {ads.length > 1 && (
              <>
                <div
                  className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: colors.muted }}
                >
                  Outings · launch order
                </div>
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {ads.map((a, i) => {
                    const active = i === sel;
                    return (
                      <button
                        key={a.ad_id}
                        type="button"
                        onClick={() => setSel(i)}
                        aria-pressed={active}
                        aria-controls={selectedAdId}
                        title={`${a.ad_created_date ?? ""} · ${a.category ?? ""}`}
                        className="rounded-md border px-2.5 py-1.5 text-xs transition-colors"
                        style={{
                          borderColor: active ? colors.accent : colors.border,
                          backgroundColor: active ? colors.accent : colors.surface,
                          color: active ? colors.onAccent : colors.text,
                          fontWeight: active ? 600 : 400,
                        }}
                      >
                        {iterLabel(a.iteration_index)}
                        {a.is_copy && (
                          <span
                            className="ml-1 text-[9px]"
                            style={{ color: active ? colors.onAccent : colors.muted }}
                          >
                            copy
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </>
            )}

            {/* selected ad */}
            {ad && (
              <div
                id={selectedAdId}
                role="region"
                aria-label="Selected ad"
                className="rounded-lg border bg-white p-4"
                style={{ borderColor: colors.border }}
              >
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span
                    className="rounded px-2 py-0.5 text-[11px] font-medium"
                    style={{
                      backgroundColor: colors.surface,
                      color: STATUS_COLOR[ad.ad_status ?? ""] ?? colors.muted,
                      border: `1px solid ${STATUS_COLOR[ad.ad_status ?? ""] ?? colors.border}`,
                    }}
                  >
                    {ad.ad_status ?? "unknown status"}
                  </span>
                  <span
                    className="rounded px-2 py-0.5 text-[11px] font-medium text-white"
                    style={{ backgroundColor: CAT_COLOR[ad.category ?? ""] ?? colors.muted }}
                  >
                    {ad.category ?? "—"}
                  </span>
                  {ad.is_copy && (
                    <span
                      className="rounded px-2 py-0.5 text-[11px]"
                      style={{ border: `1px solid ${colors.border}`, color: colors.muted }}
                    >
                      duplicated ad
                    </span>
                  )}
                  <span className="text-[11px]" style={{ color: colors.muted }}>
                    launched {ad.ad_created_date ?? "—"}
                  </span>
                </div>

                <div className="mb-3 break-words text-sm font-medium leading-snug">
                  Ad name: {ad.ad_name || "Unnamed ad"}
                  <div className="mt-1 break-all font-mono text-[11px] font-normal" style={{ color: colors.muted }}>
                    Ad ID: {ad.ad_id}
                  </div>
                </div>

                <div className="mb-4 grid gap-3 rounded-md border p-3 sm:grid-cols-2" style={{ borderColor: colors.border }}>
                  <div>
                    <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide" style={{ color: colors.muted }}>Ad preview</div>
                    <AdPreviewLinks appearance={appearance} key={ad.ad_id} adId={ad.ad_id} url={ad.ad_preview_url} />
                  </div>
                  <div>
                    <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide" style={{ color: colors.muted }}>Website destination</div>
                    <DestinationLink appearance={appearance} adId={ad.ad_id} url={ad.destination_url} />
                  </div>
                </div>

                <div className="mb-3 flex flex-wrap gap-1.5">
                  <Flag appearance={appearance} label="F1" on={ad.f1_pass} />
                  <Flag appearance={appearance} label="F2" on={ad.f2_pass} />
                  <Flag appearance={appearance} label="F3" on={ad.f3_pass} />
                  <Flag appearance={appearance} label="F4" on={ad.f4_pass} />
                </div>

                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {(
                    [
                      ["Spend", money(ad.spend)],
                      ["Impressions", compact(ad.impressions)],
                      ["Purchases", compact(ad.purchases)],
                      ["ROAS", num(ad.roas)],
                      ["Conv. value", money(ad.conv_value)],
                      ["NCP", compact(ad.ncp_count)],
                      ["Cost / NCP", money(ad.cost_per_ncp)],
                      ["Cost / FTEWV", money(ad.cost_per_ftewv)],
                    ] as [string, string][]
                  ).map(([label, value]) => (
                    <div
                      key={label}
                      className="rounded-md border p-2"
                      style={{ borderColor: colors.border, backgroundColor: appearance === "standard" ? colors.mutedSurface : colors.bg }}
                    >
                      <div
                        className="text-[10px] uppercase tracking-wide"
                        style={{ color: colors.muted }}
                      >
                        {label}
                      </div>
                      <div className="mt-0.5 text-sm font-semibold">{value}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* all outings at a glance */}
            {ads.length > 0 && (
              <div className="mt-4">
                <div
                  className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: colors.muted }}
                >
                  All matched ads · {ads.length}
                </div>
                <div
                  className="overflow-x-auto rounded-lg border bg-white"
                  style={{ borderColor: colors.border }}
                >
                  <table aria-label="All matched ads" className="w-full min-w-[900px] text-xs">
                    <thead style={{ color: colors.muted, backgroundColor: appearance === "standard" ? colors.mutedSurface : undefined }}>
                      <tr className="text-left text-[10px] uppercase tracking-wide">
                        <th className="px-2 py-1.5">Ad name / ID</th>
                        <th className="px-2 py-1.5">Outing</th>
                        <th className="px-2 py-1.5">Launched</th>
                        <th className="px-2 py-1.5">Status</th>
                        <th className="px-2 py-1.5">Verdict</th>
                        <th className="px-2 py-1.5">Ad preview</th>
                        <th className="px-2 py-1.5">Website destination</th>
                        <th className="px-2 py-1.5 text-right">Spend</th>
                        <th className="px-2 py-1.5 text-right">ROAS</th>
                        <th className="px-2 py-1.5 text-right">₹/NCP</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ads.map((a, i) => (
                        <tr
                          key={a.ad_id}
                          onClick={() => setSel(i)}
                          className="cursor-pointer border-t"
                          style={{
                            borderColor: colors.border,
                            backgroundColor: i === sel ? colors.selected : undefined,
                          }}
                        >
                          <td className="px-2 py-1.5">
                            <button
                              type="button"
                              onClick={() => setSel(i)}
                              aria-pressed={i === sel}
                              aria-controls={selectedAdId}
                              style={{ color: colors.accent }}
                              className="min-w-48 max-w-80 rounded text-left hover:underline focus-visible:outline-2 focus-visible:outline-[var(--asset-ad-focus)]"
                            >
                              <span className="block break-words font-medium">{a.ad_name || "Unnamed ad"}</span>
                              <span className="mt-1 block break-all font-mono text-[10px]" style={{ color: colors.muted }}>{a.ad_id}</span>
                            </button>
                          </td>
                          <td className="px-2 py-1.5">
                            {iterLabel(a.iteration_index)}
                            {a.is_copy && (
                              <span className="ml-1 text-[10px]" style={{ color: colors.muted }}>
                                copy
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-1.5">{a.ad_created_date ?? "—"}</td>
                          <td
                            className="px-2 py-1.5"
                            style={{ color: STATUS_COLOR[a.ad_status ?? ""] ?? colors.muted }}
                          >
                            {a.ad_status ?? "—"}
                          </td>
                          <td
                            className="px-2 py-1.5"
                            style={{ color: CAT_COLOR[a.category ?? ""] ?? colors.muted }}
                          >
                            {a.category ?? "—"}
                          </td>
                          <td className="px-2 py-1.5">
                            <AdPreviewLinks appearance={appearance} adId={a.ad_id} url={a.ad_preview_url} inline />
                          </td>
                          <td className="px-2 py-1.5">
                            <DestinationLink appearance={appearance} adId={a.ad_id} url={a.destination_url} />
                          </td>
                          <td className="px-2 py-1.5 text-right">{money(a.spend)}</td>
                          <td className="px-2 py-1.5 text-right">{num(a.roas)}</td>
                          <td className="px-2 py-1.5 text-right">{money(a.cost_per_ncp)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {!loading && !error && ads.length === 0 && (
          <div className="px-5 py-10 text-center text-sm" style={{ color: colors.muted }}>
            No ads found for this asset.
          </div>
        )}
      </div>
    </dialog>,
    document.body,
  );
}

export default AssetAdsModal;
