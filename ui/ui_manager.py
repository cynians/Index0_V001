import math
import pygame


class UIButton:
    """
    Minimal screen-space button description.
    """

    def __init__(self, button_id, label, rect, visible=True, enabled=True):
        self.id = button_id
        self.label = label
        self.rect = rect
        self.visible = visible
        self.enabled = enabled


class UIManager:
    """
    App-level UI manager.

    Responsibilities:
    * rebuild visible widgets for current app state
    * draw widgets
    * consume UI clicks and return action ids
    * draw tab strip
    * draw time / timeline / mouse-world status
    * draw map/space info panels and hover tooltip
    * draw the Knowledge Layer shell when no simulation is active
    """

    DAY_SECONDS = 24 * 60 * 60

    def __init__(self):
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None

        self.tab_labels = []
        self.active_tab_index = 0
        self.tab_hitboxes = []

        self.time_lines = []
        self.timeline_fraction = 0.0
        self.mouse_world_label = None

        self.menu_active = False
        self.knowledge_layout = None
        self.knowledge_browser_items = []
        self.knowledge_browser_hitboxes = []
        self.knowledge_cards = []
        self.knowledge_world_model = None
        self.knowledge_selected_entity_id = None
        self.repository_scope_entity_id = None
        self.repository_scope_label = None
        self.knowledge_header_button = None
        self.knowledge_browser_scroll = 0
        self.knowledge_browser_tree_state = {
            "systems": {
                "system_sol": True,
                "body_sol": True,
            }
        }
        self.knowledge_browser_toggle_hitboxes = []

    def _format_sim_time(self, sim):
        """
        Convert sim year + elapsed sim seconds into a simple year/day/time display.
        """
        base_year = getattr(sim, "year", 0)
        elapsed_seconds = getattr(sim.sim_clock, "time", 0.0)

        whole_days = int(elapsed_seconds // self.DAY_SECONDS)
        seconds_in_day = elapsed_seconds % self.DAY_SECONDS

        hours = int(seconds_in_day // 3600)
        minutes = int((seconds_in_day % 3600) // 60)

        display_year = base_year + (whole_days // 365)
        day_of_year = (whole_days % 365) + 1

        return {
            "year": display_year,
            "day_of_year": day_of_year,
            "hours": hours,
            "minutes": minutes,
            "timeline_fraction": seconds_in_day / self.DAY_SECONDS,
        }

    def _build_knowledge_layout(self, app_width, app_height):
        """
        Build the static Knowledge Layer shell rectangles.
        """
        outer_margin = 16
        header_h = 54
        inner_gap = 14
        left_ratio = 0.30

        content_x = outer_margin
        content_y = outer_margin + header_h
        content_w = app_width - outer_margin * 2
        content_h = app_height - content_y - outer_margin

        left_w = int(content_w * left_ratio)
        right_w = content_w - left_w - inner_gap

        left_rect = pygame.Rect(content_x, content_y, left_w, content_h)
        right_rect = pygame.Rect(content_x + left_w + inner_gap, content_y, right_w, content_h)

        return {
            "header_rect": pygame.Rect(outer_margin, outer_margin, content_w, header_h),
            "left_rect": left_rect,
            "right_rect": right_rect,
        }
    def _build_knowledge_header_button(self):
        """
        Build the Knowledge Layer header action button from the current layout.
        """
        if self.knowledge_layout is None:
            self.knowledge_header_button = None
            return

        header_rect = self.knowledge_layout["header_rect"]
        self.knowledge_header_button = UIButton(
            button_id="launch_vehicle_test",
            label="Launch Vehicle Test",
            rect=pygame.Rect(header_rect.right - 220, header_rect.y + 11, 200, 30),
            visible=True,
            enabled=True,
        )

    def _kb_is_expanded(self, entity_id):
        return self.knowledge_browser_tree_state["systems"].get(entity_id, False)

    def _kb_set_expanded(self, entity_id, expanded):
        self.knowledge_browser_tree_state["systems"][entity_id] = expanded

    def _build_system_browser_items(self, world_model):
        """
        Build a collapsible tree for star systems and orbital bodies.

        Visible structure:
        star system
          star/root body
            child orbital bodies
              nested moons/sub-bodies
        """
        items = []

        if world_model is None:
            return items

        system_entities = world_model.get_entities_by_dataset("systems")
        systems_by_id = {
            entity.get("id"): entity
            for entity in system_entities
            if isinstance(entity, dict) and entity.get("id")
        }

        star_systems = sorted(
            [
                entity for entity in system_entities
                if entity.get("system_role") == "star_system"
            ],
            key=lambda entity: entity.get("name", entity.get("id", ""))
        )

        bodies = [
            entity for entity in system_entities
            if entity.get("system_role") == "orbital_body"
        ]

        bodies_by_parent = {}
        roots_by_system = {}

        for body in bodies:
            parent_body = body.get("parent_body")
            star_system_id = body.get("star_system")

            if parent_body:
                bodies_by_parent.setdefault(parent_body, []).append(body)
            else:
                roots_by_system.setdefault(star_system_id, []).append(body)

        for child_list in bodies_by_parent.values():
            child_list.sort(key=lambda entity: entity.get("name", entity.get("id", "")))

        for child_list in roots_by_system.values():
            child_list.sort(key=lambda entity: entity.get("name", entity.get("id", "")))

        def add_body_subtree(body_entity, depth):
            body_id = body_entity.get("id")
            body_name = body_entity.get("name", body_id or "unknown")
            body_class = body_entity.get("body_class", body_entity.get("type", "entity"))
            children = bodies_by_parent.get(body_id, [])
            expandable = len(children) > 0

            items.append(
                {
                    "kind": "tree_entity",
                    "entity_id": body_id,
                    "text": body_name,
                    "meta_text": f"[{body_class}]",
                    "depth": depth,
                    "expandable": expandable,
                    "expanded": self._kb_is_expanded(body_id),
                }
            )

            if expandable and self._kb_is_expanded(body_id):
                for child in children:
                    add_body_subtree(child, depth + 1)

        for system_entity in star_systems:
            system_id = system_entity.get("id")
            system_name = system_entity.get("name", system_id or "unknown")
            system_class = system_entity.get("system_class", system_entity.get("type", "entity"))
            root_bodies = roots_by_system.get(system_id, [])

            items.append(
                {
                    "kind": "tree_entity",
                    "entity_id": system_id,
                    "text": system_name,
                    "meta_text": f"[{system_class}]",
                    "depth": 0,
                    "expandable": len(root_bodies) > 0,
                    "expanded": self._kb_is_expanded(system_id),
                }
            )

            if self._kb_is_expanded(system_id):
                for root_body in root_bodies:
                    add_body_subtree(root_body, 1)

        return items

    def _build_knowledge_browser_items(self, world_model):
        """
        Build selectable browser rows from actual repository entries.
        """
        items = [
            {"kind": "label", "text": "Grouping: dataset preview"},
            {"kind": "spacer"},
            {"kind": "section", "text": "Locations"},
        ]

        if world_model is not None:
            location_entities = sorted(
                world_model.get_entities_by_dataset("locations"),
                key=lambda entity: entity.get("name", entity.get("id", ""))
            )

            for entity in location_entities:
                label = entity.get("name", entity.get("id", "unknown"))
                entity_class = entity.get("location_class", entity.get("type", "entity"))

                items.append(
                    {
                        "kind": "entity",
                        "entity_id": entity.get("id"),
                        "text": f"  {label} [{entity_class}]",
                    }
                )

            items.append({"kind": "spacer"})
            items.append({"kind": "section", "text": "Star Systems"})
            items.extend(self._build_system_browser_items(world_model))

        return items

    def _build_card_from_entity(self, entity):
        """
        Build one repository entry card from an actual world-model entity.
        """
        if entity is None or self.knowledge_layout is None:
            return None

        right_rect = self.knowledge_layout["right_rect"]
        card_index = len(self.knowledge_cards)

        card_w = 250
        card_h = 230
        x_gap = 30
        y_gap = 26
        start_x = right_rect.x + 24
        start_y = right_rect.y + 84

        available_w = max(1, right_rect.width - 48)
        col_count = max(1, available_w // (card_w + x_gap))

        col = card_index % col_count
        row = card_index // col_count

        rect_x = start_x + col * (card_w + x_gap)
        rect_y = start_y + row * (card_h + y_gap)

        dataset_name = entity.get("_dataset", entity.get("type", "entity"))

        if dataset_name == "locations":
            display_group = "location"
            subtype = entity.get("location_class", entity.get("type", "entity"))

        elif dataset_name == "systems":
            system_role = entity.get("system_role")

            if system_role == "star_system":
                display_group = "star system"
                subtype = entity.get("system_class", entity.get("type", "entity"))
            elif system_role == "orbital_body":
                display_group = "orbital body"
                subtype = entity.get("body_class", entity.get("type", "entity"))
            else:
                display_group = "system"
                subtype = entity.get("type", "entity")

        else:
            display_group = dataset_name
            subtype = entity.get("type", "entity")

        start_year = entity.get("start_year", 0)

        return {
            "entity_id": entity.get("id"),
            "title": entity.get("name", entity.get("id", "unknown")),
            "subtitle": f"{display_group} | {subtype}",
            "rect": pygame.Rect(rect_x, rect_y, card_w, card_h),
            "years": [start_year],
            "selected_year": start_year,
        }

    def _ensure_knowledge_card(self, entity):
        """
        Add a card for the given entity if it is not already open.
        """
        if entity is None:
            return

        entity_id = entity.get("id")
        if entity_id is None:
            return

        for card in self.knowledge_cards:
            if card.get("entity_id") == entity_id:
                self.knowledge_selected_entity_id = entity_id
                return

        new_card = self._build_card_from_entity(entity)
        if new_card is not None:
            self.knowledge_cards.append(new_card)
            self.knowledge_selected_entity_id = entity_id

    def rebuild_for_state(
            self,
            active_sim,
            app_width,
            app_height,
            tab_manager=None,
            camera=None,
            menu_active=False,
            world_model=None,
            repository_scope_entity_id=None
    ):
        """
        Rebuild the current widget set for the active application state.
        """
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None
        self.tab_labels = []
        self.active_tab_index = 0
        self.tab_hitboxes = []
        self.time_lines = []
        self.timeline_fraction = 0.0
        self.mouse_world_label = None

        self.menu_active = menu_active
        self.knowledge_layout = None
        self.knowledge_browser_items = []
        self.knowledge_browser_hitboxes = []
        self.knowledge_browser_toggle_hitboxes = []
        self.knowledge_world_model = world_model
        self.repository_scope_entity_id = repository_scope_entity_id
        self.repository_scope_label = None
        self.knowledge_header_button = None

        if tab_manager is not None:
            self.tab_labels = [tab.name for tab in tab_manager.tabs]
            self.active_tab_index = tab_manager.active_index

        if menu_active:
            self.knowledge_layout = self._build_knowledge_layout(app_width, app_height)
            self.knowledge_browser_items = self._build_knowledge_browser_items(world_model)
            self._build_knowledge_header_button()

            scope_entity = None
            if world_model is not None and repository_scope_entity_id:
                scope_entity = world_model.get_entity(repository_scope_entity_id)

            if scope_entity is not None:
                scope_name = scope_entity.get("name", repository_scope_entity_id)
                scope_kind = scope_entity.get(
                    "location_class",
                    scope_entity.get("system_role", scope_entity.get("type", "entity"))
                )
                self.repository_scope_label = f"Scope stub: {scope_name} [{scope_kind}]"
                self._ensure_knowledge_card(scope_entity)
                self.knowledge_selected_entity_id = scope_entity.get("id")

            elif not self.knowledge_cards and world_model is not None:
                self._ensure_knowledge_card(world_model.get_entity("planet_earth"))
                self._ensure_knowledge_card(world_model.get_entity("system_sol"))

            return

        if active_sim is None:
            return

        time_info = self._format_sim_time(active_sim)
        self.timeline_fraction = time_info["timeline_fraction"]

        self.time_lines = [
            f"Year {time_info['year']} | Day {time_info['day_of_year']}",
            f"{time_info['hours']:02d}:{time_info['minutes']:02d} | Tick {active_sim.sim_clock.tick}",
            f"Time Scale x{active_sim.sim_clock.time_scale:.2f}",
        ]

        if camera is not None:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            world_x = int((mouse_x - app_width / 2) / camera.zoom + camera.x)
            world_y = int((mouse_y - app_height / 2) / camera.zoom + camera.y)
            self.mouse_world_label = f"Mouse World: {world_x} , {world_y}"

        button_width = 180
        button_height = 32
        button_x = app_width - button_width - 20
        button_y = 42

        if getattr(active_sim, "render_mode", None) == "map":
            root_name = None
            if hasattr(active_sim, "get_root_name"):
                root_name = active_sim.get_root_name()

            if root_name:
                self.scope_label = f"Scope: {root_name}"

            existing_status_line = None
            if hasattr(active_sim, "get_root_entity"):
                root_entity = active_sim.get_root_entity()
                if root_entity:
                    canvas_w = root_entity.get("map_canvas_width_px")
                    canvas_h = root_entity.get("map_canvas_height_px")
                    map_status = root_entity.get("map_status")

                    if canvas_w and canvas_h:
                        self.scope_label = f"Scope: {root_name} | Canvas: {canvas_w} x {canvas_h}"

                    if map_status:
                        existing_status_line = f"Status: {map_status}"

            if hasattr(active_sim, "get_scope_breadcrumb"):
                breadcrumb_parts = active_sim.get_scope_breadcrumb()
                if breadcrumb_parts:
                    breadcrumb_text = " > ".join(breadcrumb_parts)
                    if existing_status_line:
                        self.breadcrumb_label = f"{existing_status_line} | {breadcrumb_text}"
                    else:
                        self.breadcrumb_label = breadcrumb_text
                elif existing_status_line:
                    self.breadcrumb_label = existing_status_line
            elif existing_status_line:
                self.breadcrumb_label = existing_status_line

            self.buttons.append(
                UIButton(
                    button_id="open_repository",
                    label="Open Repository",
                    rect=pygame.Rect(button_x, button_y, button_width, button_height),
                    visible=True,
                    enabled=True,
                )
            )

            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            root_entity_id = getattr(active_sim.context, "root_entity_id", None)

            if selected_entity_id is not None and selected_entity_id != root_entity_id:
                self.buttons.append(
                    UIButton(
                        button_id="open_region_map",
                        label="Open Region Map",
                        rect=pygame.Rect(button_x, button_y + 40, button_width, button_height),
                        visible=True,
                        enabled=True,
                    )
                )

            parent_root_entity_id = None
            if hasattr(active_sim, "get_parent_root_entity_id"):
                parent_root_entity_id = active_sim.get_parent_root_entity_id()

            if parent_root_entity_id is not None:
                self.buttons.append(
                    UIButton(
                        button_id="open_parent_region_map",
                        label="Up To Parent",
                        rect=pygame.Rect(button_x, button_y + 80, button_width, button_height),
                        visible=True,
                        enabled=True,
                    )
                )

            hover_entity_id = getattr(active_sim, "hover_entity_id", None)
            hover_screen_pos = getattr(active_sim, "hover_screen_pos", None)

            if hover_entity_id and hover_screen_pos:
                entity = active_sim.world_model.get_entity(hover_entity_id)
                if entity:
                    entity_name = entity.get("name", hover_entity_id)
                    location_class = entity.get("location_class", entity.get("type", "entity"))

                    self.hover_tooltip_lines = [
                        entity_name,
                        f"class: {location_class}",
                    ]

                    if hover_entity_id == selected_entity_id:
                        self.hover_tooltip_lines.append("selected")

                    self.hover_tooltip_pos = hover_screen_pos

            return
        if getattr(active_sim, "render_mode", None) == "vehicle":
            self.scope_label = (
                f"Vehicle: {active_sim.get_vehicle_name()} | "
                f"Mode: {active_sim.get_active_mode_label()}"
            )
            self.breadcrumb_label = f"class: {active_sim.get_vehicle_class()}"

            self.buttons.append(
                UIButton(
                    button_id="open_repository",
                    label="Open Repository",
                    rect=pygame.Rect(button_x, button_y, button_width, button_height),
                    visible=True,
                    enabled=True,
                )
            )

            self.buttons.append(
                UIButton(
                    button_id="vehicle_mode_design",
                    label="Vehicle Design",
                    rect=pygame.Rect(button_x, button_y + 40, button_width, button_height),
                    visible=True,
                    enabled=active_sim.active_view_mode != "design",
                )
            )

            self.buttons.append(
                UIButton(
                    button_id="vehicle_mode_interior",
                    label="Interior",
                    rect=pygame.Rect(button_x, button_y + 80, button_width, button_height),
                    visible=True,
                    enabled=active_sim.active_view_mode != "interior",
                )
            )

            self.buttons.append(
                UIButton(
                    button_id="vehicle_mode_operational",
                    label="Operational",
                    rect=pygame.Rect(button_x, button_y + 120, button_width, button_height),
                    visible=True,
                    enabled=active_sim.active_view_mode != "operational",
                )
            )

            payload = active_sim.get_focused_render_payload()

            if active_sim.active_view_mode in ("design", "interior"):
                blocks_by_id = {
                    block.get("id"): block
                    for block in payload.get("blocks", [])
                }

                selected_part_id = payload.get("selected_part_id")
                hover_part_id = payload.get("hover_part_id")
                focus_part_id = selected_part_id or hover_part_id

                if active_sim.active_view_mode == "design":
                    active_catalog_id = payload.get("active_catalog_component_id")
                    hover_catalog_id = payload.get("hover_catalog_component_id")
                    catalog_by_id = {
                        entry.get("id"): entry
                        for entry in payload.get("component_catalog", [])
                    }

                    if active_catalog_id in catalog_by_id:
                        entry = catalog_by_id[active_catalog_id]
                        dims = entry.get("dimensions_m", {})
                        self.hover_tooltip_lines = [
                            "Catalog Selection",
                            entry.get("label", active_catalog_id),
                            entry.get("component_type", "component"),
                            f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m",
                            "click hull to place",
                        ]
                        self.hover_tooltip_pos = (24, 250)

                    elif hover_catalog_id in catalog_by_id:
                        entry = catalog_by_id[hover_catalog_id]
                        dims = entry.get("dimensions_m", {})
                        self.hover_tooltip_lines = [
                            "Catalog Item",
                            entry.get("label", hover_catalog_id),
                            entry.get("component_type", "component"),
                            f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m",
                        ]
                        self.hover_tooltip_pos = (24, 250)

                    elif focus_part_id in blocks_by_id:
                        block = blocks_by_id[focus_part_id]
                        self.hover_tooltip_lines = [
                            "Vehicle Design",
                            block.get("label", focus_part_id),
                            block.get("component_type", "component"),
                            f"{round(block.get('width', 0.0), 2)} x {round(block.get('height', 0.0), 2)} m",
                        ]
                        if selected_part_id:
                            self.hover_tooltip_lines.append("selected")
                        elif hover_part_id:
                            self.hover_tooltip_lines.append("hover")

                        self.hover_tooltip_pos = getattr(active_sim, "hover_screen_pos", None) or (24, 250)

                elif focus_part_id in blocks_by_id:
                    block = blocks_by_id[focus_part_id]
                    self.hover_tooltip_lines = [
                        active_sim.get_active_mode_label(),
                        block.get("label", focus_part_id),
                    ]
                    if selected_part_id:
                        self.hover_tooltip_lines.append("selected")
                    elif hover_part_id:
                        self.hover_tooltip_lines.append("hover")

                    self.hover_tooltip_pos = getattr(active_sim, "hover_screen_pos", None) or (24, 250)

            else:

                modules_by_id = {

                    module.get("id"): module

                    for module in payload.get("operational_modules", [])

                }

                selected_part_id = payload.get("selected_part_id")

                hover_part_id = payload.get("hover_part_id")

                focus_part_id = selected_part_id or hover_part_id

                if focus_part_id in modules_by_id:

                    module = modules_by_id[focus_part_id]

                    self.hover_tooltip_lines = [

                        "Operational Capability",

                        module.get("group", "General"),

                        module.get("label", focus_part_id),

                        module.get("component_label", "component"),

                        module.get("status_text", "ready"),

                    ]

                    if selected_part_id:

                        self.hover_tooltip_lines.append("selected")

                    elif hover_part_id:

                        self.hover_tooltip_lines.append("hover")

                    self.hover_tooltip_pos = getattr(active_sim, "hover_screen_pos", None) or (24, 250)

                else:

                    operational_state = payload.get("operational_state", {})

                    installed_components = payload.get("installed_components", [])

                    self.hover_tooltip_lines = [

                        "Operational Control Center",

                        f"components: {len(installed_components)}",

                        f"task: {operational_state.get('task_state', '?')}",

                        f"power: {operational_state.get('power_state', '?')}",

                        f"crew: {operational_state.get('crew_state', '?')}",

                    ]

                    self.hover_tooltip_pos = (24, 250)

            return
        if getattr(active_sim, "render_mode", None) == "bioregion":
            self.scope_label = "Scope: Bioregion Test Map | 10 km x 10 km"

            avg_surface = active_sim.get_average_surface_water()
            avg_top = active_sim.get_average_top_moisture()
            avg_deep = active_sim.get_average_deep_moisture()

            rain_text = "Rain: active" if getattr(active_sim, "is_raining", False) else "Rain: dry"
            self.breadcrumb_label = (
                f"{rain_text} | Avg surf: {avg_surface:.3f} | "
                f"Avg top: {avg_top:.3f} | Avg deep: {avg_deep:.3f}"
            )

            selected_cell = getattr(active_sim, "selected_cell", None)
            hover_cell = getattr(active_sim, "hover_cell", None)

            if selected_cell is not None:
                selected_grid_cell = active_sim.get_selected_grid_cell()
                if selected_grid_cell is not None:
                    self.hover_tooltip_lines = [
                        active_sim.get_cell_label(selected_cell),
                        f"soil: {selected_grid_cell['soil_type']}",
                        f"bedrock: {selected_grid_cell['bedrock_type']}",
                        f"altitude: {selected_grid_cell['altitude']:.3f}",
                        f"z: {selected_grid_cell['z']:.3f}",
                        f"surface water: {selected_grid_cell['surface_water']:.3f}",
                        f"top moisture: {selected_grid_cell['top_moisture']:.3f}",
                        f"deep moisture: {selected_grid_cell['deep_moisture']:.3f}",
                    ]
                    self.hover_tooltip_pos = (24, 250)

            elif hover_cell is not None:
                hover_grid_cell = active_sim.get_hover_grid_cell()
                if hover_grid_cell is not None:
                    self.hover_tooltip_lines = [
                        active_sim.get_cell_label(hover_cell),
                        f"soil: {hover_grid_cell['soil_type']}",
                        f"bedrock: {hover_grid_cell['bedrock_type']}",
                        f"altitude: {hover_grid_cell['altitude']:.3f}",
                        f"z: {hover_grid_cell['z']:.3f}",
                        f"surface water: {hover_grid_cell['surface_water']:.3f}",
                        f"top moisture: {hover_grid_cell['top_moisture']:.3f}",
                        f"deep moisture: {hover_grid_cell['deep_moisture']:.3f}",
                    ]
                    self.hover_tooltip_pos = (24, 250)

            self.buttons.append(
                UIButton(
                    button_id="open_repository",
                    label="Open Repository",
                    rect=pygame.Rect(button_x, button_y, button_width, button_height),
                    visible=True,
                    enabled=True,
                )
            )

            return

        if getattr(active_sim, "render_mode", None) == "space":
            self.buttons.append(
                UIButton(
                    button_id="open_repository",
                    label="Open Repository",
                    rect=pygame.Rect(button_x, button_y, button_width, button_height),
                    visible=True,
                    enabled=True,
                )
            )

            selected_body_entity = None
            if hasattr(active_sim, "get_selected_body_entity"):
                selected_body_entity = active_sim.get_selected_body_entity()

            if selected_body_entity:
                body_name = selected_body_entity.get("name", selected_body_entity.get("id"))
                body_class = selected_body_entity.get("body_class", "body")
                self.scope_label = f"Selected: {body_name}"
                self.breadcrumb_label = f"class: {body_class}"

                self.buttons.append(
                    UIButton(
                        button_id="open_space_body_map",
                        label="Open Map",
                        rect=pygame.Rect(button_x, button_y + 40, button_width, button_height),
                        visible=True,
                        enabled=True,
                    )
                )

            hover_body_id = getattr(active_sim, "hover_system_entity_id", None)
            hover_screen_pos = getattr(active_sim, "hover_screen_pos", None)

            if hover_body_id and hover_screen_pos:
                entity = active_sim.world_model.get_entity(hover_body_id)
                if entity:
                    entity_name = entity.get("name", hover_body_id)
                    body_class = entity.get("body_class", entity.get("type", "entity"))

                    self.hover_tooltip_lines = [
                        entity_name,
                        f"class: {body_class}",
                    ]

                    selected_system_entity_id = getattr(active_sim, "selected_system_entity_id", None)
                    if hover_body_id == selected_system_entity_id:
                        self.hover_tooltip_lines.append("selected")

                    self.hover_tooltip_pos = hover_screen_pos

    def _draw_button(self, screen, font, button):
        fill_color = (55, 55, 55) if button.enabled else (35, 35, 35)
        border_color = (210, 210, 210) if button.enabled else (100, 100, 100)
        text_color = (245, 245, 245) if button.enabled else (140, 140, 140)

        pygame.draw.rect(screen, fill_color, button.rect)
        pygame.draw.rect(screen, border_color, button.rect, 2)

        text_surface = font.render(button.label, True, text_color)
        text_rect = text_surface.get_rect(center=button.rect.center)
        screen.blit(text_surface, text_rect)

    def _draw_info_panel(self, screen, font, x, y, lines):
        if not lines:
            return

        padding = 8
        line_gap = 4

        rendered = [font.render(line, True, (240, 240, 240)) for line in lines]
        panel_width = max(text.get_width() for text in rendered) + padding * 2
        panel_height = (
            sum(text.get_height() for text in rendered)
            + line_gap * (len(rendered) - 1)
            + padding * 2
        )

        panel_rect = pygame.Rect(x, y, panel_width, panel_height)
        pygame.draw.rect(screen, (28, 28, 32), panel_rect)
        pygame.draw.rect(screen, (200, 200, 200), panel_rect, 1)

        current_y = panel_rect.y + padding
        for text_surface in rendered:
            screen.blit(text_surface, (panel_rect.x + padding, current_y))
            current_y += text_surface.get_height() + line_gap

    def _draw_multiline_text(self, screen, font, lines, x, y, color=(220, 220, 220), line_gap=4):
        current_y = y
        for line in lines:
            text_surface = font.render(line, True, color)
            screen.blit(text_surface, (x, current_y))
            current_y += text_surface.get_height() + line_gap

    def _draw_hover_tooltip(self, screen, font):
        if not self.hover_tooltip_lines or not self.hover_tooltip_pos:
            return

        padding = 8
        line_gap = 4
        rendered = [font.render(line, True, (240, 240, 240)) for line in self.hover_tooltip_lines]
        panel_width = max(text.get_width() for text in rendered) + padding * 2
        panel_height = (
            sum(text.get_height() for text in rendered)
            + line_gap * (len(rendered) - 1)
            + padding * 2
        )

        tooltip_x = self.hover_tooltip_pos[0] + 14
        tooltip_y = self.hover_tooltip_pos[1] + 14

        screen_width = screen.get_width()
        screen_height = screen.get_height()

        if tooltip_x + panel_width > screen_width - 10:
            tooltip_x = self.hover_tooltip_pos[0] - panel_width - 14

        if tooltip_y + panel_height > screen_height - 10:
            tooltip_y = self.hover_tooltip_pos[1] - panel_height - 14

        tooltip_rect = pygame.Rect(tooltip_x, tooltip_y, panel_width, panel_height)
        pygame.draw.rect(screen, (24, 24, 28), tooltip_rect)
        pygame.draw.rect(screen, (210, 210, 210), tooltip_rect, 1)

        current_y = tooltip_rect.y + padding
        for text_surface in rendered:
            screen.blit(text_surface, (tooltip_rect.x + padding, current_y))
            current_y += text_surface.get_height() + line_gap

    def _draw_tab_strip(self, screen, font):
        x_offset = 20
        y_offset = 5
        padding = 10

        self.tab_hitboxes = []

        for i, label in enumerate(self.tab_labels):
            text_surface = font.render(label, True, (255, 255, 255))
            text_rect = text_surface.get_rect()

            rect = pygame.Rect(
                x_offset,
                y_offset,
                text_rect.width + padding * 2,
                text_rect.height + padding
            )

            if i == self.active_tab_index:
                pygame.draw.rect(screen, (80, 80, 120), rect)
            else:
                pygame.draw.rect(screen, (40, 40, 40), rect)

            pygame.draw.rect(screen, (200, 200, 200), rect, 1)
            screen.blit(text_surface, (rect.x + padding, rect.y + padding // 2))

            self.tab_hitboxes.append((i, rect))
            x_offset += rect.width + 5

    def _draw_time_panel(self, screen, font):
        lines = list(self.time_lines)

        if self.mouse_world_label:
            lines.append(self.mouse_world_label)

        if not lines:
            return

        self._draw_info_panel(screen, font, 20, 40, lines)

    def _draw_timeline_bar(self, screen, x, y, w, h):
        pygame.draw.rect(screen, (30, 30, 34), (x, y, w, h))
        pygame.draw.rect(screen, (200, 200, 200), (x, y, w, h), 1)

        filled_w = max(0, min(w, int(round(w * self.timeline_fraction))))
        if filled_w > 0:
            pygame.draw.rect(screen, (120, 170, 255), (x, y, filled_w, h))

        tick_positions = [0.0, 0.25, 0.5, 0.75, 1.0]
        for frac in tick_positions:
            tick_x = x + int(round(w * frac))
            pygame.draw.line(screen, (180, 180, 180), (tick_x, y), (tick_x, y + h), 1)

    def _draw_timeline_labels(self, screen, font, x, y, w):
        labels = ["00:00", "06:00", "12:00", "18:00", "24:00"]

        for i, label in enumerate(labels):
            frac = i / 4
            lx = x + int(round(w * frac))
            text_surface = font.render(label, True, (220, 220, 220))

            if i == 0:
                draw_x = lx
            elif i == len(labels) - 1:
                draw_x = lx - text_surface.get_width()
            else:
                draw_x = lx - text_surface.get_width() // 2

            screen.blit(text_surface, (draw_x, y))

    def _draw_knowledge_card(self, screen, font, card):
        """
        Draw a compact repository entry card.
        """
        rect = card["rect"]

        pygame.draw.rect(screen, (28, 30, 38), rect)
        pygame.draw.rect(screen, (170, 170, 170), rect, 1)

        title_surface = font.render(card["title"], True, (245, 245, 245))
        subtitle_surface = font.render(card["subtitle"], True, (170, 170, 170))
        screen.blit(title_surface, (rect.x + 12, rect.y + 10))
        screen.blit(subtitle_surface, (rect.x + 12, rect.y + 32))

        image_rect = pygame.Rect(rect.x + 12, rect.y + 58, rect.width - 24, 82)
        pygame.draw.rect(screen, (40, 42, 52), image_rect)
        pygame.draw.rect(screen, (120, 120, 120), image_rect, 1)
        image_text = font.render("Image / layered view placeholder", True, (195, 195, 195))
        screen.blit(image_text, (image_rect.x + 10, image_rect.y + 30))

        timeline_y = rect.y + 160
        left_x = rect.x + 16
        right_x = rect.right - 16
        center_y = timeline_y + 10

        pygame.draw.line(screen, (170, 170, 170), (left_x, center_y), (right_x, center_y), 1)

        year_positions = []
        years = card["years"]
        for index, year in enumerate(years):
            if len(years) == 1:
                frac = 0.5
            else:
                frac = index / (len(years) - 1)

            year_x = int(left_x + (right_x - left_x) * frac)
            year_positions.append((year, year_x))

            marker_rect = pygame.Rect(year_x - 5, center_y - 5, 10, 10)
            selected = year == card["selected_year"]

            fill = (210, 210, 210) if selected else (70, 70, 70)
            border = (240, 240, 240) if selected else (170, 170, 170)
            pygame.draw.rect(screen, fill, marker_rect)
            pygame.draw.rect(screen, border, marker_rect, 1)

            year_surface = font.render(str(year), True, (230, 230, 230))
            year_rect = year_surface.get_rect(center=(year_x, center_y + 22))
            screen.blit(year_surface, year_rect)

        launch_rect = pygame.Rect(rect.x + 12, rect.bottom - 36, rect.width - 24, 24)
        pygame.draw.rect(screen, (55, 55, 55), launch_rect)
        pygame.draw.rect(screen, (210, 210, 210), launch_rect, 1)
        launch_text = font.render(f"Launch [{card['selected_year']}]", True, (245, 245, 245))
        launch_text_rect = launch_text.get_rect(center=launch_rect.center)
        screen.blit(launch_text, launch_text_rect)

        card["image_rect"] = image_rect
        card["launch_rect"] = launch_rect
        card["year_hitboxes"] = []

        for year, year_x in year_positions:
            hitbox = pygame.Rect(year_x - 12, center_y - 12, 24, 48)
            card["year_hitboxes"].append((year, hitbox))

    def _draw_knowledge_layer(self, screen, font):
        """
        Draw the two-pane Knowledge Layer shell.
        """
        if self.knowledge_layout is None:
            return

        header_rect = self.knowledge_layout["header_rect"]
        left_rect = self.knowledge_layout["left_rect"]
        right_rect = self.knowledge_layout["right_rect"]

        pygame.draw.rect(screen, (18, 20, 26), header_rect)
        pygame.draw.rect(screen, (200, 200, 200), header_rect, 1)

        title_surface = font.render("Knowledge Layer", True, (245, 245, 245))

        subtitle_text = "Pre-simulation repository workspace"
        if self.repository_scope_label:
            subtitle_text = self.repository_scope_label

        subtitle_surface = font.render(subtitle_text, True, (180, 180, 180))
        screen.blit(title_surface, (header_rect.x + 14, header_rect.y + 10))
        screen.blit(subtitle_surface, (header_rect.x + 14, header_rect.y + 30))

        if self.knowledge_header_button is not None:
            self._draw_button(screen, font, self.knowledge_header_button)

        pygame.draw.rect(screen, (12, 12, 20), left_rect)
        pygame.draw.rect(screen, (200, 200, 200), left_rect, 1)

        pygame.draw.rect(screen, (12, 16, 28), right_rect)
        pygame.draw.rect(screen, (200, 200, 200), right_rect, 1)

        left_title = font.render("Repository Browser", True, (240, 240, 240))
        right_title = font.render("Card Canvas", True, (240, 240, 240))
        screen.blit(left_title, (left_rect.x + 12, left_rect.y + 10))
        screen.blit(right_title, (right_rect.x + 12, right_rect.y + 10))

        self.knowledge_browser_hitboxes = []

        line_h = font.get_height() + 4
        content_top = left_rect.y + 48
        content_bottom = left_rect.bottom - 10
        visible_h = content_bottom - content_top

        total_h = len(self.knowledge_browser_items) * line_h
        max_scroll = max(0, total_h - visible_h)
        self.knowledge_browser_scroll = max(0, min(self.knowledge_browser_scroll, max_scroll))

        line_y = content_top - self.knowledge_browser_scroll

        for item in self.knowledge_browser_items:
            row_top = line_y
            row_bottom = line_y + line_h

            if item["kind"] == "spacer":
                line_y += line_h
                continue

            if row_bottom < content_top:
                line_y += line_h
                continue

            if row_top > content_bottom:
                break

            if item["kind"] == "section":
                color = (235, 235, 235)
                text_x = left_rect.x + 12
                text_surface = font.render(item["text"], True, color)
                screen.blit(text_surface, (text_x, line_y))

            elif item["kind"] == "label":
                color = (220, 220, 220)
                text_x = left_rect.x + 12
                text_surface = font.render(item["text"], True, color)
                screen.blit(text_surface, (text_x, line_y))

            else:
                row_rect = pygame.Rect(left_rect.x + 10, line_y - 1, left_rect.width - 20, line_h)
                is_selected = item["entity_id"] == self.knowledge_selected_entity_id

                if is_selected:
                    pygame.draw.rect(screen, (42, 46, 62), row_rect)
                    pygame.draw.rect(screen, (150, 150, 170), row_rect, 1)

                color = (245, 245, 245) if is_selected else (220, 220, 220)

                depth = item.get("depth", 0)
                indent_px = depth * 18
                base_x = left_rect.x + 12 + indent_px

                if item["kind"] == "tree_entity":
                    if item.get("expandable", False):
                        caret_rect = pygame.Rect(base_x, line_y + 2, 14, 14)
                        self.knowledge_browser_toggle_hitboxes.append((item["entity_id"], caret_rect))

                        if item.get("expanded", False):
                            pygame.draw.polygon(
                                screen,
                                color,
                                [
                                    (caret_rect.x + 2, caret_rect.y + 4),
                                    (caret_rect.x + 12, caret_rect.y + 4),
                                    (caret_rect.x + 7, caret_rect.y + 11),
                                ],
                            )
                        else:
                            pygame.draw.polygon(
                                screen,
                                color,
                                [
                                    (caret_rect.x + 4, caret_rect.y + 2),
                                    (caret_rect.x + 11, caret_rect.y + 7),
                                    (caret_rect.x + 4, caret_rect.y + 12),
                                ],
                            )

                        text_x = base_x + 20
                    else:
                        text_x = base_x + 20

                    text_surface = font.render(item["text"], True, color)
                    screen.blit(text_surface, (text_x, line_y))

                    meta_text = item.get("meta_text")
                    if meta_text:
                        meta_surface = font.render(meta_text, True, (170, 170, 170))
                        screen.blit(meta_surface, (text_x + text_surface.get_width() + 8, line_y))

                    self.knowledge_browser_hitboxes.append((item["entity_id"], row_rect))

                else:
                    text_x = left_rect.x + 12
                    text_surface = font.render(item["text"], True, color)
                    screen.blit(text_surface, (text_x, line_y))
                    self.knowledge_browser_hitboxes.append((item["entity_id"], row_rect))

            line_y += line_h

        for card in self.knowledge_cards:
            self._draw_knowledge_card(screen, font, card)

    def draw(self, screen, font):
        """
        Draw all visible UI widgets and info overlays.
        """
        self._draw_tab_strip(screen, font)

        if self.menu_active:
            self._draw_knowledge_layer(screen, font)
            return

        self._draw_time_panel(screen, font)

        if self.time_lines:
            timeline_x = 20
            timeline_y = 135
            timeline_w = 320
            timeline_h = 12
            self._draw_timeline_bar(screen, timeline_x, timeline_y, timeline_w, timeline_h)
            self._draw_timeline_labels(screen, font, timeline_x, timeline_y + 18, timeline_w)

        for button in self.buttons:
            if not button.visible:
                continue
            self._draw_button(screen, font, button)

        info_lines = []
        if self.scope_label:
            info_lines.append(self.scope_label)
        if self.breadcrumb_label:
            info_lines.append(self.breadcrumb_label)

        if info_lines:
            self._draw_info_panel(screen, font, 20, 170, info_lines)

        self._draw_hover_tooltip(screen, font)

    def handle_event(self, event):
        """
        Handle UI events.

        Returns:
            action payload if a UI element consumed the click, otherwise None.
        """
        if self.menu_active and self.knowledge_layout is not None:
            left_rect = self.knowledge_layout["left_rect"]

            if event.type == pygame.MOUSEWHEEL:
                mouse_pos = pygame.mouse.get_pos()

                if left_rect.collidepoint(mouse_pos):
                    line_step = 24
                    self.knowledge_browser_scroll = max(
                        0,
                        self.knowledge_browser_scroll - event.y * line_step
                    )
                    return "__ui_consumed__"

        if event.type != pygame.MOUSEBUTTONDOWN:
            return None

        if event.button != 1:
            return None

        mouse_pos = event.pos

        for tab_index, hitbox in self.tab_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                return {
                    "id": "activate_tab",
                    "tab_index": tab_index,
                }

        if self.menu_active:
            if self.knowledge_header_button is not None:
                if self.knowledge_header_button.rect.collidepoint(mouse_pos):
                    print("[DEBUG] Knowledge header button clicked:", self.knowledge_header_button.id)
                    return self.knowledge_header_button.id
            for entity_id, hitbox in self.knowledge_browser_toggle_hitboxes:
                if hitbox.collidepoint(mouse_pos):
                    self._kb_set_expanded(entity_id, not self._kb_is_expanded(entity_id))
                    return None

            for entity_id, hitbox in self.knowledge_browser_hitboxes:
                if hitbox.collidepoint(mouse_pos):
                    self.knowledge_selected_entity_id = entity_id

                    if self.knowledge_world_model is not None:
                        entity = self.knowledge_world_model.get_entity(entity_id)
                        self._ensure_knowledge_card(entity)

                    return None

            for card in self.knowledge_cards:
                for year, hitbox in card.get("year_hitboxes", []):
                    if hitbox.collidepoint(mouse_pos):
                        card["selected_year"] = year
                        return None

                launch_rect = card.get("launch_rect")
                if launch_rect is not None and launch_rect.collidepoint(mouse_pos):
                    return {
                        "id": "knowledge_launch_entry",
                        "entity_id": card.get("entity_id"),
                        "year": card.get("selected_year"),
                    }

            return None

        for button in self.buttons:
            if not button.visible or not button.enabled:
                continue

            if button.rect.collidepoint(mouse_pos):
                return button.id

        return None