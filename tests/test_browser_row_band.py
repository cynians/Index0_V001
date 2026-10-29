import unittest

from ui.knowledge_browser_model import KnowledgeBrowserModel
from ui.knowledge_browser_ui import KnowledgeBrowserUI


class EntityRowPaletteFieldTests(unittest.TestCase):
    def test_palette_fields_prefer_card_color_then_legacy_wiki_link_color(self):
        self.assertEqual(
            {"card_color": "#b2955d", "card_header_color": "#563775"},
            KnowledgeBrowserModel._entity_row_palette_fields(
                {"card_color": "#b2955d", "card_header_color": "#563775"}
            ),
        )
        self.assertEqual(
            {"card_color": "#123456", "card_header_color": None},
            KnowledgeBrowserModel._entity_row_palette_fields({"wiki_link_color": "#123456"}),
        )
        self.assertEqual(
            {"card_color": None, "card_header_color": None},
            KnowledgeBrowserModel._entity_row_palette_fields({}),
        )

    def test_tree_rows_carry_palette_fields(self):
        datasets = {
            "categories": [
                {"id": "cat_a", "name": "A", "type": "category", "_dataset": "categories"},
            ],
            "items": [
                {
                    "id": "item_gold",
                    "name": "Gold Item",
                    "type": "item",
                    "_dataset": "items",
                    "categories": ["cat_a"],
                    "card_color": "#b2955d",
                    "card_header_color": "#563775",
                },
            ],
        }

        class _WM:
            repository_revision = 0

            def get_dataset_names(self):
                return list(datasets)

            def get_entities_by_dataset(self, name):
                return list(datasets.get(name, []))

        class _Loader:
            @staticmethod
            def get_schema(_name):
                return None

        class _Host:
            IDEA_GENERIC_FIELDS = set()

            def __init__(self):
                self.world_model = _WM()
                self.schema_loader = _Loader()
                self.browser_tree_state = {}
                self.browser_period_filter = None
                self.browser_filter_dataset = "items"
                self.browser_filter_incomplete_only = False
                self.browser_search_query = ""

            @staticmethod
            def _coerce_card_year(value):
                return value

            @staticmethod
            def _entity_display_label(entity, fallback="unknown"):
                return entity.get("name") or fallback

        model = KnowledgeBrowserModel(_Host())
        rows = {r["entity_id"]: r for r in model._build_item_browser_items(model.world_model)}

        self.assertEqual("#b2955d", rows["item_gold"]["card_color"])
        self.assertEqual("#563775", rows["item_gold"]["card_header_color"])
        self.assertIsNone(rows["cat_a"]["card_color"])


class RowBandPaletteTests(unittest.TestCase):
    def setUp(self):
        self.ui = KnowledgeBrowserUI()
        self.ui.card_drafts = {}
        self.ui.DRAFT_CACHE_PATH = None
        self.ui._write_card_drafts = lambda: None

    def test_blend_rgb_is_a_linear_mix(self):
        self.assertEqual((0, 0, 0), self.ui._blend_rgb((0, 0, 0), (255, 255, 255), 0.0))
        self.assertEqual((255, 255, 255), self.ui._blend_rgb((0, 0, 0), (255, 255, 255), 1.0))
        self.assertEqual((128, 128, 128), self.ui._blend_rgb((0, 0, 0), (255, 255, 255), 0.5))

    def test_band_is_a_dark_tint_of_the_entity_main_colour(self):
        band, accent = self.ui._browser_row_band_palette(
            {"card_color": "#c8a000", "card_header_color": "#4060c0"}
        )
        # dark: every channel pulled well below the source colour
        self.assertLess(max(band), 140)
        # warm hue preserved -- red channel still clearly dominates blue
        self.assertGreater(band[0], band[2])
        # accent tracks the (cool) secondary colour instead
        self.assertGreater(accent[2], accent[0])

    def test_uncoloured_row_falls_back_to_the_default_dark_card_colour(self):
        band, _accent = self.ui._browser_row_band_palette({"card_color": None})
        self.assertLess(max(band), 60)


if __name__ == "__main__":
    unittest.main()
