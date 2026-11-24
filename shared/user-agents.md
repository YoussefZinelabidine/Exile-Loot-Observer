# User-Agent strings

Every request ELO sends to an outside service carries an identifying User-Agent. The format is fixed here; the values come from config, never from code:

| Placeholder | Source |
| --- | --- |
| `<version>` | Package version (backend: `pyproject.toml`; app: `tauri.conf.json`) |
| `<project_url>` | `ELO_PROJECT_URL` in the server `.env` |
| `<email>` | `ELO_CONTACT_EMAIL` in the server `.env`: the **project account's** email, never a personal one |

## Server side (home server, Python)

| Service | User-Agent | Notes |
| --- | --- | --- |
| GGG website (leagues, ladder, character pages, trade search for validation) | `ELO/<version> (+<project_url>; contact: <email>)` | **Required.** `backend.crawler` refuses to send any GGG request while `ELO_CONTACT_EMAIL` or `ELO_PROJECT_URL` is empty. |
| GGG official API, once an OAuth app is approved | `OAuth <client_id>/<version> (contact: <email>)` | Exact format from GGG's developer docs. `<client_id>` from the server `.env`. Not used before approval. |
| RePoE (`repoe-fork.github.io`) | `ELO/<version> (+<project_url>; contact: <email>)` | |
| poe.re (`data.poe.re`) | `ELO/<version> (+<project_url>; contact: <email>)` | poe.re asks for `<name>/<version> (<url>)`; ours adds `+` and the contact inside the brackets, which keeps that shape. |
| poe.ninja economy API | `ELO/<version> (+<project_url>; contact: <email>)` | Documented endpoints only; cached. |
| GitHub API (publishing snapshots to Releases) | `ELO/<version> (+<project_url>; contact: <email>)` | GitHub requires a User-Agent on API calls. |
| Discord webhook | library default | Not a public service request. |

If the contact email or project URL is missing, the server jobs may still run local work (aggregation, snapshot build) but must not contact GGG. Other services may be contacted with `ELO/<version> (+<project_url>)` or, when the URL is also missing, must be skipped.

## GitHub Actions (daily upstream check)

| Service | User-Agent | Notes |
| --- | --- | --- |
| RePoE, poe.re, GGG's skill-tree export repository on GitHub | `ELO-upstream-check/<version> (+<project_url>; contact: <email>)` | Values from repository variables. **Never** any request to GGG's website or API from Actions. |

## App side (players' PCs, TypeScript/Rust)

| Service | User-Agent | Notes |
| --- | --- | --- |
| GitHub Releases (snapshot and app update downloads) | `ELO/<version> (+<project_url>)` | No email from players' PCs. `<project_url>` is compiled into the app at build time. |
| Official trade site | the player's own browser | "Open trade search" opens the player's browser; the app sends nothing itself. |

The app never contacts GGG, poe.re, RePoE or poe.ninja: everything it needs comes in the snapshot.

## Rules

- One User-Agent per product; never rotate or randomise it.
- Never put a player's or the owner's personal account name in a User-Agent.
- The crawler's `build_user_agent()` (`backend/crawler/user_agent.py`) implements the GGG row; the backend uses the same format for the other server rows.
