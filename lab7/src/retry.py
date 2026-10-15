import random
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime


def classify(status=None,exception=None):
    if exception is not None:
        return 'network',True
    if status==429:
        return 'rate_limit',True
    if status is not None and 500<=status<=599:
        return 'server',True
    if status in (401,403):
        return 'authorization_or_block',False
    if status is not None and 400<=status<=499:
        return 'client',False
    return 'ok',False


def retry_delay(attempt,retry_after=None,base=0.25,cap=2.0):
    if retry_after is not None:
        try:
            delay=float(retry_after)
        except ValueError:
            try:
                parsed=parsedate_to_datetime(retry_after)
                if parsed.tzinfo is None:
                    parsed=parsed.replace(tzinfo=timezone.utc)
                delay=(parsed-datetime.now(timezone.utc)).total_seconds()
            except (ValueError,TypeError,OverflowError):
                return random.uniform(0,min(cap,base*2**attempt)),'full_jitter_invalid_header'
        return max(0.0,delay),'Retry-After'
    return random.uniform(0,min(cap,base*2**attempt)),'full_jitter'
