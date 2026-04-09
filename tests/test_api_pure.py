"""Tests for ShoppingListWithGrocyApi pure methods.

These tests cover methods that don't require a live HA instance or HTTP calls.
The API object is instantiated with a minimal stub config and a mock hass.
"""

import pytest
from unittest.mock import MagicMock


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_api(image_size=0, bidirectional=False):
    """Return an API instance with a minimal stub config, no real HTTP session."""
    from custom_components.shopping_list_with_grocy.apis.shopping_list_with_grocy import (
        ShoppingListWithGrocyApi,
    )

    hass = MagicMock()
    hass.config.language = "en"
    hass.data = {}

    session = MagicMock()
    config = {
        "api_url": "http://grocy.local",
        "api_key": "test-key",
        "image_download_size": image_size,
        "disable_timeout": False,
        "enable_bidirectional_sync": bidirectional,
    }
    api = ShoppingListWithGrocyApi(session, hass, config)
    return api


# ── encode_base64 ─────────────────────────────────────────────────────────────


class TestEncodeBase64:
    def test_simple_string(self):
        api = make_api()
        import base64

        assert api.encode_base64("hello") == base64.b64encode(b"hello").decode()

    def test_empty_string(self):
        api = make_api()
        assert api.encode_base64("") == ""

    def test_non_string_raises(self):
        api = make_api()
        with pytest.raises(TypeError):
            api.encode_base64(123)


# ── normalize_text_for_search ─────────────────────────────────────────────────


class TestNormalizeTextForSearch:
    def test_removes_accents(self):
        api = make_api()
        assert api.normalize_text_for_search("Pâtes") == "pates"

    def test_lowercases(self):
        api = make_api()
        assert api.normalize_text_for_search("LAIT") == "lait"

    def test_strips_whitespace(self):
        api = make_api()
        assert api.normalize_text_for_search("  beurre  ") == "beurre"

    def test_empty_string(self):
        api = make_api()
        assert api.normalize_text_for_search("") == ""

    def test_none_returns_empty(self):
        api = make_api()
        assert api.normalize_text_for_search(None) == ""

    def test_complex_accents(self):
        api = make_api()
        assert api.normalize_text_for_search("Crème fraîche") == "creme fraiche"


# ── calculate_similarity ──────────────────────────────────────────────────────


class TestCalculateSimilarity:
    def test_identical_strings(self):
        api = make_api()
        assert api.calculate_similarity("lait", "lait") == 1.0

    def test_completely_different(self):
        api = make_api()
        score = api.calculate_similarity("lait", "xyzxyz")
        assert score < 0.3

    def test_partial_match(self):
        api = make_api()
        score = api.calculate_similarity("lait", "lait entier")
        assert 0.5 < score < 1.0

    def test_case_insensitive(self):
        api = make_api()
        assert api.calculate_similarity("LAIT", "lait") == 1.0

    def test_accent_insensitive(self):
        api = make_api()
        score = api.calculate_similarity("pates", "Pâtes")
        assert score == 1.0

    def test_empty_strings_return_zero(self):
        api = make_api()
        assert api.calculate_similarity("", "lait") == 0.0
        assert api.calculate_similarity("lait", "") == 0.0


# ── is_case_only_difference ───────────────────────────────────────────────────


class TestIsCaseOnlyDifference:
    def test_case_difference(self):
        api = make_api()
        assert api.is_case_only_difference("lait", "Lait") is True

    def test_same_string(self):
        api = make_api()
        assert api.is_case_only_difference("lait", "lait") is False

    def test_different_content(self):
        api = make_api()
        assert api.is_case_only_difference("lait", "beurre") is False


# ── extract_product_name_from_ha_item ─────────────────────────────────────────


class TestExtractProductName:
    def test_name_with_quantity_pattern1(self):
        """'Lait (x3)' → ('Lait', 3)"""
        api = make_api()
        name, qty = api.extract_product_name_from_ha_item("Lait (x3)")
        assert name == "Lait"
        assert qty == 3

    def test_name_with_quantity_pattern1_unicode_times(self):
        """'Beurre (×2)' → ('Beurre', 2)"""
        api = make_api()
        name, qty = api.extract_product_name_from_ha_item("Beurre (×2)")
        assert name == "Beurre"
        assert qty == 2

    def test_name_with_leading_number_pattern2(self):
        """'3 Lait' → ('Lait', 3)"""
        api = make_api()
        name, qty = api.extract_product_name_from_ha_item("3 Lait")
        assert name == "Lait"
        assert qty == 3

    def test_plain_name_no_quantity(self):
        """'Lait' → ('Lait', 1)"""
        api = make_api()
        name, qty = api.extract_product_name_from_ha_item("Lait")
        assert name == "Lait"
        assert qty == 1

    def test_strips_whitespace(self):
        api = make_api()
        name, qty = api.extract_product_name_from_ha_item("  Lait  ")
        assert name == "Lait"
        assert qty == 1

    def test_multiword_name(self):
        api = make_api()
        name, qty = api.extract_product_name_from_ha_item("Crème fraîche (x1)")
        assert name == "Crème fraîche"
        assert qty == 1


