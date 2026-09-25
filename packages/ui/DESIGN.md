# AI-engine-OS Design System

The written reference for the app's visual language. The machine-readable
source of truth is `packages/ui/src/styles.css` (all tokens); this file
explains the scales, when to use what, and the component conventions.

Feel: premium, calm, intelligent, trustworthy, enterprise-ready. That means
one accent color, soft status tints, quiet shadows, no gradients, no
glassmorphism, no decorative animation. Every visual choice must communicate
information; anything that doesn't gets removed.

---

## 1. Color

All color goes through semantic tokens. Never use raw Tailwind palette
classes (`text-red-500`, `bg-emerald-600`, `border-sky-200`…) or hex/oklch
literals in app code — light/dark theming and future rebrands depend on it.

### Surfaces & text

| Token | Class examples | Use |
| --- | --- | --- |
| `background` | `bg-background` | Page background |
| `card` | `bg-card` | Cards, tiles, tables-in-cards |
| `popover` | `bg-popover` | Dropdowns, tooltips, popovers (elevated surface) |
| `sidebar` | `bg-sidebar` | Navigation rail only |
| `border` / `input` | `border`, `border-input` | Hairlines, input outlines |
| `foreground` | `text-foreground` | Primary text (default) |
| `muted-foreground` | `text-muted-foreground` | Secondary text, labels, captions — AA on both surfaces |
| `muted` / `secondary` / `accent` | `bg-muted` … | Neutral fills: skeletons, hovers, subtle chips |

### Accent

`primary` (deep indigo) is the **only** saturated hue outside status colors.
It marks: primary action per view, active nav item (`sidebar-accent` tint),
links, focus rings (`ring`), selected states, and the brand series in charts
(`chart-brand`). If two things on one screen are indigo and both aren't
"the thing to do / where you are / you", one of them is wrong.

### Status

| Token | Meaning | Typical pairing |
| --- | --- | --- |
| `success` | Completed, healthy, positive delta | `text-success`, `bg-success/10 border-success/20` |
| `caution` | Medium severity, middling score (60–79) | amber |
| `warning` | High severity, weak score (<60) | orange |
| `destructive` | Critical, failed, negative delta, deletion | red |
| `info` | Queued, informational, "new" | sky |

Status fills are always **soft**: `bg-{tone}/10` + `border-{tone}/20` +
`text-{tone}` (see Badge). Saturated chips are reserved for nothing.

Score thresholds are app-wide and fixed: **≥ 80 success, 60–79 caution,
< 60 warning**. Don't invent per-page thresholds.

### Charts

Brand entity always uses `chart-brand`. Competitors use the fixed ordered
palette `chart-competitor-1…4` so the same entity keeps the same color in
every chart on a page. Gridlines `chart-grid`, reference/average lines
`chart-reference`. No other colors in charts.

---

## 2. Typography

Font: **Inter** (loaded in `apps/web/src/app/layout.tsx` via `next/font`,
exposed as `--font-inter`; falls back to the system stack). Mono for
model/technical identifiers only.

| Role | Classes |
| --- | --- |
| Page title | `text-2xl font-semibold tracking-tight` |
| Section title | `text-lg font-semibold` |
| Card title | `text-base font-semibold` (CardTitle) |
| Body | `text-sm` |
| Secondary text | `text-sm text-muted-foreground` |
| Caption / label | `text-xs text-muted-foreground` (`font-medium tracking-wide` for tile labels) |
| Metric number | `text-2xl font-semibold tracking-tight tabular-nums` (`text-3xl` for the hero tile) |
| Table text | `text-sm`; numeric cells `tabular-nums text-right` |

Nothing bigger than `text-3xl` anywhere. Tables and stat-tile values get
tabular figures automatically via `data-slot` rules in styles.css.

Labels/statuses are **Sentence case** app-wide (`label()` in
`components/section/primitives.tsx` enforces it). No ALL-CAPS headings.

---

## 3. Spacing

Tailwind's 4px scale, restricted to these steps: **1 (4px), 2 (8px),
3 (12px), 4 (16px), 6 (24px), 8 (32px)**.

- Inside a component (icon↔text, badge padding): 1–2
- Between related elements (label→value, form field stack): 1–3
- Card padding: 4 (dense/tile) or 6 (standard)
- Between cards / grid gaps: 4
- Between page sections: 6–8
- Page gutter: `px-4 md:px-6`, content max-width per layout

---

## 4. Border radius

Base token `--radius: 0.625rem` (10px).

| Element | Class |
| --- | --- |
| Cards, tables, drawers, empty states | `rounded-xl` (14px) |
| Modals / dialogs | `rounded-xl` |
| Buttons, inputs, dropdown items | `rounded-md` (8px) |
| Badges, status chips | `rounded-md` |
| Progress bars, avatars | `rounded-full` |

Nothing beyond `rounded-xl`. No `rounded-3xl`, no per-corner radii.

---

## 5. Shadows

Exactly two, defined as tokens:

- `shadow-card` — `0 1px 2px oklch(0 0 0 / .05)`: cards and tiles. Borders,
  not shadows, do the separating; this only lifts a card off the page a hair.
