"""Formation Sim: intent, context, and current implementation state.

Intent
------
Formation Sim is the situated workspace for designing and inspecting any
formation scale, from a Roman legion or mechanized force to an interstellar
fleet. It is deliberately generic: ``formation`` is the only prescribed
structural term; all subordinate labels are player-authored and may differ
between eras, cultures, and settings.

Context
-------
The workspace is card-launched and navigates downward through durable
formation parent/child relations. A structural parent and a faction owner are
separate facts: every created formation must belong to a faction, and that
faction may differ from the formation's structural parent. The faction anchor
establishes which equipment, doctrine, strategic context, and knowledge are
available. Formation Blueprints are faction-specific designs; realizations are
concrete formations that may be created from a blueprint and then diverge.

Current implementation state
-----------------------------
The prototype provides aggregate, formation, and personnel display scales;
clickable tree navigation with a ``To parent`` action; drag reordering; typed
point-in-time viewing defaulting to year 2400; sparse formation snapshots only
when a blueprint state changes; faction-owned blueprint creation; creation from
blueprints; and a blueprint editor for personnel and equipment. Assigned
vehicles are shown only when linked to a formation and expose side-image and
grouped crew-role data when available. Legacy wiki formation outlines remain a
temporary projection for older cards, while authored parent/child edges are
authoritative. Faction selection is searchable and scrollable so the same
interaction can scale to large faction catalogs.

The next layers—full organization editing, faction-aware equipment filtering,
knowledge-gated faction discovery, detailed personnel mannequins, and richer
deviation/history semantics—remain intentionally staged work.
"""

import re
import unicodedata

import pygame

from world.temporal import (
    DEFAULT_SIMULATION_YEAR,
    entity_available_at,
    entity_year_range,
    latest_formation_snapshot,
)


