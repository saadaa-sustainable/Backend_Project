# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Three audiences share one surface, and they arrive with different questions.

- **Media buyers / performance team** — the daily operators. They make
  scale, pause and monitor calls on live Meta ad sets and campaigns, and
  they need the verdict and the numbers behind it to be defensible
  without asking anyone.
- **Founders / leadership** — reading outcomes, not operating. Spend,
  ROAS, what is working. They do not need the framework's internals.
- **Content / creative team** — deciding what to produce next. They work
  in Creative Testing and Untested Assets, and reason about assets, SKUs
  and creative categories rather than adset mechanics.

All three use it **at a desk, throughout the day**, on a large monitor,
in long sessions, referenced continuously while working. It is not a
glanceable surface and not a presentation surface.

## Product Purpose

An internal analytics dashboard for saadaa's Meta advertising. It exists
to turn raw ad, order and fulfilment data into decisions a person can
defend: which ad sets to scale, which to pause, which creatives to make
more of, and what a rupee of ad spend actually returned once returns and
cancellations are counted.

Success is a decision made confidently and quickly, with the basis for
it visible on the same screen.

## Positioning

Meta Ads Manager reports what Meta attributes to itself. This reports
what the business actually received: last-click Shopify revenue joined to
Meta spend at ad, ad set and campaign grain, then corrected for the
fulfilment reality of Indian D2C — COD orders that were placed, counted,
and never collected.

The account's own written **Meta Ads Audit & Decision Framework** is
encoded in the product, so the verdict on screen and the verdict in the
document are the same rule.

## Operating Context

Medallion architecture over Supabase Postgres: Bronze raw dumps, Silver
flattened tables, Gold analytics tables. A FastAPI backend serves a
Next.js admin app. Nightly cron refreshes the daily grain.

Sources joined into one picture: Meta Marketing API, Shopify, GoKwik
(checkout, payment method, RTO risk), and EasyEcom (fulfilment, delivery
status, returns and credit notes, arriving by webhook).

## Capabilities and Constraints

Sections: Ads Analyse (ad / ad set / campaign, with the framework
verdict), Creative Testing, CPIS, Untested Assets, Last-Click UTM,
Customer Journey, Landing Page Analysis, Shopify Analytics, Instagram,
Meta Explorer.

Terminology that is fixed and must be used exactly:

- Verdicts: **SCALE / PAUSE / MONITOR / REPORT / OK / UNRATED**
- Creative categories: **F1–F4**
- **CBO / ABO** budget level, **NCP** new customer purchases,
  **FTEWV** (the cost benchmark the pause rule reads), **CPIS**
- Asset sources: **DAM Project** (video, graphic) and
  **Creator Hub Project** (influencer), each with a Historical archive

Data constraints that shape what may be displayed:

- **Reach is a distinct-person count and is never summable.** Summing it
  across days or entities produces a number larger than the account's
  lifetime reach.
- Meta daily insights land a day in arrears, so windows anchor on the
  last date present in the data, never on the clock.
- A windowed metric describes its window or is zero; it never falls back
  to a lifetime figure.
- The data floor is 2026-01-01.

## Brand Commitments

Company: SAADAA SUSTAINABLE DESIGNS AND TECHNOLOGIES PRIVATE LIMITED,
trading as **saadaa** — a sustainable D2C apparel brand in India.

## Evidence on Hand

Real production data throughout; there is no seed or demo dataset. Any
figure shown in design work must come from the live API or be labelled
as illustrative.

Reference points captured during development, useful because they show
the shape of real values: ~3,030 ad sets and ~530 campaigns; ad set names
that run past 40 characters; influencer register of 14,709 rows against
2,350 with a usable link; COD returns running far above prepaid.

## Product Principles

1. **The number and its basis travel together.** Any figure a decision
   rests on must be able to say where it came from, on the same screen.
2. **Density is the product.** These users read wide tables at a desk all
   day. Rows and columns per screen are a feature, not clutter to be
   designed away.
3. **One vocabulary.** The framework's words mean one thing in the
   document, the SQL, the API and the UI.
4. **Never imply precision the data does not have.** Windows, grains and
   populations are stated, not assumed.
5. **Three readers, one surface.** An operator, a founder and a creative
   must each find their answer without the other two's detail in the way.

## Accessibility & Inclusion

Long daily sessions on a desktop monitor. The existing chart palette is
CVD-validated (`admin/src/lib/theme.ts`) and any palette change must
preserve that. Text contrast must hold at body sizes for all-day reading.
