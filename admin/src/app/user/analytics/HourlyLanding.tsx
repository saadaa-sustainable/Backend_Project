"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  LandingHourlyPage,
  LandingHourlyResponse,
  fetchLandingHourly,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import {
  FilterCell,
  SectionHeader,
  Segmented,
  TableFrame,
  filterControlClass,
} from "./SectionChrome";

/**
 * Which PAGE the hour belongs to.
 *
 * The Hourly Tracker answers "how is the store doing this hour". This
 * answers the same question one level down, per landing page, off
 * hourly_landing_tracker.
 *
 * Two numbers on every row look like they should match and do not, by
 * design. `Meta sales` and `Meta ROAS` are what Meta reports for the ads
 * POINTING at a page. `Shopify sales` and `Shopify ROAS` are what the
 * store booked from people who LANDED on it. An ad can send someone to a
 * collection who buys from a product page; Meta credits the collection,
 * the store credits the product. Showing one and calling it revenue
 * would hide that; showing both is the point of the table.
 */

const IST_OFFSET_MIN = 330;

/** Today in Asia/Kolkata, whatever the viewer's clock says. The store
 *  reports in IST, so the dashboard has to think in IST. */
function istToday(): string {
  const now = new Date();
  const ist = new Date(now.getTime() + (IST_OFFSET_MIN + now.getTimezoneOffset()) * 60000);
  return ist.toISOString().slice(0, 10);
}

