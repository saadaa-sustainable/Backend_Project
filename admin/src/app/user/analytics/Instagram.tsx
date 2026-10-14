"use client";

/**
 * Instagram — per-post Silver read over public.insta_data.
 *
 * Layout: profile strip → KPI tiles → filter row → grid of post cards
 * with thumbnail + engagement stats. Click a card to open a details
 * drawer with every field the Silver table carries.
 *
 * Data freshness: insta_data is populated by the older
 * ingest_instagram.py path (Silver-writing). The newer
 * ingest_instagram_chronological (used by /admin/ingest) writes Bronze
 * (raw_dump_instagram) only — so a "days stale" banner is shown when
 * Silver's max ingested_at lags today. The Refresh button re-fires a
 * Bronze fetch but does NOT re-flatten Silver on its own (that's a
 * separate script — refresh_ig_silver.py or equivalent, not yet wired
 * to a /sync endpoint).
 */

import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  InstagramPostRow,
  InstagramProfile,
  InstagramSort,
  fetchInstagram,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import { instagramAvatarUrl, instagramThumbUrl } from "@/lib/api";
import {
  FieldLabel,
  FigureBand,
  FilterCell,
  FilterRule,
  SectionHeader,
  Segmented,
  filterControlClass,
} from "./SectionChrome";

const PAGE_SIZE = 60;

const SORT_OPTIONS: { value: InstagramSort; label: string }[] = [
  { value: "posted_at", label: "Newest first" },
  { value: "like_count", label: "Most liked" },
  { value: "comments_count", label: "Most commented" },
  { value: "insights_reach", label: "Highest reach" },
  { value: "insights_views", label: "Most views (insights)" },
  { value: "total_views_count", label: "Most views (total)" },
  { value: "insights_total_interactions", label: "Most interactions" },
];

// Whole numbers, grouped Indian-style like every other figure in this
// dashboard. The compact form rounded to one decimal, so 552,572
// followers read as "552.6K" and 1,361 posts as "1.4K" -- close enough
// to look precise and wrong enough to be useless for reconciling
// against Instagram itself.
function fmtInt(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return Math.round(n).toLocaleString("en-IN");
}
function fmtPct(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return `${n.toFixed(2)}%`;
}
function fmtDate(s: string | null) {
  if (!s) return "—";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s.slice(0, 10) : d.toISOString().slice(0, 10);
}

function daysAgo(iso: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return Math.floor((Date.now() - d.getTime()) / 86_400_000);
}

