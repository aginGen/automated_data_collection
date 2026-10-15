MARKERS=('captcha','access denied','доступ ограничен','verify you are human')


def inspect_response(status,body,expected=True,min_bytes=80):
    text=body.decode('utf-8',errors='replace').casefold()
    markers=[marker for marker in MARKERS if marker in text]
    if status==403 or markers or (status==200 and not expected):
        return dict(verdict='blocked',reason='status, marker or missing expected records',markers=markers)
    if status==429 or (status==200 and len(body)<min_bytes):
        return dict(verdict='suspicious',reason='rate limit or unusually small response',markers=markers)
    return dict(verdict='ok',reason='',markers=[])
