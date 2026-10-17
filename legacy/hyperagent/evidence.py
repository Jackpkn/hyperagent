"""Bounded, immutable page observations shared by policy, recovery and verification."""

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit


def web_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not (
            parsed.username or parsed.password
        )
    except ValueError:
        return False


class EvidenceLedger:
    def __init__(self, limit=24):
        self.limit = limit
        self.sources = []

    def observe(self, page):
        url = page.get("url", "")
        if not web_url(url):
            return
        content = {"url": url, "title": page.get("title", ""), "text": page.get("text", "")[:16000]}
        links = {action["href"]: action.get("label", "") for action in page.get("actions", [])
                 if web_url(action.get("href"))}
        content["links"] = [{"label": label, "url": url} for url, label in list(links.items())[:150]]
        identity = hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]
        if any(source["id"] == identity for source in self.sources):
            return
        self.sources.append({"id": identity, **content, "captured_at": datetime.now(timezone.utc).isoformat()})
        self.sources = self.sources[-self.limit:]


EVIDENCE_SCHEMA = {"type": "array", "items": {
    "type": "object", "properties": {
        "source_id": {"type": "string"},
        "field": {"type": "string", "enum": ["text", "title"]},
        "quote": {"type": "string"},
    }, "required": ["source_id", "field", "quote"], "additionalProperties": False,
}}


def grounded_references(references, sources):
    """Require every exact quote to occur in the referenced field of that observation."""
    by_id = {source["id"]: source for source in sources}
    return isinstance(references, list) and bool(references) and all(
        isinstance(ref, dict) and isinstance(ref.get("source_id"), str) and ref["source_id"] in by_id
        and isinstance(ref.get("field"), str) and ref["field"] in {"text", "title"}
        and isinstance(ref.get("quote"), str) and ref["quote"].strip()
        and ref["quote"] in by_id[ref["source_id"]].get(ref["field"], "")
        for ref in references
    )


def grounded_urls(value, sources):
    """A model-authored URL must be an observed page or anchor in the cited sources."""
    allowed = {source["url"] for source in sources}
    allowed.update(link["url"] for source in sources for link in source.get("links", []))

    def check(item, url_field=False):
        if item is None:
            return True
        if isinstance(item, dict):
            return all(check(v, str(k).lower().endswith(("url", "urls", "link", "links", "href")))
                       for k, v in item.items())
        if isinstance(item, list):
            return all(check(v, url_field) for v in item)
        if url_field:
            return isinstance(item, str) and web_url(item) and item in allowed
        if isinstance(item, str):
            if re.search(r"(?<![:/\w])//[^\s/]+", item):
                return False  # Protocol-relative links are not observed absolute URLs.
            if item.strip().lower().startswith(("http://", "https://")) and not any(c.isspace() for c in item.strip()):
                return item.strip() in allowed
            return all(match in allowed or match.rstrip('.,);]') in allowed
                       for match in re.findall(r'https?://[^\s<>"\']+', item, flags=re.IGNORECASE))
        return True

    return check(value)
