"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import {
  BreakdownItem,
  DashboardKpis,
  DashboardSessions,
  DashboardSessionTrend,
  TopCpisSku,
  TopLandingPage,
  fetchDashboardCategoryBreakdown,
  fetchDashboardChannelBreakdown,
  fetchDashboardKpis,
  fetchDashboardSessions,
  fetchDashboardSessionTrend,
  fetchDashboardTopCpisSkus,
  fetchDashboardTopLandingPages,
} from "@/lib/api";
import { useCachedFetch } from "@/lib/useCachedFetch";
import { fromKpis as acquisitionFromKpis } from "./acquisitionMer";
import { DraggableGrid, GridItem } from "./DraggableGrid";
import { BarChart } from "./charts/BarChart";
import { SessionTrendChart } from "./charts/SessionTrendChart";
import { DateRangePicker, resolvePreset, type DateRange, type PresetKey } from "@/components/DateRangePicker";
import { SectionHeader, Segmented } from "./SectionChrome";

const SOURCE_KEY = "analytics-dashboard-session-source";

/** Which measurement system the session band divides by.
 *
 *  Shopify and GA4 both watch the same traffic, so they are two
 *  readings of one thing, not two things to add together: summing their
 *  session counts would count a visitor twice and halve cost per
 *  session. "Both" therefore compares them rather than combining them,
 *  and the gap between them is the useful part. */
type SessionSource = "shopify" | "google" | "both";

const SOURCE_OPTIONS: { value: string; label: string; title: string }[] = [
  { value: "shopify", label: "Shopify",
    title: "Shopify's own sessions, narrowed to Meta-driven traffic by utm_source." },
  { value: "google", label: "Google",
    title: "GA4's sessions, revenue and purchases. All traffic -- GA4 cannot be narrowed to Meta." },
  { value: "both", label: "Both",
    title: "The two side by side, with the gap between them." },
];

function loadSource(): SessionSource {
  if (typeof window === "undefined") return "shopify";
  try {
    const v = window.localStorage.getItem(SOURCE_KEY);
    if (v === "shopify" || v === "google" || v === "both") return v;
  } catch {
    // Private windows and blocked site data throw on read. The default
    // is correct, so there is nothing to recover.
  }
  return "shopify";
}

/** One source's four figures, for the comparison table. */
interface SourceMetrics {
  costPerSession: number | null;
  revenuePerSession: number | null;
  conversionRate: number | null;
  arpu: number | null;
  sessions: number | null;
}

/** Shopify against GA4, with the gap between them.
 *
 *  The gap is the reason this view exists: two systems watching the
 *  same shop disagree, and how much they disagree is worth knowing. It
 *  is NOT a pure measurement difference though -- the denominators
 *  differ in scope, because Shopify can see which sessions Meta sent
 *  and GA4 cannot. The footnote says so rather than letting the number
 *  be read as if the two counted the same population.
 */
