"""Independent-site review plugin detection and extraction strategies."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable
from urllib.parse import parse_qs, quote, urlencode, urlparse

from .html_signals import HtmlSignals, extract_signals
from .http import HttpClient


MARKETPLACE_DOMAINS = (
    "amazon.",
    "aliexpress.",
    "ebay.",
    "etsy.",
    "walmart.",
    "target.",
    "temu.",
    "shein.",
)


@dataclass(slots=True)
class SiteProfile:
    url: str
    hostname: str
    is_independent_site: bool
    platform: str | None = None
    shop_domain: str | None = None
    product_id: str | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PluginDetection:
    plugin: str
    confidence: str
    evidence: list[str]
    strategy: str
    endpoint: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.endpoint is not None and not self.missing

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_ready"] = self.is_ready
        return data


@dataclass(slots=True)
class PageAnalysis:
    site: SiteProfile
    plugins: list[PluginDetection]

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site.to_dict(),
            "plugins": [plugin.to_dict() for plugin in self.plugins],
        }


@dataclass(slots=True)
class ReviewResult:
    plugin: str
    endpoint: str
    reviews: list[dict[str, Any]]
    raw_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_page(url: str, html: str) -> PageAnalysis:
    signals = extract_signals(html, url)
    site = classify_site(url, signals)
    if not site.is_independent_site:
        return PageAnalysis(site=site, plugins=[])

    plugins = sorted(
        detect_review_plugins(signals, site),
        key=lambda item: (item.confidence != "high", item.plugin),
    )
    return PageAnalysis(site=site, plugins=plugins)


def classify_site(url: str, signals: HtmlSignals) -> SiteProfile:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    merchant_domain = _strip_www(hostname)
    reasons: list[str] = []

    for marketplace_domain in MARKETPLACE_DOMAINS:
        if marketplace_domain in hostname:
            return SiteProfile(
                url=url,
                hostname=hostname,
                is_independent_site=False,
                reasons=[f"known marketplace domain: {marketplace_domain}"],
            )

    haystack = signals.haystack
    platform: str | None = None
    shop_domain = _first_match(
        haystack,
        [
            r"([a-z0-9][a-z0-9-]*\.myshopify\.com)",
            r"Shopify\.shop\s*=\s*['\"]([^'\"]+)['\"]",
            r"shop_domain['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
        ],
    )
    if "cdn.shopify.com" in haystack or "ShopifyAnalytics" in haystack or shop_domain:
        platform = "shopify"
        reasons.append("Shopify signals found in page source")

    product_id = _first_match(
        haystack,
        [
            r"ShopifyAnalytics\.meta\.product\s*=\s*\{[^{}]*['\"]id['\"]\s*:\s*([0-9]+)",
            r"['\"]platform_product_id['\"]\s*[:=]\s*['\"]?([0-9]+)",
            r"['\"]product_id['\"]\s*[:=]\s*['\"]?([0-9]+)",
            r"data-product-id\s*=\s*['\"]([0-9]+)['\"]",
            r"data-productid\s*=\s*['\"]([0-9]+)['\"]",
        ],
    )

    if not shop_domain and platform == "shopify":
        shop_domain = merchant_domain

    reasons.append("domain is not a known marketplace")
    return SiteProfile(
        url=url,
        hostname=hostname,
        is_independent_site=True,
        platform=platform,
        shop_domain=shop_domain,
        product_id=product_id,
        reasons=reasons,
    )


def detect_review_plugins(signals: HtmlSignals, site: SiteProfile) -> list[PluginDetection]:
    haystack = signals.haystack
    candidates = [
        _detect_bazaarvoice(haystack),
        _detect_yotpo(haystack, site),
        _detect_judgeme(haystack, site),
        _detect_okendo(haystack, site),
        _detect_trustpilot(signals, site),
        _detect_loox(haystack, site),
    ]
    return [candidate for candidate in candidates if candidate is not None]


def fetch_reviews(
    url: str,
    html: str | None = None,
    plugin: str | None = None,
    client: HttpClient | None = None,
    limit: int = 100,
) -> tuple[PageAnalysis, ReviewResult | None]:
    client = client or HttpClient()
    page_html = html if html is not None else client.get_text(url)
    analysis = analyze_page(url, page_html)

    selected = _select_plugin(analysis.plugins, plugin)
    if selected is None or not selected.endpoint:
        return analysis, None

    if selected.plugin == "trustpilot":
        trustpilot_html = client.get_text(selected.endpoint)
        reviews = _extract_trustpilot_reviews(trustpilot_html, selected.endpoint)
        return analysis, ReviewResult(
            plugin=selected.plugin,
            endpoint=selected.endpoint,
            reviews=reviews[:limit],
            raw_count=len(reviews),
        )

    payload = client.get_json(_with_limit(selected, limit))
    reviews = _normalise_json_reviews(selected.plugin, payload)
    return analysis, ReviewResult(
        plugin=selected.plugin,
        endpoint=selected.endpoint,
        reviews=reviews[:limit],
        raw_count=len(reviews),
    )


def _detect_bazaarvoice(haystack: str) -> PluginDetection | None:
    if "api.bazaarvoice.com" not in haystack and "bazaarvoice" not in haystack.lower():
        return None

    passkey = _first_match(
        haystack,
        [
            r"[?&]passkey=([^&'\"\s]+)",
            r"['\"]passkey['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"bvPasskey\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"data-bv-passkey\s*=\s*['\"]([^'\"]+)['\"]",
        ],
    )
    product_id = _first_match(
        haystack,
        [
            r"[?&]Filter=ProductId:([^&'\"\s]+)",
            r"['\"]ProductId['\"]\s*[:=]\s*['\"]?([A-Za-z0-9_.:-]+)",
            r"['\"]productId['\"]\s*[:=]\s*['\"]?([A-Za-z0-9_.:-]+)",
            r"data-bv-product-id\s*=\s*['\"]([^'\"]+)['\"]",
        ],
    )
    params = _clean_params({"passkey": passkey, "product_id": product_id})
    missing = _missing(params, ["passkey", "product_id"])
    endpoint = None
    if not missing:
        query = urlencode(
            {
                "apiversion": "5.4",
                "passkey": passkey,
                "Filter": f"ProductId:{product_id}",
                "Include": "Products",
                "Stats": "Reviews",
                "Limit": "100",
                "Offset": "0",
                "Sort": "SubmissionTime:desc",
            }
        )
        endpoint = f"https://api.bazaarvoice.com/data/reviews.json?{query}"

    return PluginDetection(
        plugin="bazaarvoice",
        confidence="high",
        evidence=["api.bazaarvoice.com or Bazaarvoice markers found"],
        strategy="Extract passkey and ProductId from page source, then call /data/reviews.json.",
        endpoint=endpoint,
        params=params,
        missing=missing,
    )


def _detect_yotpo(haystack: str, site: SiteProfile) -> PluginDetection | None:
    if "yotpo.app_key" not in haystack and "yotpo" not in haystack.lower():
        return None

    app_key = _first_match(
        haystack,
        [
            r"yotpo\.app_key\s*=\s*['\"]([^'\"]+)['\"]",
            r"['\"]app_key['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"data-appkey\s*=\s*['\"]([^'\"]+)['\"]",
            r"data-app-key\s*=\s*['\"]([^'\"]+)['\"]",
        ],
    )
    sku = _first_match(
        haystack,
        [
            r"yotpo_product_id\s*[:=]\s*['\"]?([A-Za-z0-9_.:-]+)",
            r"data-product-id\s*=\s*['\"]([A-Za-z0-9_.:-]+)['\"]",
            r"['\"]sku['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
        ],
    ) or site.product_id

    params = _clean_params({"app_key": app_key, "sku": sku})
    missing = _missing(params, ["app_key", "sku"])
    endpoint = None
    if not missing:
        endpoint = f"https://api-cdn.yotpo.com/v1/widget/{quote(app_key)}/products/{quote(sku)}/reviews.json?per_page=100&page=1"

    return PluginDetection(
        plugin="yotpo",
        confidence="high",
        evidence=["yotpo.app_key or Yotpo markers found"],
        strategy="Use public app_key plus product sku/internal product id with Yotpo widget API.",
        endpoint=endpoint,
        params=params,
        missing=missing,
    )


def _detect_judgeme(haystack: str, site: SiteProfile) -> PluginDetection | None:
    if "jdgm-widget" not in haystack and "judge.me" not in haystack.lower():
        return None

    shop = _first_match(
        haystack,
        [
            r"data-shop-domain\s*=\s*['\"]([^'\"]+)['\"]",
            r"shop_domain['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"([a-z0-9][a-z0-9-]*\.myshopify\.com)",
        ],
    ) or site.shop_domain
    product_id = _first_match(
        haystack,
        [
            r"class\s*=\s*['\"][^'\"]*jdgm-widget[^'\"]*['\"][^>]*data-id\s*=\s*['\"]([0-9]+)['\"]",
            r"data-product-id\s*=\s*['\"]([0-9]+)['\"]",
            r"platform_product_id['\"]?\s*[:=]\s*['\"]?([0-9]+)",
        ],
    ) or site.product_id

    params = _clean_params({"shop_domain": shop, "platform_product_id": product_id})
    missing = _missing(params, ["shop_domain", "platform_product_id"])
    endpoint = None
    if not missing:
        endpoint = f"https://judge.me/api/v1/reviews?{urlencode(params)}"

    return PluginDetection(
        plugin="judge.me",
        confidence="high",
        evidence=["jdgm-widget class or Judge.me markers found"],
        strategy="Build Judge.me reviews URL from Shopify shop domain and platform product id.",
        endpoint=endpoint,
        params=params,
        missing=missing,
    )


def _detect_okendo(haystack: str, site: SiteProfile) -> PluginDetection | None:
    if "api.okendo.io" not in haystack and "okendo" not in haystack.lower():
        return None

    store_id = _first_match(
        haystack,
        [
            r"api\.okendo\.io/v1/stores/([^/'\"\s]+)/",
            r"['\"]store_id['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"['\"]subscriberId['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"okendo\.init\s*\(\s*['\"]([^'\"]+)['\"]",
        ],
    )
    product_id = _first_match(
        haystack,
        [
            r"products/shopify-([0-9]+)",
            r"data-product-id\s*=\s*['\"]([0-9]+)['\"]",
        ],
    ) or site.product_id

    params = _clean_params({"store_id": store_id, "shopify_product_id": product_id})
    missing = _missing(params, ["store_id", "shopify_product_id"])
    endpoint = None
    if not missing:
        endpoint = f"https://api.okendo.io/v1/stores/{quote(store_id)}/products/shopify-{quote(product_id)}/reviews?limit=100"

    return PluginDetection(
        plugin="okendo",
        confidence="high",
        evidence=["api.okendo.io or Okendo markers found"],
        strategy="Call Okendo store/product REST endpoint and preserve rich buyer attributes from JSON.",
        endpoint=endpoint,
        params=params,
        missing=missing,
    )


def _detect_trustpilot(signals: HtmlSignals, site: SiteProfile) -> PluginDetection | None:
    haystack = signals.haystack.lower()
    if "widget.trustpilot.com" not in haystack and "trustpilot" not in haystack:
        return None

    merchant_domain = _strip_www(site.hostname)
    endpoint = f"https://www.trustpilot.com/review/{merchant_domain}"
    return PluginDetection(
        plugin="trustpilot",
        confidence="high",
        evidence=["Trustpilot iframe/widget markers found"],
        strategy=(
            "Do not parse obfuscated widget iframe; fetch the merchant review page "
            "and extract application/ld+json structured reviews."
        ),
        endpoint=endpoint,
        params={"merchant_domain": merchant_domain},
    )


def _detect_loox(haystack: str, site: SiteProfile) -> PluginDetection | None:
    if "loox.io/api" not in haystack and "loox" not in haystack.lower():
        return None

    shop = _first_match(
        haystack,
        [
            r"[?&]shop=([^&'\"\s]+)",
            r"data-shop-domain\s*=\s*['\"]([^'\"]+)['\"]",
            r"([a-z0-9][a-z0-9-]*\.myshopify\.com)",
        ],
    ) or site.shop_domain
    product_id = _first_match(
        haystack,
        [
            r"[?&]pid=([^&'\"\s]+)",
            r"data-product-id\s*=\s*['\"]([0-9]+)['\"]",
        ],
    ) or site.product_id

    params = _clean_params({"shop": shop, "pid": product_id})
    missing = _missing(params, ["shop", "pid"])
    endpoint = None
    if not missing:
        endpoint = f"https://loox.io/api/v2/reviews?{urlencode(params)}&limit=100"

    return PluginDetection(
        plugin="loox",
        confidence="medium",
        evidence=["loox.io/api or Loox markers found"],
        strategy="Use Loox API and extract both review text and buyer image URLs when present.",
        endpoint=endpoint,
        params=params,
        missing=missing,
    )


def _select_plugin(
    plugins: Iterable[PluginDetection],
    requested_plugin: str | None,
) -> PluginDetection | None:
    ready = [plugin for plugin in plugins if plugin.endpoint]
    if requested_plugin:
        requested = requested_plugin.lower()
        return next((item for item in ready if item.plugin.lower() == requested), None)
    return next((item for item in ready if item.confidence == "high"), ready[0] if ready else None)


def _with_limit(detection: PluginDetection, limit: int) -> str:
    if detection.plugin == "bazaarvoice":
        return _replace_query_param(detection.endpoint or "", "Limit", str(limit))
    if detection.plugin in {"yotpo", "okendo", "loox"}:
        param = "per_page" if detection.plugin == "yotpo" else "limit"
        return _replace_query_param(detection.endpoint or "", param, str(limit))
    return detection.endpoint or ""


def _replace_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query[key] = [value]
    return parsed._replace(query=urlencode(query, doseq=True)).geturl()


def _normalise_json_reviews(plugin: str, payload: object) -> list[dict[str, Any]]:
    if plugin == "bazaarvoice":
        rows = _dig(payload, ["Results"], [])
        return [_review("bazaarvoice", item, item.get("ReviewText"), item.get("Rating"), item.get("UserNickname"), item.get("Title"), item.get("SubmissionTime"), _photos(item)) for item in _objects(rows)]

    if plugin == "yotpo":
        rows = _dig(payload, ["response", "reviews"], [])
        return [_review("yotpo", item, item.get("content"), item.get("score"), _dig(item, ["user", "display_name"]), item.get("title"), item.get("created_at"), _photos(item)) for item in _objects(rows)]

    if plugin == "judge.me":
        rows = _dig(payload, ["reviews"], [])
        return [_review("judge.me", item, item.get("body"), item.get("rating"), _dig(item, ["reviewer", "name"]), item.get("title"), item.get("created_at"), _photos(item)) for item in _objects(rows)]

    if plugin == "okendo":
        rows = _dig(payload, ["reviews"], None) or _dig(payload, ["body", "reviews"], [])
        return [_review("okendo", item, item.get("body") or item.get("reviewBody"), item.get("rating"), item.get("reviewerDisplayName") or item.get("customerDisplayName"), item.get("title"), item.get("dateCreated") or item.get("createdAt"), _photos(item), buyer_attributes=item.get("attributes") or item.get("customerAttributes")) for item in _objects(rows)]

    if plugin == "loox":
        rows = _dig(payload, ["reviews"], [])
        return [_review("loox", item, item.get("content") or item.get("body"), item.get("rating"), item.get("author") or item.get("name"), item.get("title"), item.get("created_at") or item.get("date"), _photos(item)) for item in _objects(rows)]

    return []


def _extract_trustpilot_reviews(html: str, url: str) -> list[dict[str, Any]]:
    signals = extract_signals(html, url)
    reviews: list[dict[str, Any]] = []
    for obj in signals.json_ld_objects():
        for review in _walk_jsonld_reviews(obj):
            reviews.append(
                _review(
                    "trustpilot",
                    review,
                    review.get("reviewBody") or review.get("description"),
                    _dig(review, ["reviewRating", "ratingValue"]),
                    _dig(review, ["author", "name"]) or review.get("author"),
                    review.get("headline") or review.get("name"),
                    review.get("datePublished"),
                    [],
                )
            )
    return reviews


def _walk_jsonld_reviews(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, list):
        for item in obj:
            yield from _walk_jsonld_reviews(item)
        return
    if not isinstance(obj, dict):
        return

    node_type = obj.get("@type")
    if node_type == "Review":
        yield obj

    review_value = obj.get("review")
    if isinstance(review_value, dict):
        yield from _walk_jsonld_reviews(review_value)
    elif isinstance(review_value, list):
        for review in review_value:
            yield from _walk_jsonld_reviews(review)

    graph = obj.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            yield from _walk_jsonld_reviews(item)


def _review(
    source: str,
    raw: dict[str, Any],
    text: Any,
    rating: Any,
    author: Any,
    title: Any,
    created_at: Any,
    images: list[str],
    buyer_attributes: Any = None,
) -> dict[str, Any]:
    data = {
        "source": source,
        "title": title,
        "text": text,
        "rating": rating,
        "author": author,
        "created_at": created_at,
        "images": images,
    }
    if buyer_attributes:
        data["buyer_attributes"] = buyer_attributes
    data["raw"] = raw
    return data


def _photos(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("Photos", "photos", "images", "images_data", "pictures", "media"):
        value = item.get(key)
        if not value:
            continue
        urls.extend(_extract_urls(value))
    return list(dict.fromkeys(urls))


def _extract_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith(("http://", "https://")) else []
    if isinstance(value, dict):
        found: list[str] = []
        for nested in value.values():
            found.extend(_extract_urls(nested))
        return found
    if isinstance(value, list):
        found = []
        for nested in value:
            found.extend(_extract_urls(nested))
        return found
    return []


def _objects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _dig(value: Any, path: list[str], default: Any = None) -> Any:
    current = value
    for part in path:
        if not isinstance(current, dict):
            return default
        current = current.get(part)
    return default if current is None else current


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def _clean_params(params: dict[str, str | None]) -> dict[str, str]:
    return {key: value for key, value in params.items() if value}


def _missing(params: dict[str, str], required: list[str]) -> list[str]:
    return [key for key in required if not params.get(key)]


def _strip_www(hostname: str) -> str:
    return hostname[4:] if hostname.startswith("www.") else hostname


def analysis_to_json(analysis: PageAnalysis, result: ReviewResult | None = None) -> str:
    payload: dict[str, Any] = {"analysis": analysis.to_dict()}
    if result is not None:
        payload["result"] = result.to_dict()
    return json.dumps(payload, ensure_ascii=False, indent=2)
