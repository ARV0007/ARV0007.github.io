---
title: Cache the lookup, never the decision
date: 2026-11-07
summary: Adding a Redis cache in front of API key authentication in Transakt, my payment gateway. The rule that made it safe, the short list of ways an entry can go stale, and how to prove a request really came from the cache.
---

Every request to [Transakt](https://github.com/ARV0007/transakt) that carries an `X-API-Key` header starts the same way: find the merchant the key belongs to. That was a PostgreSQL query, and in production the database is Neon, reached over the public internet. Redis, meanwhile, sits on Render's private network right next to the app.

API keys get read on every call and almost never change. That's exactly what a cache is for. But this cache sits in front of authentication, so "a bit stale sometimes" isn't automatically fine. Before writing any code I wanted to know exactly when it could be wrong.

## How the key check works

A Transakt key looks like `tk_ab12cd34...`. The first 8 characters are a prefix stored in plain text, so it can be looked up. The full key is never stored, only its SHA-256 hash. To authenticate, the filter finds the merchant by prefix, hashes the key it was given, and compares the two hashes in constant time.

The slow part is the lookup by prefix. The decision is the comparison.

## The rule: cache the lookup, never the decision

The cache stores what the lookup returns: merchant id, role and the stored hash, under `apikey:<prefix>`, for five minutes. It never stores "this key is valid".

In outline, the filter does this:

```java
CachedPrincipal principal = apiKeyCache.get(prefix)
        .or(() -> lookUpInDatabase(prefix))   // and cache what it finds
        .orElse(null);

if (principal != null && ApiKeyHasher.matches(apiKey, principal.apiKeyHash())) {
    // authenticated as principal.merchantId()
}
```

The hash comparison runs on every request, cached or not. So the cache can save a database query, but it can never let a wrong key through. That was the line I didn't want to cross. The raw key isn't stored anywhere, cache included.

## The list of ways an entry goes stale

For any cache, the real design work is listing what can make an entry wrong. For this one the list is short:

| What changes | Can it make an entry wrong? | Handled by |
|---|---|---|
| The key's hash | No, it's written once at signup | |
| Role, through the API | No, no endpoint changes a role | |
| Role, edited by hand in psql | Yes | The 5-minute TTL |
| Merchant deleted | Yes | Evicted on delete |

Writing that table down was most of the design. It also tells you what to do later: if someone adds an endpoint that changes roles, it has to evict too. I wrote that into the docs as a known limitation, so it doesn't depend on someone remembering.

## Three decisions that weren't obvious

**Evict twice on delete.** Deleting a merchant evicts its entry before the database delete and again after. Why both? A request that read the row just before the delete could write it back into the cache just after the first eviction. Without the second one, a deleted merchant's key could keep working for up to five minutes.

**Don't cache "not found".** Caching misses would save database work when someone sprays random prefixes, but it would also refuse a brand-new key until the cached miss expired. Spraying random prefixes is the rate limiter's problem, not the cache's.

**Fail open.** If Redis is down, every lookup is a cache miss and the filter goes to Postgres, exactly as before the cache existed. A cache outage should cost latency, never availability. The rate limiter already worked this way.

## Proving a request came from the cache

From outside, a cache hit and a database lookup look identical: same 200, same body. So how do you test that the second request actually used the cache?

You break the database copy in between:

1. Sign up, call `/merchants/me` with the key. That fills the cache.
2. Overwrite the stored hash in Postgres with 64 zeros.
3. Call again with the same key.

If the second call still authenticates, Postgres wasn't asked, because the database copy can no longer match anything. The other tests cover the rest: a forged key with a real prefix gets 403 even when the entry is cached, deleting a merchant removes the entry and refuses its key at once, and an unknown prefix is never cached.

One thing that caught me: these tests use `@Transactional`, which rolls back Postgres after each test. It doesn't roll back Redis. Without flushing Redis before each test, one test's cache entries leak into the next.

## What it saved

A benchmark runs on every pull request that touches the cache, and posts its numbers back on the PR. Two runs on GitHub Actions, Postgres and Redis as local containers:

| Median (p50) | Run 1 | Run 2 |
|---|---|---|
| Lookup from Postgres | 407 µs | 520 µs |
| Lookup from Redis | 115 µs | 182 µs |
| Whole request, cache cold | 1,377 µs | 1,753 µs |
| Whole request, cache warm | 617 µs | 797 µs |

So the lookup itself is about 3x faster, and a whole authenticated request takes roughly 55% less time warm than cold. Two honest caveats. The cold path includes writing the entry into the cache, which flatters the comparison a little. And in CI both stores are on localhost, while in production Postgres is across the internet, so the real saving is probably bigger. I haven't measured that yet.

## What I took from it

Before adding a cache, list everything that can make an entry wrong. If you can't write that list, you're not ready to add it. And when the cache sits next to a security check, keep the check out of the cache entirely.

The change is [PR #1](https://github.com/ARV0007/transakt/pull/1), with the benchmark output in the comments. You can also [try Transakt in your browser](/demos/transakt/), including a forged key.