function SourceComparison({ shopify, google }: { shopify: SourceMetrics; google: SourceMetrics }) {
  const rows: {
    label: string;
    a: number | null;
    b: number | null;
    fmt: (n: number | null) => string;
    /** Percentage points, not per cent: a rate's gap is a subtraction. */
    points?: boolean;
  }[] = [
    { label: "Cost / session", a: shopify.costPerSession, b: google.costPerSession, fmt: formatPerSession },
    { label: "Revenue / session", a: shopify.revenuePerSession, b: google.revenuePerSession, fmt: formatPerSession },
    { label: "Conversion rate", a: shopify.conversionRate, b: google.conversionRate, fmt: formatConversionRate, points: true },
    { label: "ARPU", a: shopify.arpu, b: google.arpu, fmt: formatPerSession },
  ];

  function gap(a: number | null, b: number | null, points: boolean): string {
    if (a === null || b === null) return "\u2014";
    if (points) return `${((b - a) * 100).toFixed(2)} pt`;
    if (a === 0) return "\u2014";
    const pct = ((b - a) / Math.abs(a)) * 100;
    return `${pct > 0 ? "+" : ""}${pct.toFixed(0)}%`;
  }

  return (
    <div className="mt-3">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-xs text-text-secondary">
            <th className="border-b border-border-primary pb-2 font-normal">Metric</th>
            <th className="border-b border-border-primary pb-2 text-right font-normal">Shopify</th>
            <th className="border-b border-border-primary pb-2 text-right font-normal">Google (GA4)</th>
            <th className="border-b border-border-primary pb-2 text-right font-normal"
                title="How far GA4 sits from Shopify. Partly a measurement difference and partly a scope one -- see the note below.">
              Gap
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td className="border-b border-border-soft py-2 text-text-secondary">{r.label}</td>
              <td className="border-b border-border-soft py-2 text-right tabular-nums font-medium text-text-primary">
                {r.fmt(r.a)}
              </td>
              <td className="border-b border-border-soft py-2 text-right tabular-nums font-medium text-text-primary">
                {r.fmt(r.b)}
              </td>
              <td className="border-b border-border-soft py-2 text-right tabular-nums text-text-secondary">
                {gap(r.a, r.b, !!r.points)}
              </td>
            </tr>
          ))}
          <tr>
            <td className="py-2 text-text-secondary">Sessions</td>
            <td className="py-2 text-right tabular-nums text-text-secondary">
              {shopify.sessions?.toLocaleString("en-IN") ?? "\u2014"}
            </td>
            <td className="py-2 text-right tabular-nums text-text-secondary">
              {google.sessions?.toLocaleString("en-IN") ?? "\u2014"}
            </td>
            <td className="py-2 text-right tabular-nums text-text-secondary">
              {gap(shopify.sessions, google.sessions, false)}
            </td>
          </tr>
        </tbody>
      </table>
      <p className="mt-3 text-xs text-text-secondary">
        The two columns do not cover the same population, so part of every gap is scope rather
        than disagreement. Shopify is narrowed to Meta-driven sessions by <code>utm_source</code>;
        GA4 is all traffic, because it cannot be narrowed — its landing pages carry no query
        string and it files most Meta traffic under Organic Social. ARPU is blank for Shopify:
        it counts sessions and customers, never users.
      </p>
    </div>
  );
}

const STORAGE_KEY = "analytics-dashboard-widget-order";
const RANGE_KEY = "analytics-dashboard-date-range";
const DEFAULT_ORDER = ["kpis", "session-performance", "category", "channel", "landing-pages", "cpis-skus"];

