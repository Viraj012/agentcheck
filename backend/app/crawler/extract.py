"""Turn HTML into clean main text (headings kept as markdown) and outgoing links."""

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin

import trafilatura

from app.crawler.urls import InvalidURLError, normalize_url


@dataclass(frozen=True)
class ExtractedPage:
    title: str
    text: str


def extract_page(html: str, url: str) -> ExtractedPage:
    document = trafilatura.bare_extraction(
        html,
        url=url,
        output_format="python",
        include_formatting=True,
        include_comments=False,
        include_images=False,
        include_links=False,
        with_metadata=True,
    )
    if document is None:
        return ExtractedPage(title="", text="")
    return ExtractedPage(title=(document.title or "").strip(), text=(document.text or "").strip())


def extract_links(html: str, base_url: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    links: list[str] = []
    for href in parser.hrefs:
        try:
            url = normalize_url(urldefrag(urljoin(base_url, href)).url)
        except InvalidURLError:
            continue
        if url not in links:
            links.append(url)
    return links


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href.strip())
