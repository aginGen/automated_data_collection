import hashlib
import os
import random
import time
from pathlib import Path


class TokenBucket:
    def __init__(self, rate=2.0, burst=1, jitter=0.25, crawl_delay=0.0):
        if rate <= 0 or burst < 1 or not 0.2 <= jitter <= 0.3:
            raise ValueError('Неверные параметры ограничителя')
        self.rate, self.burst, self.jitter = rate, burst, jitter
        self.tokens, self.updated = float(burst), time.monotonic()
        self.last_request, self.crawl_delay, self.delay = 0.0, crawl_delay, 0.0

    def acquire(self):
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now-self.updated)*self.rate)
        self.updated = now
        token_wait = max(0.0, (1-self.tokens)/self.rate)
        interval_wait = max(0.0, max(self.delay,self.crawl_delay)-(now-self.last_request))
        pause = max(token_wait,interval_wait)+random.uniform(0,self.jitter/self.rate)
        if pause:
            time.sleep(pause)
        now = time.monotonic()
        self.tokens = min(self.burst,self.tokens+(now-self.updated)*self.rate)-1
        self.updated = self.last_request = now
        return pause

    def observe(self, latency, status):
        self.delay = min(3.0,(self.delay+max(0.04,latency))/2)
        if status in (429,503):
            self.delay = min(3.0,max(self.delay*2,1/self.rate))


class DomainLease:
    def __init__(self,directory,host):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True)
        self.path=directory/(hashlib.sha256(host.encode()).hexdigest()+'.lock')

    def __enter__(self):
        self.file=self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        if os.name=='nt':
            import msvcrt
            try:
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as error:
                self.file.close()
                raise RuntimeError('Для домена уже работает другой воркер') from error
        else:
            import fcntl
            fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return self

    def __exit__(self,*args):
        self.file.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
        self.file.close()
