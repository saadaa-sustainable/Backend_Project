"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError, fetchAssetIterations, type AssetAnalysisRow, type AssetIteration } from "@/lib/api";
import { lockBodyScroll } from "@/lib/bodyScrollLock";
import { useAnalyticsSectionVisible } from "@/lib/analyticsSectionVisibility";
import { FigureBand, Segmented } from "./SectionChrome";
import { MarkClose } from "./Pictograms";
import { AssetPreviewCell } from "./AssetPreview";

const number = (n: number | null | undefined) => n == null ? "—" : Math.round(n).toLocaleString("en-IN");
const money = (n: number | null | undefined) => n == null ? "—" : `₹${number(n)}`;
const ratio = (n: number | null | undefined) => n == null ? "—" : `${n.toFixed(2)}x`;
const cost = (n: number | null) => n == null ? "—" : `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const divide = (n: number | null | undefined, d: number | null | undefined, scale = 1) =>
  n != null && d != null && d > 0 ? n / d * scale : null;
const day = (s: string | null) => s ? new Date(`${s}T00:00:00`).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—";
const refreshed = (s: string | null) => s ? `${new Date(s).toLocaleString("en-GB", {
  day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata",
})} IST` : "—";
const isActive = (ad: AssetIteration) => ad.ad_effective_status?.trim().toUpperCase() === "ACTIVE";

function Metrics({ values }: { values: [string, string][] }) {
  return <dl className="my-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-6">
    {values.map(([label, value]) => <div key={label}>
      <dt className="text-[11px] leading-normal text-text-secondary">{label}</dt>
      <dd className="mt-1 break-words font-mono text-[14px] tabular-nums text-text-primary">{value}</dd>
    </div>)}
  </dl>;
}

function MappedAd({ ad, assetId, latest }: { ad: AssetIteration; assetId: string; latest: number }) {
  const ctr = divide(ad.link_clicks, ad.impressions, 100);
  return <article data-ad-id={ad.ad_id} className="border-b border-border-primary py-4">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[12px]">
      <span className="font-mono text-text-secondary">ITE {ad.iter_no}</span>
      <span className={`px-1.5 py-0.5 text-[11px] font-semibold ${ad.won ? "bg-success-bg text-success-text" : "bg-bg-muted text-text-secondary"}`}>
        {ad.category ?? "Unrated"}
      </span>
      {ad.won && <span className="text-[11px] text-success-text">Won here</span>}
      {ad.iter_no === latest && <span className="text-[11px] text-text-secondary">Latest iteration</span>}
      <span className="basis-full text-text-secondary sm:ml-auto sm:basis-auto">Created {day(ad.ad_created_date)}</span>
    </div>
    <h4 className="mb-1 mt-2 break-words font-mono text-[13px] font-medium leading-normal">{ad.ad_name ?? ad.ad_id}</h4>
    <p className="break-words text-[12px] text-text-secondary">{ad.account_name ?? "Account unavailable"} · {ad.ad_effective_status ?? "Status unavailable"}</p>
    <Metrics values={[
      ["Spend", money(ad.spend)], ["Impressions", number(ad.impressions)],
      ["Shopify ROAS", ratio(ad.shopify_roas)], ["Meta ROAS", ratio(ad.roas)],
      ["Shopify orders", number(ad.shopify_orders)], ["Meta purchases", number(ad.purchases)],
    ]} />
    <details>
      <summary className="w-fit cursor-pointer py-1 text-[12px] text-text-secondary hover:text-text-primary focus-visible:outline-2">More metrics and ad details</summary>
      <div className="bg-bg-base px-3 py-0.5">
        <Metrics values={[
          ["Shopify revenue", money(ad.shopify_revenue)], ["Meta conversion value", money(ad.conv_value)],
          ["Link clicks", number(ad.link_clicks)], ["Link CTR", ctr == null ? "—" : `${ctr.toFixed(2)}%`],
          ["Cost / link click", cost(divide(ad.spend, ad.link_clicks))], ["CPM", cost(divide(ad.spend, ad.impressions, 1000))],
          ["New customer purchases", number(ad.ncp)], ["Cost / NCP", cost(divide(ad.spend, ad.ncp))],
          ["First-time engaged visitors", number(ad.ftewv)], ["Cost / engaged visitor", cost(divide(ad.spend, ad.ftewv))],
          ["Cost / Shopify order", cost(divide(ad.spend, ad.shopify_orders))], ["Cost / Meta purchase", cost(divide(ad.spend, ad.purchases))],
        ]} />
      </div>
      <dl className="mt-3 grid grid-cols-[100px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12px] leading-normal">
        {([
          ["Asset", assetId], ["Ad ID", ad.ad_id], ["Campaign", ad.campaign_name ?? "—"],
          ["Ad set", ad.adset_name ?? "—"], ["Match source", ad.match_source ?? "—"],
          ["Name conflict", ad.name_conflict == null ? "—" : ad.name_conflict ? "Yes" : "No"],
          ["Shopify refreshed", refreshed(ad.gold_refreshed_at)],
        ] as [string, string][]).map(([label, value]) => <div key={label} className="contents">
          <dt className="text-text-secondary">{label}</dt><dd className="break-words">{value}</dd>
        </div>)}
      </dl>
    </details>
  </article>;
}

export function AssetAnalysisDrawer({ row, onClose }: { row: AssetAnalysisRow; onClose: () => void }) {
  const [ads, setAds] = useState<AssetIteration[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const visible = useAnalyticsSectionVisible();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    let cancelled = false;
    fetchAssetIterations(row.asset_id)
      .then((data) => { if (!cancelled) setAds(data.iterations); })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof ApiError ? e.message : "Could not load mapped ads."); });
    return () => { cancelled = true; };
  }, [row.asset_id]);

  useEffect(() => {
    if (!visible) onClose();
  }, [visible, onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();
    const unlock = lockBodyScroll();
    return () => {
      dialog?.close();
      unlock();
      if (previous?.isConnected) previous.focus();
    };
  }, []);

  const shown = filter === "active" ? ads?.filter(isActive) : ads;
  const latest = Math.max(0, ...(ads ?? []).map((ad) => ad.iter_no));
  const firstWin = ads?.find((ad) => ad.won);
  // Match the API's newest-date ordering, including its ad-ID tie break.
  // The drawer is lifetime even when the board has a creation-date filter.
  const newestAd = ads?.reduce<AssetIteration | undefined>((newest, ad) => {
    if (!newest) return ad;
    const adDate = ad.ad_created_date ?? "", newestDate = newest.ad_created_date ?? "";
    return adDate > newestDate || (adDate === newestDate && ad.ad_id < newest.ad_id) ? ad : newest;
  }, undefined);
  const sum = (key: "spend" | "conv_value" | "ncp") => ads?.length ? ads.reduce((n, ad) => n + ad[key], 0) : null;
  const spend = sum("spend"), conv = sum("conv_value"), ncp = sum("ncp");

  return createPortal(<dialog ref={dialogRef} aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
    className="fixed inset-y-0 left-auto right-0 m-0 h-dvh max-h-none w-full max-w-[1060px] overflow-y-auto border-0 border-l border-border-primary bg-bg-white p-0 text-text-primary backdrop:bg-black/25 sm:w-[96vw]">
    <div className="px-4 py-5 sm:px-6">
      <div className="flex items-start justify-between gap-4 border-b border-border-primary pb-3">
        <AssetPreviewCell asset={row} variant="compact" appearance="standard" />
        <div className="min-w-0 flex-1">
          <h3 id={titleId} className="break-words font-mono text-[20px] font-semibold">{row.asset_id}</h3>
          <p className="mt-1.5 text-[12px] text-text-secondary">Current result: {ads ? newestAd?.category ?? "Unrated" : "—"}</p>
          {firstWin && <p className="mt-1 text-[12px] text-success-text">First won at iteration {firstWin.iter_no} · {day(firstWin.ad_created_date)}</p>}
          <p className="mt-1.5 text-[12px] text-text-secondary">{row.media ?? "—"} · {row.account_name ?? "—"}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close asset details" autoFocus className="flex min-h-10 min-w-10 shrink-0 items-center justify-center p-2 text-text-secondary hover:text-text-primary"><MarkClose /></button>
      </div>
      <FigureBand figures={[
        { label: "Lifetime spend", value: money(spend) }, { label: "Meta ROAS", value: ratio(divide(conv, spend)) },
        { label: "NCP", value: number(ncp) }, { label: "Cost / NCP", value: cost(divide(spend, ncp)) },
        { label: "Mapped ads", value: ads ? number(ads.length) : "—" },
        { label: "Active ads", value: ads ? number(ads.filter(isActive).length) : "—" },
      ]} />
      <section className="mt-5" aria-label="Mapped ads" aria-busy={!ads && !error}>
        <div className="flex flex-wrap items-center gap-3 border-b border-border-primary pb-2">
          <h4 className="text-[15px] font-semibold">Mapped ads</h4>
          <span role="status" className="text-[12px] text-text-secondary">{ads ? `${shown?.length ?? 0} ${filter === "active" ? "active ads" : "ads"} of ${ads.length} mapped` : ""}</span>
          <div className="sm:ml-auto [&_button]:min-h-9">
            {ads && <Segmented options={[{ value: "all", label: "All ads" }, { value: "active", label: "Active ads" }]} value={filter} onChange={setFilter} />}
          </div>
        </div>
        <p className="mt-2 text-[12px] leading-relaxed text-text-secondary">
          Lifetime metrics · oldest ad first · {filter === "active" ? "active ads, including older iterations and zero-spend ads" : "includes paused and zero-spend ads"}.<br />
          Asset totals above include all mapped ads. Meta ROAS uses Meta conversion value; Shopify ROAS uses the existing attribution summary. Missing values appear as —.
        </p>
        {error && <p role="alert" className="py-5 text-[13px] text-error-text">{error}</p>}
        {!ads && !error && <p role="status" className="py-5 text-[13px] text-text-secondary">Loading mapped ad details…</p>}
        {ads && !shown?.length && <p role="status" className="py-5 text-[13px] text-text-secondary">{ads.length ? "No active ads for this asset. Select All ads to view its mapped ads." : "No mapped ads are available for this asset."}</p>}
        {shown?.map((ad) => <MappedAd key={ad.ad_id} ad={ad} assetId={row.asset_id} latest={latest} />)}
      </section>
    </div>
  </dialog>, document.body);
}
