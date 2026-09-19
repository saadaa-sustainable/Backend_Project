This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

Start this project's FastAPI backend from the repository root:

```bash
SCHEDULER_ENABLED=false .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8002
```

This local UI backend does not start a second ingestion scheduler. Existing
ingestion jobs can continue in their own process.

Set the matching URL in `admin/.env.local` (Next.js reads this file, not the
repository-root `.env`):

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://localhost:8002
```

Then run the frontend from `admin/`:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

If an analytics page still reports a backend connection error after a restart,
check `lsof -nP -iTCP:8002 -sTCP:LISTEN` for an older server on the same port.
An old process bound to `127.0.0.1` can receive browser requests even when another
server is listening on `0.0.0.0`. Give the UI backend its own free port and update
`NEXT_PUBLIC_API_BASE_URL` to match. Refresh the browser after changing this URL;
restart Next.js if it still requests the previous port.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
