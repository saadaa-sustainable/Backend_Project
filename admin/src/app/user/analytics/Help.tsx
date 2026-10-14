"use client";

/**
 * The one place the analytics surface explains itself.
 *
 * Every section used to carry its own prose: a paragraph above CPIS's
 * filters, a note under each chart, a sentence under the Last-Click
 * step cards, the data-floor banner above all thirteen. All of it was
 * read once and then scrolled past every day after, while costing the
 * first figure its place on the screen.
 *
 * The text here is NOT rewritten marketing copy -- it is the same
 * wording, moved. Where a sentence stated a rule (how a SKU matches an
 * ad name, which listing a stock figure comes from), that rule is
 * reproduced exactly, because people act on it.
 *
 * Articles are plain data, not MDX or a CMS: thirteen sections of
 * explanation is a page, not a content platform, and a `const` array
 * cannot drift out of sync with a build step.
 */

import { useMemo, useState } from "react";
import { MarkSearch, MarkChevron } from "./Pictograms";

type Topic = "definitions" | "attribution" | "freshness" | "sections" | "trouble";

const TOPICS: { key: Topic; label: string }[] = [
  { key: "definitions", label: "Metrics & definitions" },
  { key: "attribution", label: "Attribution" },
  { key: "freshness", label: "Data & freshness" },
  { key: "sections", label: "Section by section" },
  { key: "trouble", label: "Troubleshooting" },
];

interface Article {
  id: string;
  topic: Topic;
  /** Sections this answers for -- drives the `?` beside each title. */
  sections: string[];
  question: string;
  body: React.ReactNode;
}

const P = ({ children }: { children: React.ReactNode }) => (
  <p className="m-0 text-[14.5px] leading-[1.65] text-text-primary">{children}</p>
);
const Code = ({ children }: { children: React.ReactNode }) => (
  <code className="rounded bg-bg-muted px-1.5 py-0.5 font-mono text-[12.5px]">{children}</code>
);

