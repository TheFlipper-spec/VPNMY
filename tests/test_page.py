from html.parser import HTMLParser
from pathlib import Path


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])


def test_status_page_has_unique_ids_and_subscription_actions():
    page = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    parser = PageParser()
    parser.feed(page)
    parser.close()

    assert len(parser.ids) == len(set(parser.ids))
    assert {"subscription-url", "copy", "nodes", "source-list", "status"} <= set(parser.ids)
    assert 'new URL("./FL1PVPN", document.baseURI)' in page
    assert "Date.now() - updatedTime" in page
