"use client";

/**
 * Reusable table-loading skeleton. Renders a fake table with N rows of
 * shimmering grey placeholder cells so the layout doesn't jump when
 * real data arrives.
 *
 * Preferred over a single "Loading…" line because the analytics tabs
 * take 3-10s on prod -- a plain text placeholder makes the app feel
 * stuck for that whole window.
 *
 * Usage:
 *   {loading ? <TableSkeleton rows={10} columns={8} /> : <RealTable/>}
 */

interface Props {
  rows?: number;
  columns?: number;
  showHeader?: boolean;
  showKpis?: boolean;   // pre-table KPI tiles
  message?: string | null;
}

export function TableSkeleton({
  rows = 8,
  columns = 8,
  showHeader = true,
  showKpis = false,
  message = null,
}: Props) {
  return (
    <div className="flex flex-col gap-4">
      {showKpis && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="skeleton-shimmer h-[76px] rounded-md border border-border-primary bg-bg-surface"
            />
          ))}
        </div>
      )}
      <div className="overflow-hidden rounded-lg border border-border-primary bg-white shadow-sm">
        <table className="min-w-full text-xs">
          {showHeader && (
            <thead>
              <tr>
                {Array.from({ length: columns }).map((_, i) => (
                  <th key={i} className="px-3 py-3 text-left">
                    <div className="skeleton-shimmer h-3 w-16 rounded" />
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {Array.from({ length: rows }).map((_, r) => (
              <tr key={r} className="border-t border-border-soft">
                {Array.from({ length: columns }).map((_, c) => (
                  <td key={c} className="px-3 py-2.5">
                    <div
                      className="skeleton-shimmer h-3 rounded"
                      style={{ width: c === 0 ? "60%" : c === 1 ? "80%" : "45%" }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {message ? (
        <div className="text-center text-xs text-text-tertiary">{message}</div>
      ) : (
        <div className="text-center text-xs text-text-tertiary">
          Fetching data… this can take a few seconds on the first load.
        </div>
      )}
      {/* Shimmer keyframes -- defined inline so this component is
          self-contained and doesn't need a global CSS update. */}
      <style jsx>{`
        :global(.skeleton-shimmer) {
          position: relative;
          overflow: hidden;
          background-color: rgb(226 232 240 / 0.6);
        }
        :global(.skeleton-shimmer::after) {
          content: "";
          position: absolute;
          inset: 0;
          background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.5) 50%,
            transparent 100%
          );
          animation: shimmer 1.4s infinite;
        }
        @keyframes shimmer {
          from {
            transform: translateX(-100%);
          }
          to {
            transform: translateX(100%);
          }
        }
      `}</style>
    </div>
  );
}