export const HELP_ARTICLES: Article[] = [
  {
    id: "data-floor",
    topic: "freshness",
    sections: ["*"],
    question: "Why every figure starts 01 Jan 2026",
    body: (
      <>
        <P>
          Shopify order history effectively begins then — 376,348 of 377,215 orders fall in 2026,
          against 794 in all of 2025 — while Meta&apos;s lifetime spend and conversion value reach back
          years.
        </P>
        <P>
          Pairing them unbounded produced ads showing real Meta revenue against zero Shopify revenue:
          2,751 ads carrying ₹36.9 Cr of conversion value and no orders at all. That reads as
          catastrophic performance. It is a coverage gap, not a result.
        </P>
        <P>
          So <strong>Lifetime</strong> means &ldquo;since 01 Jan 2026&rdquo; — the first date on which
          Meta daily and Shopify both have real coverage.
        </P>
      </>
    ),
  },
  {
    id: "cpis-match",
    topic: "definitions",
    sections: ["cpis"],
    question: "How CPIS matches an ad to a SKU",
    body: (
      <>
        <P>
          An ad counts towards a master SKU when the SKU code appears in the ad&apos;s name. The match
          is a word-boundary regex on <Code>ad_lifecycle.ad_name</Code>, so <Code>SMCP</Code> matches{" "}
          <Code>NCP_CBO_SMCP_EX-EC</Code> but never <Code>SMCPT</Code>.
        </P>
        <P>
          Prefixes: <Code>SD</Code> women, <Code>SM</Code> men, <Code>SU</Code> unisex.
        </P>
        <P>
          Product identity, price, variants and inventory all come from the live Shopify catalogue.
        </P>
        <P>
          UTM-based per-order attribution is deliberately not used here. It is reserved for the
          per-colour-variant drill-down, because a UTM identifies the ad and one ad can carry several
          colours of the same SKU.
        </P>
      </>
    ),
  },
  {
    id: "verdicts",
    topic: "definitions",
    sections: ["ads-analyse", "creative-testing"],
    question: "How each verdict is decided",
    body: (
      <>
        <P>
          Straight from the account&apos;s written audit framework. Every threshold below is from that
          document, not chosen here.
        </P>
        <P>
          <strong>SCALE</strong> — 3-day last-click ROAS above 2.5 <em>and</em> 7-day above 2.5. An
          independent rule: the document is explicit that the kill and monitor criteria must not be
          applied to it, so it is evaluated first.
        </P>
        <P>
          <strong>PAUSE</strong> — 3-day and 7-day both below 1.5, <em>and</em> cost per first-time
          engaged website visitor above the account&apos;s benchmark.
        </P>
        <P>
          <strong>REPORT</strong> — the same ROAS failure, but cost per FTEWV is below the benchmark.
          The document says report rather than pause: the ad set is buying cheap first-time visitors
          even though revenue has not followed, which is a judgement for a person.
        </P>
        <P>
          <strong>MONITOR</strong> — 7-day below 1.5 but 3-day has recovered above it. Recent
          improvement, so do not pause yet.
        </P>
        <P>
          The F1–F4 gates are separate: LC ROAS above 2, new-customer ROAS above 2.5, cost per new
          customer under ₹525, and cost per first-time visitor under the account benchmark.
        </P>
      </>
    ),
  },
  {
    id: "units-in-stock",
    topic: "definitions",
    sections: ["cpis"],
    question: "Units in stock — which listing the number comes from",
    body: (
      <>
        <P>
          A SKU can appear on more than one Shopify listing: a price-test or A/B duplicate is a
          separate product record with its own variant rows, so each listing carries its own
          inventory count.
        </P>
        <P>
          An unpublished duplicate never sells, so its quantity freezes at the moment it was created.
          Taking the highest count across listings therefore picks the stalest one, every time.
        </P>
        <P>
          The figure here takes the quantity from an <strong>active</strong> listing whenever the SKU
          has one, and falls back to the highest otherwise. Measured 2026-10-13 on SMCSS: the active
          listing held 796 units, a draft price-test duplicate held a frozen 1,244, and ShopifyQL
          independently reported 806.
        </P>
      </>
    ),
  },
  {
    id: "date-basis",
    topic: "definitions",
    sections: ["ads-analyse"],
    question: "Delivery date, ad created, first seen — which to pick",
    body: (
      <>
        <P>
          <strong>Delivery</strong> keeps every ad that actually ran inside the window and re-sums
          every metric at daily grain, so a row describes the period you picked and nothing else.
          This is the one to use for &ldquo;what happened last week&rdquo;.
        </P>
        <P>
          <strong>Ad created</strong> and <strong>First seen</strong> instead select which ads to
          show — those launched or first delivered inside the window — and then report what those ads
          did in <em>total</em>. Use them for &ldquo;how are the things we launched in September
          doing&rdquo;.
        </P>
      </>
    ),
  },
  {
    id: "chart-floor",
    topic: "definitions",
    sections: ["cpis", "shopify-analytics"],
    question: "Reading the day-by-day chart",
    body: (
      <P>
        Each line runs between its own low and high, so compare the <em>shape</em>, not the height.
        The floor is each line&apos;s own minimum, not zero — two lines crossing means their trends
        crossed, not that the quantities met.
      </P>
    ),
  },
  {
    id: "multi-filter",
    topic: "definitions",
    sections: ["ads-analyse"],
    question: "How multi-filter rules combine",
    body: (
      <>
        <P>
          The builder lives behind <strong>More filters</strong> on the filter rule. Each rule is a
          field, an operator and a value; one connector governs the whole set, because mixed
          connectors need precedence rules and &ldquo;a AND b OR c&rdquo; silently means different
          things to different people.
        </P>
        <P>
          <strong>AND</strong> keeps ads matching every rule. <strong>OR</strong> keeps ads matching
          at least one. <strong>Exclude matches</strong> flips whichever of the two is set: AND plus
          exclude keeps everything except ads matching every rule, OR plus exclude keeps ads matching
          none of them.
        </P>
        <P>
          Keyword operators &mdash; <Code>contains all of</Code>, <Code>contains any of</Code>,{" "}
          <Code>contains none of</Code> &mdash; split the value on spaces. To look for several
          different ads in one go, <strong>contains any of</strong> on a single rule is usually
          simpler than several OR-ed rules.
        </P>
        <P>
          Rules are evaluated server-side across every matching ad, not just the rows in view, and
          nothing is sent until <strong>Apply</strong>.
        </P>
      </>
    ),
  },
  {
    id: "thresholds",
    topic: "definitions",
    sections: ["ads-analyse"],
    question: "Changing the F1–F4 thresholds",
    body: (
      <>
        <P>
          The four thresholds sit behind <strong>More filters</strong> beside the rule builder. They
          are the account&apos;s defaults until you type over them: F1 an impression floor, F2 a ROAS
          floor, F3 a ceiling on cost per NCP, F4 a ceiling on cost per first-time engaged website
          visitor.
        </P>
        <P>
          At the defaults the server&apos;s stored category is authoritative and the counts describe
          every matching ad. The moment you change a threshold the verdict is recomputed here, over
          the rows loaded so far &mdash; so the counts describe what is on screen, and scrolling for
          more raises them. <strong>Reset to defaults</strong> hands the question back to the server.
        </P>
      </>
    ),
  },
  {
    id: "adset-matched",
    topic: "attribution",
    sections: ["last-click-utm"],
    question: "“Adset matched, ad name failed” — what it means",
    body: (
      <>
        <P>
          These orders are <strong>not</strong> unmatched. Their ad set and campaign are attributed;
          only the ad is not.
        </P>
        <P>
          Each row is either an ad to rename or a tracking template to correct. Fixing one moves every
          future order on that pair into step 2.
        </P>
      </>
    ),
  },
  {
    id: "rollup-rules",
    topic: "trouble",
    sections: ["ads-analyse"],
    question: "Why metric rules apply to loaded rows, not the whole table",
    body: (
      <P>
        At the Ad Sets and Campaigns levels, rules run in the browser over the rows already fetched
        for that level — not server-side over everything. A rule that looks like it is hiding rows is
        filtering the page you have, so widen the date range or raise the row limit before concluding
        the data is missing.
      </P>
    ),
  },
  {
    id: "first-vs-last",
    topic: "attribution",
    sections: ["first-click", "last-click-utm"],
    question: "First click against last click — why the two disagree",
    body: (
      <P>
        Last click credits the ad that immediately preceded the order; first click credits the ad that
        began the journey. Prospecting ads look better on first click and retargeting ads look better
        on last click, which is the point of having both. The gap, not either column, is the finding.
      </P>
    ),
  },
  {
    id: "freshness",
    topic: "freshness",
    sections: ["*"],
    question: "When the data updates, and what to do if it looks stale",
    body: (
      <>
        <P>
          The pipeline runs nightly and rebuilds the silver and gold tables in order. Meta reports a
          day in arrears, so the newest day you can see is normally yesterday.
        </P>
        <P>
          Every date preset is anchored on the newest day the data actually covers, not on the clock —
          otherwise &ldquo;Last 7 Days&rdquo; would ask for a window whose final day does not exist
          yet and quietly sum six days against Meta&apos;s seven.
        </P>
        <P>
          The date control shows the window it resolved to. If that date is more than two days old,
          the nightly run did not finish and the figures are genuinely behind.
        </P>
      </>
    ),
  },
];

