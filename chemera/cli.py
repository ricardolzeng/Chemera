"""Command line entry points for Chemera."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .http import FetchError, HttpClient
from .review_plugins import analysis_to_json, analyze_page, fetch_reviews


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chemera-reviews",
        description="Detect independent-site review plugins and optionally fetch reviews.",
    )
    parser.add_argument("url", help="Product page URL to inspect.")
    parser.add_argument(
        "--html-file",
        type=Path,
        help="Use a saved HTML file instead of downloading the page.",
    )
    parser.add_argument(
        "--fetch-reviews",
        action="store_true",
        help="Fetch reviews using the best ready plugin strategy.",
    )
    parser.add_argument(
        "--plugin",
        choices=["bazaarvoice", "yotpo", "judge.me", "okendo", "trustpilot", "loox"],
        help="Force a detected plugin strategy when fetching reviews.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum reviews to request/return when fetching. Default: 100.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds. Default: 20.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = HttpClient(timeout=args.timeout)

    try:
        html = _load_html(args.url, args.html_file, client)
        if args.fetch_reviews:
            analysis, result = fetch_reviews(
                args.url,
                html=html,
                plugin=args.plugin,
                client=client,
                limit=max(args.limit, 1),
            )
            print(analysis_to_json(analysis, result))
        else:
            analysis = analyze_page(args.url, html)
            print(analysis_to_json(analysis))
    except FetchError as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"File error: {exc}", file=sys.stderr)
        return 3

    return 0


def _load_html(url: str, html_file: Path | None, client: HttpClient) -> str:
    if html_file is not None:
        return html_file.read_text(encoding="utf-8")
    return client.get_text(url)


if __name__ == "__main__":
    raise SystemExit(main())
