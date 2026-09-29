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

import { IconComment, IconHeart, IconReach } from "./Icons";
import {
  ApiError,
  InstagramPostRow,
  InstagramProfile,
  InstagramSort,
  fetchInstagram,
} from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import { instagramThumbUrl } from "@/lib/api";

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

const MEDIA_TYPE_COLORS: Record<string, string> = {
  IMAGE: "bg-info-bg text-info-text",
  VIDEO: "bg-accent-purple-bg text-accent-purple",
  CAROUSEL_ALBUM: "bg-success-bg text-success-text",
};

function fmtInt(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
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

  return (
    <div className="flex flex-col gap-4">
      {/* Header + freshness banner */}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-text-primary">Instagram content</h2>
          <p className="text-xs text-text-secondary">
            Per-post Silver read over <code className="rounded bg-bg-muted px-1 py-0.5 text-[10px]">insta_data</code> —
            engagement counts, insights reach/views, media metadata.
          </p>
        </div>
        {staleness !== null && (
          <span
            className={
              "rounded-full px-3 py-1 text-xs " +
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
      </div>

      {/* Profile strip */}
      {summary && summary.profiles.length > 0 && (
        <div className="flex flex-wrap gap-3">
          {summary.profiles.map((p) => (
            <button
              key={p.ig_user_id ?? p.username ?? "?"}
              onClick={() => setUsername(username === (p.username ?? "") ? "" : (p.username ?? ""))}
              className={
                "flex items-center gap-3 rounded-lg border p-2 text-left shadow-sm transition-colors " +
                (username === p.username
                  ? "border-text-primary bg-bg-surface"
                  : "border-border-primary bg-white hover:border-border-primary")
              }
              title={username === p.username ? "Click to clear filter" : `Filter to @${p.username}`}
            >
              {p.profile_picture_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={p.profile_picture_url}
                  alt={p.username ?? ""}
                  className="h-11 w-11 rounded-full object-cover"
                />
              ) : (
                <div className="flex h-11 w-11 items-center justify-center rounded-full bg-bg-muted text-xs text-text-secondary">
                  IG
                </div>
              )}
              <div>
                <div className="text-sm font-semibold">@{p.username ?? "?"}</div>
                <div className="text-[10px] text-text-secondary">
                  {fmtInt(p.followers_count)} followers · {fmtInt(p.media_count)} posts
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* KPI tiles */}
      {summary && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Tile label="Posts (filtered)" value={fmtInt(summary.total_posts)} />
          <Tile label="Total reach" value={fmtInt(summary.total_reach)} />
          <Tile label="Total likes" value={fmtInt(summary.total_likes)} />
          <Tile label="Total comments" value={fmtInt(summary.total_comments)} />
          <Tile
            label="Engagement rate"
            value={fmtPct(summary.avg_engagement_rate_pct)}
            hint="interactions ÷ reach × 100"
          />
        </div>
      )}

      {/* Media-type chips */}
      {summary && Object.keys(summary.media_type_counts).length > 0 && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setMediaType("")}
            className={
              "rounded-full border px-3 py-1 text-xs " +
              (mediaType === "" ? "border-text-primary bg-text-primary text-white" : "border-border-primary bg-white hover:bg-bg-muted")
            }
          >
            All ({summary.total_posts})
          </button>
          {Object.entries(summary.media_type_counts).map(([mt, count]) => {
            const cls = MEDIA_TYPE_COLORS[mt] ?? "bg-bg-muted text-text-secondary";
            const active = mediaType === mt;
            return (
              <button
                key={mt}
                onClick={() => setMediaType(active ? "" : mt)}
                className={
                  "rounded-full border px-3 py-1 text-xs " +
                  (active
                    ? "border-text-primary " + cls
                    : "border-border-primary bg-white hover:bg-bg-muted")
                }
              >
                {mt} ({count.toLocaleString()})
              </button>
            );
          })}
        </div>
      )}

      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-primary bg-white p-2 shadow-sm">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search caption…"
          className="w-64 rounded-md border border-border-primary px-2 py-1 text-sm"
        />
        <select
          value={mediaProductType}
          onChange={(e) => setMediaProductType(e.target.value)}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        >
          <option value="">All formats</option>
          <option value="FEED">Feed</option>
          <option value="REELS">Reels</option>
          <option value="STORY">Story</option>
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as InstagramSort)}
          className="rounded-md border border-border-primary px-2 py-1 text-sm"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              Sort: {o.label}
            </option>
          ))}
        </select>
        <button
          onClick={() => {
            setUsername("");
            setMediaType("");
            setMediaProductType("");
            setSearch("");
            setSort("posted_at");
          }}
          className="rounded-md border border-border-primary bg-white px-2 py-1 text-xs hover:bg-bg-muted"
        >
          Clear filters
        </button>
        <span className="ml-auto text-xs text-text-secondary">
          {total.toLocaleString()} posts match
        </span>
        <ExportButton
          rows={rows as unknown as Record<string, unknown>[]}
          filename="instagram"
          disabled={loading || !rows.length}
        />
      </div>

      {error && <div className="rounded-md border border-error-mid bg-error-bg p-2 text-sm text-error-text">{error}</div>}

      {/* Post grid */}
      {loading ? (
        <p className="text-sm text-text-secondary">Loading…</p>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-border-primary bg-white p-8 text-center text-sm text-text-secondary">
          No posts match these filters.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {rows.map((r) => (
            <PostCard key={r.id} r={r} onClick={() => setSelected(r)} />
          ))}
        </div>
      )}

      {/* Load more */}
      {rows.length < total && (
        <div className="text-center">
          <button
            onClick={loadMore}
            disabled={loadingMore}
            className="rounded-md border border-border-primary bg-white px-4 py-1.5 text-xs hover:bg-bg-muted disabled:opacity-40"
          >
            {loadingMore ? "Loading…" : `Load more (${rows.length} of ${total})`}
          </button>
        </div>
      )}

      {/* Details drawer */}
      {selected && <PostDrawer r={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border-primary bg-white p-2 shadow-sm">
      <div className="text-[10px] uppercase tracking-wide text-text-secondary">{label}</div>
      <div className="font-mono text-lg font-semibold text-text-primary">{value}</div>
      {hint && <div className="text-[9px] text-text-tertiary">{hint}</div>}
    </div>
  );
}

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

