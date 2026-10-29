"""Fielding: what the cards in a formation's deck draw from the world.

Owner, 2026-10-29: a copy of a card added to a deck takes its people and its
equipment from the world, and the equipment has to be carried to the
formation. A blueprint deck is a plan and draws nothing.

- Manpower comes from a pop. A large service is one cumulative pop ("US Army
  service members", ``pop_type: service``, with a ``faction``). A formation
  draws on its own ``manpower_pop``, else the nearest ancestor's, else its
  faction's first service pop. Nothing is written to the pop: its free
  headcount is its ``population_count`` less the people that every drawing
  deck on it holds.
- Equipment comes from depots: sites (``site_class: depot``) under a faction's
  control (``controlling_factions``) holding ``inventory_items`` ``[{item,
  quantity}]`` and ``vehicle_stock`` ``[{vehicle, quantity}]``. A formation
  draws on its ``supply_depot`` (or the nearest ancestor's) first, then on
  its faction's other depots. Stock leaves the depot at once.
- Each depot a formation draws on gets one ``logistics`` entity
  (``route_class: formation supply``, ``status: requested``) from the depot
  to the formation's ``location``, listing the cargo in ``cargo_manifest``.
  The depot lists it in ``outbound_logistics_routes``. This is the logistics
  demand the logistics simulation reads.
- What a pool cannot give is kept on the deck row as ``short`` (``{"people":
  n, "vehicle:<id>": n, "item:<id>": n}``) and the copy is fielded
  understrength. Removing a copy removes its shortfall first, so the weakest
  copy goes; then the people return to their pool and the equipment to its
  depot, and that part of the demand is cancelled.
"""

import re


SUPPLY_ROUTE_CLASS = "formation supply"
STOCK_FIELDS = {"vehicle": "vehicle_stock", "item": "inventory_items"}


def short_key(kind, reference):
    return f"{kind}:{reference}"


