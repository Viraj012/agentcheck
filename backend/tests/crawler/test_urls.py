import pytest

from app.crawler.urls import InvalidURLError, crawl_scope, in_scope, normalize_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Help.Example.com", "https://help.example.com/"),
        ("HTTP://example.com:80/a", "http://example.com/a"),
        ("https://example.com:443/a?b=1#frag", "https://example.com/a?b=1"),
        ("  https://example.com/docs/  ", "https://example.com/docs/"),
        ("https://bücher.example/", "https://xn--bcher-kva.example/"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://example.com/",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://example.com:8443/",
        "http://example.com:22/",
        "http://user:pass@example.com/",
        "https:///nohost",
        "not a url",
        "",
    ],
)
def test_normalize_url_rejects(raw: str) -> None:
    with pytest.raises(InvalidURLError):
        normalize_url(raw)


@pytest.mark.parametrize(
    ("start", "scope"),
    [
        ("https://x.com/", "/"),
        ("https://x.com/help/", "/help/"),
        ("https://x.com/help/getting-started", "/help/"),
        ("https://x.com/index.html", "/"),
    ],
)
def test_crawl_scope(start: str, scope: str) -> None:
    assert crawl_scope(start) == scope


def test_in_scope() -> None:
    start = "https://x.com/help/"
    assert in_scope("https://x.com/help/returns", start)
    assert not in_scope("https://x.com/blog/post", start)
    assert not in_scope("https://other.com/help/returns", start)
    assert not in_scope("http://x.com/help/returns", start)
