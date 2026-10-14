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
import { FieldLabel, FigureBand, type Figure } from "./SectionChrome";
import { MarkChevron } from "./Pictograms";

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

  const figures: Figure[] = [
    {
      label: "Orders affected",
      value: totals.orders.toLocaleString("en-IN"),
      basis: `${fmtRs(totals.sales)} attributed to an adset, not to an ad`,
      title:
        "Orders whose utm_term named a known adset but whose utm_content matched no ad name inside it.",
    },
    {
      label: "Distinct mismatches",
      value: totals.rows.toLocaleString("en-IN"),
      basis: "utm_content × adset pairs to fix",
      title:
        "One row per distinct naming mismatch, which is the grain someone fixing ad names works at, not one per order.",
    },
    {
      label: "Adsets involved",
      value: totals.adsets.toLocaleString("en-IN"),
      basis:
        totals.adsets > 0 && totals.rows > totals.adsets
          ? `${(totals.rows / totals.adsets).toFixed(1)} bad names per adset`
          : "one mismatch each",
      title:
        "Fewer adsets than mismatches means the drift is concentrated in a handful of adsets.",
    },
    {
      label: "No ads held",
      value: totals.noAds.toLocaleString("en-IN"),
      basis: "missing ads, not drifted names",
      title:
        "The adset is in the roster but we hold no ads for it, so no name could have matched. A rename will not fix these.",
    },
  ];

  /* Flat, like everything else in this section now.
   *
   * This was a bordered white card holding four more cards, each with a
   * coloured dot and a coloured top edge -- amber, blue, violet, red --
   * on a surface whose whole colour rule is that a hue carries meaning.
   * None of these did: they were four figures about one thing. Signal
   * red in particular was spent on a figure that is usually zero.
   *
   * So: a label on a rule, the four figures in the shared figure band,
   * the disclosure, the table. Every number is the one that was there,
   * and the sentence under the table is not deleted -- it is already in
   * Help, word for word, under "Adset matched, ad name failed", which
   * is what the ? opens.
   */
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border-primary pb-1.5">
        <div className="flex items-center gap-2">
          <FieldLabel>Adset matched · ad name failed</FieldLabel>
          <a
            href="#help"
            title="What this worklist means, and what to do with a row"
            aria-label="Help for adset matched, ad name failed"
            className="text-[11px] text-text-tertiary underline underline-offset-2 transition-colors hover:text-text-primary"
          >
            ?
          </a>
        </div>
        <span className="text-[11.5px] text-text-tertiary">
          Step 2&apos;s failures, not a step of their own — the adset matched, the ad name did not
        </span>
      </div>

      {error && <div className="py-3 text-sm text-error-text">{error}</div>}
      {loading && !error && (
        <div className="py-4 text-sm text-text-tertiary">Loading…</div>
      )}
      {!loading && !error && totals.orders === 0 && (
        <div className="py-3 text-sm text-text-tertiary">
          No name misses in this window — every order whose adset matched also matched an ad name.
        </div>
      )}

      {!loading && !error && totals.orders > 0 && (
        <>
          <FigureBand compact figures={figures} />

          <div>
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="flex items-center gap-1.5 text-[12.5px] text-text-secondary transition-colors hover:text-text-primary"
            >
              {open
                ? "Hide the mismatches"
                : `Show the ${totals.rows.toLocaleString("en-IN")} mismatches`}
              <span className={`transition-transform ${open ? "rotate-180" : ""}`}>
                <MarkChevron size={11} />
              </span>
            </button>
          </div>

          {open && (
            <div className="max-h-[60vh] overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-bg-base">
                  <tr className="border-b border-border-primary text-[10px] font-semibold uppercase tracking-[0.07em] text-text-tertiary">
                    <th className="px-2 py-2 font-semibold">utm_content said</th>
                    <th className="px-2 py-2 font-semibold">Ads actually in that adset</th>
                    <th className="px-2 py-2 font-semibold">Adset / Campaign</th>
                    <th className="px-2 py-2 text-right font-semibold">Orders</th>
                    <th className="px-2 py-2 text-right font-semibold">Sales</th>
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
                            {/* Keyed by position, not by name. An ad
                                set can hold two ads with the SAME
                                name -- that is the whole reason this
                                panel exists -- so the name is not a
                                unique key and React warned once per
                                duplicate. The list is display-only
                                and never reorders, so the index is a
                                stable key here. */}
                            {r.candidate_ad_names.map((n, j) => (
                              <span key={`${j}-${n}`} className="font-mono text-[11px] text-text-secondary">
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
        </>
      )}
    </div>
  );
}

export default NameMissPanel;
