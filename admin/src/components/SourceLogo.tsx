import type { IngestSource } from "@/lib/api";

// Simplified brand-colored glyphs (not exact logo reproductions) used purely
// to identify which service a fetch source talks to at a glance.

function MetaGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 36 36" className={className} aria-hidden="true">
      <path
        fill="#0866FF"
        d="M9 20.5c0-6 3.2-11 7.6-11 2.6 0 4.4 1.8 6 4.4l.4.7.4-.7c1.6-2.6 3.4-4.4 6-4.4 4.4 0 7.6 5 7.6 11s-3.2 8.5-6.8 8.5c-2.4 0-4-1.4-6.4-5.2l-.8-1.3-.8 1.3c-2.4 3.8-4 5.2-6.4 5.2C12.2 29 9 26.5 9 20.5Z"
      />
      <path
        fill="#0866FF"
        d="M16.6 12.4c-2.9 3.6-4.8 8.9-4.8 13 0 1.9.6 2.6 1.4 2.6.9 0 1.9-.7 3.4-2.9 1.3-1.9 2.5-4.1 3.5-6.1-1.1-2.6-2.2-4.8-3.5-6.6Z"
        opacity=".55"
      />
    </svg>
  );
}

function ShopifyGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 36 36" className={className} aria-hidden="true">
      <path
        fill="#95BF47"
        d="M26.5 9.2c-.1-.4-.4-.6-.7-.6l-2.1-.2-1.6-1.6c-.3-.3-.9-.2-1.1-.1 0 0-.3.1-.7.3-.4-1.2-1.2-2.3-2.5-2.3h-.1c-.4-.5-.9-.7-1.3-.7-3.3 0-4.9 4.2-5.4 6.3-1.3.4-2.2.7-2.4.7-.7.2-.7.3-.8 1L6 27.4l16.4 3.1 8.9-1.9S26.6 9.5 26.5 9.2ZM19 7.2c-.4.1-.9.3-1.4.4v-.3c0-1-.1-1.8-.4-2.5 1 .1 1.6 1.3 1.8 2.4Zm-2.7-2.2c.3.7.5 1.6.5 2.9v.2l-2.6.8c.5-1.9 1.4-2.9 2.1-3.9ZM17 6.5v-.1c.6-.2 1.1-.3 1.6-.5v.5l-1.6.1Z"
      />
      <path
        fill="#5E8E3E"
        d="m25.8 8.6-2.1-.2-1.6-1.6c-.1-.1-.1-.1-.2-.1L22.4 30.5l8.9-1.9-4.8-19.6c-.1-.3-.4-.4-.7-.4Z"
      />
      <path
        fill="#fff"
        d="m18.4 14.1-1 3.3s-1.1-.5-2.4-.5c-2 0-2.1 1.2-2.1 1.5 0 1.6 4.3 2.3 4.3 6.1 0 3-1.9 4.9-4.5 4.9-3.1 0-4.7-1.9-4.7-1.9l.8-2.7s1.6 1.4 3 1.4c.9 0 1.3-.7 1.3-1.3 0-2.2-3.5-2.3-3.5-5.7 0-2.9 2.1-5.8 6.3-5.8 1.6 0 2.5.5 2.5.5Z"
      />
    </svg>
  );
}

function InstagramGlyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 36 36" className={className} aria-hidden="true">
      <defs>
        <radialGradient id="ig-grad" cx="30%" cy="107%" r="150%">
          <stop offset="0%" stopColor="#FFDD55" />
          <stop offset="10%" stopColor="#FFDD55" />
          <stop offset="50%" stopColor="#FF543E" />
          <stop offset="100%" stopColor="#C837AB" />
        </radialGradient>
      </defs>
      <rect x="4" y="4" width="28" height="28" rx="8" fill="url(#ig-grad)" />
      <rect x="10" y="10" width="16" height="16" rx="5" fill="none" stroke="#fff" strokeWidth="2" />
      <circle cx="18" cy="18" r="4.2" fill="none" stroke="#fff" strokeWidth="2" />
      <circle cx="24.2" cy="11.8" r="1.3" fill="#fff" />
    </svg>
  );
}

const GLYPHS: Record<IngestSource, (props: { className?: string }) => React.JSX.Element> = {
  meta: MetaGlyph,
  shopify: ShopifyGlyph,
  instagram: InstagramGlyph,
};

export function SourceLogo({ source, className = "h-5 w-5" }: { source: IngestSource; className?: string }) {
  const Glyph = GLYPHS[source];
  return <Glyph className={className} />;
}
