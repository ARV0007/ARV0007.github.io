---
title: When close(timeout) doesn't time out
date: 2026-11-07
summary: KafkaProducer.close(Duration) could block forever if a send callback got stuck. A small fix to Apache Kafka, and the Thread.join(0) trap hiding next to it.
---

`KafkaProducer.close(Duration timeout)` reads like a promise: wait up to this long for pending sends, then give up and return. Shutdown code relies on that. If a service gets 30 seconds to stop and the producer close takes forever, the process gets killed instead of shutting down cleanly.

[KAFKA-9998](https://issues.apache.org/jira/browse/KAFKA-9998) is a case where the promise breaks. My fix is [apache/kafka#23926](https://github.com/apache/kafka/pull/23926).

## How it hangs

The producer sends records on a background I/O thread. When a send finishes, or fails, the producer runs your callback on that same thread.

When the timeout runs out before pending sends are done, `close()` force-closes the producer. The I/O thread then fails every pending record and runs each record's callback. After that, `close()` waited for the I/O thread to stop:

```java
this.ioThread.join();
```

No timeout. If a callback blocks (waiting on a lock, a full queue, a slow network call), the I/O thread can't stop, and `close()` waits with it. You asked for 100 ms and got forever.

## The trap next to it

While reading that method I found a second way to wait forever, one line up:

```java
this.ioThread.join(closeTimer.remainingMs());
```

This looks bounded. But `Thread.join(long millis)` has a special case: **`join(0)` means wait forever**, not "don't wait". When the close timer has already run out, `remainingMs()` is 0, and the bounded wait silently becomes an unbounded one. It's documented, but easy to miss.

## The fix

Two small private methods in `KafkaProducer`:

```java
private void joinIoThread(long timeoutMs) throws InterruptedException {
    if (timeoutMs > 0) {
        this.ioThread.join(timeoutMs);
    }
}

private void joinIoThreadAfterForceClose() throws InterruptedException {
    joinIoThread(maxBlockTimeMs);
    if (this.ioThread.isAlive()) {
        log.warn("The producer I/O thread did not stop within {} ms ({}) after the producer was force closed, " +
                "possibly because a callback is blocking it. Continuing to close without waiting for it.",
                maxBlockTimeMs, ProducerConfig.MAX_BLOCK_MS_CONFIG);
    }
}
```

`joinIoThread` makes "zero" mean zero. `joinIoThreadAfterForceClose` caps the wait after a forced close at `max.block.ms`, the setting that already decides how long producer methods may block. If the thread is still alive after that, it logs a warning that names the likely cause and moves on.

Why not keep waiting? Because nothing good comes of it. The producer has been force-closed; the records are already failed. The only thing left is a stuck callback, and that's the application's bug to find. The warning tells them where to look, which a silent hang never did.

Why not simply stop at the close timeout? Because in the normal case the forced close finishes in milliseconds, and waiting for it means every callback has run by the time `close()` returns. Code may rely on that. A separate, bounded wait keeps that behaviour when nothing is stuck.

## Testing a hang

You can't write a test that waits forever to prove something doesn't wait forever. So the test builds the hang on purpose and puts a ceiling on how long it's willing to watch:

1. A producer pointed at a mock client that never answers, with `max.block.ms` set to 500.
2. Send a record whose callback signals that it started, then blocks on a latch.
3. Call `close(timeout)` on another thread.
4. Wait for the callback to start, which proves the forced close ran it.
5. Expect `close()` to return within 10 seconds. Before the fix, it never does.

There are two versions of that test, one with a 100 ms close timeout and one with zero, to cover both `join` calls. A third test checks the normal path: a forced close with a callback that doesn't block still runs the callback before `close()` returns, so the fix didn't trade one surprise for another.

## What I took from it

A timeout parameter is only as good as every wait underneath it. One unbounded `join()` deep inside makes the whole method unbounded, and an API that sometimes ignores its timeout is worse than one without a timeout, because people stop planning for the hang.

And `join(0)` goes on my list of APIs where zero means the opposite of what you'd guess.

The PR is open for review.
