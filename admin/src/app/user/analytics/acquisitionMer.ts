import type { DashboardKpis } from "@/lib/api";

/**
 * Acquisition MER and its readable inverse, from one KPI payload.
 *
 * Extracted from the Dashboard because the awkward cases are the whole
 * point and they need a test: a payload with no acquisition figure at
 * all, a window with spend but no acquisitions, and a window with
 * acquisitions but no spend. Inline in JSX, each of those was one
 * optional-chain away from either throwing or asserting something
 * false.
 */
export interface AcquisitionFigures {
  /** Customers acquired in the window, or null when the payload cannot
   *  say. Absence is not zero -- see `fromKpis`. */
  newCustomers: number | null;
  /** Revenue from newly acquired customers / ad spend, both over the
   *  selected window. Money over money, so it reads like a ROAS. */
  acquisitionMer: number | null;
  /** ad spend / new customers -- the same two figures inverted, in
   *  rupees, because the ratio itself lands near 0.002. */
  costPerNewCustomer: number | null;
}

const EMPTY: AcquisitionFigures = {
  newCustomers: null, acquisitionMer: null, costPerNewCustomer: null,
};

export function fromKpis(kpis: DashboardKpis | null | undefined): AcquisitionFigures {
  if (!kpis) return EMPTY;

  // `new_customers` is optional on the type for a reason that bites at
  // runtime: `request()` casts JSON without validating it, and
  // useCachedFetch serves sessionStorage for five minutes, so a tab
  // opened before this field shipped -- or one talking to an older
  // server mid-deploy -- yields a KPI object without it.
  //
  // Null, NOT 0. Zero asserts "we acquired nobody this window", which
  // is a finding worth acting on; absence only means "this response
  // cannot say", and the card shows an em dash for it.
  const newCustomers = typeof kpis.new_customers === "number" ? kpis.new_customers : null;
  if (newCustomers === null) return EMPTY;
  // Optional for the same cached-payload reason as the head count.
  const newCustomerRevenue = typeof kpis.new_customer_revenue === "number"
    ? kpis.new_customer_revenue : 0;

  const spend = kpis.total_spend;
  return {
    newCustomers,
    // Undefined rather than Infinity when nothing was spent: a ratio
    // with an empty denominator has no value, and Infinity would
    // render as the best acquisition ever recorded.
    //
    // The numerator is new-customer REVENUE, not the head count. Both
    // readings of "acquisition MER" were on the table; this is the one
    // that is money over money and therefore comparable with the ROAS
    // figures beside it. The head count is still carried, as
    // `newCustomers`, and still drives cost per acquisition below.
    acquisitionMer: spend > 0 ? newCustomerRevenue / spend : null,
    // Likewise undefined when nothing was acquired -- "every rupee per
    // customer" is not a number.
    costPerNewCustomer: newCustomers > 0 ? spend / newCustomers : null,
  };
}
