# Mateo Fitness Dashboard — Handoff

High-fidelity prototype for a personal performance dashboard. iPhone-sized,
dark theme, built in React via inline JSX (no build step — all files are
loaded through Babel Standalone at runtime).

## File map

```
Mateo Fitness Dashboard.html   Root. Mounts <App/> and wires all screens.
ios-frame.jsx                  iPhone bezel + status bar chrome.
theme.jsx                      Palette tokens (Lime, Sunset, Electric, Ice, Graphite).
data.jsx                       ALL mock data — replace with real API.
ui.jsx                         Shared primitives: Ring, Panel, Stat, Chip, Sparkline,
                                BarRow, ProgressBar, Sheet, SectionHead, TabBar, Btn.
screens1.jsx                   Today, Train screens.
screens2.jsx                   Fuel, Body, Coach screens.
trends.jsx                     Trends screen (30d metrics + correlations).
journal.jsx                    Morning check-in card + journal tag sheet.
modals.jsx                     Ring-detail sheet, Log Meal, Log Workout, Chat, Primer.
voice.jsx                      Voice input UI (demo only — no STT wired).
```

Components share scope through `Object.assign(window, {...})` at the bottom
of each file. If you port this to a bundler, replace those with proper
ES exports.

## What's real vs mocked

| Interactive                                                | Cosmetic only                                 |
| :--------------------------------------------------------- | :-------------------------------------------- |
| Tab navigation (persisted in localStorage)                 | Voice input button (animation only)           |
| Tap a ring → detail sheet                                  | Log Meal form (validates, doesn't persist)    |
| "What do these numbers mean?" primer sheet                 | Log Workout form (same)                       |
| Journal morning check-in (submit mutates module object)    | Chat uses `window.claude.complete()` — sandbox helper, WILL NOT EXIST in prod |
| Palette picker in Tweaks panel                             | Hydration "+ add" buttons (no state update)   |
| Week scrubber on Train screen                              | Supplement checkboxes (static)                |

Sparklines are computed from arrays in `data.jsx`. Bar charts the same.
Nothing comes from an API.

## Known shortcuts (fix before shipping)

1. **`JOURNAL_TODAY.submitted = true` mutates the module object directly**
   (see `journal.jsx` → `save()` in `JournalSheet`). Prototype convenience.
   Move to real state + API persistence.

2. **Chat LLM**: `modals.jsx → ChatModal` uses `window.claude.complete()`,
   a sandbox-only helper. Point at your LLM endpoint and stream the response.

3. **Palette tweaks** live in the `TWEAKS` object and persist via
   `__edit_mode_set_keys` postMessage — that's a host-specific protocol.
   In prod, move palette choice to user settings.

4. **Per-user data**: `MATEO`, `BASE`, `TODAY` are all hardcoded. These
   become API reads (most likely a single `GET /v1/today` payload + a
   `GET /v1/trends` payload for the Trends tab).

5. **Correlations**: `CORRELATIONS` in `data.jsx` is static dummy data.
   In prod, these are computed server-side from 30–60 days of journal
   tags × biometric deltas. The UI expects:
   `{ tag, metric, effect, unit, n, confidence: "high" | "medium" | "low", direction }`

6. **Date/time handling** is zero. `TODAY.dateFull` is a string literal.
   Swap to real Date objects and a timezone-aware formatter.

## Data contracts the screens expect

Today screen (`screens1.jsx` → `TodayScreen`) reads:
- `TODAY.recovery` (0–100)
- `TODAY.strain` (0–21 float) + `TODAY.strainTarget: { low, high, reason }`
- `TODAY.sleep: { score, hours, minutes, efficiency, deep, rem, core, awake }`
- `TODAY.sleepNeedTonight: { totalMin, bedtimeBy }`
- `TODAY.hrv`, `TODAY.rhr`, `BASE.hrv`, `BASE.rhr`
- `HRV_30D` (array of 30 numbers)
- `RECOVERY_WEEK` (array of 7 `{ d, date, rec, strain, tag, today }`)
- `TODAY.water`, `TODAY.waterGoal`

Trends screen reads `TRENDS_30D` (paired `{ cur, prev, unit, better }` for each metric)
and `TREND_SERIES` (30-entry sparkline arrays keyed by metric).

## Accessibility gaps

- No ARIA roles on the custom controls (rings, tabs, sheets).
- No focus management on modal open/close.
- Ring colors meet contrast but the label text at 9px is borderline.
  Consider min-size 11px when you port to production.

## Design tokens

Primary accent: defined per-palette in `theme.jsx`. The "Lime" default is
`#C6F85B`. Warn (strain/effort) is orange, Cyan is hydration/sleep,
Purple is REM, Yellow is mid-state. If you migrate to a token system,
these five roles are the full set used.

## Open questions for the PM

- When does the AI Coach chat need streaming vs. a single completion?
- Does the morning journal need to be blocking (like Whoop) or
  dismissible (like Oura)? Current design: dismissible card.
- Trends correlations — how many days before we show them? Current
  copy says 14, but the data pipeline may need 30+.
- Is the "Tweaks" palette picker a real feature or designer-only?
