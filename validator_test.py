from app.upstream_security import validate_upstream_url

tests = [
    "https://example.com",
    "http://127.0.0.1:8081",
    "http://169.254.169.254",
    "http://metadata.google.internal",
    "file:///etc/passwd",
    "https://user:pass@example.com",
]

for url in tests:
    try:
        validate_upstream_url(url)
        print(f"ACCEPTED: {url}")
    except Exception as exc:
        print(f"REJECTED: {url} ({exc})")
