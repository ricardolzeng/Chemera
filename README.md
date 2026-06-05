# Chemera

Chemera is a small Python crawler helper for detecting and collecting reviews
from independent ecommerce sites. It is designed to run on Windows without
extra browser/runtime dependencies.

## What it does

- Checks whether a URL looks like an independent site instead of a marketplace
  such as Amazon.
- Detects common review widgets from DOM/source/request-domain signals.
- Builds the matching public review API endpoint when required fields are
  available.
- Optionally fetches and normalizes review JSON into a common shape.
- Supports saved HTML files for local debugging.

## Supported review plugins

| Plugin | Detection signals | Strategy | Confidence |
| --- | --- | --- | --- |
| Bazaarvoice | `api.bazaarvoice.com`, Bazaarvoice markers | Extract `passkey` and `ProductId`, then call `/data/reviews.json`. | High |
| Yotpo | `yotpo.app_key`, Yotpo markers | Use public `app_key` and product sku/internal id with widget API. | High |
| Judge.me | `jdgm-widget`, Judge.me markers | Use Shopify shop domain and platform product id. | High |
| Okendo | `api.okendo.io`, Okendo markers | Call store/product REST endpoint and preserve buyer attributes when returned. | High |
| Trustpilot | `widget.trustpilot.com`, Trustpilot markers | Do not parse the obfuscated iframe. Fetch `trustpilot.com/review/{merchant-domain}` and parse JSON-LD reviews. | High |
| Loox | `loox.io/api`, Loox markers | Use Loox reviews API and preserve buyer image URLs when present. | Medium |

## Install on Windows

From the repository root:

```powershell
py -m pip install -e .
```

No third-party Python package is required for the current implementation.

## Usage

Detect independent-site status and review plugin:

```powershell
chemera-reviews "https://example.com/products/product-handle"
```

Fetch reviews with the best detected ready strategy:

```powershell
chemera-reviews "https://example.com/products/product-handle" --fetch-reviews --limit 50
```

Force one strategy:

```powershell
chemera-reviews "https://example.com/products/product-handle" --fetch-reviews --plugin judge.me
```

Debug with a saved HTML file:

```powershell
chemera-reviews "https://example.com/products/product-handle" --html-file .\page.html
```

The command prints JSON with:

- `analysis.site`: independent-site/platform/product signals
- `analysis.plugins`: detected plugins, evidence, endpoint, missing fields
- `result.reviews`: normalized reviews when `--fetch-reviews` is used

## Notes and limits

- The current detector works from the initial HTML/source and script URLs. Sites
  that render all widget configuration after client-side JavaScript execution
  may need a future Playwright/Selenium rendering layer.
- Amazon and other marketplaces are intentionally classified as non-independent
  sites by domain and skipped by the independent-site review plugin pipeline.
- Respect each site's terms, robots rules, rate limits, and privacy obligations.
  Prefer official APIs where available.
