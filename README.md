# ELO (Exile Loot Observer)

A free Windows desktop tool for **Path of Exile 1** that tells you which mods on a rare item are in demand, based on what popular builds on the current softcore trade league ladder actually wear. It is not a price checker.

- **What to farm**: the most sought-after mods per item type, overall or per build.
- **Check an item**: hover a rare item in game and press a hotkey for a verdict (KEEP / PRICE CHECK / NO BUYER).
- **Stash search**: build a stash search string from a build's key mods.

## Repository layout

| Folder | What | Owner |
| --- | --- | --- |
| `backend/` | Python server jobs: importers, normaliser, classifier, aggregation, snapshot builder | Backend agent |
| `backend/crawler/` | Safe HTTP client, shared rate limiter, ladder and character crawler | Crawler agent |
| `app/` | Tauri v2 + Svelte 5 + TypeScript desktop app and overlay | Frontend and overlay agent |
| `shared/` | Snapshot JSON Schemas and golden test fixtures used by both sides | Orchestrator |
| `docs/` | Decisions and job specs | Orchestrator |

`specs/` (design documents) is kept locally and is not tracked.

## Development setup (Windows dev PC)

Requirements: Python 3.12+, Node.js LTS + pnpm, Rust stable, Microsoft C++ Build Tools, WebView2, Docker (local PostgreSQL 16+).

```powershell
# Backend (from the repo root, using the root .venv)
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# App
cd app
pnpm install
pnpm tauri dev
```

Copy `.env.example` to `.env` and fill in the values. `.env` is never committed.

## Credits and notices

This product isn't affiliated with or endorsed by Grinding Gear Games in any way.

Stash search fragments come from [poe.re](https://poe.re)'s generated data, used under its data terms. Mod data and trade stat IDs come from [RePoE (repoe-fork)](https://github.com/repoe-fork/repoe). The item parser starts from [Awakened PoE Trade](https://github.com/SnosMe/awakened-poe-trade) (MIT licence; notice kept with the code).
