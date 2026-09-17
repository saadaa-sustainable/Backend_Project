"use client";

/**
 * "Adset matched, ad name did not" -- the naming-drift worklist.
 *
 * Replaces the STEP 6 / campaign-only tile, which was showing 0 in every
 * recent window: utm_campaign fallbacks essentially stopped happening
 * once tracking templates moved to numeric ad ids, so a whole tile was
 * being spent on a permanently-empty branch while the one bucket that
 * needs human action had nowhere to be read.
 *
 * Grain is one row per distinct (utm_content, adset), NOT one per order.
 * A count of orders tells you the size of the problem; it does not tell
 * you what to fix. What you need side by side is the name the order
 * carried and the names that actually exist in that adset -- which is
 * the whole panel:
 *
 *     utm_content said   SDCP_whisper-Hook_FLVO_Jan2025
 *     adset contains     CLP-SDCP+FBP+OFF-RS+IHP+SDCP_whisper-Hook_..._W
 *                        CLP-SDCP+FBP+OFF-RS+IHP+SDCP_price_FLVO_Jan2025
 *
 * Read that way a row is either a rename to make, or a tracking template
 * to correct. `ads_in_adset = 0` is a different failure and is called out
 * as such -- the adset is in the roster but we hold no ads for it, so no
 * name could have matched and nobody should go hunting for one.
 */

import { useEffect, useState } from "react";
import { ApiError, NameMissResponse, NameMissRow, fetchNameMisses } from "@/lib/api";
import { theme } from "@/lib/theme";
import { StatTile } from "./StatTile";

const fmtRs = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

