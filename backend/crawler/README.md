# backend/crawler/

The only code allowed to send requests to GGG: safe HTTP client, the one shared rate limiter, circuit breaker, ladder crawler, character fetcher, home-side update monitor, adaptive sampling, and the request layer of the validation searches.

- **Owner:** crawler agent.
- **Safety rules (non-negotiable, design section "Crawler → Safety rules"):**
  - Hard cap at 80% of every measured rate limit.
  - Hard-coded daily maximum of 1,700 characters (items + tree); no setting can raise it.
  - One shared rate limiter for every crawler and validation job; requests spread evenly across each window.
  - Circuit breaker: any 429 stops all jobs for at least `Retry-After` (default 1 hour) and sends a Discord alert.
  - Logged out, one machine, owner's home IP, no proxies, no IP rotation, no multiple accounts. User-Agent names the app and a contact email.
- **Development:** no live calls to GGG. Work from recorded responses and fixtures only.