function daysAgo(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

const RANGES = [
  { value: "0", label: "Today" },
  { value: "1", label: "2 days" },
  { value: "6", label: "7 days" },
  { value: "29", label: "30 days" },
];

type Metric = {
  band: Band;
  key: keyof LandingHourlyPage;
  label: string;
  w: number;
  kind: "money" | "int" | "ratio" | "pct";
};

// Three bands, because the columns answer three different questions
// about one page and must not be read as a funnel:
//
//   TRAFFIC   what LANDED here        (ShopifyQL sessions)
//   ORDERS    what was PLACED here    (the order's own URL)
//   META ADS  what was AIMED here     (the ad creative's URL)
type Band = "traffic" | "orders" | "ads";
const BANDS: { band: Band; label: string }[] = [
  { band: "traffic", label: "Traffic — landed here" },
  { band: "orders", label: "Orders — placed here" },
  { band: "ads", label: "Meta ads — aimed here" },
];

const METRICS: Metric[] = [
  { band: "traffic", key: "sessions", label: "Sessions", w: 84, kind: "int" },
  { band: "traffic", key: "visitors", label: "Visitors", w: 84, kind: "int" },
  { band: "traffic", key: "bounce_rate", label: "Bounce %", w: 84, kind: "pct" },
  { band: "traffic", key: "atc_rate", label: "ATC %", w: 76, kind: "pct" },
  { band: "traffic", key: "checkout_rate", label: "Checkout %", w: 92, kind: "pct" },
  { band: "orders", key: "revenue", label: "Shopify sales", w: 104, kind: "money" },
  { band: "orders", key: "orders", label: "Shopify orders", w: 88, kind: "int" },
  { band: "orders", key: "new_customer_sales", label: "New customer sales", w: 112, kind: "money" },
  { band: "orders", key: "repeat_customer_sales", label: "Repeat customer sales", w: 118, kind: "money" },
  { band: "orders", key: "new_customer_orders", label: "New orders", w: 82, kind: "int" },
  { band: "orders", key: "repeat_customer_orders", label: "Repeat orders", w: 88, kind: "int" },
  { band: "ads", key: "meta_spend", label: "Meta spend", w: 96, kind: "money" },
  { band: "ads", key: "ncp", label: "NCP", w: 70, kind: "int" },
  { band: "ads", key: "meta_purchases", label: "Conversions", w: 88, kind: "int" },
  { band: "ads", key: "meta_conv_value", label: "Meta sales", w: 100, kind: "money" },
  { band: "ads", key: "meta_roas", label: "Meta ROAS", w: 88, kind: "ratio" },
  { band: "ads", key: "shopify_roas", label: "Shopify ROAS", w: 92, kind: "ratio" },
  { band: "ads", key: "meta_impressions", label: "Impressions", w: 98, kind: "int" },
];

const inr = (n: number) =>
  `₹${Math.round(n).toLocaleString("en-IN")}`;

function cell(value: number | null | undefined, kind: Metric["kind"]): string {
  if (value === null || value === undefined) return "—";
  if (kind === "money") return inr(value);
  if (kind === "ratio") return value.toFixed(2);
  if (kind === "pct") return `${(value * 100).toFixed(1)}%`;
  return Math.round(value).toLocaleString("en-IN");
}

/** A UTC timestamp read as the IST clock the store trades on. */
function istStamp(v: string | null): string {
  if (!v) return "\u2014";
  const d = new Date(v);
  if (isNaN(d.getTime())) return v;
  return d.toLocaleString("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit",
    month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).replace(",", "");
}

/** A page path is long and the interesting part is the end of it -- the
 *  handle, not the "/collections" every row shares. Cut on a segment
 *  boundary so the result still reads as a path: "…tions/women-airy-linen"
 *  looks like a typo, "…/women-airy-linen" does not. The full path is on
 *  the cell's title attribute either way. */
function shortPath(path: string): string {
  if (path.length <= 46) return path;
  const tail = path.slice(-45);
  const cut = tail.indexOf("/");
  return `…${cut === -1 ? tail : tail.slice(cut)}`;
}

export function HourlyLanding() {
  const [range, setRange] = useState("1");
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"pages" | "hours">("pages");
  const [data, setData] = useState<LandingHourlyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const today = useMemo(istToday, []);
  const from = useMemo(() => daysAgo(today, Number(range)), [today, range]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchLandingHourly({ day: today, from_day: from, limit: 300 }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [today, from]);

  useEffect(() => {
    void load();
  }, [load]);

  const pages = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    return q
      ? data.pages.filter((p) => p.landing_page_path.toLowerCase().includes(q))
      : data.pages;
  }, [data, search]);

  const exportRows = useMemo(
    () =>
      pages.map((p) => {
        const row: Record<string, string | number> = { "Landing page": p.landing_page_path };
        for (const m of METRICS) row[m.label] = (p[m.key] as number | null) ?? "";
        return row;
      }),
    [pages],
  );

  const cov = data?.coverage;

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader title="Hourly Landing Page Tracker" helpId="hourly-landing">
        <Segmented
          value={view}
          onChange={(v) => setView(v as "pages" | "hours")}
          options={[
            { value: "pages", label: "By page" },
            { value: "hours", label: "By hour" },
          ]}
        />
        <ExportButton
          rows={exportRows}
          filename={`hourly-landing-${from}-to-${today}.csv`}
          disabled={!exportRows.length}
        />
      </SectionHeader>

      <div className="flex flex-wrap items-end gap-3">
        <FilterCell label="Window">
          <select
            className={filterControlClass}
            value={range}
            onChange={(e) => setRange(e.target.value)}
          >
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </FilterCell>
        <FilterCell label="Page contains">
          <input
            className={filterControlClass}
            placeholder="/collections/short-kurtas"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </FilterCell>
        <div className="text-[12px] text-text-tertiary">
          {from} to {today} (IST)
          {data?.refreshed_at && ` · refreshed ${data.refreshed_at.slice(0, 16).replace("T", " ")}`}
        </div>
      </div>

      {/* Coverage is stated before any number is read, not footnoted after.
          GA4 does not see every order, so these totals are a subset of the
          store's and a reader comparing them to the Hourly Tracker needs to
          know by how much. */}
      {/* The partial-day warning comes first: every figure under it is
          short by whatever the order ingest has not reached. */}
      {cov?.stale && (
        <div className="rounded-md border border-red-500/40 bg-red-500/[0.07] px-3 py-2 text-[12px] text-text-secondary">
          <span className="mr-2 rounded border border-red-500/40 px-1.5 py-px text-[10px] font-bold uppercase tracking-wide text-red-500">
            Stale
          </span>
          Orders and sessions were last pulled{" "}
          <b className="text-text-primary">{istStamp(cov.data_through)} IST</b>, which is
          over an hour ago — the hourly refresh is not running. Every hour since then
          reads zero because nothing fetched it, not because nothing sold. For
          comparison the hourly campaign tracker has{" "}
          <b className="text-text-primary">{inr(cov.all_revenue)}</b> across{" "}
          <b className="text-text-primary">{cov.all_orders.toLocaleString("en-IN")}</b>{" "}
          orders in this window.
        </div>
      )}

      {cov && (
        <div className="rounded-md border border-border-soft bg-bg-subtle px-3 py-2 text-[12px] text-text-secondary">
          <b className="text-text-primary">Sessions</b> are visits that landed on a page;{" "}
          <b className="text-text-primary">orders</b> are orders placed on it, keyed on
          the order&apos;s own URL. Those are different pages for 94% of ad-driven orders
          — people land on a collection and buy from a product — so the two bands are
          facts about the same page, not a funnel, and there is deliberately no
          conversion rate dividing one by the other. Bounce, ATC and Checkout % are all
          session-based and safe to read as rates.{" "}
          <b className="text-text-primary">Meta spend</b>:{" "}
          {Math.round((cov.spend_share ?? 0) * 100)}% of {inr(cov.all_spend)} reaches a
          page — the rest is ads whose creative has no readable landing URL, usually ones
          launched today. Read a page&apos;s ROAS as its own, not as the account&apos;s.
        </div>
      )}

      {error && (
        <div className="rounded-md border border-border-soft bg-bg-subtle px-3 py-2 text-[12.5px] text-text-primary">
          {error}
        </div>
      )}

      {loading && !data && (
        <div className="px-1 py-6 text-[13px] text-text-tertiary">Loading…</div>
      )}

      {data?.empty && !loading && (
        <div className="rounded-md border border-border-soft bg-bg-subtle px-3 py-6 text-center text-[13px] text-text-tertiary">
          Nothing collected for this window yet. Run
          <code className="mx-1">scripts/refresh_hourly_landing.py</code>
          to fill it.
        </div>
      )}

      {!!data && !data.empty && view === "pages" && (
        <TableFrame
          footer={
            <span className="text-[12px] text-text-tertiary">
              {pages.length.toLocaleString("en-IN")} page
              {pages.length === 1 ? "" : "s"}
            </span>
          }
        >
          <table className="border-collapse bg-bg-white text-[12.5px]">
            <thead>
              <tr className="bg-bg-white text-left text-[11px] uppercase tracking-wide text-text-tertiary">
                <th
                  style={{ minWidth: 260 }}
                  className="sticky left-0 z-10 whitespace-nowrap border-b border-r border-border-soft bg-bg-white px-3 py-2 font-medium"
                >
                  Landing page
                </th>
                {METRICS.map((m) => (
                  <th
                    key={m.key}
                    style={{ minWidth: m.w }}
                    className="whitespace-normal border-b border-r border-border-soft px-3 py-2 text-right align-bottom font-medium last:border-r-0"
                  >
                    {m.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.totals && !search && (
                <tr className="bg-bg-subtle font-semibold">
                  <td className="sticky left-0 z-10 whitespace-nowrap border-b border-r border-border-soft bg-bg-subtle px-3 py-2">
                    All pages
                  </td>
                  {METRICS.map((m) => (
                    <td
                      key={m.key}
                      className="border-b border-r border-border-soft px-3 py-2 text-right tabular-nums last:border-r-0"
                    >
                      {cell(data.totals![m.key] as number | null, m.kind)}
                    </td>
                  ))}
                </tr>
              )}
              {pages.map((p) => (
                <tr key={p.landing_page_path} className="hover:bg-bg-subtle">
                  <td
                    title={p.landing_page_path}
                    className="sticky left-0 z-10 whitespace-nowrap border-b border-r border-border-soft bg-bg-white px-3 py-2 hover:bg-bg-subtle"
                  >
                    {shortPath(p.landing_page_path)}
                  </td>
                  {METRICS.map((m) => (
                    <td
                      key={m.key}
                      className="border-b border-r border-border-soft px-3 py-2 text-right tabular-nums last:border-r-0"
                    >
                      {cell(p[m.key] as number | null, m.kind)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </TableFrame>
      )}

      {!!data && !data.empty && view === "hours" && (
        <TableFrame>
          <table className="border-collapse bg-bg-white text-[12.5px]">
            <thead>
              <tr className="bg-bg-white text-left text-[11px] uppercase tracking-wide text-text-tertiary">
                <th className="border-b border-r border-border-soft px-3 py-2 font-medium">
                  Hour (IST)
                </th>
                <th className="border-b border-r border-border-soft px-3 py-2 text-right font-medium">
                  Shopify sales
                </th>
                <th className="border-b border-r border-border-soft px-3 py-2 text-right font-medium">
                  Orders
                </th>
                <th className="border-b border-r border-border-soft px-3 py-2 text-right font-medium">
                  New customer sales
                </th>
                <th className="border-b border-r border-border-soft px-3 py-2 text-right font-medium">
                  Repeat customer sales
                </th>
                <th className="border-b border-r border-border-soft px-3 py-2 text-right font-medium">
                  Meta spend
                </th>
                <th className="border-b border-r border-border-soft px-3 py-2 text-right font-medium">
                  Meta sales
                </th>
                <th className="border-b border-border-soft px-3 py-2 text-right font-medium">
                  NCP
                </th>
              </tr>
            </thead>
            <tbody>
              {data.hours.map((h) => (
                <tr key={h.hour_of_day} className="hover:bg-bg-subtle">
                  <td className="border-b border-r border-border-soft px-3 py-2 tabular-nums">
                    {String(h.hour_of_day).padStart(2, "0")}:00
                  </td>
                  <td className="border-b border-r border-border-soft px-3 py-2 text-right tabular-nums">
                    {inr(h.revenue)}
                  </td>
                  <td className="border-b border-r border-border-soft px-3 py-2 text-right tabular-nums">
                    {h.orders.toLocaleString("en-IN")}
                  </td>
                  <td className="border-b border-r border-border-soft px-3 py-2 text-right tabular-nums">
                    {inr(h.new_customer_sales)}
                  </td>
                  <td className="border-b border-r border-border-soft px-3 py-2 text-right tabular-nums">
                    {inr(h.repeat_customer_sales)}
                  </td>
                  <td className="border-b border-r border-border-soft px-3 py-2 text-right tabular-nums">
                    {inr(h.meta_spend)}
                  </td>
                  <td className="border-b border-r border-border-soft px-3 py-2 text-right tabular-nums">
                    {inr(h.meta_conv_value)}
                  </td>
                  <td className="border-b border-border-soft px-3 py-2 text-right tabular-nums">
                    {Math.round(h.ncp).toLocaleString("en-IN")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableFrame>
      )}
    </section>
  );
}
