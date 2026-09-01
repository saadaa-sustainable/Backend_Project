"use client";

/**
 * Slim top bar for the /user analytics panel — kwikengage.ai pattern
 * (2026-08-31 screenshot). White strip, right-aligned notification bell
 * + greeting + avatar chevron. The greeting text uses the auto-memory
 * "userEmail" (website@saadaa.in) as the display identity here; a real
 * auth flow would replace this with the logged-in user's name.
 */
export function UserTopBar() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-end gap-4 border-b border-border-primary bg-bg-white px-6">
      <button
        type="button"
        aria-label="Notifications"
        className="relative flex h-9 w-9 items-center justify-center rounded-full text-text-secondary transition-colors hover:bg-bg-surface hover:text-text-primary"
      >
        <span className="text-[16px]">🔔</span>
        <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-error-mid" />
      </button>

      <div className="flex items-center gap-2.5">
        <span className="text-[13px] font-medium text-text-primary">
          Welcome, <span className="font-semibold">SAADAA</span>
        </span>
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-yellow-bg text-[13px] font-semibold text-accent-yellow">
          S
        </div>
        <span className="text-text-tertiary text-xs">▾</span>
      </div>
    </header>
  );
}
