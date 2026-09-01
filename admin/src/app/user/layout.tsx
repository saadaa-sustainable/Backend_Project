import { UserTopBar } from "@/components/UserTopBar";

/**
 * Nested layout for /user/* — adds the slim white top bar over a gray
 * canvas (bg-bg-base = #F4F6F9). The sidebar itself is rendered by the
 * root layout's AppNav (which switches between admin and user variants
 * by path prefix), so we only own the top bar + content padding here.
 *
 * The negative-margin trick reverses the root layout's
 * `mx-auto max-w-7xl px-8 py-8` wrapper for /user routes so the top bar
 * spans the full viewport-minus-sidebar (matching kwikengage's flush
 * top strip). Everything nested below gets its own generous padding.
 */
export default function UserLayout({ children }: LayoutProps<"/user">) {
  return (
    <div className="-mx-8 -my-8 flex min-h-[calc(100vh)] flex-col">
      <UserTopBar />
      <div className="flex-1 bg-bg-base px-6 py-6">{children}</div>
    </div>
  );
}
