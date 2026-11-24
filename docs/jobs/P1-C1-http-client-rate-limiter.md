# P1-C1 · Safe HTTP client and rate limiter

- **Agent:** crawler agent (Sonnet) · **Status:** draft, waiting for owner approval and answers below
- **Design sections:** Crawler → Rate limits, Safety rules, Invalid requests; Implementation → Backend 2

## Goal

Fill in the E0-c stubs so every GGG request goes through one safe path: circuit breaker → daily budget → shared limiter (≤ 80% of every rule, spread evenly) → request with the agreed User-Agent → limiter updated from the response headers → any 429 trips the breaker and alerts Discord. Tested only against recorded headers; never talks to GGG.

## Files

`backend/crawler/**` only (plus a migration request to the backend agent through the orchestrator if limiter state goes into Postgres).

## Inputs and outputs

- Inputs: response headers `X-Rate-Limit-Policy`, `X-Rate-Limit-Rules`, `X-Rate-Limit-<Rule>`, `X-Rate-Limit-<Rule>-State`, `Retry-After`; config `contact_email`, `project_url`.
- Output: `SafeHttpClient.get()` returning an `httpx.Response`, or raising `CircuitOpenError`, `DailyBudgetExceededError`, `RateLimitedError`.

## Acceptance tests (all offline)

1. Header parsing: recorded header sets for the three policies (values from `MEASURED_LIMITS`), multiple rules, active penalties, missing headers.
2. Limiter: with a fake clock, never exceeds 80% of any rule over any window; requests are spread evenly (no bursts); follows tightened live limits immediately.
3. Budget: the 1,701st character in a day is refused; restart does not reset it (if persisted); no constructor or setting can raise 1,700.
4. Breaker: a 429 stops all further requests for `Retry-After` (default 3,600 s), calls `send_alert` once, and stays open across restart (if persisted).
5. User-Agent: exact format from `shared/user-agents.md`; refuses to send any GGG request while contact email or project URL is empty.
6. Client: uses an injectable `httpx` transport (`MockTransport`) so tests never open a socket.

## Safety rules

All of section "Safety rules" apply. Constants stay hard-coded (`constants.py`).

## Open questions for the owner

1. **Sharing the limiter across processes** (crawler loop, validation job, smoke tests):
   (a) State in Postgres (one row per policy/rule + an advisory lock): every job process shares it and it survives restarts. Needs a small table from P1-B1. *(recommended)*
   (b) One long-running crawler process; every other job asks it to send requests. Simpler limiter, but validation and smoke tests must talk to that process.
   (c) A lock file on disk. Simple, but fragile if a process dies holding it.
2. **Sync or async client:** (a) sync `httpx.Client`, one request at a time (requests are spaced seconds apart anyway) *(recommended)*; (b) async.
3. **Which limit wins:** (a) 80% of `min(live header limit, measured limit)`, so the crawler never speeds up if GGG raises limits *(recommended)*; (b) 80% of the live header limit only.
4. **Budget unit and day:** (a) 1 unit per character (items + tree), charged when its items request is sent; day = UTC calendar day *(recommended)*; (b) count requests instead; (c) rolling 24 h.
5. **Persist breaker and budget state:** (a) yes, same store as question 1 *(recommended)*; (b) in memory only.

## Done when

Checks pass (`pytest backend/crawler`, `ruff`), the reviewer passes it, and the orchestrator has run **no** live request (the first live smoke test is a separate, owner-approved step).
