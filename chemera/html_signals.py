"""Extract reusable signals from a product page's HTML."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


@dataclass(slots=True)
class ScriptBlock:
    source: str | None
    type: str | None
    text: str


@dataclass(slots=True)
class HtmlSignals:
    html: str
    base_url: str
    classes: set[str] = field(default_factory=set)
    script_sources: list[str] = field(default_factory=list)
    iframe_sources: list[str] = field(default_factory=list)
    link_hrefs: list[str] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    scripts: list[ScriptBlock] = field(default_factory=list)
    attributes_text: list[str] = field(default_factory=list)

    @property
    def haystack(self) -> str:
        parts = [
            self.html,
            " ".join(self.classes),
            " ".join(self.script_sources),
            " ".join(self.iframe_sources),
            " ".join(self.link_hrefs),
            " ".join(self.meta.values()),
            " ".join(self.attributes_text),
        ]
        return "\n".join(parts)

    def json_ld_objects(self) -> list[Any]:
        objects: list[Any] = []
        for script in self.scripts:
            if (script.type or "").lower() != "application/ld+json":
                continue
            try:
                objects.append(json.loads(script.text.strip()))
            except json.JSONDecodeError:
                continue
        return objects


class _SignalParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.signals = HtmlSignals(html="", base_url=base_url)
        self._base_url = base_url
        self._current_script: dict[str, str | None] | None = None
        self._script_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value or "" for name, value in attrs}
        self.signals.attributes_text.append(
            " ".join(f"{name}={value}" for name, value in attr_map.items())
        )

        class_value = attr_map.get("class")
        if class_value:
            self.signals.classes.update(class_value.split())

        if tag == "script":
            source = attr_map.get("src")
            if source:
                self.signals.script_sources.append(urljoin(self._base_url, source))
            self._current_script = {
                "source": urljoin(self._base_url, source) if source else None,
                "type": attr_map.get("type"),
            }
            self._script_parts = []
        elif tag == "iframe":
            source = attr_map.get("src")
            if source:
                self.signals.iframe_sources.append(urljoin(self._base_url, source))
        elif tag == "link":
            href = attr_map.get("href")
            if href:
                self.signals.link_hrefs.append(urljoin(self._base_url, href))
        elif tag == "meta":
            key = attr_map.get("name") or attr_map.get("property")
            content = attr_map.get("content")
            if key and content:
                self.signals.meta[key.lower()] = content

    def handle_data(self, data: str) -> None:
        if self._current_script is not None:
            self._script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or self._current_script is None:
            return

        self.signals.scripts.append(
            ScriptBlock(
                source=self._current_script.get("source"),
                type=self._current_script.get("type"),
                text="".join(self._script_parts),
            )
        )
        self._current_script = None
        self._script_parts = []


def extract_signals(html: str, base_url: str) -> HtmlSignals:
    parser = _SignalParser(base_url)
    parser.signals.html = html
    parser.feed(html)
    parser.close()
    return parser.signals
