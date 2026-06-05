import unittest

from chemera.review_plugins import analyze_page


class ReviewPluginDetectionTests(unittest.TestCase):
    def test_marketplace_domain_is_not_independent_site(self):
        analysis = analyze_page(
            "https://www.amazon.com/dp/B000000",
            "<html><body><div class='jdgm-widget'></div></body></html>",
        )

        self.assertFalse(analysis.site.is_independent_site)
        self.assertEqual(analysis.plugins, [])

    def test_bazaarvoice_endpoint_is_built_from_passkey_and_product_id(self):
        analysis = analyze_page(
            "https://brand.example/products/widget",
            """
            <script>
            window.bv = { passkey: "kuy-example", ProductId: "SKU-123" };
            </script>
            <script src="https://api.bazaarvoice.com/data/bv.js"></script>
            """,
        )

        detection = analysis.plugins[0]
        self.assertEqual(detection.plugin, "bazaarvoice")
        self.assertTrue(detection.is_ready)
        self.assertIn("passkey=kuy-example", detection.endpoint)
        self.assertIn("Filter=ProductId%3ASKU-123", detection.endpoint)

    def test_judgeme_uses_shopify_shop_and_product_id(self):
        analysis = analyze_page(
            "https://store.example/products/widget",
            """
            <script src="https://cdn.shopify.com/shop.js"></script>
            <script>Shopify.shop = "brand.myshopify.com";</script>
            <div class="jdgm-widget" data-id="987654321"></div>
            """,
        )

        detection = analysis.plugins[0]
        self.assertEqual(detection.plugin, "judge.me")
        self.assertTrue(detection.is_ready)
        self.assertIn("shop_domain=brand.myshopify.com", detection.endpoint)
        self.assertIn("platform_product_id=987654321", detection.endpoint)

    def test_trustpilot_redirects_to_merchant_review_page(self):
        analysis = analyze_page(
            "https://www.apple.com/store",
            '<iframe src="https://widget.trustpilot.com/trustboxes/abc"></iframe>',
        )

        detection = analysis.plugins[0]
        self.assertEqual(detection.plugin, "trustpilot")
        self.assertEqual(detection.endpoint, "https://www.trustpilot.com/review/apple.com")

    def test_loox_detection_keeps_medium_confidence_and_image_strategy(self):
        analysis = analyze_page(
            "https://brand.example/products/widget",
            """
            <script src="https://loox.io/api/widget.js?shop=brand.myshopify.com&pid=123"></script>
            <div class="loox-rating"></div>
            """,
        )

        detection = analysis.plugins[0]
        self.assertEqual(detection.plugin, "loox")
        self.assertEqual(detection.confidence, "medium")
        self.assertTrue(detection.is_ready)
        self.assertIn("shop=brand.myshopify.com", detection.endpoint)
        self.assertIn("pid=123", detection.endpoint)


if __name__ == "__main__":
    unittest.main()
