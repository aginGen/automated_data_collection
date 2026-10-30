import time, random


class Limiter:
    def __init__(self, rate=0.5, burst=1, delay=0):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last = time.monotonic()
        self.next = 0
        self.ewma = 0
        self.delay = delay

    def acquire(self, deadline):
        while True:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            wait = max((1 - self.tokens) / self.rate, self.next - now, 0)
            if now + wait > deadline:
                return False
            if wait > 0:
                time.sleep(wait)
                continue
            self.tokens -= 1
            self.next = now + max(
                self.delay, self.ewma * 2, 1 / self.rate
            ) * random.uniform(1, 1.25)
            return True

    def observe(self, ms, status):
        self.ewma = 0.8 * self.ewma + 0.2 * ms / 1000
        if status in (429, 503):
            self.ewma = max(self.ewma, 1 / self.rate) * 2
            # Apply the increased delay to the very next request, even when
            # the previous admission has already scheduled a shorter pause.
            delay = max(self.delay, self.ewma * 2, 1 / self.rate)
            self.next = max(self.next, time.monotonic() + delay * random.uniform(1, 1.25))