export function Instagram() {
  const [rows, setRows] = useState<InstagramPostRow[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<{
    total_posts: number;
    total_reach: number;
    total_views: number;
    total_likes: number;
    total_comments: number;
    avg_engagement_rate_pct: number | null;
    media_type_counts: Record<string, number>;
    profiles: InstagramProfile[];
    silver_last_ingested_at: string | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [username, setUsername] = useState("");
  const [mediaType, setMediaType] = useState("");
  const [mediaProductType, setMediaProductType] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<InstagramSort>("posted_at");
  const [selected, setSelected] = useState<InstagramPostRow | null>(null);

  const filters = useMemo(
    () => ({
      username: username || undefined,
      media_type: mediaType || undefined,
      media_product_type: mediaProductType || undefined,
      search: search || undefined,
      sort,
    }),
    [username, mediaType, mediaProductType, search, sort],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchInstagram({ ...filters, limit: PAGE_SIZE, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        setSummary(res.summary);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the FastAPI backend.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [filters]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const res = await fetchInstagram({ ...filters, limit: PAGE_SIZE, offset: rows.length });
      setRows((prev) => [...prev, ...res.rows]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load more posts.");
    } finally {
      setLoadingMore(false);
    }
  }

  const staleness = summary ? daysAgo(summary.silver_last_ingested_at) : null;

  // The panel always has something to show: the post you picked, or
  // the first one in the grid. Derived, never written to state -- an
  // effect that "selects" a row would fight the filters every refetch.
  const detail = selected ?? rows[0] ?? null;

  return (
    <div className="flex flex-col gap-4">
      {/* Header + freshness banner */}
      {/* Which table this reads is a Help question. How STALE it is is
          not -- that changes whether you trust the numbers, so the
          freshness badge stays on the title. */}
      <SectionHeader title="Instagram" helpId="freshness">
        {staleness !== null && (
          <span
            className={
              "px-2 py-0.5 text-[11.5px] " +
              (staleness > 3
                ? "bg-warning-bg text-warning-text"
                : "bg-success-bg text-success-text")
            }
            title={`Silver last flattened ${summary?.silver_last_ingested_at ?? "?"}`}
          >
            Silver freshness: {staleness}d ago
            {staleness > 3 && " · consider re-flattening"}
          </span>
        )}
      </SectionHeader>

      {/* Profile strip. A filter, so it reads as one: a rule of pills,
          not a row of shadowed cards. */}
      {summary && summary.profiles.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border-primary pb-2.5">
          <FieldLabel className="!inline mr-1">Account</FieldLabel>
          {summary.profiles.map((p) => {
            const active = username === p.username;
            return (
              <button
                key={p.ig_user_id ?? p.username ?? "?"}
                onClick={() => setUsername(username === (p.username ?? "") ? "" : (p.username ?? ""))}
                aria-pressed={active}
                className={
                  "flex items-center gap-2 border px-2 py-1 text-left transition-colors " +
                  (active
                    ? "border-text-primary bg-bg-surface"
                    : "border-border-primary hover:bg-bg-surface")
                }
                title={active ? "Click to clear filter" : `Filter to @${p.username}`}
              >
                <ProfileAvatar username={p.username} />
                <span className="flex flex-col">
                  <span className="text-[12.5px] font-medium text-text-primary">@{p.username ?? "?"}</span>
                  <span className="text-[10.5px] text-text-tertiary tabular-nums">
                    {fmtInt(p.followers_count)} followers · {fmtInt(p.media_count)} posts
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* The figures.
          "Posts (filtered)" used to lead this row and is gone. It sat
          directly under a profile strip quoting Instagram's own post
          counts and disagreed with them -- 1,361 against 1,414 -- because
          it counted what WE have ingested across every tracked account
          while the strip counts one account, live. Both were right and
          the pairing read as an error. The same number still appears
          beside the filters, as "N posts match", where it answers the
          question a reader is actually asking at that moment.

          The (i) popovers each tile carried are now the figure's own
          title: same words, one less thing to click. */}
      {summary && (
        <FigureBand
          figures={[
            {
              label: "Total reach",
              value: (
                <span title="Reach summed across the posts above. Instagram reports reach per post, and the same person reached by two posts counts in both, so this is larger than the number of people reached.">
                  {fmtInt(summary.total_reach)}
                </span>
              ),
            },
            {
              label: "Total likes",
              value: (
                <span title="Likes summed across the posts above, as they stood at the last ingest. Counts keep moving on Instagram; these do not until the next run.">
                  {fmtInt(summary.total_likes)}
                </span>
              ),
            },
            {
              label: "Total comments",
              value: (
                <span title="Comments summed across the posts above, as they stood at the last ingest.">
                  {fmtInt(summary.total_comments)}
                </span>
              ),
            },
            {
              label: "Engagement rate",
              value: fmtPct(summary.avg_engagement_rate_pct),
              basis: "interactions ÷ reach × 100",
            },
          ]}
        />
      )}

      {/* Filters, on one rule. The media-type chips joined it: they are
          a filter like the rest, and a second chip row above the figures
          was a third band of counts. */}
      <FilterRule
        actions={
          <>
            <span className="text-[11.5px] text-text-tertiary tabular-nums">
              {total.toLocaleString("en-IN")} posts match
            </span>
            <button
              onClick={() => {
                setUsername("");
                setMediaType("");
                setMediaProductType("");
                setSearch("");
                setSort("posted_at");
              }}
              className="text-[12.5px] text-text-secondary transition-colors hover:text-text-primary"
            >
              Clear filters
            </button>
            <ExportButton
              rows={rows as unknown as Record<string, unknown>[]}
              filename="instagram"
              disabled={loading || !rows.length}
            />
          </>
        }
      >
        {summary && Object.keys(summary.media_type_counts).length > 0 && (
          <FilterCell label="Media type">
            <Segmented
              options={[
                { value: "", label: `All (${summary.total_posts.toLocaleString("en-IN")})` },
                ...Object.entries(summary.media_type_counts).map(([mt, count]) => ({
                  value: mt,
                  label: `${mt} (${count.toLocaleString("en-IN")})`,
                })),
              ]}
              value={mediaType}
              onChange={setMediaType}
            />
          </FilterCell>
        )}

        <FilterCell label="Format" className="w-36" htmlFor="ig-format">
          <select
            id="ig-format"
            value={mediaProductType}
            onChange={(e) => setMediaProductType(e.target.value)}
            className={filterControlClass}
          >
            <option value="">All formats</option>
            <option value="FEED">Feed</option>
            <option value="REELS">Reels</option>
            <option value="STORY">Story</option>
          </select>
        </FilterCell>

        <FilterCell label="Sort by" className="w-52" htmlFor="ig-sort">
          <select
            id="ig-sort"
            value={sort}
            onChange={(e) => setSort(e.target.value as InstagramSort)}
            className={filterControlClass}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </FilterCell>

        <FilterCell label="Caption" className="w-56" htmlFor="ig-search">
          <input
            id="ig-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search…"
            className={filterControlClass}
          />
        </FilterCell>
      </FilterRule>

      {error && <div className="border border-error-mid bg-error-bg p-2 text-sm text-error-text">{error}</div>}

      {/* The grid and the post it selects, side by side. The details
          used to be a drawer over the page: you could read one post or
          the grid, never both, and comparing two meant opening and
          closing. */}
      <div className="flex flex-wrap items-start gap-5">
        <div className="min-w-[320px] flex-[1_1_620px]">
          {loading ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={`ik-${i}`} className="border border-border-primary bg-bg-white" style={{ opacity: 1 - i * 0.07 }}>
                  <div className="aspect-square w-full animate-pulse bg-bg-muted" />
                  <div className="px-2.5 py-2">
                    <div className="h-3 w-1/2 animate-pulse bg-bg-muted" />
                  </div>
                </div>
              ))}
            </div>
          ) : rows.length === 0 ? (
            <p className="border-b border-border-primary py-8 text-center text-[13px] text-text-tertiary">
              No posts match these filters.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {rows.map((r) => (
                <PostCard
                  key={r.id}
                  r={r}
                  selected={detail?.id === r.id}
                  onClick={() => setSelected(r)}
                />
              ))}
            </div>
          )}

          {/* Load more */}
          {rows.length < total && (
            <div className="mt-4 text-center">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                className="border border-border-primary px-4 py-1.5 text-[12.5px] text-text-secondary transition-colors hover:text-text-primary disabled:opacity-40"
              >
                {loadingMore ? "Loading…" : `Load more (${rows.length} of ${total})`}
              </button>
            </div>
          )}
        </div>

        <aside className="w-full flex-[0_1_360px] border border-border-primary bg-bg-white p-4 lg:sticky lg:top-4">
          {detail ? <PostPanel r={detail} /> : (
            <p className="py-8 text-center text-[13px] text-text-tertiary">
              Pick a post to see its figures.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────

/** Instagram's own embed for a post, from the permalink we store.
 *
 *  Why not the stored image: media_url and thumbnail_url are CDN URLs
 *  that EXPIRE. They 403 within days, which is what the broken tiles in
 *  this grid are. The permalink does not expire, and we have one for
 *  1,519 of 1,522 posts against 967 thumbnails -- better coverage and
 *  stable.
 *
 *  /embed is the public endpoint, so it needs no token and no app
 *  review, and it renders whatever the post actually is now: video plays
 *  as video, a carousel keeps its arrows.
 */
/** A thumbnail that does not expire, served by our own proxy.
 *
 *  Instagram's /p/<code>/media/ endpoint never goes stale, unlike the
 *  stored thumbnail_url -- 55 of the 63 tiles on the first screen were
 *  already 403ing. But it 302s to a CDN URL signed against the
 *  requester, and that signed URL 403s when the browser follows it from
 *  our origin: 58 of 59 follows failed in the page, while the same URL
 *  returns a JPEG to a server-side fetch. So the server fetches it.
 *
 *  The shortcode is taken from the column when we have one and parsed
 *  from the permalink otherwise, because the proxy needs the /p/ form:
 *  /reel/<code>/media/ answers 404 for the same post /p/<code>/media/
 *  serves.
 */
function proxiedThumb(
  permalink: string | null | undefined,
  shortcode: string | null | undefined,
): string | null {
  const code =
    shortcode?.trim() ||
    permalink?.match(/instagram\.com\/(?:p|reel|reels|tv)\/([^/?#]+)/)?.[1];
  return code ? instagramThumbUrl(code) : null;
}

function embedUrl(permalink: string | null | undefined): string | null {
  if (!permalink) return null;
  // Accept both /p/<code> and /reel/<code>, with or without the trailing
  // slash Instagram sometimes omits.
  if (!/^https:\/\/(www\.)?instagram\.com\//.test(permalink)) return null;
  return `${permalink.replace(/\/?$/, "/")}embed`;
}

/** Profile picture, or the account's initial.
 *
 *  Never the stored profile_picture_url: those are expired CDN links
 *  that 403 to the server as well as the browser, which is why this
 *  row showed three broken-image icons. The proxy serves the freshest
 *  capture in raw_dump_instagram, and 404s when even that has aged out
 *  -- true today for two of the three accounts, where only a fresh
 *  ingest can help. A letter is a better answer than a broken frame.
 */
function ProfileAvatar({ username }: { username: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!username || failed) {
    return (
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-bg-muted text-sm font-semibold uppercase text-text-secondary">
        {username?.[0] ?? "IG"}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={instagramAvatarUrl(username)}
      alt={username}
      className="h-11 w-11 shrink-0 rounded-full object-cover"
      onError={() => setFailed(true)}
    />
  );
}

/** One post in the grid: the picture, the day, and the reach.
 *
 *  It used to carry the media type, the product type, the account, two
 *  lines of caption and three counters as well -- sixty cards' worth of
 *  that is a wall, and every one of those fields is on the panel beside
 *  the grid the moment the card is picked. What a thumbnail grid is for
 *  is finding the post, and a date and a reach is what you find it by. */
function PostCard({ r, selected, onClick }: { r: InstagramPostRow; selected: boolean; onClick: () => void }) {
  // Stored image first -- it is already in the browser cache on a
  // revisit. When it 403s, fall back to the permalink thumbnail, which
  // cannot expire. Only if BOTH fail is there nothing to show.
  const sources = [
    r.thumbnail_url ?? r.media_url,
    proxiedThumb(r.permalink, r.shortcode),
  ].filter((u): u is string => !!u);
  const [srcIdx, setSrcIdx] = useState(0);
  const thumb = sources[srcIdx] ?? null;
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      title={
        `${fmtDate(r.posted_at)} · ${r.media_type ?? "?"}${r.media_product_type ? " · " + r.media_product_type : ""}\n` +
        `@${r.username ?? r.media_owner_username ?? "?"}\n` +
        `Reach ${fmtInt(r.insights_reach)} · likes ${fmtInt(r.like_count)} · comments ${fmtInt(r.comments_count)}\n` +
        (r.caption ? r.caption.slice(0, 160) : "no caption")
      }
      className={
        "flex flex-col overflow-hidden border bg-bg-white text-left transition-colors " +
        (selected ? "border-accent-yellow ring-1 ring-inset ring-accent-yellow" : "border-border-primary hover:border-text-primary")
      }
    >
      {/* overflow-hidden, and the media inside is ABSOLUTE. aspect-square
          alone did nothing here: an in-flow `h-full` image still sizes
          its parent, so a 320x568 reel stretched its tile to 404px
          while a 320x320 feed post sat at 228px and the grid came out
          ragged. Positioning the image out of flow leaves the tile
          height to the aspect ratio alone, so every preview is the
          same square and object-cover crops the overflow. */}
      <div className="relative aspect-square w-full overflow-hidden border-b border-border-primary bg-bg-muted">
        {/* The grid stays on stored images on purpose: fifty Instagram
            iframes on one screen is fifty third-party documents, and the
            page would crawl. The embed is in the panel, one at a time.

            But these URLs expire, so a dead one must not render as a
            broken-image icon with no way forward. onError swaps in a
            note that the post is still openable -- picking the card
            fills the panel, where the permalink embed shows the post
            whatever the CDN has done. */}
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={thumb}
            src={thumb}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            loading="lazy"
            // No Referer. Instagram's CDN refuses hotlinked images by
            // referrer, so the same URL that returns a JPEG to curl
            // returns 403 to a page on localhost. Sending none is what
            // makes the permalink thumbnail usable at all.
            referrerPolicy="no-referrer"
            onError={() => setSrcIdx((i) => i + 1)}
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-2 text-center text-[11px] text-text-tertiary">
            <span>no preview</span>
            <span className="text-[10px]">pick it to view the post</span>
          </div>
        )}
      </div>
      <div className="flex items-center justify-between gap-1 px-2.5 py-2 font-mono text-[11.5px] tabular-nums">
        <span className="text-text-secondary">{fmtDate(r.posted_at)}</span>
        {/* Reach, which is what the board asks for -- but Instagram
            only returns it for posts inside its insights window, and
            older ones carry none. Rather than a column of dashes, those
            fall back to likes AND SAY SO: a bare number under a card is
            read as one metric, so the unit has to be printed when it
            changes. */}
        {r.insights_reach !== null && r.insights_reach !== undefined ? (
          <span
            title="Reach"
            className={selected ? "font-semibold text-text-primary" : "text-text-primary"}
          >
            {fmtInt(r.insights_reach)}
          </span>
        ) : (
          <span title="No reach reported for this post — showing likes" className="text-text-tertiary">
            {fmtInt(r.like_count)} likes
          </span>
        )}
      </div>
    </button>
  );
}

/** One figure in the panel's grid. */
function PanelFigure({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="min-w-0">
      <FieldLabel>{label}</FieldLabel>
      <div className="mt-0.5 font-mono text-[17px] text-text-primary tabular-nums" title={title}>
        {value}
      </div>
    </div>
  );
}

/**
 * The selected post, beside the grid rather than over it.
 *
 * Every field the drawer listed is still here: the six that decide
 * whether a post worked are the figure grid, and the rest -- ids,
 * watch times, flags -- are one disclosure down, where a field you
 * consult twice a month belongs.
 */
function PostPanel({ r }: { r: InstagramPostRow }) {
  const sources = [
    r.thumbnail_url ?? r.media_url,
    proxiedThumb(r.permalink, r.shortcode),
  ].filter((u): u is string => !!u);
  const [srcIdx, setSrcIdx] = useState(0);
  const thumb = sources[srcIdx] ?? null;
  const embed = embedUrl(r.permalink);
  const rest: [string, React.ReactNode][] = [
    ["Owner", "@" + (r.media_owner_username ?? r.username ?? "?")],
    ["Media ID", r.media_id ?? "—"],
    ["Shortcode", r.shortcode ?? "—"],
    ["Total views", fmtInt(r.total_views_count)],
    ["Shares", fmtInt(r.shares_count)],
    ["Reposts", fmtInt(r.reposts_count)],
    ["Insights views", fmtInt(r.insights_views)],
    ["Profile visits", fmtInt(r.insights_profile_visits)],
    ["Follows from post", fmtInt(r.insights_follows)],
    ["Profile activity", fmtInt(r.insights_profile_activity)],
    ["Navigation", fmtInt(r.insights_navigation)],
    ["Replies", fmtInt(r.insights_replies)],
    ["Avg watch (ms)", fmtInt(r.avg_watch_time_ms)],
    ["Total watch (ms)", fmtInt(r.total_watch_time_ms)],
    ["Reel skip rate", fmtPct(r.reels_skip_rate_pct)],
    ["AI generated?", r.is_ai_generated === null ? "—" : r.is_ai_generated ? "Yes" : "No"],
    ["Comments enabled?", r.is_comment_enabled === null ? "—" : r.is_comment_enabled ? "Yes" : "No"],
    ["Shared to feed?", r.is_shared_to_feed === null ? "—" : r.is_shared_to_feed ? "Yes" : "No"],
    ["Audio type", r.media_audio_type ?? "—"],
    ["Ingested", r.ingested_at ? r.ingested_at.slice(0, 19).replace("T", " ") : "—"],
  ];
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="m-0 text-[15px] font-semibold text-text-primary">Post details</h3>
        <span className="font-mono text-[11.5px] text-text-tertiary">
          {fmtDate(r.posted_at)} · {(r.media_product_type ?? r.media_type ?? "?").toLowerCase()}
        </span>
      </div>

      <div className="relative flex aspect-[4/5] w-full items-center justify-center overflow-hidden border border-border-primary bg-bg-muted">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={thumb}
            src={thumb}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            referrerPolicy="no-referrer"
            onError={() => setSrcIdx((i) => i + 1)}
          />
        ) : (
          <span className="text-[11px] text-text-tertiary">no stored preview</span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <PanelFigure label="Reach" value={fmtInt(r.insights_reach)} title="People who saw this post, as Instagram reports it" />
        <PanelFigure label="Views" value={fmtInt(r.insights_views)} title="Views from insights. Total views, which counts differently, is under all fields." />
        <PanelFigure label="Likes" value={fmtInt(r.like_count)} />
        <PanelFigure label="Comments" value={fmtInt(r.comments_count)} />
        <PanelFigure label="Saves" value={fmtInt(r.saved_count)} />
        <PanelFigure label="Interactions" value={fmtInt(r.insights_total_interactions)} title="Likes, comments, saves and shares together, as Instagram totals them" />
      </div>

      <div className="flex flex-col gap-2 border-t border-border-soft pt-3">
        <FieldLabel>Caption</FieldLabel>
        {/* Captions run to T&Cs and giveaway rules. The whole thing is
            here -- it just scrolls instead of pushing the links off the
            panel. */}
        <p className="m-0 max-h-44 overflow-y-auto whitespace-pre-wrap text-[12.5px] leading-relaxed text-text-secondary">
          {r.caption ?? <span className="italic text-text-tertiary">no caption</span>}
        </p>
        <div className="flex flex-wrap gap-3">
          {r.permalink && (
            <a href={r.permalink} target="_blank" rel="noreferrer" className="text-[12.5px] text-text-link">
              Open on Instagram →
            </a>
          )}
          {r.media_url && r.media_url !== r.thumbnail_url && (
            <a href={r.media_url} target="_blank" rel="noreferrer" className="text-[12.5px] text-text-link">
              Media URL →
            </a>
          )}
        </div>
      </div>

      {/* The post itself, not a stored still. Behind a disclosure so the
          panel does not mount a third-party document on every pick. */}
      {embed && (
        <details className="border-t border-border-soft pt-3">
          <summary className="cursor-pointer text-[12.5px] text-text-secondary">Show the post itself</summary>
          <iframe
            src={embed}
            title="Instagram post"
            loading="lazy"
            // Instagram's embed is ~400px of chrome plus the media, and
            // it scrolls internally rather than resizing to fit.
            className="mt-3 h-[560px] w-full border border-border-primary bg-bg-white"
            // allow-scripts + allow-same-origin is what the embed needs
            // to render; popups so "View on Instagram" still works.
            sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </details>
      )}

      <details className="border-t border-border-soft pt-3">
        <summary className="cursor-pointer text-[12.5px] text-text-secondary">All fields</summary>
        <table className="mt-2 w-full text-[11.5px]">
          <tbody>
            {rest.map(([k, v]) => (
              <tr key={k} className="border-b border-border-soft">
                <td className="py-1 text-text-secondary">{k}</td>
                <td className="py-1 text-right font-mono text-text-primary tabular-nums">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