def _quantity(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class Fielding:
    def __init__(self, deck):
        self.deck = deck
        self.sim = deck.sim

    # ------------------------------------------------------------------
    # Where a formation draws from
    # ------------------------------------------------------------------

    def _ids(self, value):
        return self.sim._relation_ids(value)

    def draws(self, formation_id):
        entity = self.deck._entity(formation_id)
        return isinstance(entity, dict) and entity.get("formation_kind") != "blueprint"

    def _lineage(self, formation_id):
        seen = set()
        current = formation_id
        while current and current not in seen:
            seen.add(current)
            entity = self.deck._entity(current)
            if not isinstance(entity, dict):
                return
            yield entity
            parents = self._ids(entity.get("parents")) or self._ids(entity.get("parent_formation"))
            current = parents[0] if parents else None

    def _inherited(self, formation_id, field):
        for entity in self._lineage(formation_id):
            ids = self._ids(entity.get(field))
            if ids:
                return ids[0]
        return None

    def faction_id(self, formation_id):
        return self._inherited(formation_id, "faction")

    def manpower_pop_id(self, formation_id):
        pop_id = self._inherited(formation_id, "manpower_pop")
        if pop_id:
            return pop_id
        faction = self.faction_id(formation_id)
        if not faction:
            return None
        service = sorted(
            pop["id"] for pop in self.deck._dataset("pops")
            if pop.get("pop_type") == "service" and faction in self._ids(pop.get("faction"))
        )
        return service[0] if service else None

    def depot_ids(self, formation_id):
        depots = []
        own = self._inherited(formation_id, "supply_depot")
        if own:
            depots.append(own)
        faction = self.faction_id(formation_id)
        if faction:
            depots += sorted(
                location["id"] for location in self.deck._dataset("locations")
                if location.get("site_class") == "depot" and location["id"] not in depots
                and faction in self._ids(location.get("controlling_factions"))
            )
        return depots

    def destination_id(self, formation_id):
        return self._inherited(formation_id, "location")

    def label(self, entity_id):
        entity = self.deck._entity(entity_id)
        if isinstance(entity, dict):
            return self.sim._display_label(entity.get("pretty_name") or entity.get("name") or entity_id)
        return str(entity_id)

    # ------------------------------------------------------------------
    # Pools
    # ------------------------------------------------------------------

    def people_held(self, formation_id):
        held = 0
        for row in self.deck.deck_entries(formation_id):
            card = self.deck.card(row["card"])
            if card is not None:
                need = row["count"] * self.deck.card_totals(card)["people"]
                held += max(0, need - row["short"].get("people", 0))
        return held

    def pop_size(self, pop_id):
        pop = self.deck._entity(pop_id)
        return _quantity(pop.get("population_count")) if isinstance(pop, dict) else 0

    def pop_drawn(self, pop_id):
        return sum(
            self.people_held(formation["id"])
            for formation in self.sim._formation_entities()
            if isinstance(formation, dict) and formation.get("id") and self.draws(formation["id"])
            and self.manpower_pop_id(formation["id"]) == pop_id
        )

    def pop_free(self, pop_id):
        return max(0, self.pop_size(pop_id) - self.pop_drawn(pop_id))

    def stock(self, depot_id, kind, reference):
        depot = self.deck._entity(depot_id)
        rows = depot.get(STOCK_FIELDS[kind]) if isinstance(depot, dict) else None
        return sum(
            _quantity(row.get("quantity"))
            for row in (rows if isinstance(rows, (list, tuple)) else [])
            if isinstance(row, dict) and row.get(kind) == reference
        )

    def _change_stock(self, depot_id, kind, reference, delta):
        depot = self.deck._entity(depot_id)
        field = STOCK_FIELDS[kind]
        rows = [dict(row) for row in (depot.get(field) or []) if isinstance(row, dict)]
        row = next((row for row in rows if row.get(kind) == reference), None)
        if row is None:
            row = {kind: reference, "quantity": 0}
            rows.append(row)
        row["quantity"] = max(0, _quantity(row.get("quantity")) + delta)
        self.sim._save_entity_fields(depot_id, {field: rows})

    # ------------------------------------------------------------------
    # Logistics demand
    # ------------------------------------------------------------------

    def demand_id(self, formation_id, depot_id):
        slug = re.sub(r"[^a-z0-9]+", "_", f"{formation_id}_from_{depot_id}".casefold()).strip("_")
        return f"log_supply_{slug}"

    def demands(self, formation_id):
        return [
            entity for entity in self.deck._dataset("logistics")
            if entity.get("route_class") == SUPPLY_ROUTE_CLASS and formation_id in self._ids(entity.get("requested_by"))
        ]

    @staticmethod
    def _manifest(demand):
        return [dict(row) for row in (demand.get("cargo_manifest") or []) if isinstance(row, dict)]

    def _request(self, formation_id, depot_id, kind, reference, quantity):
        demand_id = self.demand_id(formation_id, depot_id)
        demand = self.deck._entity(demand_id)
        if not isinstance(demand, dict):
            destination = self.destination_id(formation_id)
            demand = {
                "id": demand_id, "_dataset": "logistics", "type": "logistics",
                "name": f"Supply for {self.deck.formation_label(formation_id)} from {self.label(depot_id)}",
                "route_class": SUPPLY_ROUTE_CLASS, "status": "requested",
                "origin_location": depot_id, "requested_by": formation_id,
                "cargo_manifest": [{"kind": kind, kind: reference, "quantity": quantity}],
                "associated_locations": [depot_id] + ([destination] if destination else []),
            }
            demand["pretty_name"] = demand["name"]
            if destination:
                demand["destination_location"] = destination
            loader = getattr(self.sim.world_model, "loader", None)
            if loader is None or not loader.persist_entity(demand):
                return False
            if hasattr(self.sim.world_model, "mark_repository_changed"):
                self.sim.world_model.mark_repository_changed([demand_id])
            depot = self.deck._entity(depot_id) or {}
            routes = self._ids(depot.get("outbound_logistics_routes"))
            if demand_id not in routes:
                self.sim._save_entity_fields(depot_id, {"outbound_logistics_routes": routes + [demand_id]})
            return True
        manifest = self._manifest(demand)
        row = next((row for row in manifest if row.get("kind") == kind and row.get(kind) == reference), None)
        if row is None:
            manifest.append({"kind": kind, kind: reference, "quantity": quantity})
        else:
            row["quantity"] = _quantity(row.get("quantity")) + quantity
        return self.sim._save_entity_fields(demand_id, {"cargo_manifest": manifest, "status": "requested"})

    def _cancel(self, formation_id, kind, reference, quantity):
        """Take ``quantity`` back out of this formation's open demands, last depot first, into the depots."""
        for demand in reversed(self.demands(formation_id)):
            if quantity <= 0:
                break
            if demand.get("status") != "requested":
                continue
            manifest = self._manifest(demand)
            row = next((row for row in manifest if row.get("kind") == kind and row.get(kind) == reference), None)
            if row is None:
                continue
            back = min(quantity, _quantity(row.get("quantity")))
            row["quantity"] = _quantity(row.get("quantity")) - back
            manifest = [row for row in manifest if _quantity(row.get("quantity")) > 0]
            fields = {"cargo_manifest": manifest}
            if not manifest:
                fields["status"] = "cancelled"
            self.sim._save_entity_fields(demand["id"], fields)
            depot_id = self._ids(demand.get("origin_location"))
            if depot_id:
                self._change_stock(depot_id[0], kind, reference, back)
            quantity -= back

    # ------------------------------------------------------------------
    # Fielding and standing down
    # ------------------------------------------------------------------

    def field(self, formation_id, card, copies=1):
        """Draw ``copies`` of the card. Returns what was taken, requested and left short."""
        draw = self.deck.card_draw(card)
        report = {"pop": self.manpower_pop_id(formation_id), "people": 0, "short": {}, "requested": {}}
        need = copies * sum(draw["people"].values())
        if need:
            free = self.pop_free(report["pop"]) if report["pop"] else 0
            report["people"] = min(need, free)
            if need > report["people"]:
                report["short"]["people"] = need - report["people"]
        depots = self.depot_ids(formation_id)
        for (kind, reference), quantity in draw["equipment"].items():
            remaining = copies * quantity
            for depot_id in depots:
                take = min(remaining, self.stock(depot_id, kind, reference))
                if take <= 0:
                    continue
                self._change_stock(depot_id, kind, reference, -take)
                self._request(formation_id, depot_id, kind, reference, take)
                report["requested"].setdefault(depot_id, []).append((kind, reference, take))
                remaining -= take
                if remaining <= 0:
                    break
            if remaining > 0:
                report["short"][short_key(kind, reference)] = remaining
        return report

    def stand_down(self, formation_id, card, short, copies=1):
        """Return ``copies`` of the card; ``short`` is the deck row's shortfall. Returns the new shortfall."""
        draw = self.deck.card_draw(card)
        short = dict(short or {})
        per_copy = sum(draw["people"].values())
        if per_copy:
            short["people"] = max(0, short.get("people", 0) - copies * per_copy)
        for (kind, reference), quantity in draw["equipment"].items():
            key = short_key(kind, reference)
            need = copies * quantity
            covered = min(short.get(key, 0), need)
            short[key] = short.get(key, 0) - covered
            self._cancel(formation_id, kind, reference, need - covered)
        return {key: value for key, value in short.items() if value > 0}

    def describe_short(self, short):
        parts = []
        for key, value in (short or {}).items():
            if key == "people":
                parts.append(f"{value} people")
                continue
            kind, _, reference = key.partition(":")
            label = self.deck.equipment_label({"kind": kind, kind: reference})
            parts.append(f"{value} {label}")
        return ", ".join(parts)

    def notice(self, card_label, report):
        pop = self.label(report["pop"]) if report["pop"] else None
        parts = []
        if report["people"]:
            parts.append(f"{report['people']} people from {pop}")
        for depot_id, rows in report["requested"].items():
            cargo = ", ".join(f"{quantity} {self.deck.equipment_label({'kind': kind, kind: reference})}"
                              for kind, reference, quantity in rows)
            parts.append(f"{cargo} requested from {self.label(depot_id)}")
        text = f"Fielded {card_label}"
        if report["short"]:
            text += f" understrength, short {self.describe_short(report['short'])}"
            if "people" in report["short"] and not report["pop"]:
                text += " (no manpower pool)"
        return text + (": " + "; ".join(parts) if parts else "") + "."
