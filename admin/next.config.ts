import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /** Hosts allowed to request dev-only assets (/_next/static chunks and
   *  the /_next/hmr socket), beyond the `localhost` the server starts on.
   *
   *  Next 16 blocks every other origin by default. Browsing the dashboard
   *  on 127.0.0.1 therefore got a page shell with several chunks and the
   *  HMR socket silently refused — so the tab rendered stale code and
   *  never picked up an edit, with nothing in the browser to explain it.
   *  The dev log is the only place it showed:
   *
   *    ⚠ Blocked cross-origin request to Next.js dev resource
   *      /_next/hmr from "127.0.0.1".
   *
   *  127.0.0.1 and localhost are the same machine here, so allowing it
   *  costs nothing and removes a failure that reads exactly like "my
   *  change did not apply". Development only; the production build
   *  ignores this. */
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