class FormationSimulation:
    """Interactive formation hierarchy and semantic-zoom prototype."""

    DISPLAY_SCALES = ("aggregate", "formation", "personnel")

    def __init__(self, world_model=None, formation_id=None, year=DEFAULT_SIMULATION_YEAR):
        self.world_model = world_model
        self.formation_id = formation_id
        self.year = int(year) if year is not None else DEFAULT_SIMULATION_YEAR
        self.render_mode = "formation"
        self.show_time_ui = False
        self.suppress_global_overlays = True
        self.free_camera_pan = True
        self.world_units_to_meters = 1.0
        self.min_zoom = 1.0
        self.max_zoom = 1.0
        self.preferred_zoom = 1.0
        self.sim_clock = _StaticClock()

        self.hover_node_id = None
        self.hitboxes = {}
        self.viewport_size = (1200, 800)
        self.pending_navigation_action = None
        self.creation_menu_active = False
        self.blueprint_selection_active = False
        self.creation_active = False
        self.creation_buffer = ""
        self.creation_parent_id = None
        self.creation_mode = None
        self.creation_blueprint_id = None
        self.creation_faction_id = None
        self.faction_selection_active = False
        self.faction_picker_offset = 0
        self.faction_search_buffer = ""
        self.faction_search_active = False
        self.creation_cursor = 0
        self.name_field_focused = False
        self.year_editing = False
        self.year_buffer = ""
        self.personnel_editing = False
        self.personnel_buffer = ""
        self.blueprint_editor_section = "equipment"
        self._draft_counter = 0
        self.drag_press_node_id = None
        self.drag_press_pos = None
        self.dragging_node_id = None

        self.structure = self._build_structure()
        self.selected_node_id = self.structure["id"]
        self.display_scale = "aggregate"

    @property
    def root_name(self):
        entity = self.world_model.get_entity(self.formation_id) if self.world_model else None
        if isinstance(entity, dict):
            return entity.get("pretty_name") or entity.get("name") or self.formation_id or "Formation"
        return self.formation_id or "Formation"

    def _relation_ids(self, value):
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, dict):
            candidate = value.get("id") or value.get("entity_id")
            return [candidate] if candidate else []
        if isinstance(value, (list, tuple, set)):
            result = []
            for item in value:
                for entity_id in self._relation_ids(item):
                    if entity_id not in result:
                        result.append(entity_id)
            return result
        return []

    @staticmethod
    def _normalized_label(value):
        value = unicodedata.normalize("NFKC", str(value or ""))
        return " ".join(value.casefold().split())

    @staticmethod
    def _display_label(value):
        # A handful of legacy cards contain a replacement character in names.
        # Keep the stored value untouched, but make the common German label
        # readable in the formation workspace.
        return str(value or "").replace("\ufffd", "ä")

    def _formation_entities(self):
        get_dataset = getattr(self.world_model, "get_dataset", None) if self.world_model else None
        if not callable(get_dataset):
            return []
        entities = get_dataset("formations") or []
        return list(entities.values()) if isinstance(entities, dict) else list(entities)

    def _resolve_formation_reference(self, reference):
        reference = str(reference or "").strip()
        if not reference:
            return None
        direct = self.world_model.get_entity(reference) if self.world_model else None
        if isinstance(direct, dict) and (
            direct.get("_dataset") == "formations" or direct.get("type") == "formation"
        ):
            return direct
        wanted = self._normalized_label(reference)
        for entity in self._formation_entities():
            if not isinstance(entity, dict):
                continue
            labels = (entity.get("name"), entity.get("pretty_name"), entity.get("id"))
            if any(self._normalized_label(label) == wanted for label in labels):
                return entity
        return None

    def _wiki_formation_outline(self, entity):
        """Read the legacy card's explicit Formation section into descriptors."""
        wiki_entry = str(entity.get("wiki_entry") or "")
        section_match = re.search(
            r"(?ims)^!\s*formations\s*(.*?)(?=^!\s+|\Z)",
            wiki_entry,
        )
        if not section_match:
            return []

        groups = []
        current = None
        for raw_line in section_match.group(1).splitlines():
            line = raw_line.strip()
            links = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", line)
            if not links:
                continue
            if line.startswith("!!"):
                current = {"label": links[0].strip(), "children": []}
                groups.append(current)
            elif current is not None:
                current["children"].append(links[0].strip())
        return groups

    def _descriptor_node(self, parent_id, reference, ancestry):
        entity = self._resolve_formation_reference(reference)
        if entity is not None:
            entity_id = entity.get("id")
            return self._entity_node(entity_id, ancestry) if entity_id else None

        self._draft_counter += 1
        return {
            "id": f"unlinked:{parent_id}:{self._draft_counter}",
            "label": self._display_label(reference),
            "kind": "formation",
            "personnel": None,
            "children": [],
            "is_unlinked": True,
            "source_reference": reference,
        }

    @staticmethod
    def _node_reference_key(node):
        return node.get("entity_id") or node.get("source_reference") or node.get("id")

    def _wiki_children_for_entity(self, entity, entity_id, ancestry):
        outlines = self._wiki_formation_outline(entity)
        if not outlines:
            # Some legacy child cards are empty even though their parent card
            # names their contents. Reconstruct only the explicitly named
            # references that point back to this formation.
            for candidate in self._formation_entities():
                if not isinstance(candidate, dict):
                    continue
                for group in self._wiki_formation_outline(candidate):
                    group_entity = self._resolve_formation_reference(group["label"])
                    if group_entity and group_entity.get("id") == entity_id:
                        outlines.append({"label": group["label"], "children": group["children"]})

        children = []
        for group in outlines:
            # When this card is itself the named group, its listed references
            # are its children; do not add the group as a child of itself.
            if self._resolve_formation_reference(group["label"]):
                group_entity = self._resolve_formation_reference(group["label"])
                if group_entity and group_entity.get("id") == entity_id:
                    existing_keys = {self._node_reference_key(node) for node in children}
                    for reference in group["children"]:
                        child = self._descriptor_node(entity_id, reference, ancestry)
                        if child is not None and self._node_reference_key(child) not in existing_keys:
                            children.append(child)
                            existing_keys.add(self._node_reference_key(child))
                    continue
            group_node = self._descriptor_node(entity_id, group["label"], ancestry)
            if group_node is None:
                continue
            existing_keys = {
                self._node_reference_key(node) for node in group_node.get("children", [])
            }
            for reference in group["children"]:
                child = self._descriptor_node(group_node["id"], reference, ancestry | {entity_id})
                if child is not None and self._node_reference_key(child) not in existing_keys:
                    group_node.setdefault("children", []).append(child)
                    existing_keys.add(self._node_reference_key(child))
            children.append(group_node)
        return children

    def _children_for_entity(self, entity_id):
        entity = self.world_model.get_entity(entity_id) if self.world_model else None
        if not isinstance(entity, dict):
            return []

        state = latest_formation_snapshot(entity, self.year)
        child_ids = self._relation_ids(
            state.get("organization") if isinstance(state, dict) else entity.get("offspring")
        )
        if isinstance(state, dict) and "organization" in state:
            return child_ids
        if not child_ids and not isinstance(state, dict):
            child_ids = self._relation_ids(entity.get("offspring"))
        if child_ids:
            return child_ids

        # Some older records only carry the child-side parent relation.
        for candidate in self._formation_entities():
            if entity_id in self._relation_ids(candidate.get("parents")):
                child_id = candidate.get("id")
                if child_id and child_id not in child_ids:
                    child_ids.append(child_id)
        indexed_ids = {child_id: index for index, child_id in enumerate(child_ids)}

        def sort_key(child_id):
            child = self.world_model.get_entity(child_id) if self.world_model else None
            order = child.get("formation_order") if isinstance(child, dict) else None
            try:
                return (0, int(order), indexed_ids[child_id])
            except (TypeError, ValueError):
                return (1, indexed_ids[child_id], indexed_ids[child_id])

        return sorted(child_ids, key=sort_key)

    def _entity_available_at_view_year(self, entity):
        return entity_available_at(entity, self.year)

    def _entity_node(self, entity_id, ancestry=None):
        ancestry = set(ancestry or set())
        if entity_id in ancestry:
            return None
        entity = self.world_model.get_entity(entity_id) if self.world_model else None
        if not isinstance(entity, dict):
            return None

        next_ancestry = ancestry | {entity_id}
        state = latest_formation_snapshot(entity, self.year)
        state = state if isinstance(state, dict) else {}
        children = []
        for child_id in self._children_for_entity(entity_id):
            child = self._entity_node(child_id, next_ancestry)
            if child is not None:
                children.append(child)

        # The Kaiserheer and similar legacy cards describe hierarchy in their
        # wiki section before the relation fields were authored. Use those
        # explicit references as a temporary projection, merging in durable
        # edges without inventing a division taxonomy.
        wiki_children = self._wiki_children_for_entity(entity, entity_id, next_ancestry)
        if not children:
            children = wiki_children
        else:
            existing_by_id = {child.get("id"): child for child in children}
            for wiki_child in wiki_children:
                existing = existing_by_id.get(wiki_child.get("id"))
                if existing is None:
                    children.append(wiki_child)
                    existing_by_id[wiki_child.get("id")] = wiki_child
                elif not existing.get("children") and wiki_child.get("children"):
                    existing["children"] = wiki_child["children"]

        equipment = self._equipment_for_entity(entity)
        for item_id in self._relation_ids(entity.get("equipment_items")):
            item = self.world_model.get_entity(item_id) if self.world_model else None
            if isinstance(item, dict):
                label = self._display_label(item.get("pretty_name") or item.get("name") or item_id)
                if label not in equipment:
                    equipment.append(label)

        return {
            "id": entity_id,
            "entity_id": entity_id,
            "label": self._display_label(entity.get("pretty_name") or entity.get("name") or entity_id),
            "kind": "formation",
            "personnel": state.get("personnel", entity.get("personnel") or entity.get("strength")),
            "children": children,
            "start_year": entity.get("start_year"),
            "end_year": entity.get("end_year"),
            "year_range": entity_year_range(entity),
            "is_available": self._entity_available_at_view_year(entity),
            "formation_kind": entity.get("formation_kind") or "realization",
            "faction_id": (
                self._relation_ids(entity.get("faction"))[0]
                if self._relation_ids(entity.get("faction")) else None
            ),
            "faction_label": self._faction_label(entity.get("faction")),
            "parents": self._relation_ids(entity.get("parents")),
            "related": self._relation_ids(entity.get("related")),
            "equipment": equipment,
            "vehicles": [
                vehicle
                for vehicle in (
                    self._vehicle_node(vehicle_id)
                    for vehicle_id in self._vehicle_ids_for_entity(entity_id, entity)
                )
                if vehicle is not None
            ],
            "blueprints": [
                blueprint
                for blueprint in (
                    self._blueprint_node(blueprint_id)
                    for blueprint_id in self._relation_ids(entity.get("blueprints"))
                )
                if blueprint is not None
            ],
            "blueprint_items": [
                item
                for item in (
                    self._item_node(item_id)
                    for item_id in self._relation_ids(
                        state.get("blueprint_items", entity.get("blueprint_items"))
                    )
                )
                if item is not None
            ],
            "formation_snapshots": list(entity.get("formation_snapshots") or []),
        }

    def _faction_label(self, value):
        faction_ids = self._relation_ids(value)
        if not faction_ids or not self.world_model:
            return None
        faction = self.world_model.get_entity(faction_ids[0])
        if not isinstance(faction, dict):
            return None
        return self._display_label(faction.get("pretty_name") or faction.get("name") or faction_ids[0])

    def get_parent_formation_id(self):
        entity = self.world_model.get_entity(self.formation_id) if self.world_model else None
        if not isinstance(entity, dict):
            return None
        for parent_id in self._relation_ids(entity.get("parents")):
            parent = self.world_model.get_entity(parent_id) if self.world_model else None
            if isinstance(parent, dict) and (
                parent.get("_dataset") == "formations" or parent.get("type") == "formation"
            ):
                return parent_id
        for candidate in self._formation_entities():
            if self.formation_id in self._relation_ids(candidate.get("offspring")):
                return candidate.get("id")
            if self.formation_id in self._relation_ids(candidate.get("children")):
                return candidate.get("id")
        return None

    def _equipment_for_entity(self, entity):
        equipment = []
        for reference in self._relation_ids(entity.get("related")):
            related = self.world_model.get_entity(reference) if self.world_model else None
            if isinstance(related, dict) and (
                related.get("_dataset") == "vehicles" or related.get("type") == "vehicle"
            ):
                label = related.get("pretty_name") or related.get("name") or reference
                equipment.append(self._display_label(label))
        return equipment

    def _vehicle_entities(self):
        get_dataset = getattr(self.world_model, "get_dataset", None) if self.world_model else None
        if not callable(get_dataset):
            return []
        entities = get_dataset("vehicles") or []
        return list(entities.values()) if isinstance(entities, dict) else list(entities)

    def _vehicle_ids_for_entity(self, entity_id, entity):
        vehicle_ids = self._relation_ids(entity.get("vehicles"))
        for vehicle in self._vehicle_entities():
            if not isinstance(vehicle, dict):
                continue
            references = self._relation_ids(vehicle.get("operated_by"))
            references += self._relation_ids(vehicle.get("operators"))
            vehicle_id = vehicle.get("id")
            if entity_id in references and vehicle_id and vehicle_id not in vehicle_ids:
                vehicle_ids.append(vehicle_id)
        return vehicle_ids

    def _vehicle_node(self, vehicle_id):
        vehicle = self.world_model.get_entity(vehicle_id) if self.world_model else None
        if not isinstance(vehicle, dict):
            return None

        roles = vehicle.get("crew_roles") or []
        if isinstance(roles, dict):
            roles = [{"role": role, "count": count} for role, count in roles.items()]
        normalized_roles = []
        for role in roles if isinstance(roles, (list, tuple)) else []:
            if isinstance(role, str):
                role = {"role": role, "count": 1}
            if not isinstance(role, dict):
                continue
            label = str(role.get("role") or role.get("name") or "Crew").strip() or "Crew"
            try:
                count = max(0, int(role.get("count", role.get("number", 1))))
            except (TypeError, ValueError):
                count = 1
            normalized_roles.append({"role": label, "count": count})
        if not normalized_roles and vehicle.get("crew_complement") is not None:
            try:
                normalized_roles = [{"role": "Crew", "count": max(0, int(vehicle["crew_complement"]))}]
            except (TypeError, ValueError):
                normalized_roles = []

        label = vehicle.get("pretty_name") or vehicle.get("name") or vehicle_id
        return {
            "id": vehicle_id,
            "entity_id": vehicle_id,
            "label": self._display_label(label),
            "kind": "vehicle",
            "vehicle_class": vehicle.get("vehicle_class") or "vehicle",
            "profile": vehicle.get("formation_display_profile") or vehicle.get("vehicle_class") or "vehicle",
            "side_image": vehicle.get("card_image_side"),
            "crew_complement": vehicle.get("crew_complement"),
            "crew_roles": normalized_roles,
            "start_year": vehicle.get("start_year"),
            "end_year": vehicle.get("end_year"),
            "year_range": entity_year_range(vehicle),
            "is_available": self._entity_available_at_view_year(vehicle),
        }

    def _item_entities(self):
        get_dataset = getattr(self.world_model, "get_dataset", None) if self.world_model else None
        if not callable(get_dataset):
            return []
        entities = get_dataset("items") or []
        return list(entities.values()) if isinstance(entities, dict) else list(entities)

    def _item_node(self, item_id):
        item = self.world_model.get_entity(item_id) if self.world_model else None
        if not isinstance(item, dict):
            return None
        return {
            "id": item_id,
            "entity_id": item_id,
            "label": self._display_label(item.get("pretty_name") or item.get("name") or item_id),
            "kind": "item",
            "item_class": item.get("item_class") or "item",
            "start_year": item.get("start_year"),
            "end_year": item.get("end_year"),
            "year_range": entity_year_range(item),
            "is_available": self._entity_available_at_view_year(item),
        }

    def _blueprint_node(self, blueprint_id):
        blueprint = self.world_model.get_entity(blueprint_id) if self.world_model else None
        if not isinstance(blueprint, dict):
            return None
        item_ids = self._relation_ids(blueprint.get("blueprint_items"))
        faction_id = self._relation_ids(blueprint.get("faction"))
        faction = self.world_model.get_entity(faction_id[0]) if faction_id and self.world_model else None
        return {
            "id": blueprint_id,
            "entity_id": blueprint_id,
            "label": self._display_label(blueprint.get("pretty_name") or blueprint.get("name") or blueprint_id),
            "kind": "blueprint",
            "formation_kind": "blueprint",
            "start_year": blueprint.get("start_year"),
            "end_year": blueprint.get("end_year"),
            "year_range": entity_year_range(blueprint),
            "is_available": self._entity_available_at_view_year(blueprint),
            "faction_id": faction_id[0] if faction_id else None,
            "faction_label": (
                self._display_label(faction.get("pretty_name") or faction.get("name") or faction_id[0])
                if isinstance(faction, dict) else None
            ),
            "items": [
                item
                for item in (self._item_node(item_id) for item_id in item_ids)
                if item is not None
            ],
        }

    def _build_structure(self):
        root = self._entity_node(self.formation_id) if self.formation_id else None
        if root is None:
            root = {
                "id": self.formation_id or "formation_root",
                "label": self.root_name,
                "kind": "formation",
                "children": [],
                "vehicles": [],
                "blueprints": [],
            }
        return root

    def update(self, dt):
        """The first prototype has no autonomous formation simulation yet."""

    def consumes_global_keydown(self):
        return (
            self.creation_active
            or self.year_editing
            or self.personnel_editing
            or (self.faction_selection_active and self.faction_search_active)
        )

    def handle_event(self, event):
        if event.type != pygame.KEYDOWN:
            return False

        if self.year_editing:
            if event.key == pygame.K_ESCAPE:
                self.year_editing = False
                self.year_buffer = ""
                return True
            if event.key == pygame.K_RETURN:
                try:
                    self.set_year(int(self.year_buffer))
                except (TypeError, ValueError):
                    pass
                self.year_editing = False
                self.year_buffer = ""
                return True
            if event.key == pygame.K_BACKSPACE:
                self.year_buffer = self.year_buffer[:-1]
                return True
            character = getattr(event, "unicode", "")
            if character.isdigit() or (character == "-" and not self.year_buffer):
                if len(self.year_buffer) < 8:
                    self.year_buffer += character
            return True

        if self.personnel_editing:
            if event.key == pygame.K_ESCAPE:
                self.personnel_editing = False
                self.personnel_buffer = ""
                return True
            if event.key == pygame.K_RETURN:
                try:
                    value = max(0, int(self.personnel_buffer))
                except (TypeError, ValueError):
                    value = None
                if value is not None:
                    self._update_blueprint_fields({"personnel": value})
                self.personnel_editing = False
                self.personnel_buffer = ""
                return True
            if event.key == pygame.K_BACKSPACE:
                self.personnel_buffer = self.personnel_buffer[:-1]
                return True
            character = getattr(event, "unicode", "")
            if character.isdigit() and len(self.personnel_buffer) < 8:
                self.personnel_buffer += character
            return True

        if self.faction_selection_active and self.faction_search_active:
            if event.key == pygame.K_ESCAPE:
                self.cancel_creation()
                return True
            if event.key == pygame.K_BACKSPACE:
                self.faction_search_buffer = self.faction_search_buffer[:-1]
                self.faction_picker_offset = 0
                return True
            if event.key == pygame.K_RETURN:
                options = self._filtered_faction_options()
                if len(options) == 1:
                    self.choose_faction(options[0].get("id"))
                return True
            character = getattr(event, "unicode", "")
            if character and character.isprintable() and len(self.faction_search_buffer) < 80:
                self.faction_search_buffer += character
                self.faction_picker_offset = 0
            return True

        if not self.creation_active:
            return False
        if event.key == pygame.K_ESCAPE:
            self.cancel_creation()
            return True
        if event.key == pygame.K_RETURN:
            self.commit_creation()
            return True
        if event.key == pygame.K_BACKSPACE:
            if self.creation_cursor > 0:
                self.creation_buffer = (
                    self.creation_buffer[: self.creation_cursor - 1]
                    + self.creation_buffer[self.creation_cursor:]
                )
                self.creation_cursor -= 1
            return True
        if event.key == pygame.K_DELETE:
            if self.creation_cursor < len(self.creation_buffer):
                self.creation_buffer = (
                    self.creation_buffer[: self.creation_cursor]
                    + self.creation_buffer[self.creation_cursor + 1:]
                )
            return True
        if event.key == pygame.K_LEFT:
            self.creation_cursor = max(0, self.creation_cursor - 1)
            return True
        if event.key == pygame.K_RIGHT:
            self.creation_cursor = min(len(self.creation_buffer), self.creation_cursor + 1)
            return True
        if event.key == pygame.K_HOME:
            self.creation_cursor = 0
            return True
        if event.key == pygame.K_END:
            self.creation_cursor = len(self.creation_buffer)
            return True
        character = getattr(event, "unicode", "")
        if character and character.isprintable() and len(self.creation_buffer) < 64:
            self.creation_buffer = (
                self.creation_buffer[: self.creation_cursor]
                + character
                + self.creation_buffer[self.creation_cursor:]
            )
            self.creation_cursor += len(character)
        return True

    def draw(self):
        """Rendering is dispatched through FormationRenderer."""

    def get_center(self):
        return 0.0, 0.0

    def get_initial_camera_zoom(self, screen_w, screen_h):
        return 1.0

    def consumes_camera_update(self):
        return True

    def handle_pre_camera_event(self, event):
        # Formation Sim is a screen-space workspace; display scale is changed
        # through its own controls instead of the global world camera.
        return event.type == pygame.MOUSEWHEEL

    def get_title(self):
        return f"Formation Sim: {self.root_name}"

    def get_display_model(self):
        return {
            "root": self.structure,
            "selected_node_id": self.selected_node_id,
            "display_scale": self.display_scale,
            "year": self.year,
            "hover_node_id": self.hover_node_id,
            "creation_active": self.creation_active,
            "creation_menu_active": self.creation_menu_active,
            "blueprint_selection_active": self.blueprint_selection_active,
            "faction_selection_active": self.faction_selection_active,
            "creation_buffer": self.creation_buffer,
            "creation_cursor": self.creation_cursor,
            "name_field_focused": self.name_field_focused,
            "year_editing": self.year_editing,
            "blueprint_editor_section": self.blueprint_editor_section,
        }

    def set_year(self, year):
        """Change the Formation Sim's point-in-time view and rebuild its projection."""
        try:
            normalized_year = int(year)
        except (TypeError, ValueError):
            return False
        if normalized_year == self.year:
            return False
        self.year = normalized_year
        selected_id = self.selected_node_id
        self.structure = self._build_structure()
        self.selected_node_id = selected_id if self._find_node(selected_id) else self.structure["id"]
        return True

    def _walk(self, node):
        yield node
        for child in node.get("children", []):
            yield from self._walk(child)

    def _find_node(self, node_id):
        for node in self._walk(self.structure):
            if node.get("id") == node_id:
                return node
        return None

    def _find_parent(self, node_id, node=None):
        node = self.structure if node is None else node
        for child in node.get("children", []):
            if child.get("id") == node_id:
                return node
            parent = self._find_parent(node_id, child)
            if parent is not None:
                return parent
        return None

    def _scale_for_node(self, node):
        if node is None or node.get("id") == self.structure.get("id"):
            return "aggregate"
        return "formation" if node.get("children") else "personnel"

    def set_viewport(self, width, height):
        self.viewport_size = (max(1, int(width)), max(1, int(height)))

    def set_hitboxes(self, hitboxes):
        self.hitboxes = dict(hitboxes or {})

    def open_creation_menu(self, parent_id=None):
        parent_id = parent_id or self.selected_node_id
        if self._find_node(parent_id) is None:
            return False
        self.creation_parent_id = parent_id
        self.creation_menu_active = True
        self.blueprint_selection_active = False
        self.creation_active = False
        self.faction_picker_offset = 0
        self.faction_search_buffer = ""
        self.faction_search_active = False
        return True

    def _blueprint_options(self, parent_id=None):
        parent = self.world_model.get_entity(parent_id) if self.world_model and parent_id else None
        ids = self._relation_ids(parent.get("blueprints")) if isinstance(parent, dict) else []
        for entity in self._formation_entities():
            if entity.get("formation_kind") == "blueprint" and entity.get("id") not in ids:
                ids.append(entity.get("id"))
        options = []
        for blueprint_id in ids:
            node = self._blueprint_node(blueprint_id)
            if node is not None:
                options.append(node)
        return options

    def _faction_options(self):
        get_dataset = getattr(self.world_model, "get_dataset", None) if self.world_model else None
        if not callable(get_dataset):
            return []
        factions = get_dataset("factions") or []
        factions = list(factions.values()) if isinstance(factions, dict) else list(factions)
        return [
            faction for faction in factions
            if isinstance(faction, dict) and faction.get("id")
        ]

    def _filtered_faction_options(self):
        query = self._normalized_label(self.faction_search_buffer)
        if not query:
            return self._faction_options()
        return [
            faction
            for faction in self._faction_options()
            if query in self._normalized_label(
                " ".join(str(faction.get(field) or "") for field in ("pretty_name", "name", "id"))
            )
        ]

    def choose_creation_mode(self, mode):
        if not self.creation_menu_active:
            return False
        self.creation_menu_active = False
        if mode == "new_formation":
            self.creation_mode = "formation"
            self.faction_selection_active = True
            self.faction_picker_offset = 0
            self.faction_search_buffer = ""
            self.faction_search_active = True
            return True
        if mode == "new_blueprint":
            self.creation_mode = "blueprint"
            self.faction_selection_active = True
            self.faction_picker_offset = 0
            self.faction_search_buffer = ""
            self.faction_search_active = True
            return True
        if mode == "from_blueprint":
            self.blueprint_selection_active = True
            return True
        return False

    def choose_blueprint(self, blueprint_id):
        if not self.blueprint_selection_active:
            return False
        if not any(node.get("id") == blueprint_id for node in self._blueprint_options(self.creation_parent_id)):
            return False
        self.blueprint_selection_active = False
        blueprint = self._blueprint_node(blueprint_id)
        self.creation_blueprint_id = blueprint_id
        self.creation_mode = "from_blueprint"
        self.creation_buffer = blueprint.get("label", "") if blueprint else ""
        self.creation_cursor = len(self.creation_buffer)
        self.name_field_focused = False
        self.faction_selection_active = True
        self.faction_picker_offset = 0
        self.faction_search_buffer = ""
        self.faction_search_active = True
        self.creation_active = False
        return True

    def choose_faction(self, faction_id):
        if not self.faction_selection_active:
            return False
        if not any(faction.get("id") == faction_id for faction in self._filtered_faction_options()):
            return False
        mode = self.creation_mode or "formation"
        blueprint_id = self.creation_blueprint_id
        buffer = self.creation_buffer
        self.faction_selection_active = False
        self.faction_picker_offset = 0
        self.faction_search_buffer = ""
        self.faction_search_active = False
        handled = self.begin_creation(self.creation_parent_id, mode=mode)
        self.creation_faction_id = faction_id if handled else None
        if handled and mode == "from_blueprint":
            self.creation_blueprint_id = blueprint_id
            self.creation_buffer = buffer
            self.creation_cursor = len(buffer)
        return handled

    def begin_creation(self, parent_id=None, mode="formation"):
        parent_id = parent_id or self.selected_node_id
        if self._find_node(parent_id) is None:
            return False
        self.creation_parent_id = parent_id
        self.creation_buffer = ""
        self.creation_active = True
        self.creation_mode = mode
        self.creation_blueprint_id = None
        self.creation_faction_id = None
        self.creation_menu_active = False
        self.blueprint_selection_active = False
        self.faction_selection_active = False
        self.faction_picker_offset = 0
        self.faction_search_buffer = ""
        self.faction_search_active = False
        self.creation_cursor = 0
        self.name_field_focused = True
        return True

    def cancel_creation(self):
        self.creation_menu_active = False
        self.blueprint_selection_active = False
        self.creation_active = False
        self.creation_buffer = ""
        self.creation_parent_id = None
        self.creation_mode = None
        self.creation_blueprint_id = None
        self.creation_faction_id = None
        self.faction_selection_active = False
        self.faction_picker_offset = 0
        self.faction_search_buffer = ""
        self.faction_search_active = False
        self.creation_cursor = 0
        self.name_field_focused = False

    def begin_year_edit(self):
        self.year_editing = True
        self.year_buffer = ""

    def set_creation_cursor_from_screen_x(self, screen_x, field_left):
        """Place the name caret from a click in the monospace name field."""
        relative_x = max(0, int(screen_x) - int(field_left))
        self.creation_cursor = min(len(self.creation_buffer), max(0, int((relative_x + 4) / 8)))
        self.name_field_focused = True

    def begin_personnel_edit(self):
        value = self.structure.get("personnel") if isinstance(self.structure, dict) else None
        self.personnel_editing = True
        self.personnel_buffer = str(value if value is not None else 0)

    def _blueprint_view_state(self, entity):
        state = latest_formation_snapshot(entity, self.year)
        if isinstance(state, dict):
            return state
        return self._blueprint_state(entity)

    def _blueprint_state(self, entity):
        organization = self._relation_ids(entity.get("offspring"))
        for candidate in self._formation_entities():
            if entity.get("id") in self._relation_ids(candidate.get("parents")):
                candidate_id = candidate.get("id")
                if candidate_id and candidate_id not in organization:
                    organization.append(candidate_id)
        return {
            "personnel": entity.get("personnel"),
            "blueprint_items": self._relation_ids(entity.get("blueprint_items")),
            "organization": organization,
        }

    def _blueprint_state_at_view_year(self, entity):
        state = latest_formation_snapshot(entity, self.year)
        return state if isinstance(state, dict) else self._blueprint_state(entity)

    def _save_entity_fields(self, entity_id, fields):
        entity = self.world_model.get_entity(entity_id) if self.world_model else None
        if not isinstance(entity, dict):
            return False
        changed = False
        set_literal = getattr(self.world_model, "set_literal", None) if self.world_model else None
        for field_name, value in fields.items():
            current_value = entity.get(field_name)
            if current_value == value:
                continue
            if field_name == "personnel" and current_value is None and value in (None, 0):
                continue
            if field_name in {"blueprint_items", "equipment_items", "formation_snapshots"} and not current_value and not value:
                continue
            if callable(set_literal):
                set_literal(entity_id, field_name, value, persist=True)
            else:
                entity[field_name] = value
            changed = True
        return changed

    def _record_blueprint_change(self, entity_id, before_state, force=False):
        entity = self.world_model.get_entity(entity_id) if self.world_model else None
        if not isinstance(entity, dict):
            return False
        after_state = self._blueprint_state(entity)
        if not force and before_state == after_state:
            return False
        snapshots = [entry for entry in (entity.get("formation_snapshots") or []) if isinstance(entry, dict)]
        entry = {"start_year": self.year, "end_year": self.year, "state": after_state}
        replaced = False
        for index, existing in enumerate(snapshots):
            if existing.get("start_year") == self.year and existing.get("end_year", self.year) == self.year:
                if existing.get("state") == after_state:
                    return False
                snapshots[index] = entry
                replaced = True
                break
        if not replaced:
            snapshots.append(entry)
        snapshots.sort(key=lambda value: int(value.get("start_year", self.year)))
        return self._save_entity_fields(entity_id, {"formation_snapshots": snapshots})

    def _update_blueprint_fields(self, fields):
        entity = self.world_model.get_entity(self.formation_id) if self.world_model else None
        if not isinstance(entity, dict) or entity.get("formation_kind") != "blueprint":
            return False
        before_state = self._blueprint_view_state(entity)
        changed = self._save_entity_fields(self.formation_id, fields)
        if changed:
            self._record_blueprint_change(self.formation_id, before_state)
            self.structure = self._build_structure()
        return changed

    def _reset_drag(self):
        self.drag_press_node_id = None
        self.drag_press_pos = None
        self.dragging_node_id = None

    def _reorder_node(self, node_id, target_id):
        if node_id == target_id or node_id == self.structure.get("id"):
            return False
        parent = self._find_parent(node_id)
        target_parent = self._find_parent(target_id)
        if parent is None or parent is not target_parent:
            return False
        siblings = parent.get("children", [])
        dragged = next((node for node in siblings if node.get("id") == node_id), None)
        if dragged is None or dragged.get("is_unlinked"):
            return False
        original_index = siblings.index(dragged)
        target_index = next(
            (index for index, node in enumerate(siblings) if node.get("id") == target_id),
            None,
        )
        if target_index is None:
            return False
        siblings.pop(original_index)
        # Dropping onto a row places the dragged formation on that row's
        # previous position. Keeping the original target index when dragging
        # downward makes A dropped on B become B, A; dragging upward inserts
        # before the target.
        siblings.insert(target_index, dragged)

        parent_entity_id = parent.get("entity_id")
        if parent_entity_id and self.world_model is not None:
            set_literal = getattr(self.world_model, "set_literal", None)
            for index, child in enumerate(siblings):
                child_entity_id = child.get("entity_id")
                if not child_entity_id:
                    continue
                if callable(set_literal):
                    set_literal(child_entity_id, "formation_order", index, persist=True)
                else:
                    child_entity = self.world_model.get_entity(child_entity_id)
                    if isinstance(child_entity, dict):
                        child_entity["formation_order"] = index
        return True

    def _new_formation_id(self, label):
        slug = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_") or "formation"
        base = f"form_{slug}"
        candidate = base
        index = 2
        while self.world_model and self.world_model.get_entity(candidate):
            candidate = f"{base}_{index}"
            index += 1
        return candidate

    def commit_creation(self):
        if not self.creation_active:
            return False
        label = " ".join(self.creation_buffer.split()).strip()
        parent_id = self.creation_parent_id or self.selected_node_id
        parent = self._find_node(parent_id)
        faction_ids = {
            faction.get("id")
            for faction in self._faction_options()
            if isinstance(faction, dict)
        }
        if not label or parent is None or self.creation_faction_id not in faction_ids:
            return False

        entity_id = None
        loader = getattr(self.world_model, "loader", None) if self.world_model else None
        parent_entity_id = parent.get("entity_id")
        parent_before_state = None
        parent_entity = self.world_model.get_entity(parent_entity_id) if self.world_model and parent_entity_id else None
        if isinstance(parent_entity, dict) and parent_entity.get("formation_kind") == "blueprint":
            parent_before_state = self._blueprint_state(parent_entity)
        if loader is not None and parent_entity_id:
            entity_id = self._new_formation_id(label)
            mode = self.creation_mode or "formation"
            if mode == "blueprint":
                entity_id = self._new_formation_id(label)
                entity = {
                    "id": entity_id,
                    "_dataset": "formations",
                    "type": "formation",
                    "name": label,
                    "pretty_name": label,
                    "entry_status": "draft",
                    "formation_kind": "blueprint",
                    "faction": self.creation_faction_id,
                    "designed_for": parent_entity_id,
                    "blueprint_items": [],
                    "formation_snapshots": [
                        {
                            "start_year": self.year,
                            "end_year": self.year,
                            "state": {
                                "personnel": None,
                                "blueprint_items": [],
                                "organization": [],
                            },
                        }
                    ],
                }
            elif mode == "from_blueprint":
                blueprint = self.world_model.get_entity(self.creation_blueprint_id)
                state = latest_formation_snapshot(blueprint, self.year) if isinstance(blueprint, dict) else None
                state = state if isinstance(state, dict) else {}
                item_ids = self._relation_ids(
                    state.get("blueprint_items", blueprint.get("blueprint_items"))
                    if isinstance(blueprint, dict) else []
                )
                entity = {
                    "id": entity_id,
                    "_dataset": "formations",
                    "type": "formation",
                    "name": label,
                    "pretty_name": label,
                    "entry_status": "draft",
                    "formation_kind": "realization",
                    "parents": [parent_entity_id],
                    "blueprint": self.creation_blueprint_id,
                    "faction": self.creation_faction_id,
                    "personnel": state.get("personnel", blueprint.get("personnel") if isinstance(blueprint, dict) else None),
                    "equipment_items": item_ids,
                    "start_year": self.year,
                }
            else:
                parent_is_blueprint = isinstance(parent_entity, dict) and parent_entity.get("formation_kind") == "blueprint"
                entity = {
                    "id": entity_id,
                    "_dataset": "formations",
                    "type": "formation",
                    "name": label,
                    "pretty_name": label,
                    "formation_kind": "blueprint" if parent_is_blueprint else "realization",
                    "parents": [parent_entity_id],
                    "faction": self.creation_faction_id,
                    "start_year": self.year,
                }
            if not loader.persist_entity(entity):
                entity_id = None
            elif hasattr(self.world_model, "mark_repository_changed"):
                self.world_model.mark_repository_changed()

            if entity_id and parent_before_state is not None:
                self._record_blueprint_change(parent_entity_id, parent_before_state)

            if entity_id and mode == "from_blueprint":
                self._realize_blueprint_children(
                    self.creation_blueprint_id,
                    entity_id,
                )

            if entity_id and mode == "blueprint":
                owner = self.world_model.get_entity(parent_entity_id)
                blueprint_ids = self._relation_ids(owner.get("blueprints")) if isinstance(owner, dict) else []
                if entity_id not in blueprint_ids:
                    blueprint_ids.append(entity_id)
                    self._save_entity_fields(parent_entity_id, {"blueprints": blueprint_ids})
                self.pending_navigation_action = {
                    "id": "knowledge_launch_mode",
                    "entity_id": entity_id,
                    "launch_mode": "formation",
                }

        if entity_id:
            self.structure = self._build_structure()
            # Keep the parent active so repeated creation produces siblings,
            # rather than nesting the next new formation under the one just
            # created.
            self.selected_node_id = parent_id
        else:
            self._draft_counter += 1
            parent.setdefault("children", []).append({
                "id": f"draft:{self._draft_counter}",
                "label": label,
                "kind": "formation",
                "personnel": None,
                "children": [],
                "faction_id": self.creation_faction_id,
                "faction_label": self._faction_label(self.creation_faction_id),
                "is_draft": True,
            })
            self.selected_node_id = parent_id
        self.display_scale = "formation"
        self.cancel_creation()
        return True

    def _realize_blueprint_children(self, blueprint_id, actual_parent_id):
        """Copy a blueprint's organization into child realization Formations."""
        blueprint = self.world_model.get_entity(blueprint_id) if self.world_model else None
        loader = getattr(self.world_model, "loader", None) if self.world_model else None
        if not isinstance(blueprint, dict) or loader is None:
            return
        state = self._blueprint_state_at_view_year(blueprint)
        for child_blueprint_id in self._relation_ids(state.get("organization")):
            child_blueprint = self.world_model.get_entity(child_blueprint_id)
            if not isinstance(child_blueprint, dict):
                continue
            child_state = self._blueprint_state_at_view_year(child_blueprint)
            child_label = child_blueprint.get("pretty_name") or child_blueprint.get("name") or child_blueprint_id
            child_id = self._new_formation_id(child_label)
            child = {
                "id": child_id,
                "_dataset": "formations",
                "type": "formation",
                "name": child_label,
                "pretty_name": child_label,
                "entry_status": "draft",
                "formation_kind": "realization",
                "parents": [actual_parent_id],
                "blueprint": child_blueprint_id,
                "personnel": child_state.get("personnel"),
                "equipment_items": self._relation_ids(child_state.get("blueprint_items")),
                "start_year": self.year,
            }
            if loader.persist_entity(child):
                if hasattr(self.world_model, "mark_repository_changed"):
                    self.world_model.mark_repository_changed()
                self._realize_blueprint_children(child_blueprint_id, child_id)

    def consume_pending_navigation_action(self):
        action = self.pending_navigation_action
        self.pending_navigation_action = None
        return action

    def handle_pointer_motion(self, event, camera, screen_pos):
        self.hover_node_id = None
        for key, rect in self.hitboxes.items():
            if key.startswith("tree:") and rect.collidepoint(screen_pos):
                self.hover_node_id = key[5:]
                break
        if self.drag_press_node_id and getattr(event, "buttons", (False,))[0]:
            start_x, start_y = self.drag_press_pos or screen_pos
            if self.dragging_node_id is None and (
                abs(screen_pos[0] - start_x) + abs(screen_pos[1] - start_y) >= 8
            ):
                pressed = self._find_node(self.drag_press_node_id)
                if pressed is not None and not pressed.get("is_unlinked"):
                    self.dragging_node_id = self.drag_press_node_id
        return False

    def handle_pointer_event(self, event, camera, screen_pos):
        if event.type not in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) or event.button != 1:
            if (
                event.type == pygame.MOUSEBUTTONDOWN
                and event.button in (4, 5)
                and self.faction_selection_active
            ):
                visible = 13
                options = self._filtered_faction_options()
                maximum = max(0, len(options) - visible)
                delta = -1 if event.button == 4 else 1
                self.faction_picker_offset = max(0, min(maximum, self.faction_picker_offset + delta))
                return True
            return False

        if event.type == pygame.MOUSEBUTTONUP:
            if self.dragging_node_id:
                target_id = next(
                    (key[5:] for key, rect in self.hitboxes.items()
                     if key.startswith("tree:") and rect.collidepoint(screen_pos)),
                    None,
                )
                self._reorder_node(self.dragging_node_id, target_id)
                self._reset_drag()
                return True
            node_id = self.drag_press_node_id
            self._reset_drag()
            if node_id:
                node = self._find_node(node_id)
                if node is not None:
                    return self._activate_tree_node(node)
            return False

        for key, rect in self.hitboxes.items():
            if not rect.collidepoint(screen_pos):
                continue

            if key == "year:current":
                self.begin_year_edit()
                return True

            if key == "year:previous":
                self.set_year(self.year - 1)
                return True

            if key == "year:next":
                self.set_year(self.year + 1)
                return True

            if key.startswith("scale:"):
                scale = key[6:]
                if scale in self.DISPLAY_SCALES:
                    self.display_scale = scale
                return True

            if key == "create":
                return self.open_creation_menu(self.selected_node_id)

            if key == "creation:new_formation":
                return self.choose_creation_mode("new_formation")

            if key == "creation:from_blueprint":
                return self.choose_creation_mode("from_blueprint")

            if key == "creation:new_blueprint":
                return self.choose_creation_mode("new_blueprint")

            if key == "creation:faction:search":
                self.faction_search_active = True
                return True

            if key.startswith("creation:faction:"):
                return self.choose_faction(key[len("creation:faction:"):])

            if key == "creation:name":
                self.set_creation_cursor_from_screen_x(screen_pos[0], rect.x + 10)
                return True

            if key.startswith("creation:blueprint:"):
                return self.choose_blueprint(key[len("creation:blueprint:"):])

            if key == "blueprint:personnel:set":
                self.begin_personnel_edit()
                return True

            if key == "blueprint:section:organization":
                self.blueprint_editor_section = "organization"
                return True

            if key == "blueprint:section:equipment":
                self.blueprint_editor_section = "equipment"
                return True

            if key == "blueprint:organization:add":
                if self.open_creation_menu(self.structure.get("id")):
                    return self.choose_creation_mode("new_blueprint")
                return False

            if key.startswith("blueprint:organization:"):
                child_id = key[len("blueprint:organization:"):]
                child = self._find_node(child_id)
                if child is not None and child.get("entity_id"):
                    self.pending_navigation_action = {
                        "id": "knowledge_launch_mode",
                        "entity_id": child["entity_id"],
                        "launch_mode": "formation",
                    }
                return True

            if key == "blueprint:personnel:minus":
                current = self.structure.get("personnel", 0)
                try:
                    current = int(current or 0)
                except (TypeError, ValueError):
                    current = 0
                self._update_blueprint_fields({"personnel": max(0, current - 100)})
                return True

            if key == "blueprint:personnel:plus":
                current = self.structure.get("personnel", 0)
                try:
                    current = int(current or 0)
                except (TypeError, ValueError):
                    current = 0
                self._update_blueprint_fields({"personnel": max(0, current + 100)})
                return True

            if key.startswith("blueprint:item:"):
                item_id = key[len("blueprint:item:"):]
                entity = self.world_model.get_entity(self.formation_id) if self.world_model else None
                if isinstance(entity, dict) and entity.get("formation_kind") == "blueprint":
                    before_state = self._blueprint_view_state(entity)
                    item_ids = self._relation_ids(before_state.get("blueprint_items"))
                    if item_id in item_ids:
                        item_ids.remove(item_id)
                    else:
                        item_ids.append(item_id)
                    if self._save_entity_fields(self.formation_id, {"blueprint_items": item_ids}):
                        self._record_blueprint_change(self.formation_id, before_state)
                        self.structure = self._build_structure()
                return True

            if key == "parent":
                parent_id = self.get_parent_formation_id()
                if parent_id:
                    self.pending_navigation_action = {
                        "id": "knowledge_launch_mode",
                        "entity_id": parent_id,
                        "launch_mode": "formation",
                    }
                    return True
                return False

            if key.startswith("blueprint:"):
                blueprint_id = key[len("blueprint:"):]
                if self.world_model and self.world_model.get_entity(blueprint_id):
                    self.pending_navigation_action = {
                        "id": "knowledge_launch_mode",
                        "entity_id": blueprint_id,
                        "launch_mode": "formation",
                    }
                return True

            if key.startswith("tree:"):
                node_id = key[5:]
                node = self._find_node(node_id)
                if node is None:
                    return True
                self.selected_node_id = node_id
                self.drag_press_node_id = node_id
                self.drag_press_pos = screen_pos
                return True

        return False

    def _activate_tree_node(self, node):
        node_id = node.get("id")
        self.selected_node_id = node_id
        self.display_scale = self._scale_for_node(node)
        if node.get("is_unlinked"):
            parent = self._find_parent(node_id)
            parent_id = parent.get("id") if parent else self.selected_node_id
            self.begin_creation(parent_id=parent_id)
            self.creation_buffer = node.get("label", "")
            return True
        entity_id = node.get("entity_id")
        if entity_id and entity_id != self.formation_id:
            self.pending_navigation_action = {
                "id": "knowledge_launch_mode",
                "entity_id": entity_id,
                "launch_mode": "formation",
            }
        return True


class _StaticClock:
    tick = 0
    time_scale = 1.0

    def update(self, dt):
        return None