- `shadow-overlay` — `0 10px 30px -10px oklch(0 0 0 / .2)`: things that float
  (dropdowns, popovers, sheets, dialogs, tooltips).

No colored shadows, no glows, no inner shadows.

---

## 6. Motion

Only functional transitions: overlay enter/exit (sheet slide 200–300ms,
dialog/tooltip fade+zoom via `tw-animate-css`), and `transition-colors` on
interactive hovers. Nothing loops, nothing bounces, nothing animates on
scroll. Skeletons pulse — that's the loading affordance, not decoration.

---

## 7. Components (`@ai-search-growth-os/ui`)

Everything below is exported from `packages/ui/src/index.ts`. App code
composes these; it does not re-create them per page.

**Button** — variants: `default` (indigo, max one per view), `secondary`,
`outline`, `ghost`, `destructive`, `link`. Sizes `sm`/`default`/`lg`/`icon`.
Destructive actions confirm via `ConfirmDialog`, never `window.confirm`.

**Card** — `Card/CardHeader/CardTitle/CardDescription/CardContent/CardFooter`.
`rounded-xl border bg-card shadow-card`. Don't nest cards.

**Badge / StatusBadge** — soft tints only. Domain statuses go through
`StatusBadge` (`components/section/primitives.tsx`), which maps status →
variant (`critical/high/medium/low/info/success/muted`) and Sentence-cases
the label. New statuses get added to that map, not styled inline.

**MetricCard / MetricCardSkeleton** — THE metric/KPI card. Anatomy, top to
bottom: uppercase label + status (tone dot + word), big value(+unit), delta
("↑ 8 points · vs previous audit" — **real stored history only, never an
invented trend**), an optional progress bar *or* sparkline (sparklines also
only from real series with ≥2 points), one-line meaning, context line
(n =, provenance), and an action slot (pages pass the app-level
`MetricAction` link, "View analysis →"). Everything after the value is
optional — omit what the data doesn't support. `size="hero"` for a page's
headline number. No bespoke KPI markup in pages.

**AiInsight / AiActionList** — THE "AI Recommendation" pattern, used
everywhere the product turns measured data into advice. Anatomy: sparkles
eyebrow, headline (**what I found** — one plain statement of a measured
fact), *Why this matters* (mechanism, cautious language — never an outcome
claim like "will increase traffic by N%"), *Recommended action* (sentence
or `AiActionList`), *Evidence* (the exact numbers behind the headline), and
a footer with a provenance line ("From the technical SEO audit · 2 h ago")
plus the CTA. App pages build content with the pure builders in
`apps/web/src/lib/ai-insights.ts` and render via `AiInsightCard`; a surface
whose data doesn't exist renders nothing rather than an invented insight.

**Callout** — inline notices: `info | success | warning | error | sample`.
`sample` is the standard "Sample data" notice (never call it "mock").

**EmptyState** — one empty-state anatomy, three tones: `invitation`
(feature never used — explain + primary CTA; never looks like an error),
`neutral` (filter/search matched nothing), `error` (load failed — pair with
Retry).

**Table + DataTable** — tables live inside `rounded-xl border` wrappers;
numeric columns right-aligned tabular; `DataTable` handles the
loading (TableSkeleton) and empty states so pages don't.

**Tooltip / SimpleTooltip** — replaces native `title=`. `TooltipProvider`
is mounted once in the root layout; use `<SimpleTooltip label="…">` around
any icon-only control (icon-only buttons must also keep `aria-label`).

**AlertDialog / ConfirmDialog** — confirmation for destructive/irreversible
actions; `destructive` prop turns the confirm button red.

**SegmentedControl** — single-select view switches (time ranges, tabs-as-
filter). Radix ToggleGroup underneath; always pass `aria-label`.

**Sheet** — side drawers (detail views, mobile nav). Slides in/out, uses
`shadow-overlay`; content areas scroll (`overflow-y-auto`).

**Progress** — score/percentage bars; tint via `indicatorClassName` with the
score-threshold tones above.

**Skeleton / TableSkeleton / MetricCardSkeleton** — loading states mirror the
layout they replace; never a spinner-only page.

**Inputs** — `Input`, `Label`, `NativeSelect`: `rounded-md border-input`,
focus ring in `ring` (indigo). Labels always visible, not placeholder-only.

### Layout conventions

- Sidebar: `bg-sidebar`, sticky full-height, active item
  `bg-sidebar-accent text-sidebar-accent-foreground` — the only nav accent.
- One `default` (indigo) button per view; supporting actions are
  `outline`/`ghost`.
- Dashboard pattern: hero MetricCard → supporting MetricCard row → charts →
  tables. Data always carries its context (n=, period, source).

---

## 8. Adding to the system

1. New color/need → add a semantic token to `styles.css` (both themes, and
   the `@theme inline` mapping), then use its class. Never inline a color.
2. New reusable component → build it in `packages/ui/src`, export it from
   `index.ts`, document it here. If a pattern appears on two pages, it
   belongs in the package.
3. Never add: gradients, glassmorphism/backdrop-blur, neon hues, looping
   animation, radius beyond `xl`, shadows beyond the two tokens, type beyond
   `text-3xl`.
