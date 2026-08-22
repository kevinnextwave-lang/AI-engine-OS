# @ai-search-growth-os/ui

Shared shadcn/ui primitives (`Button`, `Input`, `Label`, `Card`, `Sheet`, `DropdownMenu`, `Avatar`, `Separator`) and the `cn()` helper, plus the Tailwind v4 theme in `src/styles.css`.

The package ships TSX source; `apps/web` transpiles it via `transpilePackages` in `next.config.ts` and scans it for Tailwind classes with `@source` in its global stylesheet.

To add more shadcn components, run `npx shadcn add <name>` inside `apps/web` and move the generated file here (swap `@/lib/utils` for `./utils`), then export it from `src/index.ts`.
