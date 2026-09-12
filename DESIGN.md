# McFox Health Dashboard Design Contract

This file is the design contract for frontend/UI work in this repo. It is
inspired by Google's `design.md` pattern: agents should read it before changing
screens, components, theme tokens, copy, or interaction states.

Product direction and scope gates live in [PRISM_PRODUCT_ARCHITECTURE.md](PRISM_PRODUCT_ARCHITECTURE.md). Chat is the current PRISM Coach interface; this file governs the deployed McFox UI and does not authorize a frontend redesign during foundation work or PR5.

## Purpose

- Product: personal health and fitness dashboard for one primary user.
- Audience: Mateo, checking the app mostly on a phone, often quickly.
- Primary surfaces: Today, Train, Fuel, Progress, bottom sheets, coach chat.
- Design intent: dense, calm, high-signal, dark, data-forward, and tactile.
- Non-goals: marketing pages, generic wellness aesthetics, decorative heroes,
  beige wellness palettes, or explain-the-app instructional panels.

## Source Of Truth

- Token source: [src/theme.ts](src/theme.ts).
- Canonical palette: `zine` / "Newsprint".
- Alternate palettes: `lime` and `graphite`; keep them functional, but do not
  let them redefine the app's default visual language.
- Component source: [src/components](src/components).
- Screen source: [src/screens](src/screens).
- Product context: [PROJECT-OVERVIEW.md](PROJECT-OVERVIEW.md).

## Tokens

```yaml
tokens:
  canonicalTheme: zine
  color:
    bg: "#050505"
    surface: "#0d0d0d"
    surfaceRaised: "#141414"
    surfaceActive: "#1c1c1c"
    surfaceStrong: "#272727"
    border: "rgba(255,255,255,0.06)"
    text: "#fafafa"
    textMuted: "#bdbdbd"
    textSubtle: "#7a7a7a"
    textFaint: "#4a4a4a"
    primary: "#fff45c"
    primaryDim: "rgba(255,244,92,0.10)"
    warning: "#ff5722"
    warningDim: "rgba(255,87,34,0.10)"
    danger: "#ff3b30"
    dangerDim: "rgba(255,59,48,0.10)"
    cyan: "#ffffff"
    cyanDim: "rgba(255,255,255,0.08)"
    purple: "#ff9ec7"
    purpleDim: "rgba(255,158,199,0.10)"
    yellow: "#fff45c"
    yellowDim: "rgba(255,244,92,0.10)"
  typography:
    fontFamily: "'Outfit', system-ui, sans-serif"
    monoFamily: "'JetBrains Mono', monospace"
    display: "compact, heavy, used sparingly for metrics"
    labels: "uppercase, small, generous positive letter spacing"
  radius:
    button: 10-14
    panel: 14-20
    sheet: "24px 24px 0 0"
  layout:
    maxWidth: 520
    outerPadding: 14
    safeArea: true
```

`src/theme.ts` is the executable source of truth. Update this file when changing
design intent or contracts, but update `src/theme.ts` when changing actual token
values.

## Layout

- Phone-first. The main shell is a centered, max-width 520px app column.
- Use fixed bottom navigation with safe-area padding; content must clear the
  tab bar, center FAB, and iOS home indicator.
- Prefer compact sections and repeatable panels over large hero blocks.
- Do not put cards inside cards. Repeated list items, modals, and functional
  panels are valid card surfaces.
- Fixed-format elements such as rings, charts, tabs, and metric grids need
  stable dimensions so labels and loading states do not resize the layout.

## Components

- `Panel`: default grouped surface. Use for meaningful health data clusters,
  not for page-level wrappers.
- `Sheet`: bottom-sheet modal. Closed sheets must not remain focusable or
  interactive; focus returns to the opener when the sheet closes.
- `TabBar`: persistent app navigation. Keep labels short and predictable.
- `Btn`: primary actions use `primary`; secondary actions use the raised
  surface. Button labels should be concrete verbs.
- `Chip`: status or context only. Do not use chips as long explanatory copy.
- Rings and charts: show current value and target context together. Avoid
  unlabeled color-only meaning.

## Interaction States

- Loading: short, quiet, and scoped to the active tab or panel.
- Empty: explain the missing data source and offer the next useful action.
- Error: visible to the user, with retry when possible. Do not leave an
  infinite skeleton after an API error.
- Failed write: keep the input open, preserve the user's draft, show a concise
  error, and allow retry.
- Disabled: visibly muted and non-interactive.
- Optimistic updates: only close or clear user input after the write succeeds.

## Accessibility

- Closed modals/sheets must be unmounted or hidden from focus and screen
  readers.
- Preserve keyboard escape-to-close behavior for sheets.
- Maintain readable contrast on all palettes.
- Interactive targets should be thumb-friendly, generally 40px or larger when
  space allows.
- Use `aria-pressed`, `aria-expanded`, labels, and dialog roles where the UI
  state is not obvious from text.
- Respect reduced-motion needs when adding new animation.

## Content

- Voice: direct, low-drama, plain English.
- Units: show health units inline (`bpm`, `kcal`, `g`, `oz`, `m`, `h`).
- Dates: user-facing day boundaries are America/Los_Angeles, not device-local
  time.
- Labels must match backend semantics. If a metric is computed over 7 nights,
  the UI says 7 nights.

## Verification

- Run `npm run typecheck` after TypeScript changes.
- Run `npm run build` before shipping frontend changes.
- For UI changes, run local browser QA at mobile width and confirm no hidden
  sheets/dialogs remain in the accessibility tree.
- When design.md tooling is installed, run
  `npx @google/design.md lint DESIGN.md`.

