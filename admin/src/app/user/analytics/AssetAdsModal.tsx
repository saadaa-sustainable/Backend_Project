"use client";

/**
 * Per-asset ad drill-down, opened by clicking a row in Creative Testing.
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

import { useEffect, useState } from "react";
import {
  ApiError,
  CreativeTestingAdRow,
  fetchCreativeTestingAds,
} from "@/lib/api";
import { AdPreviewLinks, DestinationLink } from "./AdLinks";

const CT = {
  border: "#E8E2D5",
  muted: "#9A9384",
  gold: "#C9A227",
  goldDeep: "#B07E12",
  cream: "#FAF8F3",
};

const CAT_COLOR: Record<string, string> = {
  "Incremental Winner": "#15803D",
  Winner: "#2E7D32",
  "P0 analysis": "#3B6BF5",
  "P1 analysis": "#D97706",
  "P2 analysis": "#8B5A2B",
  "Result Awaited": "#C9A227",
  Discarded: "#C0392B",
};

const STATUS_COLOR: Record<string, string> = {
  ACTIVE: "#2E7D32",
  PAUSED: "#D97706",
  ADSET_PAUSED: "#D97706",
  CAMPAIGN_PAUSED: "#D97706",
  ARCHIVED: "#9A9384",
  DELETED: "#C0392B",
};

function money(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return "₹" + Math.round(n).toLocaleString("en-IN");
}
function compact(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1e7) return (n / 1e7).toFixed(2) + "Cr";
  if (Math.abs(n) >= 1e5) return (n / 1e5).toFixed(2) + "L";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + "K";
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

function Flag({ label, on }: { label: string; on: boolean | null }) {
  return (
    <span
      className="rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{
        backgroundColor: on ? "#EAF5EC" : "#F2F0EA",
        color: on ? "#2E7D32" : CT.muted,
        border: `1px solid ${on ? "#BFDFC6" : CT.border}`,
      }}
    >
      {label} {on ? "✓" : "✕"}
    </span>
  );
}

export function AssetAdsModal({
  assetId,
  onClose,
}: {
  assetId: string;
  onClose: () => void;
}) {
  const [ads, setAds] = useState<CreativeTestingAdRow[]>([]);
  const [media, setMedia] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchCreativeTestingAds(assetId)
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
  }, [assetId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !e.defaultPrevented && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const ad = ads[sel];
  const totalSpend = ads.reduce((a, x) => a + (x.spend ?? 0), 0);
  const totalConv = ads.reduce((a, x) => a + (x.conv_value ?? 0), 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(40,36,28,0.45)" }}
      onClick={onClose}
    >
      <div
        className="max-h-[88vh] w-full max-w-4xl overflow-y-auto rounded-xl shadow-2xl"
        style={{ backgroundColor: CT.cream, border: `1px solid ${CT.border}` }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div
          className="flex items-start justify-between gap-3 border-b px-5 py-4"
          style={{ borderColor: CT.border }}
        >
          <div>
            <div className="font-mono text-lg font-semibold tracking-tight">{assetId}</div>
            <div className="text-xs" style={{ color: CT.muted }}>
              {media ?? "—"} · {ads.length} ad{ads.length === 1 ? "" : "s"} ·{" "}
              {ads.length > 1 ? "iterated creative" : "single outing"} · lifetime spend{" "}
              {money(totalSpend)} · blended ROAS{" "}
              {totalSpend > 0 ? num(totalConv / totalSpend) : "—"}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border px-2 py-1 text-sm"
            style={{ borderColor: CT.border, color: CT.muted }}
          >
            ✕
          </button>
        </div>

        {loading && (
          <div className="px-5 py-10 text-center text-sm" style={{ color: CT.muted }}>
            Loading ads…
          </div>
        )}
        {error && <div className="px-5 py-6 text-sm text-rose-700">{error}</div>}

        {!loading && !error && ads.length > 0 && (
          <div className="px-5 py-4">
            {/* iteration toggle — only meaningful when there's more than one */}
            {ads.length > 1 && (
              <>
                <div
                  className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: CT.muted }}
                >
                  Outings · launch order
                </div>
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {ads.map((a, i) => {
                    const active = i === sel;
                    return (
                      <button
                        key={a.ad_id}
                        onClick={() => setSel(i)}
                        title={`${a.ad_created_date ?? ""} · ${a.category ?? ""}`}
                        className="rounded-md border px-2.5 py-1.5 text-xs transition-colors"
                        style={{
                          borderColor: active ? CT.goldDeep : CT.border,
                          backgroundColor: active ? CT.goldDeep : "#FFFFFF",
                          color: active ? "#FFFFFF" : "#3A362E",
                          fontWeight: active ? 600 : 400,
                        }}
                      >
                        {iterLabel(a.iteration_index)}
                        {a.is_copy && (
                          <span
                            className="ml-1 text-[9px]"
                            style={{ color: active ? "#F4E7C8" : CT.muted }}
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
                role="region"
                aria-label="Selected ad"
                className="rounded-lg border bg-white p-4"
                style={{ borderColor: CT.border }}
              >
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span
                    className="rounded px-2 py-0.5 text-[11px] font-medium"
                    style={{
                      backgroundColor: "#FFFFFF",
                      color: STATUS_COLOR[ad.ad_status ?? ""] ?? CT.muted,
                      border: `1px solid ${STATUS_COLOR[ad.ad_status ?? ""] ?? CT.border}`,
                    }}
                  >
                    {ad.ad_status ?? "unknown status"}
                  </span>
                  <span
                    className="rounded px-2 py-0.5 text-[11px] font-medium text-white"
                    style={{ backgroundColor: CAT_COLOR[ad.category ?? ""] ?? CT.muted }}
                  >
                    {ad.category ?? "—"}
                  </span>
                  {ad.is_copy && (
                    <span
                      className="rounded px-2 py-0.5 text-[11px]"
                      style={{ border: `1px solid ${CT.border}`, color: CT.muted }}
                    >
                      duplicated ad
                    </span>
                  )}
                  <span className="text-[11px]" style={{ color: CT.muted }}>
                    launched {ad.ad_created_date ?? "—"}
                  </span>
                </div>

                <div className="mb-3 break-all font-mono text-[12px] leading-snug">
                  {ad.ad_name ?? "—"}
                </div>

                <div className="mb-4 grid gap-3 rounded-md border p-3 sm:grid-cols-2" style={{ borderColor: CT.border }}>
                  <div>
                    <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide" style={{ color: CT.muted }}>Ad preview</div>
                    <AdPreviewLinks key={ad.ad_id} adId={ad.ad_id} url={ad.ad_preview_url} />
                  </div>
                  <div>
                    <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide" style={{ color: CT.muted }}>Website destination</div>
                    <DestinationLink adId={ad.ad_id} url={ad.destination_url} />
                  </div>
                </div>

                <div className="mb-3 flex flex-wrap gap-1.5">
                  <Flag label="F1" on={ad.f1_pass} />
                  <Flag label="F2" on={ad.f2_pass} />
                  <Flag label="F3" on={ad.f3_pass} />
                  <Flag label="F4" on={ad.f4_pass} />
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
                      style={{ borderColor: CT.border, backgroundColor: CT.cream }}
                    >
                      <div
                        className="text-[10px] uppercase tracking-wide"
                        style={{ color: CT.muted }}
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
            {ads.length > 1 && (
              <div className="mt-4">
                <div
                  className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
                  style={{ color: CT.muted }}
                >
                  All outings
                </div>
                <div
                  className="overflow-x-auto rounded-lg border bg-white"
                  style={{ borderColor: CT.border }}
                >
                  <table className="w-full min-w-[620px] text-xs">
                    <thead style={{ color: CT.muted }}>
                      <tr className="text-left text-[10px] uppercase tracking-wide">
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
                            borderColor: CT.border,
                            backgroundColor: i === sel ? "#FDF8E8" : undefined,
                          }}
                        >
                          <td className="px-2 py-1.5">
                            {iterLabel(a.iteration_index)}
                            {a.is_copy && (
                              <span className="ml-1 text-[10px]" style={{ color: CT.muted }}>
                                copy
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-1.5">{a.ad_created_date ?? "—"}</td>
                          <td
                            className="px-2 py-1.5"
                            style={{ color: STATUS_COLOR[a.ad_status ?? ""] ?? CT.muted }}
                          >
                            {a.ad_status ?? "—"}
                          </td>
                          <td
                            className="px-2 py-1.5"
                            style={{ color: CAT_COLOR[a.category ?? ""] ?? CT.muted }}
                          >
                            {a.category ?? "—"}
                          </td>
                          <td className="px-2 py-1.5">
                            <AdPreviewLinks adId={a.ad_id} url={a.ad_preview_url} inline />
                          </td>
                          <td className="px-2 py-1.5">
                            <DestinationLink adId={a.ad_id} url={a.destination_url} />
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
          <div className="px-5 py-10 text-center text-sm" style={{ color: CT.muted }}>
            No ads found for this asset.
          </div>
        )}
      </div>
    </div>
  );
}

export default AssetAdsModal;
