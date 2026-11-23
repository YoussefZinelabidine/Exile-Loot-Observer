# E0-c · Crawler surface

- **Agent:** crawler agent (Sonnet)
- **Approved by owner:** 2026-11-23 ("Yes, implement E0")
- **Design sections:** Crawler → Rate limits, Safety rules; Implementation → Backend → Build order 2

## Goal

The public surface of the crawler's safety layer: constants, data types, class and function signatures with docstrings, so Phase 1 can fill in the logic. Bodies raise `NotImplementedError` except where stated.

## Files you may create or edit

- `backend/crawler/**` only (a `README.md` already exists there; keep it).

Do not touch anything else. In particular `pyproject.toml`, `backend/__init__.py` and `backend/common/` are being written **in parallel** by the backend agent.

## Interfaces from the backend agent you may rely on

- `backend.common.config.get_settings()` → `Settings` with `contact_email: str | None`, `project_url: str | None`.
- `backend.common.alerts.send_alert(message: str, *, level: str = "error") -> None`.

Import them inside functions or at module level as you see fit, but your stubs must not *call* them at import time.

## What to build

1. **`constants.py`** (fully implemented, `typing.Final`):
   - `RATE_LIMIT_CAP_FRACTION = 0.8`
   - `DAILY_CHARACTER_MAX = 1700` (items + tree; comment: hard-coded, no setting can raise it)
   - `DEFAULT_RETRY_AFTER_SECONDS = 3600`
   - policy name constants: `POLICY_LADDER_VIEW = "ladder-view"`, `POLICY_CHARACTER = "backend-character-request-limit"`, `POLICY_ITEMS = "backend-item-request-limit"`
   - `MEASURED_LIMITS`: the 19 Nov 2026 measurements as data (per policy, list of `(max_hits, period_seconds)`): ladder-view `(5,5), (10,10)`; character `(15,60), (90,1800), (180,7200)`; items `(30,60), (90,1800), (180,7200)`. Comment that these are reference values only: the limiter always follows the live headers, and that the ladder `15:10` rule in HANDOFF is unconfirmed (open question).
2. **`errors.py`** (implemented): `CrawlerError`, `CircuitOpenError` (carries `retry_at`), `DailyBudgetExceededError`, `RateLimitedError` (429; carries `retry_after_seconds`).
3. **`rate_limit_headers.py`**: frozen dataclasses `RateLimitRule(max_hits, period_seconds, penalty_seconds)`, `RateLimitState(hits, period_seconds, active_penalty_seconds)`, `RulePair(rule, state)`, `PolicySnapshot(policy: str, rules: dict[str, list[RulePair]])` (key = rule name such as `ip`, `account`, `client`). Stub `parse_rate_limit_headers(headers: Mapping[str, str]) -> PolicySnapshot | None` with a docstring describing the header format: `X-Rate-Limit-Policy`, `X-Rate-Limit-Rules` (comma-separated rule names), `X-Rate-Limit-<Rule>` = `hits:period:penalty,...`, `X-Rate-Limit-<Rule>-State` = `hits:period:active_penalty,...`, plus `Retry-After`. Stub `parse_retry_after(headers) -> float | None`.
4. **`limiter.py`**: `class SharedRateLimiter` with stubbed methods `acquire(policy: str) -> None` (blocks until a request is allowed at ≤ 80% of every rule, spread evenly), `update_from_headers(snapshot: PolicySnapshot) -> None`, `on_rate_limited(retry_after_seconds: float | None) -> None`. Docstring must state: one instance shared by every crawler and validation job; how it is shared across processes is **an open question for Phase 1** (do not implement or choose a mechanism).
5. **`budget.py`**: `class DailyCharacterBudget` with stubbed `try_consume(n: int = 1) -> bool`, `remaining() -> int`; its constructor must not accept any maximum above `DAILY_CHARACTER_MAX` (implement just this guard: raise `ValueError` if a larger cap is passed).
6. **`circuit_breaker.py`**: `class CircuitBreaker` with stubbed `trip(retry_after_seconds: float | None, reason: str) -> None` (docstring: stops all jobs for at least Retry-After, default 1 h, and calls `send_alert`), `is_open() -> bool`, `retry_at() -> datetime | None`, `check() -> None` (raises `CircuitOpenError`).
7. **`user_agent.py`**: stub `build_user_agent(version: str, *, contact_email: str | None, project_url: str | None) -> str`. Docstring: final format not agreed yet (open question); must name the app and a contact email.
8. **`http_client.py`**: `class SafeHttpClient` (synchronous, wraps `httpx.Client`; mark "sync vs async is provisional" in the docstring) with stubbed `get(url: str, *, policy: str, params: Mapping[str, str] | None = None) -> httpx.Response`. Docstring lists the order of checks: circuit breaker → daily budget (character endpoints only) → limiter → request → update limiter from headers → on 429 trip breaker.
9. **`__init__.py`**: module docstring; re-export the main names.
10. **`tests/`**: `test_constants.py` (real asserts on the constant values and the budget cap guard) and one placeholder test module per stubbed module, each test marked `pytest.mark.skip(reason="Phase 1")` describing what it will check. A `tests/fixtures/README.md` saying recorded GGG responses go here (none yet).

## Hard rules

- **No requests to GGG or any website.** No live calls, not even to test.
- Do not open or read `.env`. No git write commands. No Docker commands. No database access.
- Constants must be plain module constants, not read from config or environment.
- If anything here is unclear or leaves more than one reasonable choice, stop and report back instead of choosing.

## Checks (definition of done)

From the repo root using `.venv\Scripts\python.exe`. If `pip install -e ".[dev]"` is not possible yet because the backend agent has not finished `pyproject.toml`, run the checks with `PYTHONPATH` set to the repo root and `pytest`/`ruff` installed in the venv, and say so in your report.
1. `python -m pytest backend/crawler -q`: constants tests pass, the rest skipped.
2. `python -m ruff check backend/crawler` reports nothing (if ruff config is missing, use defaults and say so).
3. `python -c "import backend.crawler"` works.

Report back: files created, commands run and their results, and anything you were unsure about.
