---
title: 200 payments in, 2 counted
date: 2026-11-07
summary: Two replicas of Sentinel's fraud scorer updating one merchant's history in Redis at the same time. Why a read-then-write lost 198 of 200 updates, how one Lua script fixed it, and how pipelining made it 10x faster without breaking it.
---

[Sentinel](https://github.com/ARV0007/transakt-sentinel) scores every payment that settles in my payment gateway for fraud risk. Most of the useful signals are about history: how many payments has this merchant taken in the last two minutes? Is this amount far above their usual? How old is the account?

So before scoring a payment, the scorer reads the merchant's recent history, and after reading it, records the new payment so the next one sees it. That history lives in Redis, so that a restart or a redeploy doesn't wipe it and hand fraudsters a clean slate.

Two Redis calls. Read, then write. It worked fine with one scorer.

## Two replicas, one merchant

The scorer is meant to run as more than one copy, all reading from the same Kafka topic. Payments from one busy merchant can land on both copies at once. Then this can happen:

1. Replica A reads the history: 5 payments so far.
2. Replica B reads the history: 5 payments so far.
3. A writes: now 6.
4. B writes: now 6.

Two payments came in, the count went up by one. Worse, both payments were scored as if the other didn't exist, and "many payments in a short time" is exactly the signal a velocity burst should trip.

I wrote a test to see how bad it gets: 200 payments for one merchant, sent concurrently through two scorer instances against a real Redis. The naive read-then-write version ended with a count of **2**. Nearly every update was lost.

## One step instead of two

Redis runs a Lua script as a single step. While the script runs, no other command touches those keys. So the fix is to move read-and-record into one script. Shortened a little:

```lua
local ts = tonumber(ARGV[1])
local floor = ts - tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', '(' .. floor)   -- drop old events
local rows = redis.call('ZRANGEBYSCORE', KEYS[1], floor, ts, 'WITHSCORES')
local total = tonumber(redis.call('GET', KEYS[2]) or '0')
-- (skip this payment's own entry if Kafka redelivered it)
if redis.call('ZADD', KEYS[1], ts, ARGV[4]) == 1 then
  redis.call('INCR', KEYS[2])   -- count only a genuinely new payment
end
-- cap the set, set expiries
return {total - replay, prior}
```

The history is a sorted set per merchant, scored by timestamp, plus an all-time counter. The script trims the window, reads what's left, adds the new payment and returns the history *as it was before this payment*. That's what the features need.

Two details came from thinking about Kafka rather than about concurrency. Kafka delivers at least once, so the same payment can arrive twice. The script recognises its own payment id in the set and never compares a payment with itself. And the counter only goes up if `ZADD` actually added something, so a redelivery doesn't count twice.

The same test now passes with every payment seeing a different "count before me", 0 through 199, and a final count of **200**. The assertion checks both, because a final count of 200 alone could still hide two payments that saw the same history.

## Then it was slow

Correct, but each payment now cost one round trip to Redis. With Redis behind it, the scorer did about 355 payments a second.

The fix was batching. I changed the Kafka consumer to take up to 200 messages per poll and score them together, so the scorer could send all their scripts in one **pipeline**: one round trip instead of 200. That took it to about **3,505 payments a second**, roughly 10x.

But was batching still correct? Payments number 3 and 7 of a merchant might be in the same batch, and number 7 has to see number 3 in its history.

It does, for a reason worth spelling out: Redis executes the commands of a pipeline in the order it receives them. Each script is still atomic by itself, and they run in order, so payment 7's script runs after payment 3's has already recorded it. Another client could slip a command in between two scripts, but that was already possible one at a time, and it doesn't break anything because each script is complete on its own.

I didn't want to rely on reasoning alone, so a test computes a whole batch through one pipeline and checks every feature of every payment against computing them one at a time. It runs against an in-memory fake and against real Redis in CI.

## What I took from it

Read-then-write against shared state is a race, even when each call is fast and even when it works every time on your laptop. The test that showed it only failed once I used two clients and real concurrency against a real Redis; the in-memory fake couldn't show it.

And making something fast is a separate step from making it correct. The pipelining change needed its own argument for why order was preserved, and its own test.

The script is in [`features.py`](https://github.com/ARV0007/transakt-sentinel/blob/main/services/risk-scorer/app/features.py) and the tests are in [`test_state.py`](https://github.com/ARV0007/transakt-sentinel/blob/main/services/risk-scorer/tests/test_state.py). You can see the scorer at work in the [Sentinel replay](/demos/sentinel/).
