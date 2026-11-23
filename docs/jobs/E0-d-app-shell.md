# E0-d · App shell

- **Agent:** frontend and overlay agent (Sonnet)
- **Approved by owner:** 2026-11-23 ("Yes, implement E0")
- **Design sections:** Implementation → Frontend → Requirements, Build order 1 (skeleton); What the user sees

## Goal

A Tauri v2 + Svelte 5 + TypeScript + Vite app in `app/` with the main window, side menu, four empty screens, the dark theme from the mock-ups, the three official plugins registered, and Vitest set up. Surface only.

## Files you may create or edit

- `app/**` only (the folder exists and is empty).

## What to build

1. **Project**: Vite + Svelte 5 + TypeScript (plain Svelte, **not SvelteKit**; no router library: the side menu switches a screen state), Tauri v2 in `app/src-tauri/`, pnpm. You may use `create-tauri-app` non-interactively or set it up by hand; remove template demo content (greet command, logos).
   - `productName`: `ELO`; window title `ELO — Exile Loot Observer`; main window about 1100 × 720, min 900 × 600.
   - `identifier`: `com.exilelootobserver.elo` (provisional, flagged to the owner).
   - Version `0.0.1`.
2. **Plugins** (official Tauri v2): `global-shortcut`, `clipboard-manager`, `store`, registered in `src-tauri/src/lib.rs`, their JS packages added, minimal capability permissions in `src-tauri/capabilities/default.json`. No updater plugin yet. No overlay window yet. No shortcuts registered yet.
3. **Theme**: `src/styles/theme.css` with CSS custom properties taken from the mock-ups:

   | Token | Value | Use |
   | --- | --- | --- |
   | `--bg` | `#0B0D10` | app background |
   | `--surface` | `#161A21` | panels, cards |
   | `--surface-input` | `#0F1217` | inputs |
   | `--border` | `#2A303B` | default borders |
   | `--border-strong` | `#3A414E` | buttons, NO BUYER verdict background |
   | `--text` | `#E8EAED` | primary text |
   | `--text-2` | `#C9CED6` | secondary text |
   | `--text-muted` | `#A3A9B5` | labels, roll tiers |
   | `--text-faint` | `#8D94A1` | greyed mods, hints |
   | `--accent` | `#9CC3FF` | links, primary button |
   | `--accent-hover` | `#C6DBFF` | link hover |
   | `--keep` | `#4CC38A` | KEEP |
   | `--price-check` | `#F0B455` | PRICE CHECK |
   | `--price-check-border` | `#5A4826` | warning chip border |
   | `--demand-tier` | `#F2C66D` | S / A / B letters |
   | `--danger` | `#F28B82` | corrupted, errors |

   Text on KEEP / PRICE CHECK / accent backgrounds uses `--bg`. Radii: 8px controls, 12px panels. Fonts: Inter (body), Space Grotesk (headings), JetBrains Mono (regex / code), **bundled locally** via `@fontsource` packages (the app must work offline; no Google Fonts requests).
4. **Layout**: `App.svelte` with a left side menu: What to farm, Stash search, Check an item, Data and settings. Each screen is a component in `src/screens/` showing its title and a one-line "Coming in Phase N" note (What to farm: 4, Stash search: 4, Check an item: 2, Data and settings: 4). The Data and settings screen also shows, as static text: "This product isn't affiliated with or endorsed by Grinding Gear Games in any way.", "ELO supports Path of Exile in windowed fullscreen and the English game client only.", and a credit line "Stash search fragments by poe.re" linking to https://poe.re.
5. **Empty module folders** with an `index.ts` holding only a comment saying what goes there and that its types wait for the snapshot schema in `shared/schema`: `src/lib/snapshot/`, `src/lib/parser/`, `src/lib/scoring/`, `src/lib/stash-search/`.
6. **Vitest**: config, `pnpm test` script, and one placeholder test (`it.todo`) per lib folder.
7. **`app/README.md`**: owner (frontend and overlay agent), how to run (`pnpm install`, `pnpm tauri dev`), the Awakened PoE Trade MIT reuse note (parser comes later; licence notice must be kept with copied code).

## Hard rules

- No requests to GGG, poe.re or any game website, at build or run time.
- Do not copy code from poe.re / poe-vendor-string (AGPL).
- No git write commands. No Docker. Do not read `.env`.
- Do not run `pnpm tauri dev` or `pnpm tauri build` (no windows, no installers).
- If anything here is unclear or leaves more than one reasonable choice, stop and report back instead of choosing.

## Checks (definition of done)

In `app/`:
1. `pnpm install` succeeds.
2. `pnpm check` (svelte-check + tsc) reports no errors.
3. `pnpm build` (Vite build) succeeds.
4. `pnpm test` runs (todos only).
5. In `app/src-tauri/`: `cargo check` succeeds (first build can take several minutes; run it in the background if needed).

Report back: files created, commands run and their results, versions of Tauri / Svelte / Vite installed, and anything you were unsure about.
