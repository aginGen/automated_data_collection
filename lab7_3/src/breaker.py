import time


class Breaker:
    def __init__(self, threshold=2, cooldown=4):
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.state = "closed"
        self.opened = 0
        self.activations = 0

    def allow(self):
        if self.state == "open":
            if time.monotonic() - self.opened < self.cooldown:
                return False
            self.state = "half-open"
        return True

    def result(self, failed):
        if not failed:
            self.failures = 0
            self.state = "closed"
            return
        self.failures += 1
        if self.state == "half-open" or self.failures >= self.threshold:
            self.state = "open"
            self.opened = time.monotonic()
            self.activations += 1
