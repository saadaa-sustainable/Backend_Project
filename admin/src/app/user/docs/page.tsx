import { readFile } from "node:fs/promises";
import path from "node:path";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders the connector documentation from its markdown source.
 *
 * The markdown is read from `public/docs/`, not from the repo's `docs/`
 * folder: Render builds this app with `rootDir: admin`, so anything above
 * that directory is outside the deployed tree. `prebuild` copies it in, so
 * `docs/mcp-connector.md` stays the single source and cannot drift from a
 * second copy committed here.
 *
 * A Server Component on purpose -- the file is read once on the server and
 * only HTML reaches the browser, so no markdown parser ships to the client.
 */

const DOC = {
  file: "mcp-connector.md",
  pdf: "/docs/mcp-connector.pdf",
  title: "The SAADAA Analytics connector for Claude",
  blurb: "Connecting the read-only MCP connector, and how to prompt it so the answers are defensible.",
};

/** Heading text -> the slug ReactMarkdown would not give us otherwise. */
function slug(children: React.ReactNode): string {
  return String(children)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export const metadata = {
  title: "Documentation",
  description: DOC.blurb,
};

export default async function DocsPage() {
  let markdown: string | null = null;
  try {
    markdown = await readFile(path.join(process.cwd(), "public", "docs", DOC.file), "utf8");
  } catch {
    markdown = null;
  }

  // Everything above the first horizontal rule is the lead, which the page
  // header below already states. Dropping it avoids saying it twice.
  const body = markdown?.includes("\n---\n")
    ? markdown.slice(markdown.indexOf("\n---\n") + 5)
    : markdown;

  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-8">
      <header className="mb-8 border-b border-border-primary pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight text-text-primary">{DOC.title}</h1>
            <p className="mt-1.5 max-w-2xl text-sm text-text-secondary">{DOC.blurb}</p>
          </div>
          <a
            href={DOC.pdf}
            download
            className="shrink-0 rounded-md border border-border-primary bg-bg-white px-3.5 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-bg-muted"
          >
            ↓ Download PDF
          </a>
        </div>
      </header>

      {body === null ? (
        <p className="rounded-md border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-text">
          The documentation file is missing. It is copied in by the <code>prebuild</code> step from{" "}
          <code>docs/{DOC.file}</code> at the repository root.
        </p>
      ) : (
        <article className="text-[14.5px] leading-relaxed text-text-primary">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h2 className="mt-10 border-b border-border-primary pb-2 text-xl font-semibold tracking-tight">
                  {children}
                </h2>
              ),
              h2: ({ children }) => (
                <h2
                  id={slug(children)}
                  className="mt-10 scroll-mt-6 border-b border-border-primary pb-2 text-lg font-semibold tracking-tight"
                >
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3 id={slug(children)} className="mt-7 scroll-mt-6 text-[15px] font-semibold">
                  {children}
                </h3>
              ),
              a: ({ href, children }) => (
                <a href={href} className="text-text-link underline underline-offset-2">
                  {children}
                </a>
              ),
              ul: ({ children }) => <ul className="my-3 list-disc space-y-1 pl-6">{children}</ul>,
              ol: ({ children }) => <ol className="my-3 list-decimal space-y-1 pl-6">{children}</ol>,
              hr: () => <hr className="my-9 border-border-soft" />,
              // Markdown paths are relative to docs/, which prebuild copies
              // to public/docs/. The page lives at /user/docs, so a bare
              // relative src would resolve against /user/ and 404.
              img: ({ src, alt }) => (
                <figure className="my-5">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={typeof src === "string" && !/^(https?:|\/)/.test(src) ? `/docs/${src}` : (src as string)}
                    alt={alt ?? ""}
                    className="w-full rounded-md border border-border-primary"
                  />
                  {alt ? (
                    <figcaption className="mt-1.5 text-[12.5px] italic text-text-tertiary">{alt}</figcaption>
                  ) : null}
                </figure>
              ),
              // react-markdown wraps a lone image in <p>; a <figure> inside a
              // <p> is invalid and React will warn. Unwrap that case.
              p: ({ children }) => {
                const only = Array.isArray(children) ? children.filter((c) => c !== "\n") : [children];
                const isFigure =
                  only.length === 1 &&
                  typeof only[0] === "object" &&
                  (only[0] as { type?: unknown })?.type !== undefined &&
                  (only[0] as { props?: { alt?: unknown } })?.props?.alt !== undefined;
                return isFigure ? <>{children}</> : <p className="my-3">{children}</p>;
              },
              // A quoted block in this document is always a caution, never a
              // citation -- so it reads as one.
              blockquote: ({ children }) => (
                <blockquote className="my-4 rounded-r-md border-l-[3px] border-warning-border bg-warning-bg px-4 py-2.5 text-[14px] text-text-primary">
                  {children}
                </blockquote>
              ),
              table: ({ children }) => (
                <div className="my-4 overflow-x-auto rounded-md border border-border-primary">
                  <table className="w-full border-collapse text-[13px]">{children}</table>
                </div>
              ),
              thead: ({ children }) => <thead className="bg-bg-muted">{children}</thead>,
              th: ({ children }) => (
                <th className="border-b border-border-primary px-3 py-2 text-left font-semibold text-text-primary">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border-b border-border-soft px-3 py-2 align-top text-text-primary">{children}</td>
              ),
              // Inside a fenced block the chip styling has to go: a light
              // pill on the dark <pre> reads as a nested box. react-markdown
              // gives fenced code a `language-*` class and inline code none,
              // which is the only thing that distinguishes them here.
              code: ({ className, children }) => {
                const fenced = typeof className === "string" && className.includes("language-");
                return fenced ? (
                  <code className={className}>{children}</code>
                ) : (
                  <code className="rounded bg-bg-muted px-1.5 py-0.5 font-mono text-[0.86em] text-text-primary">
                    {children}
                  </code>
                );
              },
              pre: ({ children }) => (
                <pre className="my-4 overflow-x-auto rounded-md bg-slate-900 p-4 font-mono text-[12.5px] leading-relaxed text-slate-100">
                  {children}
                </pre>
              ),
            }}
          >
            {body}
          </ReactMarkdown>
        </article>
      )}
    </div>
  );
}
