import time


class CircuitBreaker:
    def __init__(self,threshold=2,cooldown=1.2):
        self.threshold,self.cooldown=threshold,cooldown
        self.state,self.failures='closed',0
        self.opened_at,self.activations=0.0,0

    def allow(self):
        if self.state=='open':
            if time.monotonic()-self.opened_at<self.cooldown:
                return False
            self.state='half-open'
        return True

    def record(self,ok):
        if ok:
            self.failures,self.state=0,'closed'
        else:
            self.failures+=1
            if self.state=='half-open' or self.failures>=self.threshold:
                self.state,self.opened_at='open',time.monotonic()
                self.activations+=1