function formatCurrency(n: number): string {
  return `₹${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatPerSession(n: number | null): string {
  return n === null || !Number.isFinite(n)
    ? "—"
    : `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatConversionRate(n: number | null): string {
  return n === null || !Number.isFinite(n)
    ? "—"
    : n.toLocaleString("en-IN", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

type DateSelection = { preset: PresetKey; range: DateRange | null };
const ROLLING_PRESETS = new Set<PresetKey>([
  "today", "yesterday", "last7", "last30", "last90", "thisMonth", "lastMonth",
]);

function validDay(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value))
    && new Date(value).toISOString().slice(0, 10) === value;
}

function loadDateSelection(): DateSelection {
  try {
    const saved = JSON.parse(window.localStorage.getItem(RANGE_KEY) ?? "null");
    if (saved?.preset === "lifetime") return { preset: "lifetime", range: null };
    if (ROLLING_PRESETS.has(saved?.preset)) {
      // Persist the intent, not the absolute dates from a previous visit.
      return { preset: saved.preset, range: resolvePreset(saved.preset) };
    }
    if (saved?.preset === "custom" && validDay(saved.from) && validDay(saved.to)
      && saved.from <= saved.to) {
      return { preset: "custom", range: { from: saved.from, to: saved.to } };
    }
  } catch {
    // Invalid or unavailable storage must not block current data.
  }
  return { preset: "last30", range: resolvePreset("last30") };
}

function fmtDay(d: string): string {
  const t = Date.parse(d);
  return Number.isNaN(t)
    ? d
    : new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Small caption under a widget title naming the window it really covers. */
function WindowBadge({ text, muted = false }: { text: string; muted?: boolean }) {
  return (
    <span
      className={`ml-2 rounded px-1.5 py-0.5 align-middle text-[10px] font-normal ${
        muted
          ? "bg-bg-surface text-text-secondary"
          : "bg-accent-bg text-accent-text"
      }`}
    >
      {text}
    </span>
  );
}

function loadOrder(): string[] {
  if (typeof window === "undefined") return DEFAULT_ORDER;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_ORDER;
    const parsed = JSON.parse(raw) as string[];
    if (Array.isArray(parsed)) {
      const saved = [...new Set(parsed.filter((id) => DEFAULT_ORDER.includes(id)))];
      // Preserve existing widget arrangements when this section is added.
      if (!saved.includes("session-performance") && saved.includes("kpis")) {
        saved.splice(saved.indexOf("kpis") + 1, 0, "session-performance");
      }
      return [...saved, ...DEFAULT_ORDER.filter((id) => !saved.includes(id))];
    }
    return DEFAULT_ORDER;
  } catch {
    return DEFAULT_ORDER;
  }
}

// Small placeholder shown inside a widget while it's fetching. Keeps
// the widget's height stable so the grid doesn't reflow when data
// lands. Sized to roughly the widget's final height.
function WidgetSkeleton({ heightPx = 96 }: { heightPx?: number }) {
  return (
    <div
      className="animate-pulse rounded bg-bg-surface"
      style={{ minHeight: heightPx }}
    />
  );
}

const subscribeToHydration = () => () => {};
const clientSnapshot = () => true;
const serverSnapshot = () => false;

export function Dashboard() {
  // Read saved filters before mounting fetch hooks, avoiding an unwanted
  // lifetime request followed immediately by the selected range.
  const hydrated = useSyncExternalStore(subscribeToHydration, clientSnapshot, serverSnapshot);
  return hydrated ? <DashboardContent /> : <WidgetSkeleton heightPx={240} />;
}

function DashboardContent() {
  const [order, setOrder] = useState<string[]>(loadOrder);
  const [{ preset, range }, setDateSelection] = useState<DateSelection>(loadDateSelection);
  // Lazy initializer, like `order` and the date selection above:
  // DashboardContent renders only after the hydration gate, so reading
  // localStorage here cannot disagree with the server's HTML.
  const [source, setSource] = useState<SessionSource>(loadSource);
  useEffect(() => {
    const updateRollingDates = () => setDateSelection((current) => {
      if (!ROLLING_PRESETS.has(current.preset)) return current;
      const next = resolvePreset(current.preset);
      return next.from === current.range?.from && next.to === current.range?.to
        ? current : { preset: current.preset, range: next };
    });
    const timer = window.setInterval(updateRollingDates, 60_000);
    window.addEventListener("focus", updateRollingDates);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", updateRollingDates);
    };
  }, []);

  const from = range?.from ?? null;
  const to = range?.to ?? null;

  // Each widget owns its own cached fetch, so switching tabs and coming
  // back is an instant cache-hit render (sessionStorage, 5min TTL) and
  // no widget blocks another. If any one fails, only that tile goes
  // dark -- the rest still render.
  //
  // Every tile shares the exact range. Version the cache to discard the
  // previous fixed-window SKU and landing-page payloads.
  const rangeKey = `v2|${from && to ? `${from}|${to}` : "lifetime"}`;
  const kpis     = useCachedFetch<DashboardKpis>(`dashboard/kpis|${rangeKey}`,
                                                   () => fetchDashboardKpis(from, to));
  const sessions = useCachedFetch<DashboardSessions>(`dashboard/sessions|${rangeKey}`,
                                                   () => fetchDashboardSessions(from, to));
  const sessionTrend = useCachedFetch<DashboardSessionTrend>(`dashboard/session-trend|${rangeKey}`,
                                                   () => fetchDashboardSessionTrend(from, to));
  const category = useCachedFetch<BreakdownItem[]>(`dashboard/category-breakdown|${rangeKey}`,
                                                   () => fetchDashboardCategoryBreakdown(from, to));
  const channel  = useCachedFetch<BreakdownItem[]>(`dashboard/channel-breakdown|${rangeKey}`,
                                                   () => fetchDashboardChannelBreakdown(from, to));
  const landing  = useCachedFetch<TopLandingPage[]>(`dashboard/top-landing-pages|${rangeKey}`,
                                                   () => fetchDashboardTopLandingPages(from, to));
  const cpisSkus = useCachedFetch<TopCpisSku[]>(`dashboard/top-cpis-skus|${rangeKey}`,
                                                   () => fetchDashboardTopCpisSkus(from, to));

  const rangeLabel = from && to ? `${fmtDay(from)} – ${fmtDay(to)}` : "Lifetime";
  // Set by the backend only when the chosen window starts before the daily
  // spend table begins, i.e. spend/impressions are genuinely partial. Without
  // saying so, a range reaching into 2025 shows a far smaller spend and reads
  // as a collapse rather than as missing history.
  // Acquisition MER = new-customer sales over the window / ad spend
  // over the same window. Derived in acquisitionMer.ts rather than
  // here because its awkward cases -- a cached payload carrying no
  // acquisition figure, a window with spend but no acquisitions, a
  // window with acquisitions but no spend -- each need a test, and
  // inline in JSX none of them had one.
  const { newCustomers, acquisitionMer, costPerNewCustomer } = acquisitionFromKpis(kpis.data);

  // Acquisition MER divides BY spend, so a window reaching past the
  // daily table's floor does not merely understate spend -- it
  // overstates the ratio, and in the flattering direction. The note has
  // to say so, or a range starting before 2025-12-29 silently reads as
  // the best acquisition the account has ever had.
  const spendFloorNote = kpis.data?.spend_data_from
    ? `Spend and impressions only exist from ${fmtDay(kpis.data.spend_data_from)} onwards — earlier days in this range are not included, so Acquisition MER reads high and cost per new customer reads low.`
    : null;
  // Meta-driven sessions. Every numerator below is Meta's, so the
  // denominator has to be too -- against all traffic, cost per session
  // read 27.6% low (14,519,759 Meta sessions of 20,045,933 lifetime).
  const sessionCount = sessions.data?.total_sessions ?? null;
  const allSessionCount = sessions.data?.all_sessions ?? null;
  const metaShare = allSessionCount && allSessionCount > 0 && sessionCount !== null
    ? (sessionCount / allSessionCount) * 100 : null;
  const costPerSession = kpis.data && sessionCount !== null && sessionCount > 0
    ? kpis.data.total_spend / sessionCount : null;
  // The Meta slice of Shopify, not all of it. The denominator is
  // Meta-driven sessions, so the numerator has to be the orders those
  // sessions could have produced -- dividing ALL Shopify revenue by
  // Meta-only sessions read 97% high (Rs 4.65cr over 29 Sep - 28 Oct
  // where Meta drove Rs 2.36cr, against 14,57,313 of 19,56,848
  // sessions). Both halves are now selected by one utm_source rule.
  const metaRevenue = kpis.data?.meta_shopify_revenue ?? null;
  const metaOrders = kpis.data?.meta_shopify_orders ?? null;
  const revenuePerSession = metaRevenue !== null && sessionCount !== null && sessionCount > 0
    ? metaRevenue / sessionCount : null;
  const conversionRate = metaOrders !== null && sessionCount !== null && sessionCount > 0
    ? metaOrders / sessionCount : null;

  // GA4 divided by GA4. Its revenue and purchases are its own, so the
  // denominator is its own session count rather than Shopify's -- the
  // point of a second source is that it counted both halves itself.
  //
  // All traffic, unavoidably. GA4 cannot be narrowed to Meta from what
  // we hold: its landing_page column carries no query string (0 of
  // 68,241 rows over 30 days have a utm_source) and its channel_group
  // files the bulk of Meta under Organic Social -- 1,194,834 sessions
  // there against 20,242 in Paid Social, while Shopify's utm_source
  // rule finds 1,504,827. Only cost per session mixes sources, and
  // only that tile is caveated.
  const ga4Sessions = sessions.data?.ga4_sessions ?? null;
  const ga4Revenue = sessions.data?.ga4_revenue ?? null;
  const ga4Purchases = sessions.data?.ga4_purchases ?? null;
  const ga4CostPerSession = kpis.data && ga4Sessions !== null && ga4Sessions > 0
    ? kpis.data.total_spend / ga4Sessions : null;
  const ga4RevenuePerSession = ga4Revenue !== null && ga4Sessions !== null && ga4Sessions > 0
    ? ga4Revenue / ga4Sessions : null;
  const ga4ConversionRate = ga4Purchases !== null && ga4Sessions !== null && ga4Sessions > 0
    ? ga4Purchases / ga4Sessions : null;

  const requestedDays = from && to
    ? Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1 : null;
  const partialSessions = sessions.data && requestedDays !== null
    && sessions.data.available_days < requestedDays;

  const error =
    kpis.error?.message ||
    category.error?.message ||
    channel.error?.message ||
    landing.error?.message ||
    cpisSkus.error?.message ||
    null;

  function handleApplyRange(r: { from: string; to: string }, pk: string) {
    setDateSelection({ preset: pk as PresetKey, range: pk === "lifetime" ? null : r });
    try {
      window.localStorage.setItem(RANGE_KEY, JSON.stringify({ preset: pk, from: r.from, to: r.to }));
    } catch {
      // non-fatal: the range still applies, it just won't persist.
    }
  }

  function handleReorder(next: string[]) {
    setOrder(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // localStorage unavailable — reordering still works for this session, just doesn't persist.
    }
  }

  const items: GridItem[] = [
    {
      id: "kpis",
      span: 3,
      content: kpis.data ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{formatCurrency(kpis.data.total_spend)}</p>
            <p className="mt-0.5 text-xs text-text-secondary">
              Total ad spend<WindowBadge text={rangeLabel} />
            </p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{formatCurrency(kpis.data.total_shopify_revenue)}</p>
            <p className="mt-0.5 text-xs text-text-secondary">Shopify revenue (attributed)</p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">{kpis.data.total_shopify_orders.toLocaleString()}</p>
            <p className="mt-0.5 text-xs text-text-secondary">Attributed orders</p>
          </div>
          <div>
            <p className="tabular-nums text-2xl font-semibold text-text-primary">
              {(kpis.data.total_impressions / 1_000_000).toFixed(1)}M
            </p>
            <p className="mt-0.5 text-xs text-text-secondary">Impressions</p>
          </div>
          {/* Acquisition MER: new-customer SALES ÷ spend, both over the
              selected window. A customer counts here only if their
              FIRST EVER Shopify order falls inside it, so this is
              revenue from customers acquired, not from customers
              active.

              Money over money, so it reads like a ROAS -- which is the
              point, because it is directly comparable with the account
              MER. The head count and the per-customer cost sit under
              it: 2.85x says how efficiently spend converts, ₹464 says
              what each acquisition cost. */}
          <div>
            <p
              className="tabular-nums text-2xl font-semibold text-text-primary"
              title="Acquisition MER — revenue from customers acquired in this window ÷ ad spend over the same window."
            >
              {acquisitionMer === null ? "—" : `${acquisitionMer.toFixed(2)}x`}
            </p>
            <p className="mt-0.5 text-xs text-text-secondary">
              Acquisition MER<WindowBadge text={rangeLabel} />
            </p>
            {newCustomers !== null && (
              <p className="mt-1 text-[11px] text-text-tertiary tabular-nums">
                {newCustomers.toLocaleString("en-IN")} new customers
                {costPerNewCustomer !== null && <> · {formatCurrency(costPerNewCustomer)} each</>}
              </p>
            )}
          </div>
        </div>
      ) : (
        <WidgetSkeleton heightPx={80} />
      ),
    },
    {
      id: "session-performance",
      span: 3,
      content: (
        <section aria-labelledby="dashboard-session-performance">
          <h3 id="dashboard-session-performance" className="text-sm font-medium text-text-primary">
            Session performance<WindowBadge text={rangeLabel} />
          </h3>
          {sessions.error || kpis.error ? (
            <div role="alert" className="mt-3 flex flex-wrap items-center gap-3 text-sm text-error-text">
              <span>Could not load session performance.</span>
              <button type="button" className="underline underline-offset-2" onClick={() => {
                if (sessions.error) sessions.refetch();
                if (kpis.error) kpis.refetch();
              }}>Retry session metrics</button>
            </div>
          ) : !sessions.data || !kpis.data ? (
            <div className="mt-3" role="status" aria-label="Loading session performance">
              <WidgetSkeleton heightPx={100} />
            </div>
          ) : (
            <>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                <Segmented
                  options={SOURCE_OPTIONS}
                  value={source}
                  onChange={(v) => {
                    const next = v as SessionSource;
                    setSource(next);
                    try { window.localStorage.setItem(SOURCE_KEY, next); } catch {
                      // A remembered tab is a convenience, not state the
                      // figures depend on. Losing it costs one click.
                    }
                  }}
                />
                <span className="text-[11px] text-text-tertiary">
                  {source === "shopify"
                    ? "Shopify sessions, Meta-driven only"
                    : source === "google"
                      ? "GA4 sessions, all traffic"
                      : "Two readings of the same traffic, not two traffic sources"}
                </span>
              </div>

              {source === "both" ? (
                <SourceComparison
                  shopify={{
                    costPerSession, revenuePerSession, conversionRate,
                    arpu: null, sessions: sessionCount,
                  }}
                  google={{
                    costPerSession: ga4CostPerSession,
                    revenuePerSession: ga4RevenuePerSession,
                    conversionRate: ga4ConversionRate,
                    arpu: sessions.data.ga4_arpu ?? null,
                    sessions: ga4Sessions,
                  }}
                />
              ) : (
              <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <dt className="text-xs text-text-secondary">Cost / session</dt>
                  <dd className="mt-1 tabular-nums text-2xl font-semibold text-text-primary">
                    {formatPerSession(source === "google" ? ga4CostPerSession : costPerSession)}
                  </dd>
                  <dd className="mt-1 text-xs text-text-secondary">
                    {source === "google"
                      ? "Meta ad spend \u00f7 all GA4 sessions \u2014 GA4 cannot isolate Meta traffic"
                      : "Ad spend \u00f7 Meta-driven Shopify sessions"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-text-secondary">Revenue / session</dt>
                  <dd className="mt-1 tabular-nums text-2xl font-semibold text-text-primary">
                    {formatPerSession(source === "google" ? ga4RevenuePerSession : revenuePerSession)}
                  </dd>
                  <dd className="mt-1 text-xs text-text-secondary">
                    {source === "google"
                      ? "GA4 revenue \u00f7 GA4 sessions"
                      : "Meta-driven Shopify revenue \u00f7 Meta-driven Shopify sessions"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-text-secondary">
                    Conversion rate{source === "google" ? " (GA4)" : " (attributed)"}
                  </dt>
                  <dd className="mt-1 tabular-nums text-2xl font-semibold text-text-primary">
                    {formatConversionRate(source === "google" ? ga4ConversionRate : conversionRate)}
                  </dd>
                  <dd className="mt-1 text-xs text-text-secondary">
                    {source === "google"
                      ? "GA4 purchases \u00f7 GA4 sessions \u00d7 100"
                      : "Meta-driven Shopify orders \u00f7 Meta-driven Shopify sessions \u00d7 100"}
                  </dd>
                </div>
                {/* ARPU is GA4's end to end -- its revenue over its own
                    user count. Deliberately NOT Shopify revenue over
                    GA4 users: the value of this figure is that one
                    source counted both halves, and mixing them would
                    describe neither. It therefore disagrees with the
                    Shopify revenue on the cards above, and should.

                    The denominator is active user-DAYS, summed from a
                    daily table. GA4's own window ARPU deduplicates
                    users across the period and so reads higher (37.52
                    against 31.42 over 30 days). Daily was chosen so
                    every date range gets an answer instead of only the
                    windows a lookup table happened to store -- the
                    label says user-days precisely so the two are not
                    confused.

                    Blank on the Shopify tab, and blank on purpose:
                    Shopify counts sessions and customers, never users,
                    so it has no denominator for this. Revenue per
                    purchasing customer would fill the tile with a
                    number ~48x larger that answers a different
                    question, so the tile says what is missing instead. */}
                <div>
                  <dt className="text-xs text-text-secondary">ARPU{source === "google" ? " (GA4)" : ""}</dt>
                  <dd className="mt-1 tabular-nums text-2xl font-semibold text-text-primary">
                    {source !== "google" || sessions.data.ga4_arpu == null
                      ? "\u2014"
                      : formatPerSession(sessions.data.ga4_arpu)}
                  </dd>
                  <dd className="mt-1 text-xs text-text-secondary">
                    {source !== "google"
                      ? "Shopify counts sessions and customers, not users \u2014 see the Google tab"
                      : sessions.data.ga4_arpu == null
                        ? "No GA4 user data for this range"
                        : <>GA4 revenue ÷ GA4 active user-days{sessions.data.ga4_active_users != null
                            && <> · {sessions.data.ga4_active_users.toLocaleString("en-IN")} user-days</>}</>}
                  </dd>
                </div>
              </dl>
              )}

              {/* Shopify's own totals, every traffic source.

                  Totals, NOT a second set of ratios. The tiles above
                  are Meta-driven on both halves and that is what makes
                  them correct; printing an all-traffic revenue per
                  session beside them would put two different numbers
                  for one metric on one tab, and the reader has no way
                  to tell which is meant. These are the raw figures the
                  Meta slice is a part of, with that part named. */}
              {source === "shopify" && (
                <div className="mt-4 border-t border-border-primary pt-3">
                  <p className="text-xs font-medium text-text-secondary">
                    Shopify totals &middot; every traffic source
                  </p>
                  <dl className="mt-2 grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div>
                      <dt className="text-xs text-text-secondary">Total revenue</dt>
                      <dd className="mt-1 tabular-nums text-xl font-semibold text-text-primary">
                        {formatCurrency(kpis.data.total_shopify_revenue)}
                      </dd>
                      <dd className="mt-1 text-xs text-text-secondary">
                        {kpis.data.total_shopify_orders.toLocaleString("en-IN")} orders
                        {metaRevenue !== null && kpis.data.total_shopify_revenue > 0 && (
                          <> &middot; {formatCurrency(metaRevenue)} of it Meta-driven
                            {" "}({(100 * metaRevenue / kpis.data.total_shopify_revenue).toFixed(1)}%)</>
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-text-secondary">Total sessions</dt>
                      <dd className="mt-1 tabular-nums text-xl font-semibold text-text-primary">
                        {allSessionCount === null ? "\u2014" : allSessionCount.toLocaleString("en-IN")}
                      </dd>
                      <dd className="mt-1 text-xs text-text-secondary">
                        {sessionCount === null || metaShare === null
                          ? "Across all traffic sources"
                          : `${sessionCount.toLocaleString("en-IN")} of them Meta-driven (${metaShare.toFixed(1)}%)`}
                      </dd>
                    </div>
                  </dl>
                </div>
              )}
              <p className="mt-3 border-t border-border-primary pt-3 text-xs text-text-secondary">
                {/* The denominator the tiles above actually used, named
                    per tab -- on the Google tab the Shopify figure would
                    describe a number that is not on screen. */}
                {source === "google"
                  ? (ga4Sessions === null
                      ? "No GA4 session data is available for this period."
                      : `${ga4Sessions.toLocaleString("en-IN")} GA4 sessions across all traffic sources.`
                        + (sessionCount !== null
                            ? ` Shopify counted ${sessionCount.toLocaleString("en-IN")} Meta-driven sessions over the same days.`
                            : ""))
                  : sessionCount === null
                    ? "No Shopify session data is available for this period."
                    : sessionCount === 0
                      ? "No Meta-driven Shopify sessions were recorded for this period. Session metrics are unavailable."
                      : `${sessionCount.toLocaleString("en-IN")} Meta-driven Shopify sessions`
                        + (allSessionCount !== null && metaShare !== null
                          ? ` — ${metaShare.toFixed(1)}% of ${allSessionCount.toLocaleString("en-IN")} across all traffic sources.`
                          : ".")}
                {sessions.data.session_data_from && sessions.data.session_data_to && (
                  <> Recorded {fmtDay(sessions.data.session_data_from)} – {fmtDay(sessions.data.session_data_to)}.</>
                )}
              </p>
              {sessionCount !== null && sessionCount > 0 && (partialSessions || !range) && (
                <p className="mt-1 text-xs text-text-secondary">
                  {partialSessions
                    ? "Session coverage is incomplete for this range. These ratios use the available session count."
                    : "Lifetime ratios use all available data; spend, revenue, orders and session history may cover different periods."}
                </p>
              )}
            </>
          )}
          <div className="mt-4 border-t border-border-primary pt-4">
            {sessionTrend.error ? (
              <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-error-text">
                <span>Could not load daily session trends.</span>
                <button type="button" className="underline underline-offset-2" onClick={sessionTrend.refetch}>Retry chart</button>
              </div>
            ) : sessionTrend.data ? (
              <SessionTrendChart key={rangeKey} points={sessionTrend.data.points} source={source} />
            ) : (
              <div role="status" aria-label="Loading daily session trends"><WidgetSkeleton heightPx={340} /></div>
            )}
          </div>
        </section>
      ),
    },
    {
      id: "category",
      span: 2,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">
            Spend by category<WindowBadge text={rangeLabel} />
          </h3>
          <div className="mt-3">
            {category.data ? (
              <BarChart
                categories={category.data.map((c) => c.label)}
                series={[{ name: "Spend", values: category.data.map((c) => c.value) }]}
                height={220}
                valueFormat={(n) => `₹${(n / 100000).toFixed(1)}L`}
              />
            ) : (
              <WidgetSkeleton heightPx={220} />
            )}
          </div>
        </div>
      ),
    },
    {
      id: "channel",
      span: 1,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">
            Shopify revenue by channel<WindowBadge text={rangeLabel} />
          </h3>
          <div className="mt-3 flex flex-col gap-2">
            {channel.data ? (
              channel.data
                .slice()
                .sort((a, b) => b.value - a.value)
                .map((c) => (
                  <div key={c.label} className="flex items-center justify-between text-xs">
                    <span className="text-text-secondary">{c.label}</span>
                    <span className="tabular-nums font-medium text-text-primary">{formatCurrency(c.value)}</span>
                  </div>
                ))
            ) : (
              <WidgetSkeleton heightPx={200} />
            )}
          </div>
        </div>
      ),
    },
    {
      id: "landing-pages",
      span: 1,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">
            Top landing pages<WindowBadge text={rangeLabel} />
          </h3>
          <div className="mt-3 flex flex-col gap-2">
            {landing.data ? (
              landing.data.map((p) => (
                <div key={p.landing_page_path} className="flex items-center justify-between text-xs">
                  <span className="truncate text-text-secondary" title={p.landing_page_path}>
                    {p.landing_page_path}
                  </span>
                  <span className="tabular-nums font-medium text-text-primary">{p.sessions.toLocaleString()}</span>
                </div>
              ))
            ) : (
              <WidgetSkeleton heightPx={140} />
            )}
          </div>
        </div>
      ),
    },
    {
      id: "cpis-skus",
      span: 2,
      content: (
        <div>
          <h3 className="text-sm font-medium text-text-primary">
            Top SKUs by ad spend (cost / NCP)<WindowBadge text={rangeLabel} />
          </h3>
          <div className="mt-3 flex flex-col gap-2">
            {cpisSkus.data ? (
              cpisSkus.data.map((s) => (
                <div key={s.master_sku} className="flex items-center justify-between text-xs">
                  <span className="font-mono text-text-secondary">{s.master_sku}</span>
                  <span className="tabular-nums text-text-secondary">
                    {formatCurrency(s.ad_spend)} · ₹{s.cost_per_ncp?.toFixed(0) ?? "—"}/NCP
                  </span>
                </div>
              ))
            ) : (
              <WidgetSkeleton heightPx={140} />
            )}
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div className="rounded-md border border-error-mid bg-error-bg p-3 text-sm text-error-text">{error}</div>
      )}
      {/* Two standing paragraphs stood here: "drag any tile to
          rearrange" and "each tile shows the period it actually
          covers". The first describes an affordance you find by
          dragging; the second is answered by the badge each tile already
          carries. Both moved to Help.

          The spend data-floor note is NOT one of them -- it changes what
          a number means, and only appears when it applies, so it stays. */}
      <SectionHeader title="Dashboard" helpId="data-floor">
        <DateRangePicker
          value={{ from: from ?? "", to: to ?? "" }}
          preset={preset}
          align="right"
          onApply={handleApplyRange}
        />
      </SectionHeader>
      {spendFloorNote && (
        <p className="text-xs text-text-tertiary">{spendFloorNote}</p>
      )}
      <DraggableGrid items={items} order={order} onReorder={handleReorder} />
    </div>
  );
}
