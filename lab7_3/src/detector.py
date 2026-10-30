def detect(status, body, expected=True):
    text = body.decode("utf-8", "replace").lower()
    if status == 403 or any(
        s in text for s in ("captcha", "access denied", "доступ ограничен")
    ):
        return "blocked"
    if status == 429:
        return "suspicion"
    if status == 200 and (len(body) < 100 or not expected):
        return "suspicion"
    return "ok"