# ── compute_timeout ───────────────────────────────────────────────────────────


class TestComputeTimeout:
    @pytest.mark.parametrize(
        "image_size,expected",
        [
            (0, 60),
            (50, 60),
            (100, 90),
            (150, 120),
            (200, 180),
        ],
    )
    def test_known_sizes(self, image_size, expected):
        api = make_api(image_size=image_size)
        assert api.compute_timeout() == expected

    def test_unknown_size_picks_nearest(self):
        """image_size=75 → nearest key is 50 → timeout 60."""
        api = make_api(image_size=75)
        assert api.compute_timeout() == 60


# ── build_item_list — note-only items (issue #73 regression) ──────────────────


class TestBuildItemList:
    """Regression tests for issue #73: Grocy items with product_id=None crash."""

    def _make_data(self, shopping_list_items):
        return {
            "shopping_lists": [{"id": 1, "name": "Liste principale"}],
            "products": [
                {
                    "id": "1",
                    "name": "Lait",
                    "qu_id_purchase": "1",
                    "qu_id_stock": "1",
                    "qu_factor_purchase_to_stock": 1.0,
                },
            ],
            "shopping_list": shopping_list_items,
        }

    def test_normal_item(self):
        api = make_api()
        data = self._make_data(
            [
                {
                    "id": "10",
                    "product_id": "1",
                    "shopping_list_id": 1,
                    "amount": 2,
                    "done": 0,
                },
            ]
        )
        result = api.build_item_list(data)
        assert len(result) == 1
        assert len(result[0]["products"]) == 1
        assert "Lait" in result[0]["products"][0]["name"]

    def test_note_only_item_does_not_crash(self):
        """A shopping list entry with product_id=None must not raise TypeError."""
        api = make_api()
        data = self._make_data(
            [
                {
                    "id": "99",
                    "product_id": None,
                    "shopping_list_id": 1,
                    "amount": 1,
                    "done": 0,
                },
            ]
        )
        # Should not raise
        result = api.build_item_list(data)
        assert isinstance(result, list)
        # The note-only item has no product match → list is empty
        assert result[0]["products"] == []

    def test_mixed_normal_and_note_only(self):
        """Normal items are listed; note-only items are silently skipped."""
        api = make_api()
        data = self._make_data(
            [
                {
                    "id": "10",
                    "product_id": "1",
                    "shopping_list_id": 1,
                    "amount": 1,
                    "done": 0,
                },
                {
                    "id": "99",
                    "product_id": None,
                    "shopping_list_id": 1,
                    "amount": 1,
                    "done": 0,
                },
            ]
        )
        result = api.build_item_list(data)
        assert len(result[0]["products"]) == 1


# ── find_similar_products ─────────────────────────────────────────────────────


class TestFindSimilarProducts:
    def _setup_api_with_products(self, products):
        api = make_api()
        api.final_data = {
            "products": [{"id": str(i), "name": p} for i, p in enumerate(products)]
        }
        return api

    def test_finds_exact_match(self):
        api = self._setup_api_with_products(["Lait", "Beurre", "Fromage"])
        results = api.find_similar_products("Lait", threshold=0.8)
        assert len(results) >= 1
        assert results[0]["name"] == "Lait"

    def test_finds_fuzzy_match(self):
        api = self._setup_api_with_products(["Lait entier", "Beurre doux"])
        results = api.find_similar_products("lait", threshold=0.5)
        names = [r["name"] for r in results]
        assert "Lait entier" in names

    def test_no_match_returns_empty(self):
        api = self._setup_api_with_products(["Lait", "Beurre"])
        results = api.find_similar_products("xyzxyz", threshold=0.9)
        assert results == []

    def test_results_sorted_by_similarity(self):
        api = self._setup_api_with_products(["Lait entier", "Lait"])
        results = api.find_similar_products("Lait", threshold=0.5)
        scores = [r["similarity"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_search_returns_empty(self):
        api = self._setup_api_with_products(["Lait"])
        assert api.find_similar_products("") == []

    def test_no_products_returns_empty(self):
        api = make_api()
        api.final_data = {}
        assert api.find_similar_products("Lait") == []