export function NameMissPanel({
  fromDate,
  toDate,
  reloadKey,
}: {
  fromDate: string;
  toDate: string;
  reloadKey?: number;
}) {
  const [open, setOpen] = useState(false);
  // Each result is stored WITH the request it answers, and `loading` is
  // derived from "what is stored does not answer the current request".
  // The obvious shape -- setLoading(true) at the top of the effect --
  // sets state synchronously during render-commit and cascades an extra
  // render on every dependency change; deriving it costs nothing and
  // also makes a stale response impossible to show, because a response
  // keyed to an old request simply never matches.
  const [loaded, setLoaded] = useState<{ key: string; res: NameMissResponse } | null>(null);
  const [failed, setFailed] = useState<{ key: string; msg: string } | null>(null);

  const key = `${fromDate}|${toDate}|${reloadKey ?? 0}`;
  const loading = loaded?.key !== key && failed?.key !== key;
  const rows: NameMissRow[] = loaded?.key === key ? loaded.res.rows : [];
  const error = failed?.key === key ? failed.msg : null;
  const totals =
    loaded?.key === key
      ? {
          orders: loaded.res.total_orders,
          sales: loaded.res.total_sales,
          rows: loaded.res.total_rows,
          adsets: loaded.res.adsets_affected,
          noAds: loaded.res.rows_without_ads,
        }
      : { orders: 0, sales: 0, rows: 0, adsets: 0, noAds: 0 };

  useEffect(() => {
    let cancelled = false;
    fetchNameMisses({ from_date: fromDate, to_date: toDate, limit: 200 })
      .then((res) => !cancelled && setLoaded({ key, res }))
      .catch(
        (e) =>
          !cancelled &&
          setFailed({
            key,
            msg: e instanceof ApiError ? e.message : "Could not load the name-miss worklist.",
          }),
      );
    return () => {
      cancelled = true;
    };
  }, [key, fromDate, toDate]);

  return (
    <div className="rounded-lg border border-border-primary bg-white shadow-sm">
      <div className="px-3 pt-2.5">
        <div className="flex flex-wrap items-baseline gap-2">
          <span
            className="inline-block h-2.5 w-2.5 shrink-0 self-center rounded-full"
            style={{ backgroundColor: theme.warningMid }}
          />
          <h3 className="text-sm font-semibold">Adset matched · ad name failed</h3>
          <p className="text-[11px] text-text-tertiary">
            Step 2&apos;s failures, not a step of their own — the adset matched, the ad name did not
          </p>
        </div>
      </div>

      <div className="p-3">
          {error && <div className="py-4 text-center text-sm text-error-text">{error}</div>}
          {loading && !error && (
            <div className="py-8 text-center text-sm text-text-tertiary">Loading…</div>
          )}
          {!loading && !error && totals.orders === 0 && (
            <div className="py-6 text-center text-sm text-text-tertiary">
              No name misses in this window — every order whose adset matched also matched an ad name.
            </div>
          )}

          {!loading && !error && totals.orders > 0 && (
            <>
              {/* Same tile as the cascade steps and the channel KPIs --
                  literally the same component, so "matches the stepwise
                  styling" stays true when any of them is next touched. */}
              <div className="mb-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
                <StatTile
                  label="Orders affected"
                  color={theme.warningMid}
                  value={totals.orders.toLocaleString("en-IN")}
                  sub={`${fmtRs(totals.sales)} attributed to an adset, not to an ad`}
                  title="Orders whose utm_term named a known adset but whose utm_content matched no ad name inside it."
                />
                <StatTile
                  label="Distinct mismatches"
                  color={theme.infoMid}
                  value={totals.rows.toLocaleString("en-IN")}
                  sub="utm_content × adset pairs to fix"
                  title="One row per distinct naming mismatch -- the grain someone fixing ad names works at, not one per order."
                />
                <StatTile
                  label="Adsets involved"
                  color={theme.accentPurple}
                  value={totals.adsets.toLocaleString("en-IN")}
                  sub={
                    totals.adsets > 0 && totals.rows > totals.adsets
                      ? `${(totals.rows / totals.adsets).toFixed(1)} bad names per adset`
                      : "one mismatch each"
                  }
                  title="Fewer adsets than mismatches means the drift is concentrated in a handful of adsets."
                />
                <StatTile
                  label="No ads held"
                  color={totals.noAds > 0 ? theme.errorMid : theme.textTertiary}
                  value={totals.noAds.toLocaleString("en-IN")}
                  sub="missing ads, not drifted names"
                  dim={totals.noAds === 0}
                  title="The adset is in the roster but we hold no ads for it, so no name could have matched. A rename will not fix these."
                />
              </div>

              <button
                onClick={() => setOpen((v) => !v)}
                className="mb-2 rounded-md border border-border-primary bg-white px-2.5 py-1 text-xs hover:bg-bg-muted"
              >
                {open
                  ? "▴ Hide the mismatches"
                  : `▾ Show the ${totals.rows.toLocaleString("en-IN")} mismatches`}
              </button>

              {open && (
              <div className="max-h-[60vh] overflow-auto">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-white">
                    <tr className="border-b border-border-primary text-[11px] text-text-secondary">
                      <th className="px-2 py-2 font-medium">utm_content said</th>
                      <th className="px-2 py-2 font-medium">Ads actually in that adset</th>
                      <th className="px-2 py-2 font-medium">Adset / Campaign</th>
                      <th className="px-2 py-2 text-right font-medium">Orders</th>
                      <th className="px-2 py-2 text-right font-medium">Sales</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className="border-b border-border-soft align-top hover:bg-bg-surface">
                        <td className="px-2 py-1.5">
                          <span className="font-mono text-[11px]">{r.utm_content || "—"}</span>
                        </td>
                        <td className="px-2 py-1.5">
                          {r.ads_in_adset === 0 ? (
                            <span className="text-[11px] text-warning-text">
                              No ads held for this adset — nothing to match against
                            </span>
                          ) : (
                            <div className="flex flex-col gap-0.5">
                              {r.candidate_ad_names.map((n) => (
                                <span key={n} className="font-mono text-[11px] text-text-secondary">
                                  {n}
                                </span>
                              ))}
                              {r.ads_in_adset > r.candidate_ad_names.length && (
                                <span className="text-[10px] text-text-tertiary">
                                  +{r.ads_in_adset - r.candidate_ad_names.length} more
                                </span>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="max-w-[220px] truncate" title={r.adset_name ?? ""}>
                            {r.adset_name ?? "—"}
                          </div>
                          <div
                            className="max-w-[220px] truncate text-[10px] text-text-tertiary"
                            title={r.campaign_name ?? ""}
                          >
                            {r.campaign_name ?? "—"}
                          </div>
                          <div className="font-mono text-[10px] text-text-tertiary">{r.utm_term ?? "—"}</div>
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums">
                          {r.orders.toLocaleString("en-IN")}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{fmtRs(r.sales)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              )}

              <p className="mt-2 text-[11px] leading-relaxed text-text-tertiary">
                These orders are <b>not</b> unmatched — their adset and campaign are attributed, only the
                ad is not. Each row is either an ad to rename or a tracking template to correct; fixing
                one moves every future order on that pair into <b>Step 2</b>.
              </p>
            </>
          )}
      </div>
    </div>
  );
}

export default NameMissPanel;
