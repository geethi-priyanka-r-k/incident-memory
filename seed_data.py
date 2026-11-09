"""15 realistic past incidents across 5 types, used to give the agent something to remember."""

INCIDENTS = [
    # ---- Failed deployment ----
    {
        "type": "Failed deployment",
        "report": "Release v2.4 deployed and the login page returns a blank screen.",
        "root_cause": "New frontend build referenced an env var AUTH_BASE_URL that was missing in production config.",
        "fix": "Added AUTH_BASE_URL to the production config and redeployed. Rolled back to v2.3 first to restore service.",
        "didnt_work": "Clearing the CDN cache did not help.",
    },
    {
        "type": "Failed deployment",
        "report": "Deploy of order-service failed, pods stuck in CrashLoopBackOff after release.",
        "root_cause": "A database migration in the release had not run, so the app crashed on startup with 'column does not exist'.",
        "fix": "Ran the pending migration manually, then restarted pods. Added a migration step to the deploy pipeline.",
        "didnt_work": "Scaling up replicas made no difference.",
    },
    {
        "type": "Failed deployment",
        "report": "After the latest release, API returns 502 Bad Gateway on all endpoints.",
        "root_cause": "The container listened on port 3000 but the load balancer health check expected port 8080.",
        "fix": "Set the PORT variable back to 8080 and redeployed.",
        "didnt_work": "Restarting the load balancer did not help.",
    },
    # ---- Performance slowdown ----
    {
        "type": "Performance slowdown",
        "report": "Checkout takes 30 seconds to load since this morning.",
        "root_cause": "A missing index on orders.customer_id caused a full table scan after the table grew past 5M rows.",
        "fix": "Created an index on orders.customer_id. Query time dropped from 28s to 40ms.",
        "didnt_work": "Adding more app servers did not help, the bottleneck was the database.",
    },
    {
        "type": "Performance slowdown",
        "report": "Dashboard gets slower every hour and the service needs a restart every night.",
        "root_cause": "Memory leak: an in-memory cache with no eviction policy grew until the JVM spent most of its time in garbage collection.",
        "fix": "Added a max size and TTL to the cache. Memory stayed flat afterwards.",
        "didnt_work": "Increasing the heap size only delayed the problem by a few hours.",
    },
    {
        "type": "Performance slowdown",
        "report": "Search API latency jumped from 200ms to 4 seconds, CPU is normal.",
        "root_cause": "Redis cache hit rate fell to near zero because a deploy changed the cache key format and old entries were never reused.",
        "fix": "Warmed the cache with the top 1000 queries and kept the new key format stable.",
        "didnt_work": "Restarting Redis cleared the cache and made it worse.",
    },
    # ---- Third-party outage ----
    {
        "type": "Third-party outage",
        "report": "Payment gateway returning 503 errors, customers cannot pay.",
        "root_cause": "The payment provider had a regional outage. Our retries without backoff made things worse by hitting their rate limit.",
        "fix": "Enabled exponential backoff, switched traffic to the secondary payment provider, and showed a friendly retry message to users.",
        "didnt_work": "Restarting our payment service did nothing, the problem was on the provider side.",
    },
    {
        "type": "Third-party outage",
        "report": "SMS OTP messages are not being delivered to users.",
        "root_cause": "The SMS provider API key had expired and every call returned 401 silently.",
        "fix": "Rotated the API key in the secrets manager. Added an alert on non-200 responses from the SMS provider.",
        "didnt_work": "Resending messages in bulk failed with the same 401.",
    },
    {
        "type": "Third-party outage",
        "report": "Images are not loading anywhere on the site, requests to the CDN time out.",
        "root_cause": "The CDN provider had an incident in one region. Our assets had no fallback origin.",
        "fix": "Switched DNS to the backup origin and configured a failover origin for the future.",
        "didnt_work": "Purging the CDN cache could not work while the CDN itself was down.",
    },
    # ---- Database or data issue ----
    {
        "type": "Database or data issue",
        "report": "Customers see wrong order totals in their cart.",
        "root_cause": "A rounding bug: totals were calculated with floats instead of decimals, so tax summed incorrectly across many line items.",
        "fix": "Switched the calculation to Decimal, then re-ran a one-off job to correct affected orders from the last 3 days.",
        "didnt_work": "Clearing the cart cache did not fix stored totals.",
    },
    {
        "type": "Database or data issue",
        "report": "Payment service timing out with 'connection pool exhausted' errors.",
        "root_cause": "Database connection pool size was only 10 while traffic had grown, so requests queued up and timed out.",
        "fix": "Raised the pool size from 10 to 50 and added a pool usage metric.",
        "didnt_work": "Restarting the service helped for a few minutes only.",
    },
    {
        "type": "Database or data issue",
        "report": "Duplicate user accounts and duplicate emails are appearing in the database.",
        "root_cause": "No unique constraint on email plus a race condition when users double-clicked the signup button.",
        "fix": "Added a unique index on email, deduplicated existing rows, and disabled the button after the first click.",
        "didnt_work": "Validating in application code alone did not prevent the race.",
    },
    # ---- Security alert ----
    {
        "type": "Security alert",
        "report": "500 failed login attempts from one IP address in 10 minutes.",
        "root_cause": "A credential stuffing attack. The login endpoint had no rate limit.",
        "fix": "Blocked the IP range at the firewall, added rate limiting of 5 attempts per minute per IP, and forced a password reset for accounts that showed a successful login from that IP.",
        "didnt_work": "Blocking a single IP was not enough, the attacker rotated addresses.",
    },
    {
        "type": "Security alert",
        "report": "Alert: AWS access key found in a public GitHub repository.",
        "root_cause": "A developer committed a .env file by mistake.",
        "fix": "Revoked and rotated the key immediately, reviewed CloudTrail for misuse, removed the file from git history, and added a pre-commit secret scanner.",
        "didnt_work": "Deleting the file in a new commit did not remove it from history, so the key still had to be rotated.",
    },
    {
        "type": "Security alert",
        "report": "Unusual spike of requests with SQL fragments in query parameters on the search endpoint.",
        "root_cause": "Automated SQL injection scanning. One legacy endpoint built a query with string concatenation.",
        "fix": "Converted the legacy query to parameterized statements and enabled WAF rules for SQL injection patterns.",
        "didnt_work": "WAF rules alone were not enough, the underlying query had to be fixed.",
    },
]


def as_memory(inc: dict) -> str:
    """Turn an incident into one text block that Hindsight can store and recall."""
    return (
        f"Incident type: {inc['type']}. "
        f"Report: {inc['report']} "
        f"Root cause: {inc['root_cause']} "
        f"Fix: {inc['fix']} "
        f"What did NOT work: {inc['didnt_work']}"
    )
