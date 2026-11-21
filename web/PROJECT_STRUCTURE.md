# Frontend Project Structure

Next.js 16 + React 19 + TypeScript + Tailwind CSS 4

## Directory Tree

```
web/
├── public/                     # Static assets
│   ├── file.svg
│   ├── globe.svg
│   ├── next.svg
│   ├── vercel.svg
│   └── window.svg
│
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── globals.css         # Global styles & Tailwind
│   │   ├── layout.tsx          # Root layout
│   │   └── page.tsx            # Home page
│   │
│   ├── components/             # React components
│   │   ├── ui/                 # shadcn/ui components
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── input.tsx
│   │   │   └── progress.tsx
│   │   │
│   │   ├── animation-preview.tsx  # Animated sprite frame preview
│   │   └── mic-button.tsx         # Microphone button component
│   │
│   └── lib/                    # Utilities & services
│       ├── api.ts              # API client
│       └── utils.ts            # Helper utilities (cn function)
│
├── components.json             # shadcn/ui configuration
├── eslint.config.mjs           # ESLint configuration
├── next.config.ts              # Next.js configuration
├── next-env.d.ts               # Next.js TypeScript declarations
├── package.json                # Dependencies & scripts
├── postcss.config.mjs          # PostCSS configuration
├── tsconfig.json               # TypeScript configuration
└── README.md                   # Project README
```

## File Descriptions

### Source Files (`src/`)

| File | Purpose |
|------|---------|
| `app/layout.tsx` | Root layout with fonts and metadata |
| `app/page.tsx` | Main application page |
| `app/globals.css` | Global CSS with Tailwind imports |
| `components/animation-preview.tsx` | Animated sprite frame preview with auto-play |
| `components/mic-button.tsx` | Voice recording microphone button |
| `components/ui/*.tsx` | Reusable UI primitives (shadcn/ui) |
| `lib/api.ts` | Backend API client functions |
| `lib/utils.ts` | Utility functions including `cn()` for classnames |

### Configuration Files

| File | Purpose |
|------|---------|
| `next.config.ts` | Next.js settings |
| `tsconfig.json` | TypeScript compiler options |
| `components.json` | shadcn/ui component settings |
| `postcss.config.mjs` | PostCSS + Tailwind processing |
| `eslint.config.mjs` | ESLint linting rules |

## Tech Stack

- **Framework**: Next.js 16 (App Router)
- **React**: 19.2.1
- **TypeScript**: 5.x
- **Styling**: Tailwind CSS 4
- **UI Components**: shadcn/ui + Radix UI
- **Icons**: Lucide React

## Scripts

```bash
pnpm dev      # Start development server
pnpm build    # Production build
pnpm start    # Start production server
pnpm lint     # Run ESLint
```