function PostCard({ r, onClick }: { r: InstagramPostRow; onClick: () => void }) {
  // Stored image first -- it is already in the browser cache on a
  // revisit. When it 403s, fall back to the permalink thumbnail, which
  // cannot expire. Only if BOTH fail is there nothing to show.
  const sources = [
    r.thumbnail_url ?? r.media_url,
    proxiedThumb(r.permalink, r.shortcode),
  ].filter((u): u is string => !!u);
  const [srcIdx, setSrcIdx] = useState(0);
  const thumb = sources[srcIdx] ?? null;
  const mediaTypeCls = MEDIA_TYPE_COLORS[r.media_type ?? ""] ?? "bg-bg-muted text-text-secondary";
  return (
    <button
      onClick={onClick}
      className="group flex flex-col overflow-hidden rounded-lg border border-border-primary bg-white text-left shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="relative aspect-square w-full bg-bg-muted">
        {/* The grid stays on stored images on purpose: fifty Instagram
            iframes on one screen is fifty third-party documents, and the
            page would crawl. The embed is in the detail view, one at a
            time.

            But these URLs expire, so a dead one must not render as a
            broken-image icon with no way forward. onError swaps in a
            note that the post is still openable -- clicking the card
            opens the detail view, where the permalink embed shows the
            post whatever the CDN has done. */}
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={thumb}
            src={thumb}
            alt=""
            className="h-full w-full object-cover"
            loading="lazy"
            // No Referer. Instagram's CDN refuses hotlinked images by
            // referrer, so the same URL that returns a JPEG to curl
            // returns 403 to a page on localhost. Sending none is what
            // makes the permalink thumbnail usable at all.
            referrerPolicy="no-referrer"
            onError={() => setSrcIdx((i) => i + 1)}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-1 px-2 text-center text-xs text-text-tertiary">
            <span aria-hidden="true">▢</span>
            <span>no preview</span>
            <span className="text-[10px]">open to view the post</span>
          </div>
        )}
        <span className={`absolute left-2 top-2 rounded-full px-2 py-0.5 text-[9px] font-semibold ${mediaTypeCls}`}>
          {r.media_type ?? "?"}
        </span>
        {r.media_product_type && r.media_product_type !== "FEED" && (
          <span className="absolute right-2 top-2 rounded-full bg-text-primary px-2 py-0.5 text-[9px] font-semibold text-white">
            {r.media_product_type}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-1 p-2">
        <div className="flex items-center justify-between text-[10px] text-text-secondary">
          <span>@{r.username ?? r.media_owner_username ?? "?"}</span>
          <span>{fmtDate(r.posted_at)}</span>
        </div>
        <p className="line-clamp-2 text-xs text-text-primary">
          {r.caption ?? <span className="text-text-tertiary italic">no caption</span>}
        </p>
        <div className="mt-1 flex items-center gap-3 text-[10px] font-mono text-text-secondary">
          <span className="inline-flex items-center gap-1" title="Likes">
            <IconHeart /> {fmtInt(r.like_count)}
          </span>
          <span className="inline-flex items-center gap-1" title="Comments">
            <IconComment /> {fmtInt(r.comments_count)}
          </span>
          {r.insights_reach !== null && (
            <span className="inline-flex items-center gap-1" title="Reach">
              <IconReach /> {fmtInt(r.insights_reach)}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

function PostDrawer({ r, onClose }: { r: InstagramPostRow; onClose: () => void }) {
  const rows: [string, React.ReactNode][] = [
    ["Posted", fmtDate(r.posted_at)],
    ["Type", `${r.media_type ?? "?"}${r.media_product_type ? " · " + r.media_product_type : ""}`],
    ["Owner", "@" + (r.media_owner_username ?? r.username ?? "?")],
    ["Media ID", r.media_id ?? "—"],
    ["Shortcode", r.shortcode ?? "—"],
    ["Likes", fmtInt(r.like_count)],
    ["Comments", fmtInt(r.comments_count)],
    ["Total views", fmtInt(r.total_views_count)],
    ["Saves", fmtInt(r.saved_count)],
    ["Shares", fmtInt(r.shares_count)],
    ["Reposts", fmtInt(r.reposts_count)],
    ["Insights reach", fmtInt(r.insights_reach)],
    ["Insights views", fmtInt(r.insights_views)],
    ["Total interactions", fmtInt(r.insights_total_interactions)],
    ["Profile visits", fmtInt(r.insights_profile_visits)],
    ["Follows from post", fmtInt(r.insights_follows)],
    ["Avg watch (ms)", fmtInt(r.avg_watch_time_ms)],
    ["Total watch (ms)", fmtInt(r.total_watch_time_ms)],
    ["Reel skip rate", fmtPct(r.reels_skip_rate_pct)],
    ["AI generated?", r.is_ai_generated === null ? "—" : r.is_ai_generated ? "Yes" : "No"],
    ["Comments enabled?", r.is_comment_enabled === null ? "—" : r.is_comment_enabled ? "Yes" : "No"],
  ];
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="h-full w-[540px] overflow-auto border-l border-border-primary bg-white p-4 shadow-2xl"
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-semibold">Post details</h3>
          <button onClick={onClose} className="text-text-secondary hover:text-text-primary">
            ✕
          </button>
        </div>
        {/* The post itself, not a stored still. Falls back to the
            thumbnail only when there is no usable permalink -- three
            posts out of 1,522. */}
        {embedUrl(r.permalink) ? (
          <iframe
            src={embedUrl(r.permalink) ?? ""}
            title="Instagram post"
            loading="lazy"
            // Instagram's embed is ~400px of chrome plus the media, and
            // it scrolls internally rather than resizing to fit.
            className="mb-3 h-[560px] w-full rounded-lg border border-border-primary bg-white"
            // allow-scripts + allow-same-origin is what the embed needs
            // to render; popups so "View on Instagram" still works.
            sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
            referrerPolicy="no-referrer-when-downgrade"
          />
        ) : (r.thumbnail_url ?? r.media_url) ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={r.thumbnail_url ?? r.media_url ?? ""}
            alt=""
            className="mb-3 w-full rounded-lg object-cover"
          />
        ) : null}
        {r.caption && (
          <p className="mb-3 whitespace-pre-wrap rounded-md bg-bg-surface p-2 text-xs text-text-primary">
            {r.caption}
          </p>
        )}
        <div className="mb-3 flex gap-2">
          {r.permalink && (
            <a
              href={r.permalink}
              target="_blank"
              rel="noreferrer"
              className="rounded-md border border-border-primary bg-white px-3 py-1 text-xs hover:bg-bg-muted"
            >
              ↗ Open on Instagram
            </a>
          )}
          {r.media_url && r.media_url !== r.thumbnail_url && (
            <a
              href={r.media_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-md border border-border-primary bg-white px-3 py-1 text-xs hover:bg-bg-muted"
            >
              ▶ Media URL
            </a>
          )}
        </div>
        <table className="w-full text-xs">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k} className="border-b border-border-soft">
                <td className="py-1 text-text-secondary">{k}</td>
                <td className="py-1 text-right font-mono text-text-primary">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