/** Which article answers for a section, used by the `?` beside its title. */
export function helpIdForSection(tab: string): string {
  const match = HELP_ARTICLES.find((a) => a.sections.includes(tab));
  return match ? match.id : "data-floor";
}

export function Help() {
  const [topic, setTopic] = useState<Topic>("definitions");
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>("cpis-match");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q) {
      return HELP_ARTICLES.filter((a) => a.question.toLowerCase().includes(q));
    }
    return HELP_ARTICLES.filter((a) => a.topic === topic);
  }, [topic, query]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        <h2 className="m-0 text-[22px] font-semibold tracking-[-0.02em] text-text-primary">Help</h2>
        <label className="block max-w-[620px]">
          <span className="sr-only">Search help</span>
          <span className="relative flex items-center">
            <span className="pointer-events-none absolute left-3 text-text-tertiary">
              <MarkSearch />
            </span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="cost per NCP, attribution window, why is this blank…"
              className="w-full border-b border-border-primary bg-transparent py-2.5 pl-9 pr-3 text-[15px] text-text-primary outline-none placeholder:text-text-tertiary focus:border-accent-yellow"
            />
          </span>
        </label>
      </div>

      <div className="flex flex-wrap items-start gap-8">
        <nav aria-label="Help topics" className="flex w-[200px] shrink-0 flex-col gap-0.5">
          {TOPICS.map((t) => {
            const on = !query && t.key === topic;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => { setQuery(""); setTopic(t.key); }}
                className={`border-l-2 px-3 py-1.5 text-left text-[13.5px] transition-colors ${
                  on
                    ? "border-text-primary font-medium text-text-primary"
                    : "border-transparent text-text-secondary hover:text-text-primary"
                }`}
              >
                {t.label}
              </button>
            );
          })}
        </nav>

        <div className="min-w-0 flex-1">
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.07em] text-text-tertiary">
            {query ? `${visible.length} matching` : `${visible.length} articles`}
          </div>
          {visible.length === 0 && (
            <p className="text-[14px] text-text-secondary">
              Nothing matches “{query}”. Ask the data team and the answer gets added here.
            </p>
          )}
          <div className="flex flex-col">
            {visible.map((a) => {
              const open = openId === a.id;
              return (
                <article key={a.id} className="border-t border-border-primary first:border-t-0">
                  <h3 className="m-0">
                    <button
                      type="button"
                      aria-expanded={open}
                      onClick={() => setOpenId(open ? null : a.id)}
                      className="flex w-full items-center justify-between gap-4 py-3.5 text-left"
                    >
                      <span className="text-[15px] font-medium text-text-primary">{a.question}</span>
                      <span className={`shrink-0 text-text-tertiary transition-transform ${open ? "rotate-180" : ""}`}>
                        <MarkChevron />
                      </span>
                    </button>
                  </h3>
                  {open && (
                    <div className="flex max-w-[76ch] flex-col gap-3 pb-5">{a.body}</div>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
