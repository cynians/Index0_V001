import math
import unittest
from types import SimpleNamespace

from ui.knowledge_browser_ui import KnowledgeBrowserUI

CARD_W = 420
CARD_H = 340


def _isolated_browser_ui():
    ui = KnowledgeBrowserUI()
    # KnowledgeBrowserUI() loads/writes a real on-disk draft cache -- isolate it.
    ui.card_drafts = {}
    ui.DRAFT_CACHE_PATH = None
    ui._write_card_drafts = lambda: None
    return ui


def _stub_canvas(ui, neighbors_by_id, root_card):
    all_ids = {root_card["entity_id"]}
    for src, kids in neighbors_by_id.items():
        all_ids.add(src)
        all_ids.update(kids)

    ui.world_model = SimpleNamespace(
        get_entity=lambda _id: {"id": _id} if _id in all_ids else None,
        graph=None,
        touch_degrees=None,
        loader=SimpleNamespace(entities={_id: {"id": _id} for _id in all_ids}),
    )
    ui.cards = [root_card]
    ui._layout_all_cards = lambda: None
    ui._contemporary_entity_ids = lambda *a, **k: []
    ui._relation_tree_neighbor_ids = lambda eid: list(neighbors_by_id.get(eid, []))

    def ensure_card(entity, relayout=True, bring_to_front=True):
        eid = entity["id"]
        for card in ui.cards:
            if card["entity_id"] == eid:
                return card
        card = {"entity_id": eid, "canvas_w": CARD_W, "canvas_h": CARD_H,
                "canvas_x": 0, "canvas_y": 0}
        ui.cards.append(card)
        return card

    ui._ensure_card = ensure_card


def _rects(ui):
    return {
        c["entity_id"]: (c["canvas_x"], c["canvas_y"],
                         c["canvas_x"] + c.get("canvas_w", CARD_W),
                         c["canvas_y"] + c.get("canvas_h", CARD_H))
        for c in ui.cards
    }


def _centers(ui):
    return {
        eid: ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        for eid, (x0, y0, x1, y1) in _rects(ui).items()
    }


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _overlapping_pairs(ui):
    rects = list(_rects(ui).items())
    pairs = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if _overlap(rects[i][1], rects[j][1]):
                pairs.append((rects[i][0], rects[j][0]))
    return pairs


class RelationClusterLayoutTests(unittest.TestCase):
    def test_unconstrained_spawn_has_no_overlapping_cards(self):
        root_card = {"entity_id": "root", "canvas_w": CARD_W, "canvas_h": CARD_H,
                     "canvas_x": 4000, "canvas_y": 4000}
        neighbors = [f"n{i}" for i in range(12)]
        ui = _isolated_browser_ui()
        _stub_canvas(ui, {"root": neighbors}, root_card)
        ui.relation_tree_touch_degree = 1

        self.assertTrue(ui._open_relation_tree_for_card(root_card))
        self.assertEqual(len(_rects(ui)), 13)
        self.assertEqual(_overlapping_pairs(ui), [])

    def test_layout_is_a_disc_not_a_column(self):
        root_card = {"entity_id": "root", "canvas_w": CARD_W, "canvas_h": CARD_H,
                     "canvas_x": 4000, "canvas_y": 4000}
        neighbors = [f"n{i}" for i in range(12)]
        ui = _isolated_browser_ui()
        _stub_canvas(ui, {"root": neighbors}, root_card)
        ui.relation_tree_touch_degree = 1
        ui._open_relation_tree_for_card(root_card)

        xs = [x for x, _ in _centers(ui).values()]
        ys = [y for _, y in _centers(ui).values()]
        h_span = max(xs) - min(xs)
        v_span = max(ys) - min(ys)
        self.assertGreater(h_span, 2500)
        self.assertGreater(v_span, 2500)
        # Radial cluster: roughly as wide as it is tall (a column would be ~0 wide).
        self.assertGreater(min(h_span, v_span) / max(h_span, v_span), 0.6)

    def test_subtrees_are_separated_into_their_own_wedges(self):
        root_card = {"entity_id": "root", "canvas_w": CARD_W, "canvas_h": CARD_H,
                     "canvas_x": 6000, "canvas_y": 6000}
        ui = _isolated_browser_ui()
        _stub_canvas(
            ui,
            {"root": ["a", "b"],
             "a": ["a1", "a2", "a3"],
             "b": ["b1", "b2", "b3"]},
            root_card,
        )
        ui.relation_tree_touch_degree = 2
        ui._open_relation_tree_for_card(root_card)
        self.assertEqual(_overlapping_pairs(ui), [])

        centers = _centers(ui)

        def dist(p, q):
            return math.hypot(centers[p][0] - centers[q][0], centers[p][1] - centers[q][1])

        # Each cluster's members huddle around their own head, not the other one.
        for kid in ("a1", "a2", "a3"):
            self.assertLess(dist(kid, "a"), dist(kid, "b"))
        for kid in ("b1", "b2", "b3"):
            self.assertLess(dist(kid, "b"), dist(kid, "a"))

    def test_root_card_is_not_moved(self):
        root_card = {"entity_id": "root", "canvas_w": CARD_W, "canvas_h": CARD_H,
                     "canvas_x": 4000, "canvas_y": 4000}
        ui = _isolated_browser_ui()
        _stub_canvas(ui, {"root": ["a", "b", "c"]}, root_card)
        ui.relation_tree_touch_degree = 1
        ui._open_relation_tree_for_card(root_card)
        self.assertEqual((root_card["canvas_x"], root_card["canvas_y"]), (4000, 4000))

    def test_constrained_spawn_stays_bounded_and_only_crowds_the_outer_ring(self):
        root_card = {"entity_id": "root", "canvas_w": CARD_W, "canvas_h": CARD_H,
                     "canvas_x": 9000, "canvas_y": 9000}
        neighbors = [f"n{i}" for i in range(60)]
        ui = _isolated_browser_ui()
        _stub_canvas(ui, {"root": neighbors}, root_card)
        ui.relation_tree_touch_degree = 1
        ui._open_relation_tree_for_card(root_card)

        centers = _centers(ui)
        rx, ry = centers["root"]
        radii = [math.hypot(x - rx, y - ry) for e, (x, y) in centers.items() if e != "root"]
        # Radius cap keeps the cluster bounded even with 60 neighbours...
        self.assertLessEqual(max(radii), 8200)
        # ...and they all still sit on that single (outer) ring together.
        self.assertLess(max(radii) - min(radii), 50)


if __name__ == "__main__":
    unittest.main()
