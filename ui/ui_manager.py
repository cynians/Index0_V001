import math

import pygame

from ui.knowledge_browser_ui import KnowledgeBrowserUI
from ui.selection_inspector_ui import SelectionInspectorUI
from ui.timeline_ui import TimelineUI
from ui.ui_types import UIButton


class UIManager:
    """
    App-level UI manager.

    Responsibilities:
    * rebuild visible widgets for current app state
    * draw shared widgets
    * consume shared UI clicks and return action ids
    * delegate knowledge-layer workspace behavior
    * coordinate simulation-specific lower-panel UI
    """

    DAY_SECONDS = 24 * 60 * 60
    MAP_SURFACE_FIELDS = (
        "bounds",
        "geometry",
        "map_canvas_width_px",
        "map_canvas_height_px",
        "map_status",
        "map_generation_recipe",
        "map_layers",
        "map_image_path",
        "heightmap_model",
        "material_heatmap_model",
    )

    def __init__(self):
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.vehicle_requirement_lines = []
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None
        self.person_dossier_lines = []
        self.person_panel_mode = None
        self.person_panel_model = None
        self.person_panel_rect = None
        self.person_panel_close_rect = None
        self.person_panel_icons = []
        self.simulation_selection_payload = None
        self.simulation_selection_buttons = []
        self.simulation_selection_rect = None

        self.simulation_bar_rect = None
        self.simulation_bar_title = None
        self.simulation_bar_hint_lines = []
        self.simulation_bar_panel_lines = []
        self.simulation_bar_catalog_entries = []
        self.simulation_bar_catalog_hitboxes = []
        self.simulation_bar_active_catalog_id = None
        self.simulation_bar_resize_hitbox = None
        self.simulation_bar_height = 180
        self.simulation_bar_min_height = 120
        self.simulation_bar_max_height = 420
        self.simulation_bar_is_resizing = False
        self.simulation_bar_resize_start_y = 0
        self.simulation_bar_resize_start_height = 180

        self.simulation_panel_tabs = []
        self.simulation_panel_active_tab_id = None
        self.simulation_panel_tab_hitboxes = []

        self.tab_labels = []
        self.active_tab_index = 0
        self.tab_hitboxes = []

        self.time_lines = []
        self.timeline_fraction = 0.0
        self.mouse_world_label = None

        self.menu_active = False
        self.system_menu_active = False
        self.system_settings_active = False
        self.system_menu_buttons = []
        self.system_menu_rect = None
        self.repository_return_confirm_active = False
        self.repository_return_confirm_rect = None
        self.repository_return_confirm_buttons = []
        self.knowledge_ui = KnowledgeBrowserUI()
        self.selection_inspector = SelectionInspectorUI()
        self.map_history_timeline = TimelineUI()
        self.map_history_timeline_visible = False
        self.map_history_timeline_rect = None
        self.repository_return_confirm_rect = None
        self.repository_return_confirm_buttons = []
        self.map_history_timeline_drag_mode = None
        self.map_history_timeline_drag_start_pos = None
        self.map_history_timeline_drag_last_x = None
        self.map_history_timeline_reanchor_target = None
        self.map_history_selected_year = None
        self.map_history_selected_context_key = None
        self.map_ui_active = False
        self.map_context_lines = []
        self.map_status_lines = []
        self.map_empty_state_lines = []
        self.map_empty_state_actions = []
        self.map_empty_state_buttons = []
        self.map_empty_state_rect = None
        self.map_location_browser_items = []
        self.map_location_browser_hitboxes = []
        self.map_location_browser_rect = None
        self.map_legend_items = []
        self.map_legend_rect = None
        self.map_sidebar_rect = None
        self.map_sidebar_sections = []
        self.map_context_rect = None
        self.map_layer_selector_rect = None
        self.map_layer_selector_items = []
        self.map_layer_menu_mode = "root"
        self.app_font = pygame.font.SysFont("consolas", 16)
        self._text_surface_cache = {}
        self._text_surface_cache_limit = 512

    def is_text_input_active(self):
        return self.selection_inspector.is_text_input_active()

    def get_map_content_viewport_rect(self, app_width, app_height):
        """Full map canvas footprint, including content behind overlay panels.

        Map menus float over the simulation rather than reducing its canvas.
        Refinement therefore has to capture the surface beneath those menus as
        well as the unobscured center of the screen.
        """
        return pygame.Rect(0, 0, max(1, int(app_width)), max(1, int(app_height)))

    def _format_sim_time(self, sim):
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

    def _reset_shared_state(self):
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.vehicle_requirement_lines = []
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None
        self.person_dossier_lines = []
        self.person_panel_model = None
        self.person_panel_rect = None
        self.person_panel_close_rect = None
        self.person_panel_icons = []
        self.simulation_selection_payload = None
        self.simulation_selection_buttons = []
        self.simulation_selection_rect = None

        self.simulation_bar_rect = None
        self.simulation_bar_title = None
        self.simulation_bar_hint_lines = []
        self.simulation_bar_panel_lines = []
        self.simulation_bar_catalog_entries = []
        self.simulation_bar_catalog_hitboxes = []
        self.simulation_bar_active_catalog_id = None
        self.simulation_bar_resize_hitbox = None

        self.simulation_panel_tabs = []
        self.simulation_panel_active_tab_id = None
        self.simulation_panel_tab_hitboxes = []

        self.map_history_timeline_visible = False
        self.map_history_timeline_rect = None
        self.map_ui_active = False
        self.map_context_lines = []
        self.map_status_lines = []
        self.map_empty_state_lines = []
        self.map_empty_state_actions = []
        self.map_empty_state_buttons = []
        self.map_empty_state_rect = None
        self.map_location_browser_items = []
        self.map_location_browser_hitboxes = []
        self.map_location_browser_rect = None
        self.map_legend_items = []
        self.map_legend_rect = None
        self.map_sidebar_rect = None
        self.map_sidebar_sections = []
        self.map_context_rect = None
        self.map_layer_selector_rect = None
        self.map_layer_selector_items = []

        self.tab_labels = []
        self.active_tab_index = 0
        self.tab_hitboxes = []

        self.time_lines = []
        self.timeline_fraction = 0.0
        self.mouse_world_label = None

    def _short_button_label(self, label, max_chars=24):
        text = str(label or "").strip()
        if len(text) <= max_chars:
            return text
        return text[: max(1, max_chars - 1)].rstrip() + "..."

    def _render_text(self, font, text, color):
        color = tuple(color)
        cache_key = (id(font), str(text), color)
        cached = self._text_surface_cache.get(cache_key)
        if cached is not None:
            return cached

        surface = font.render(str(text), True, color)
        self._text_surface_cache[cache_key] = surface
        while len(self._text_surface_cache) > self._text_surface_cache_limit:
            self._text_surface_cache.pop(next(iter(self._text_surface_cache)))
        return surface

    def _append_map_layer_button(self, button_id, label, x, y, width, height, active=False, enabled=True, depth=0):
        indent = max(0, int(depth or 0)) * 16
        rect = pygame.Rect(x + indent, y, max(80, width - indent), height)
        button = UIButton(button_id, self._short_button_label(label), rect, enabled=enabled)
        button.map_layer_active = bool(active)
        button.map_layer_depth = max(0, int(depth or 0))
        self.buttons.append(button)
        return y + height + 6

    def _rebuild_map_layer_menu(self, active_sim, x, y, width=226):
        button_h = 28
        available_layers = set(getattr(active_sim, "get_available_layer_kinds", lambda: [])())
        active_layer = getattr(active_sim, "get_active_layer_kind", lambda: None)()
        has_materials = bool(getattr(active_sim, "get_material_distribution_items", lambda: [])())

        if self.map_layer_menu_mode == "materials":
            self.map_layer_menu_mode = "root"
        if self.map_layer_menu_mode not in {"root", "materials", "locations"}:
            self.map_layer_menu_mode = "root"

        if self.map_layer_menu_mode == "materials":
            y = self._append_map_layer_button("map_layer_menu_root", "Back", x, y, width, button_h)
            for item in getattr(active_sim, "get_material_distribution_items", lambda: [])():
                item_id = str(item.get("id") or "")
                if not item_id:
                    continue
                label = item.get("label") or item_id
                if item.get("confidence") not in (None, ""):
                    label = f"{label} ({float(item.get('confidence')):.2f})"
                y = self._append_map_layer_button(
                    f"map_select_material:{item_id}",
                    label,
                    x,
                    y,
                    width,
                    button_h,
                    active=bool(item.get("active")) and active_layer == "material_heatmaps",
                )
            return y

        if self.map_layer_menu_mode == "locations":
            y = self._append_map_layer_button("map_layer_menu_root", "Back", x, y, width, button_h)
            items = getattr(active_sim, "get_location_layer_tree_items", lambda: [])()
            if not items:
                y = self._append_map_layer_button(
                    "map_set_layer:locations",
                    "No child locations",
                    x,
                    y,
                    width,
                    button_h,
                    active=active_layer == "locations",
                    enabled=False,
                )
            for item in items:
                item_id = str(item.get("id") or "")
                if not item_id:
                    continue
                y = self._append_map_layer_button(
                    f"map_select_location:{item_id}",
                    item.get("label") or item_id,
                    x,
                    y,
                    width,
                    button_h,
                    active=bool(item.get("active")) and active_layer == "locations",
                    depth=item.get("depth", 0),
                )
            if bool(getattr(active_sim, "can_create_location_draft", lambda: False)()):
                y += 4
                options = getattr(active_sim, "get_location_draft_options", lambda: [])()
                if not options:
                    options = [{"id": "region", "label": "New Location"}]
                for option in options:
                    option_id = str(option.get("id") or "region")
                    option_label = option.get("label") or "New Location"
                    y = self._append_map_layer_button(
                        f"new_location:{option_id}",
                        option_label,
                        x,
                        y,
                        width,
                        button_h,
                        active=False,
                    )
                point_options = getattr(active_sim, "get_point_location_draft_options", lambda: [])()
                if point_options:
                    y += 4
                    for option in point_options[:3]:
                        option_id = str(option.get("id") or "site")
                        option_label = option.get("label") or "Point Location"
                        y = self._append_map_layer_button(
                            f"new_point_location:{option_id}",
                            option_label,
                            x,
                            y,
                            width,
                            button_h,
                            active=False,
                        )
            return y

        self.map_layer_selector_items = []
        title_h = 18
        chip_h = 28
        chip_gap = 6
        selector_y = y
        entries = []
        atmosphere_entry = None
        contours_entry = None
        if "locations" in available_layers:
            entries.append({
                "label": "Map",
                "detail": "Locations",
                "layer_kind": "locations",
                "active": active_layer in {"locations", "visual_map"},
                "color": (82, 108, 92),
            })
        if "true_color" in available_layers:
            entries.append({
                "label": "True Color",
                "detail": "Orbital surface",
                "layer_kind": "true_color",
                "active": active_layer == "true_color",
                "color": (151, 128, 101),
            })
        if "heightmap" in available_layers:
            entries.append({
                "label": "Height",
                "detail": "",
                "layer_kind": "heightmap",
                "active": active_layer == "heightmap",
                "color": (118, 132, 144),
            })
        if "hydrology" in available_layers:
            entries.append({
                "label": "Climate",
                "detail": "",
                "layer_kind": "hydrology",
                "active": active_layer == "hydrology",
                "color": (82, 132, 148),
            })
        if has_materials:
            entries.append({
                "label": "Materials",
                "detail": "",
                "layer_kind": "material_heatmaps",
                "active": active_layer == "material_heatmaps",
                "color": (156, 118, 74),
            })
        if "ground_materials" in available_layers:
            entries.append({
                "label": "Regions",
                "detail": "Contours + boundaries",
                "layer_kind": "ground_materials",
                "active": active_layer == "ground_materials",
                "color": (138, 118, 88),
            })
        if bool(getattr(active_sim, "has_atmosphere_visual", lambda: False)()):
            atmosphere_on = bool(getattr(active_sim, "is_atmosphere_visible", lambda: False)())
            atmosphere_entry = {
                "label": "Atmosphere On" if atmosphere_on else "Atmosphere Off",
                "detail": "Atmosphere",
                "action_id": "toggle_map_atmosphere",
                "active": atmosphere_on,
                "color": (202, 166, 82),
            }
        if bool(getattr(active_sim, "has_height_contours", lambda: False)()):
            contours_on = bool(getattr(active_sim, "is_height_contours_visible", lambda: False)())
            contours_entry = {
                "label": "Contours On" if contours_on else "Contours Off",
                "detail": "Elevation contours",
                "action_id": "toggle_map_height_contours",
                "active": contours_on,
                "color": (206, 214, 220),
            }

        columns = 2 if len(entries) <= 2 else 3
        chip_w = max(66, (width - chip_gap * (columns - 1)) // columns)
        for index, entry in enumerate(entries):
            col = index % columns
            row = index // columns
            rect = pygame.Rect(
                x + col * (chip_w + chip_gap),
                y + title_h + row * (chip_h + chip_gap),
                chip_w,
                chip_h,
            )
            self.map_layer_selector_items.append({**entry, "rect": rect})

        rows = (len(entries) + columns - 1) // columns if entries else 0
        total_h = title_h + rows * chip_h + max(0, rows - 1) * chip_gap
        if atmosphere_entry is not None:
            atmosphere_y = selector_y + total_h + chip_gap
            self.map_layer_selector_items.append({
                **atmosphere_entry,
                "rect": pygame.Rect(x, atmosphere_y, width, chip_h),
            })
            total_h += chip_gap + chip_h
        if contours_entry is not None:
            contours_y = selector_y + total_h + chip_gap
            self.map_layer_selector_items.append({
                **contours_entry,
                "rect": pygame.Rect(x, contours_y, width, chip_h),
            })
            total_h += chip_gap + chip_h
        self.map_layer_selector_rect = pygame.Rect(x, selector_y, width, max(title_h, total_h))
        y = selector_y + total_h + 10

        if active_layer == "material_heatmaps" and has_materials:
            self.map_layer_menu_mode = "materials"
            y = self._append_map_layer_button("map_layer_menu_root", "Material Choices", x, y, width, button_h, enabled=False)
            material_items = list(
                getattr(active_sim, "get_material_distribution_items", lambda: [])()
            )
            composite_items = [
                item for item in material_items
                if str(item.get("id") or "") == "composite"
            ]
            distribution_items = [
                item for item in material_items
                if str(item.get("id") or "") != "composite"
            ]
            for item in composite_items:
                item_id = str(item.get("id") or "")
                label = item.get("label") or item_id
                y = self._append_map_layer_button(
                    f"map_select_material:{item_id}",
                    label,
                    x,
                    y,
                    width,
                    button_h,
                    active=bool(item.get("active")),
                )
            grid_gap = 6
            grid_columns = 2
            grid_width = max(80, (width - grid_gap) // grid_columns)
            grid_start_y = y
            for index, item in enumerate(distribution_items):
                item_id = str(item.get("id") or "")
                if not item_id:
                    continue
                label = item.get("label") or item_id
                if item.get("confidence") not in (None, ""):
                    label = f"{label} ({float(item.get('confidence')):.2f})"
                column = index % grid_columns
                row = index // grid_columns
                rect = pygame.Rect(
                    x + column * (grid_width + grid_gap),
                    grid_start_y + row * (button_h + grid_gap),
                    grid_width,
                    button_h,
                )
                button = UIButton(
                    f"map_select_material:{item_id}",
                    self._short_button_label(label, max_chars=16),
                    rect,
                )
                button.map_layer_active = bool(item.get("active"))
                button.map_layer_depth = 0
                self.buttons.append(button)
            if distribution_items:
                grid_rows = (
                    len(distribution_items) + grid_columns - 1
                ) // grid_columns
                y = grid_start_y + grid_rows * (button_h + grid_gap)
        elif active_layer == "hydrology":
            self.map_layer_menu_mode = "root"
            climate_items = list(
                getattr(active_sim, "get_climate_display_items", lambda: [])()
            )
            if climate_items:
                y = self._append_map_layer_button(
                    "map_climate_display_header",
                    "Climate Display",
                    x,
                    y,
                    width,
                    button_h,
                    enabled=False,
                )
                for item in climate_items:
                    item_id = str(item.get("id") or "")
                    if not item_id:
                        continue
                    y = self._append_map_layer_button(
                        f"map_select_climate:{item_id}",
                        item.get("label") or item_id,
                        x,
                        y,
                        width,
                        button_h,
                        active=bool(item.get("active")),
                    )
        else:
            self.map_layer_menu_mode = "root"
        return y

    def _rebuild_ecosystem_controls(self, active_sim, x, y, width=226):
        button_height = 28
        y += 8
        can_create_biosphere_patch = bool(
            getattr(active_sim, "can_create_biosphere_patch_draft", lambda: False)()
        )
        self.buttons.append(
            UIButton(
                "new_biosphere_patch",
                "Biosphere Area",
                pygame.Rect(x, y, width, button_height),
                enabled=can_create_biosphere_patch,
            )
        )
        y += 40

        if bool(getattr(active_sim, "can_create_biosphere_from_selection", lambda: False)()):
            self.buttons.append(
                UIButton(
                    "create_biosphere",
                    "Create Biosphere",
                    pygame.Rect(x, y, width, button_height),
                )
            )
            y += 40

        return y

    def _rebuild_map_authoring_controls(self, active_sim, x, y, width=226, button_height=32, enabled=True):
        polygon_options = list(getattr(active_sim, "get_location_draft_options", lambda: [])() or [])
        point_options = list(getattr(active_sim, "get_point_location_draft_options", lambda: [])() or [])
        if not polygon_options:
            polygon_options = [{"id": "region", "label": "New Region"}]

        options = [(option, False) for option in polygon_options[:6]]
        options.extend((option, True) for option in point_options[:1])
        columns = 2 if width >= 220 and len(options) > 2 else 1
        gap = 6
        item_width = (width - gap) // 2 if columns == 2 else width
        for index, (option, is_point) in enumerate(options):
            option_id = str(option.get("id") or "region")
            label = option.get("label") or str(option_id).replace("_", " ").title()
            col = index % columns
            row = index // columns
            self.buttons.append(
                UIButton(
                    f"new_point_location:{option_id}" if is_point else f"new_location:{option_id}",
                    label,
                    pygame.Rect(x + col * (item_width + gap), y + row * (button_height + gap), item_width, button_height),
                    enabled=enabled,
                )
            )
        rows = (len(options) + columns - 1) // columns if options else 0
        return y + rows * button_height + max(0, rows - 1) * gap + 8

    def _append_map_sidebar_section(self, label, x, y, width):
        self.map_sidebar_sections.append({
            "label": str(label),
            "rect": pygame.Rect(x, y, width, 18),
        })
        return y + 22

    def _map_root_has_surface(self, root_entity):
        if not isinstance(root_entity, dict):
            return False
        return any(bool(root_entity.get(field)) for field in self.MAP_SURFACE_FIELDS)

    def _map_entity_name(self, active_sim, entity_id):
        if not entity_id:
            return None
        world_model = getattr(active_sim, "world_model", None)
        entity = world_model.get_entity(entity_id) if world_model is not None and hasattr(world_model, "get_entity") else None
        if not isinstance(entity, dict):
            return str(entity_id)
        return entity.get("pretty_name") or entity.get("name") or entity.get("id") or str(entity_id)

    def _build_map_empty_state_lines(
        self,
        active_sim,
        root_name,
        root_has_surface,
        is_editing_map_selection,
        parent_root_entity_id=None,
    ):
        if root_has_surface:
            return []

        placing_id = getattr(active_sim, "placing_location_entity_id", None)
        if is_editing_map_selection and placing_id:
            target_name = self._map_entity_name(active_sim, placing_id) or "this place"
            if parent_root_entity_id:
                parent_name = self._map_entity_name(active_sim, parent_root_entity_id) or "its parent"
                return [
                    "This parent map has not been defined yet.",
                    f"You are placing {target_name} on an empty parent workspace.",
                    f"Place {root_name or 'the parent'} on {parent_name} first, or keep this as a rough sketch.",
                ]
            return [
                "This parent map has not been defined yet.",
                f"You are placing {target_name} on an empty parent workspace.",
                "No higher parent is assigned, so there is no map context above this yet.",
            ]

        if is_editing_map_selection:
            return [
                "This map has not been defined yet.",
                "Click the grid to sketch the first polygon.",
                "Finish becomes available after at least 3 points.",
            ]

        return [
            "This map has not been defined yet.",
            f"{root_name or 'This entry'} has no bounds, geometry, map image, or generated surface.",
            "Define it from a parent map, upload a map image, or choose a parent in the repository.",
        ]

    def _build_map_empty_state_actions(self, active_sim, root_has_surface, parent_root_entity_id=None):
        if root_has_surface:
            return []

        actions = []
        root_id = getattr(getattr(active_sim, "context", None), "root_entity_id", None)
        if parent_root_entity_id and root_id:
            actions.append({
                "id": "place_current_root_on_parent",
                "label": "Place Parent On Its Parent",
            })
            actions.append({
                "id": "open_parent_region_map",
                "label": "Open Parent Map",
            })
        else:
            actions.append({
                "id": "choose_parent_in_repository",
                "label": "Choose Parent In Repository",
            })

        return actions

    def _layout_map_empty_state(self, app_width, app_height, font):
        self.map_empty_state_buttons = []
        self.map_empty_state_rect = None
        if not self.map_empty_state_lines:
            return

        padding = 18
        line_gap = 7
        button_h = 30
        button_gap = 8
        max_panel_w = min(660, max(360, app_width - 680))
        line_widths = [
            font.size(self._ellipsize_text(str(line), font, max_panel_w - padding * 2))[0]
            for line in self.map_empty_state_lines
        ]
        panel_w = max(line_widths or [320]) + padding * 2
        action_specs = list(self.map_empty_state_actions or [])
        action_h = 0
        if action_specs:
            panel_w = max(panel_w, 360)
            action_h = 14 + len(action_specs) * button_h + max(0, len(action_specs) - 1) * button_gap
        panel_h = (
            font.get_height() * len(self.map_empty_state_lines)
            + line_gap * max(0, len(self.map_empty_state_lines) - 1)
            + padding * 2
            + action_h
        )
        center_x = min(app_width // 2, app_width - 360)
        center_y = max(230, min(app_height // 2, app_height - 260))
        rect = pygame.Rect(0, 0, panel_w, panel_h)
        rect.center = (center_x, center_y)
        self.map_empty_state_rect = rect

        if action_specs:
            y = rect.y + padding + font.get_height() * len(self.map_empty_state_lines)
            y += line_gap * max(0, len(self.map_empty_state_lines) - 1) + 14
            button_w = rect.width - padding * 2
            for action in action_specs:
                self.map_empty_state_buttons.append(
                    UIButton(
                        action.get("id"),
                        action.get("label", action.get("id", "Action")),
                        pygame.Rect(rect.x + padding, y, button_w, button_h),
                        enabled=bool(action.get("id")),
                    )
                )
                y += button_h + button_gap

    def _layout_map_location_browser(self, x, y, font):
        self.map_location_browser_hitboxes = []
        self.map_location_browser_rect = None
        if not self.map_location_browser_items:
            return 0

        panel_w = 360
        row_h = max(20, font.get_height() + 6)
        max_rows = min(15, len(self.map_location_browser_items))
        panel_h = 38 + row_h * max_rows + 10
        rect = pygame.Rect(x, y, panel_w, panel_h)
        self.map_location_browser_rect = rect
        row_y = rect.y + 34
        for item in self.map_location_browser_items[:max_rows]:
            entity_id = str(item.get("id") or "")
            if entity_id:
                self.map_location_browser_hitboxes.append(
                    (entity_id, pygame.Rect(rect.x + 8, row_y, rect.width - 16, row_h))
                )
            row_y += row_h
        return rect.height

    def _rebuild_simulation_panel_tab_hitboxes(self):
        self.simulation_panel_tab_hitboxes = []

        if self.simulation_bar_rect is None or not self.simulation_panel_tabs:
            return

        x = self.simulation_bar_rect.x + 12
        y = self.simulation_bar_rect.y + 30
        h = 24
        pad_x = 10
        gap = 6

        for tab in self.simulation_panel_tabs:
            label = tab.get("label", tab.get("id", "tab"))
            tab_w = 8 * len(label) + pad_x * 2 + 4
            rect = pygame.Rect(x, y, tab_w, h)
            self.simulation_panel_tab_hitboxes.append((tab.get("id"), rect))
            x += tab_w + gap

    def _rebuild_vehicle_design_panel(self, active_sim, payload, app_width, app_height):
        blocks_by_id = {
            block.get("id"): block
            for block in payload.get("blocks", [])
        }

        selected_part_id = payload.get("selected_part_id")
        hover_part_id = payload.get("hover_part_id")
        focus_part_id = selected_part_id or hover_part_id

        bar_margin = 20
        bar_height = max(self.simulation_bar_min_height, min(self.simulation_bar_height, self.simulation_bar_max_height))
        self.simulation_bar_height = bar_height

        self.simulation_bar_rect = pygame.Rect(
            bar_margin,
            app_height - bar_height - 20,
            app_width - bar_margin * 2,
            bar_height,
        )
        self.simulation_bar_resize_hitbox = pygame.Rect(
            self.simulation_bar_rect.x,
            self.simulation_bar_rect.y - 4,
            self.simulation_bar_rect.width,
            8,
        )

        self.simulation_bar_title = "Vehicle Design"
        self.simulation_panel_tabs = active_sim.get_simulation_panel_tabs()
        self.simulation_panel_active_tab_id = active_sim.get_active_simulation_panel_tab_id()
        self._rebuild_simulation_panel_tab_hitboxes()

        if self.simulation_panel_active_tab_id == "catalog":
            self.simulation_bar_hint_lines = [
                "Drag the panel edge to resize",
                "Drag catalog cards into the hull",
                "Card footprint follows placed size",
            ]
        elif self.simulation_panel_active_tab_id == "selection":
            self.simulation_bar_hint_lines = []
        elif self.simulation_panel_active_tab_id == "layout":
            self.simulation_bar_hint_lines = []
        else:
            self.simulation_bar_hint_lines = []

        active_panel_tab_id = self.simulation_panel_active_tab_id
        grouped_catalog = payload.get("grouped_component_catalog", [])
        active_catalog_id = payload.get("active_catalog_component_id")
        self.simulation_bar_active_catalog_id = active_catalog_id

        self.simulation_bar_catalog_entries = []
        self.simulation_bar_catalog_hitboxes = []
        self.simulation_bar_panel_lines = []

        if active_panel_tab_id == "selection":
            focus_part_id = selected_part_id or hover_part_id
            if focus_part_id in blocks_by_id:
                block = blocks_by_id[focus_part_id]
                dims = dict(block.get("dimensions_m", {}))
                self.simulation_bar_panel_lines = [
                    "Selected Component",
                    block.get("label", focus_part_id),
                    block.get("component_type", "component"),
                    f"size: {dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m",
                ]
            else:
                self.simulation_bar_panel_lines = [
                    "Selection",
                    "No component selected",
                    "Choose a placed component in the hull",
                ]

        elif active_panel_tab_id == "layout":
            dims = dict(payload.get("vehicle_dimensions_m", {}))
            placed_components = payload.get("blocks", [])
            requirements = payload.get("requirement_status", [])
            satisfied = sum(1 for entry in requirements if entry.get("is_satisfied"))
            self.simulation_bar_panel_lines = [
                "Layout Summary",
                f"hull: {dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m",
                f"placed components: {len(placed_components)}",
                f"requirements: {satisfied}/{len(requirements)} satisfied",
            ]

        if active_panel_tab_id == "catalog":
            content_x = self.simulation_bar_rect.x + 14
            content_y = self.simulation_bar_rect.y + 64
            content_w = int(self.simulation_bar_rect.width * 0.62)
            section_gap_y = 10
            section_header_h = 22
            card_gap_x = 10
            card_gap_y = 10
            text_band_h = 26

            all_entries = []
            for section in grouped_catalog:
                all_entries.extend(section.get("entries", []))

            max_dim_x = 1.0
            max_dim_y = 1.0
            for entry in all_entries:
                dims = dict(entry.get("dimensions_m", {}))
                max_dim_x = max(max_dim_x, float(dims.get("x", 1.0) or 1.0))
                max_dim_y = max(max_dim_y, float(dims.get("y", 1.0) or 1.0))

            def _card_size(entry):
                dims = dict(entry.get("dimensions_m", {}))
                dim_x = float(dims.get("x", 1.0) or 1.0)
                dim_y = float(dims.get("y", 1.0) or 1.0)

                usable_max_w = 180
                usable_max_h = 90

                body_w = max(26, int((dim_x / max_dim_x) * usable_max_w))
                body_h = max(20, int((dim_y / max_dim_y) * usable_max_h))

                card_w = body_w
                card_h = body_h + text_band_h
                return card_w, card_h

            current_y = content_y

            for section in grouped_catalog:
                section_row = {
                    "kind": "section",
                    "label": section.get("title", "Section"),
                }
                section_rect = pygame.Rect(content_x, current_y, content_w, section_header_h)
                self.simulation_bar_catalog_entries.append(section_row)
                self.simulation_bar_catalog_hitboxes.append((None, section_rect, section_row))
                current_y += section_header_h + 6

                cursor_x = content_x
                row_max_h = 0

                for entry in section.get("entries", []):
                    card_w, card_h = _card_size(entry)

                    if cursor_x + card_w > content_x + content_w:
                        cursor_x = content_x
                        current_y += row_max_h + card_gap_y
                        row_max_h = 0

                    row = {
                        "kind": "entry_card",
                        "catalog_id": entry.get("id"),
                        "label": entry.get("label", entry.get("id", "component")),
                        "entry_type": entry.get("entry_type", "component"),
                        "group_name": (entry.get("operational_groups", ["General Systems"])[0] if entry.get("operational_groups") else "General Systems"),
                        "dimensions_m": dict(entry.get("dimensions_m", {})),
                        "component_type": entry.get("component_type", "component"),
                        "body_height": card_h - text_band_h,
                    }

                    card_rect = pygame.Rect(cursor_x, current_y, card_w, card_h)
                    self.simulation_bar_catalog_entries.append(row)
                    self.simulation_bar_catalog_hitboxes.append((row.get("catalog_id"), card_rect, row))

                    cursor_x += card_w + card_gap_x
                    row_max_h = max(row_max_h, card_h)

                current_y += row_max_h + section_gap_y

        mouse_pos = pygame.mouse.get_pos()
        hover_catalog_id = None
        hover_row = None
        for catalog_id, hitbox, row in self.simulation_bar_catalog_hitboxes:
            if catalog_id is None:
                continue
            if hitbox.collidepoint(mouse_pos):
                hover_catalog_id = catalog_id
                hover_row = row
                break

        if active_panel_tab_id == "catalog" and hover_row is not None:
            dims = hover_row.get("dimensions_m", {})
            self.hover_tooltip_lines = [
                "Catalog Item",
                hover_row.get("label", hover_catalog_id),
                hover_row.get("entry_type", "component"),
                hover_row.get("component_type", "component"),
                f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m",
            ]
            self.hover_tooltip_pos = mouse_pos

        elif active_panel_tab_id == "catalog" and active_catalog_id:
            active_row = None
            for catalog_id, _, row in self.simulation_bar_catalog_hitboxes:
                if catalog_id == active_catalog_id:
                    active_row = row
                    break

            if active_row is not None:
                dims = active_row.get("dimensions_m", {})
                self.hover_tooltip_lines = [
                    "Catalog Selection",
                    active_row.get("label", active_catalog_id),
                    active_row.get("entry_type", "component"),
                    active_row.get("component_type", "component"),
                    f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m",
                    "drag into hull to place",
                ]
                self.hover_tooltip_pos = pygame.mouse.get_pos()

        elif focus_part_id in blocks_by_id:
            block = blocks_by_id[focus_part_id]
            self.hover_tooltip_lines = [
                "Vehicle Design",
                block.get("label", focus_part_id),
                block.get("component_type", "component"),
            ]
            self.hover_tooltip_pos = getattr(active_sim, "hover_screen_pos", None) or pygame.mouse.get_pos()

    def _rebuild_map_history_timeline(self, active_sim, app_width, app_height, font):
        panel_h = 126
        margin = 20
        left = margin
        bottom = app_height - margin
        right_reserved = 300 if getattr(self, "map_ui_active", False) else 0

        inspector_rect = getattr(self.selection_inspector, "rect", None)
        if getattr(self.selection_inspector, "is_open", False) and inspector_rect is not None:
            candidate_left = inspector_rect.right + margin
            if app_width - candidate_left - margin - right_reserved >= 420:
                left = candidate_left
            else:
                bottom = inspector_rect.y - 12

        width = app_width - left - margin - right_reserved
        if width < 360:
            self.map_history_timeline_visible = False
            self.map_history_timeline_rect = None
            return

        timeline_items = []
        if hasattr(active_sim, "get_history_timeline_items"):
            timeline_items = active_sim.get_history_timeline_items()
        elif hasattr(active_sim.world_model, "get_timeline_items"):
            timeline_items = active_sim.world_model.get_timeline_items()

        picker_active = self.map_history_timeline_reanchor_target is not None
        if not timeline_items and not picker_active:
            self.map_history_timeline_visible = False
            self.map_history_timeline_rect = None
            self.map_history_timeline.set_items([])
            self.map_history_timeline.set_selected_year(None)
            return

        top = max(170, bottom - panel_h)
        rect = pygame.Rect(left, top, width, panel_h)

        context_label = None
        if hasattr(active_sim, "get_year_context_label"):
            context_label = active_sim.get_year_context_label()
        context_key = getattr(getattr(active_sim, "context", None), "root_entity_id", None)
        if self.map_history_selected_context_key is None:
            self.map_history_selected_context_key = context_key
        elif context_key != self.map_history_selected_context_key:
            self.map_history_selected_year = None
            self.map_history_selected_context_key = context_key

        if picker_active or not getattr(self, "map_ui_active", False):
            selected_year = getattr(active_sim, "year", None)
        else:
            selected_year = self.map_history_selected_year

        self.map_history_timeline_visible = True
        self.map_history_timeline_rect = rect
        self.map_history_timeline.set_title("Map History")
        if hasattr(active_sim, "get_history_timeline_title"):
            self.map_history_timeline.set_title(active_sim.get_history_timeline_title())
        self.map_history_timeline.set_rect(rect)
        self.map_history_timeline.set_font(font)
        self.map_history_timeline.set_year_selection_enabled(True)
        self.map_history_timeline.set_items(timeline_items)
        self.map_history_timeline.set_selected_year(
            selected_year,
            context_label=context_label if selected_year is not None else None,
        )
        self.map_history_timeline.rebuild_layout()

    def _rebuild_active_simulation_ui(self, active_sim, app_width, app_height, camera):
        if active_sim is None:
            self.person_panel_mode = None
            return

        render_mode = getattr(active_sim, "render_mode", None)
        if render_mode != "person":
            self.person_panel_mode = None
        show_time_ui = bool(getattr(active_sim, "show_time_ui", True))

        if show_time_ui:
            time_info = self._format_sim_time(active_sim)
            self.timeline_fraction = time_info["timeline_fraction"]

            self.time_lines = [
                f"Year {time_info['year']} | Day {time_info['day_of_year']}",
                f"{time_info['hours']:02d}:{time_info['minutes']:02d} | Tick {active_sim.sim_clock.tick}",
                f"Time Scale x{active_sim.sim_clock.time_scale:.2f}",
            ]
        else:
            self.timeline_fraction = 0.0
            self.time_lines = []

        if show_time_ui and camera is not None:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            world_x = (mouse_x - app_width / 2) / camera.zoom + camera.x
            world_y = (mouse_y - app_height / 2) / camera.zoom + camera.y
            if render_mode == "map":
                lon_lat = active_sim.world_to_surface_lon_lat(world_x, world_y) if hasattr(active_sim, "world_to_surface_lon_lat") else None
                if lon_lat is not None:
                    self.mouse_world_label = f"Mouse Lon/Lat: {lon_lat[0]:.3f} , {lon_lat[1]:.3f}"
                else:
                    self.mouse_world_label = f"Mouse map position: {world_x:.3f} , {world_y:.3f}"
            else:
                self.mouse_world_label = f"Mouse World: {int(world_x)} , {int(world_y)}"

        button_width = 180
        button_height = 32
        button_x = app_width - button_width - 20
        button_y = 42

        get_selection_payload = getattr(active_sim, "get_selection_inspector_payload", None)
        if get_selection_payload is not None:
            self.simulation_selection_payload = get_selection_payload()

        if render_mode == "vehicle":
            self.scope_label = (
                f"Vehicle: {active_sim.get_vehicle_name()} | "
                f"Mode: {active_sim.get_active_mode_label()}"
            )
            self.breadcrumb_label = f"class: {active_sim.get_vehicle_class()}"

            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )
            self.buttons.append(
                UIButton("vehicle_mode_design", "Vehicle Design",
                         pygame.Rect(button_x, button_y + 40, button_width, button_height),
                         enabled=active_sim.active_view_mode != "design")
            )
            self.buttons.append(
                UIButton("vehicle_mode_interior", "Interior",
                         pygame.Rect(button_x, button_y + 80, button_width, button_height),
                         enabled=active_sim.active_view_mode != "interior")
            )
            self.buttons.append(
                UIButton("vehicle_mode_operational", "Operational",
                         pygame.Rect(button_x, button_y + 120, button_width, button_height),
                         enabled=active_sim.active_view_mode != "operational")
            )

            payload = active_sim.get_focused_render_payload()

            if active_sim.active_view_mode == "design":
                requirement_status = payload.get("requirement_status", [])
                self.vehicle_requirement_lines = [
                    f"{'[OK]' if entry.get('is_satisfied') else '[ ]'} {entry.get('category', 'requirement')} ({entry.get('source_class', 'vehicle')})"
                    for entry in requirement_status
                ]
                self._rebuild_vehicle_design_panel(active_sim, payload, app_width, app_height)
                return

            self.vehicle_requirement_lines = []

            if active_sim.active_view_mode == "interior":
                blocks_by_id = {block.get("id"): block for block in payload.get("blocks", [])}
                focus_part_id = payload.get("selected_part_id") or payload.get("hover_part_id")
                if focus_part_id in blocks_by_id:
                    block = blocks_by_id[focus_part_id]
                    self.hover_tooltip_lines = [
                        active_sim.get_active_mode_label(),
                        block.get("label", focus_part_id),
                    ]
                    self.hover_tooltip_pos = getattr(active_sim, "hover_screen_pos", None) or (24, 250)
                return

            modules_by_id = {
                module.get("id"): module
                for module in payload.get("operational_modules", [])
            }
            focus_part_id = payload.get("selected_part_id") or payload.get("hover_part_id")

            if focus_part_id in modules_by_id:
                module = modules_by_id[focus_part_id]
                self.hover_tooltip_lines = [
                    "Operational Capability",
                    module.get("group", "General"),
                    module.get("label", focus_part_id),
                    module.get("component_label", "component"),
                    module.get("status_text", "ready"),
                ]
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

        self.vehicle_requirement_lines = []

        if render_mode == "map":
            self.map_ui_active = True
            map_mouse_label = self.mouse_world_label
            self.time_lines = []
            self.timeline_fraction = 0.0
            self.mouse_world_label = None

            root_name = active_sim.get_root_name() if hasattr(active_sim, "get_root_name") else None
            root_entity = active_sim.get_root_entity() if hasattr(active_sim, "get_root_entity") else None
            root_has_surface = self._map_root_has_surface(root_entity)
            if root_name:
                self.scope_label = f"Scope: {root_name}"

            existing_status_line = None
            if root_entity:
                canvas_w = root_entity.get("map_canvas_width_px")
                canvas_h = root_entity.get("map_canvas_height_px")
                map_status = root_entity.get("map_status")
                map_image_year = root_entity.get("map_image_year")

                if canvas_w and canvas_h:
                    self.scope_label = f"Scope: {root_name} | Canvas: {canvas_w} x {canvas_h}"

                if map_status:
                    existing_status_line = f"Status: {map_status}"
                if map_image_year not in (None, ""):
                    image_status = f"Map image: {map_image_year}"
                    existing_status_line = (
                        f"{existing_status_line} | {image_status}"
                        if existing_status_line
                        else image_status
                    )

            if hasattr(active_sim, "get_active_layer_label"):
                layer_label = active_sim.get_active_layer_label()
                if self.scope_label:
                    self.scope_label = f"{self.scope_label} | Layer: {layer_label}"
            else:
                layer_label = None

            if hasattr(active_sim, "is_map_editor_active"):
                is_editing_map_selection = bool(active_sim.is_map_editor_active())
            elif hasattr(active_sim, "is_polygon_editor_active"):
                is_editing_map_selection = bool(active_sim.is_polygon_editor_active())
            else:
                is_editing_map_selection = bool(
                    getattr(active_sim, "is_creating_spatial_feature", False)
                )

            if hasattr(active_sim, "get_scope_breadcrumb"):
                breadcrumb_parts = active_sim.get_scope_breadcrumb()
                if breadcrumb_parts:
                    breadcrumb_text = " > ".join(breadcrumb_parts)
                    self.breadcrumb_label = f"Path: {breadcrumb_text}"
                elif existing_status_line:
                    self.breadcrumb_label = existing_status_line
            elif existing_status_line:
                self.breadcrumb_label = existing_status_line

            if is_editing_map_selection:
                if hasattr(active_sim, "get_map_editor_status_label"):
                    draft_status_line = active_sim.get_map_editor_status_label()
                else:
                    point_count = len(getattr(active_sim, "draft_spatial_feature_points", []))
                    draft_status_line = f"Draft selection: {point_count} points"

                if self.breadcrumb_label:
                    self.breadcrumb_label = f"{self.breadcrumb_label} | {draft_status_line}"
                else:
                    self.breadcrumb_label = draft_status_line

            self.map_context_lines = ["Map Workspace"]
            if root_name:
                self.map_context_lines.append(f"Scope: {root_name}")
            if layer_label:
                self.map_context_lines.append(f"Layer: {layer_label}")
            if existing_status_line:
                self.map_context_lines.append(existing_status_line)
            if self.breadcrumb_label:
                self.map_context_lines.append(self.breadcrumb_label)
            if hasattr(active_sim, "get_projection_focus_label") and root_has_surface:
                self.map_context_lines.append(active_sim.get_projection_focus_label())
            if hasattr(active_sim, "get_map_generation_detail_label") and root_has_surface:
                self.map_context_lines.append(active_sim.get_map_generation_detail_label())

            self.map_status_lines = []
            if is_editing_map_selection:
                self.map_status_lines.append(draft_status_line)
            if map_mouse_label:
                self.map_status_lines.append(map_mouse_label)

            parent_root_entity_id = active_sim.get_parent_root_entity_id() if hasattr(active_sim,
                                                                                      "get_parent_root_entity_id") else None

            self.map_empty_state_lines = self._build_map_empty_state_lines(
                active_sim,
                root_name,
                root_has_surface,
                is_editing_map_selection,
                parent_root_entity_id=parent_root_entity_id,
            )
            self.map_empty_state_actions = self._build_map_empty_state_actions(
                active_sim,
                root_has_surface,
                parent_root_entity_id=parent_root_entity_id,
            )
            self.map_location_browser_items = []
            if hasattr(active_sim, "get_map_location_browser_items"):
                self.map_location_browser_items = active_sim.get_map_location_browser_items()
            self.map_legend_items = list(getattr(active_sim, "get_map_legend_items", lambda: [])() or [])
            map_panel_y = 44
            context_lines_for_layout = list(self.map_context_lines)
            if self.map_status_lines:
                if context_lines_for_layout:
                    context_lines_for_layout.append("")
                context_lines_for_layout.extend(self.map_status_lines)
            if context_lines_for_layout:
                map_panel_y += self._info_panel_height(self.app_font, context_lines_for_layout) + 12
            selection_rect = self._simulation_selection_panel_rect(self.app_font, 20, map_panel_y)
            if selection_rect is not None:
                map_panel_y += selection_rect.height + 12
            if self.map_location_browser_items:
                self._layout_map_location_browser(20, map_panel_y, self.app_font)
            self._layout_map_empty_state(app_width, app_height, self.app_font)

            map_control_w = min(270, max(226, app_width // 5))
            map_control_x = max(20, app_width - map_control_w - 24)
            map_control_y = 78
            self.map_sidebar_sections = []
            next_button_y = map_control_y + 30
            next_button_y = self._rebuild_map_layer_menu(active_sim, map_control_x, map_control_y, width=map_control_w) + 12

            can_author_locations = bool(
                getattr(active_sim, "can_create_location_draft", lambda: False)()
            ) and not is_editing_map_selection
            next_button_y = self._append_map_sidebar_section("LOCATION TOOLS", map_control_x, next_button_y, map_control_w)
            self.buttons.append(
                UIButton("link_existing_map_location", "Link Existing Location",
                         pygame.Rect(map_control_x, next_button_y, map_control_w, button_height),
                         enabled=not is_editing_map_selection)
            )
            next_button_y += 40
            next_button_y = self._rebuild_map_authoring_controls(
                active_sim,
                map_control_x,
                next_button_y,
                width=map_control_w,
                button_height=button_height,
                enabled=can_author_locations,
            )

            can_regenerate_current_region = bool(
                getattr(active_sim, "can_regenerate_current_region", lambda: False)()
            )
            can_regenerate_visible_region = bool(
                getattr(active_sim, "can_regenerate_region", lambda: False)()
            )
            if can_regenerate_current_region or can_regenerate_visible_region:
                next_button_y = self._append_map_sidebar_section("DETAIL GENERATION", map_control_x, next_button_y, map_control_w)
            # When both actions are available they target the same visible
            # scope, but only the lower action advances to the next detail
            # level. Keep the fixed-footprint rerun as a fallback at the
            # refinement floor instead of presenting two regenerate buttons.
            if can_regenerate_current_region and not can_regenerate_visible_region:
                current_region_label = getattr(
                    active_sim,
                    "get_current_region_regeneration_label",
                    lambda: "Regenerate This Region",
                )()
                self.buttons.append(UIButton(
                    "regenerate_current_region",
                    current_region_label,
                    pygame.Rect(map_control_x, next_button_y, map_control_w, button_height),
                ))
                next_button_y += 40
            if can_regenerate_visible_region:
                detail_label = getattr(active_sim, "get_next_detail_level_label", lambda: "Regenerate Region")()
                self.buttons.append(UIButton(
                    "regenerate_visible_region",
                    detail_label,
                    pygame.Rect(map_control_x, next_button_y, map_control_w, button_height),
                ))
                next_button_y += 40

            if bool(getattr(active_sim, "can_reset_planet_view", lambda: False)()):
                self.buttons.append(UIButton(
                    "reset_planet_map_view",
                    "Reset Equatorial View",
                    pygame.Rect(map_control_x, next_button_y, map_control_w, button_height),
                ))
                next_button_y += 40

            next_button_y = self._append_map_sidebar_section("WORKSPACE", map_control_x, next_button_y, map_control_w)
            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(map_control_x, next_button_y, map_control_w, button_height))
            )
            next_button_y += 40

            if is_editing_map_selection:
                can_finish = bool(
                    getattr(active_sim, "can_finish_map_editor", lambda: False)()
                )
                self.buttons.append(
                    UIButton("finish_map_selection", "Finish Selection (Enter)",
                             pygame.Rect(map_control_x, next_button_y, map_control_w, button_height),
                             enabled=can_finish)
                )
                next_button_y += 40
                self.buttons.append(
                    UIButton("cancel_map_selection", "Cancel Selection (Esc)",
                    pygame.Rect(map_control_x, next_button_y, map_control_w, button_height))
                )
                next_button_y += 40
            else:
                next_button_y = self._append_map_sidebar_section("ENVIRONMENT", map_control_x, next_button_y, map_control_w)
                next_button_y = self._rebuild_ecosystem_controls(
                    active_sim,
                    map_control_x,
                    next_button_y,
                    width=map_control_w,
                )

            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            root_entity_id = getattr(active_sim.context, "root_entity_id", None)

            has_navigation_controls = (
                (selected_entity_id is not None and selected_entity_id != root_entity_id)
                or parent_root_entity_id is not None
            )
            if has_navigation_controls:
                next_button_y = self._append_map_sidebar_section("NAVIGATION", map_control_x, next_button_y, map_control_w)

            if selected_entity_id is not None and selected_entity_id != root_entity_id:
                self.buttons.append(
                    UIButton("open_region_map", "Open Region Map",
                             pygame.Rect(map_control_x, next_button_y, map_control_w, button_height))
                )
                next_button_y += 40

            if parent_root_entity_id is not None:
                self.buttons.append(
                    UIButton("open_parent_region_map", "Up To Parent",
                             pygame.Rect(map_control_x, next_button_y, map_control_w, button_height))
                )
                next_button_y += 40
            self.map_sidebar_rect = pygame.Rect(
                map_control_x - 12,
                max(42, map_control_y - 36),
                map_control_w + 24,
                max(180, next_button_y - map_control_y + 50),
            )

            hover_spatial_feature_id = getattr(active_sim, "hover_spatial_feature_id", None)
            hover_entity_id = getattr(active_sim, "hover_entity_id", None)
            hover_screen_pos = getattr(active_sim, "hover_screen_pos", None)

            if hover_spatial_feature_id and hover_screen_pos:
                feature = active_sim.get_spatial_feature(hover_spatial_feature_id) if hasattr(active_sim, "get_spatial_feature") else None
                feature_layer = None
                if feature is None and hasattr(active_sim, "get_layers"):
                    for layer in active_sim.get_layers():
                        if layer.get("spatial_feature_id") == hover_spatial_feature_id:
                            feature_layer = layer
                            break

                if feature is not None:
                    owner_entity_id = feature.get("owner_entity")
                    owner_text = f"owner: {owner_entity_id}" if owner_entity_id else "draft region"
                    region_class = feature.get("region_class") or feature.get("layer_kind", "region")
                    self.hover_tooltip_lines = [
                        feature.get("name", hover_spatial_feature_id),
                        f"region: {region_class}",
                        owner_text,
                    ]
                    self.hover_tooltip_pos = hover_screen_pos
                elif feature_layer is not None:
                    self.hover_tooltip_lines = [
                        feature_layer.get("name", hover_spatial_feature_id),
                        f"region: {feature_layer.get('region_class', 'region')}",
                        "virtual aggregate",
                    ]
                    self.hover_tooltip_pos = hover_screen_pos

            elif hover_entity_id and hover_screen_pos:
                entity = active_sim.world_model.get_entity(hover_entity_id)
                if entity:
                    self.hover_tooltip_lines = [
                        entity.get("name", hover_entity_id),
                        f"class: {entity.get('location_class', entity.get('type', 'entity'))}",
                    ]
                    self.hover_tooltip_pos = hover_screen_pos

            self._rebuild_map_history_timeline(
                active_sim=active_sim,
                app_width=app_width,
                app_height=app_height,
                font=self.app_font,
            )
            return

        if render_mode == "person":
            person_name = active_sim.get_person_name() if hasattr(active_sim, "get_person_name") else "Person"
            person_class = active_sim.get_person_class() if hasattr(active_sim, "get_person_class") else "person"
            self.scope_label = f"Person: {person_name}"
            self.breadcrumb_label = f"class: {person_class}"
            self.person_dossier_lines = (
                active_sim.get_dossier_panel_lines()
                if hasattr(active_sim, "get_dossier_panel_lines")
                else []
            )

            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )
            self.buttons.append(
                UIButton("open_person_inspector", "Edit Dossier",
                         pygame.Rect(button_x, button_y + 40, button_width, button_height))
            )
            control_mode = getattr(active_sim, "control_mode", "autonomous")
            self.buttons.append(
                UIButton(
                    "person_mode_autonomous",
                    "Autonomous Queue",
                    pygame.Rect(button_x, button_y + 80, button_width, button_height),
                    enabled=control_mode != "autonomous",
                )
            )
            self.buttons.append(
                UIButton(
                    "person_mode_direct",
                    "Direct Control",
                    pygame.Rect(button_x, button_y + 120, button_width, button_height),
                    enabled=control_mode != "direct",
                )
            )

            icon_size = 46
            icon_x = app_width - icon_size - 20
            icon_y = button_y + 166
            self.person_panel_icons = [
                {
                    "id": "needs",
                    "label": "Needs",
                    "rect": pygame.Rect(icon_x, icon_y, icon_size, icon_size),
                },
                {
                    "id": "personality",
                    "label": "Personality",
                    "rect": pygame.Rect(icon_x, icon_y + icon_size + 12, icon_size, icon_size),
                },
            ]
            if self.person_panel_mode == "needs" and hasattr(active_sim, "get_needs_panel_model"):
                self.person_panel_model = active_sim.get_needs_panel_model()
            elif self.person_panel_mode == "personality" and hasattr(active_sim, "get_personality_panel_model"):
                self.person_panel_model = active_sim.get_personality_panel_model()

            if self.person_panel_model is not None:
                panel_w = min(760, max(520, app_width - 250))
                panel_h = min(610, max(430, app_height - 110))
                panel_x = max(20, icon_x - panel_w - 18)
                panel_y = max(52, (app_height - panel_h) // 2)
                self.person_panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)
                self.person_panel_close_rect = pygame.Rect(
                    self.person_panel_rect.right - 40,
                    self.person_panel_rect.y + 12,
                    26,
                    26,
                )

            self._rebuild_map_history_timeline(
                active_sim=active_sim,
                app_width=app_width,
                app_height=app_height,
                font=self.app_font,
            )
            return

        if render_mode == "space":
            if hasattr(active_sim, "get_scope_label"):
                self.scope_label = f"Space: {active_sim.get_scope_label()}"
            if hasattr(active_sim, "get_scope_breadcrumb"):
                self.breadcrumb_label = active_sim.get_scope_breadcrumb()

            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )

            selected_body_entity = active_sim.get_selected_body_entity() if hasattr(active_sim,
                                                                                    "get_selected_body_entity") else None
            if selected_body_entity:
                self.buttons.append(
                    UIButton("open_space_body_map", "Open Map",
                             pygame.Rect(button_x, button_y + 40, button_width, button_height))
                )

            hover_body_id = getattr(active_sim, "hover_system_entity_id", None)
            hover_screen_pos = getattr(active_sim, "hover_screen_pos", None)

            if hover_body_id and hover_screen_pos:
                entity = active_sim.world_model.get_entity(hover_body_id)
                if entity:
                    self.hover_tooltip_lines = [
                        entity.get("name", hover_body_id),
                        f"class: {entity.get('body_class', entity.get('type', 'entity'))}",
                    ]
                    self.hover_tooltip_pos = hover_screen_pos
            return

        if render_mode == "world_gen":
            if bool(getattr(active_sim, "is_fullscreen_editor_active", lambda: False)()):
                self.time_lines = []
                self.timeline_fraction = 0.0
                self.mouse_world_label = None
                self.scope_label = None
                self.breadcrumb_label = None
                self.buttons = []
                return

            if hasattr(active_sim, "get_scope_label"):
                self.scope_label = f"World Gen: {active_sim.get_scope_label()}"
            if hasattr(active_sim, "get_scope_breadcrumb"):
                self.breadcrumb_label = active_sim.get_scope_breadcrumb()

            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )

            return

        if render_mode == "bioregion":
            scope_label = (
                active_sim.get_scope_label()
                if hasattr(active_sim, "get_scope_label")
                else "Bioregion Test Map | 10 km x 10 km"
            )
            self.scope_label = f"Scope: {scope_label}"

            avg_surface = active_sim.get_average_surface_water()
            avg_top = active_sim.get_average_top_moisture()
            avg_deep = active_sim.get_average_deep_moisture()

            rain_text = "Rain: active" if getattr(active_sim, "is_raining", False) else "Rain: dry"
            species_count = (
                active_sim.get_selected_species_count()
                if hasattr(active_sim, "get_selected_species_count")
                else 0
            )
            self.breadcrumb_label = (
                f"{rain_text} | Avg surf: {avg_surface:.3f} | "
                f"Avg top: {avg_top:.3f} | Avg deep: {avg_deep:.3f} | "
                f"Species: {species_count}"
            )
            if hasattr(active_sim, "get_scope_breadcrumb"):
                breadcrumb = active_sim.get_scope_breadcrumb()
                if breadcrumb:
                    self.breadcrumb_label = f"{breadcrumb} | {self.breadcrumb_label}"

            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )
            next_button_y = button_y + 40
            for entry in getattr(active_sim, "get_species_catalog_entries", lambda: [])():
                species_id = str(entry.get("id") or "")
                if not species_id:
                    continue
                label = entry.get("label") or species_id
                suitability = entry.get("suitability")
                if isinstance(suitability, (int, float)):
                    label = f"{label} {int(max(0.0, min(1.0, suitability)) * 100)}%"
                prefix = "[x] " if entry.get("selected") else "[ ] "
                self.buttons.append(
                    UIButton(
                        f"biosphere_toggle_species:{species_id}",
                        self._short_button_label(prefix + label, max_chars=28),
                        pygame.Rect(button_x, next_button_y, button_width, button_height),
                    )
                )
                next_button_y += 40

    def rebuild_for_state(
            self,
            active_sim,
            app_width,
            app_height,
            tab_manager=None,
            camera=None,
            menu_active=False,
            system_menu_active=False,
            system_settings_active=False,
            repository_return_confirm_active=False,
            world_model=None,
            repository_scope_entity_id=None,
            parent_assignment_request=None
    ):
        self._reset_shared_state()
        self.menu_active = menu_active
        self.system_menu_active = system_menu_active
        self.system_settings_active = system_settings_active
        self.repository_return_confirm_active = repository_return_confirm_active
        self._rebuild_system_menu(app_width, app_height)
        self._rebuild_repository_return_confirm(app_width, app_height)

        self._rebuild_selection_inspector(active_sim, app_width, app_height)

        if tab_manager is not None:
            self.tab_labels = [tab.name for tab in tab_manager.tabs]
            self.active_tab_index = tab_manager.active_index

        if menu_active:
            self.knowledge_ui.rebuild(
                app_width=app_width,
                app_height=app_height,
                world_model=world_model,
                repository_scope_entity_id=repository_scope_entity_id,
                font=self.app_font,
                parent_assignment_request=parent_assignment_request,
            )
            return

        self._rebuild_active_simulation_ui(active_sim, app_width, app_height, camera)

    def _rebuild_repository_return_confirm(self, app_width, app_height):
        self.repository_return_confirm_rect = None
        self.repository_return_confirm_buttons = []

        if not self.repository_return_confirm_active:
            return

        panel_w = 420
        panel_h = 156
        panel_x = (app_width - panel_w) // 2
        panel_y = (app_height - panel_h) // 2
        self.repository_return_confirm_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        button_w = 156
        button_h = 34
        button_y = panel_y + panel_h - button_h - 20
        self.repository_return_confirm_buttons = [
            UIButton(
                "confirm_open_repository",
                "Return",
                pygame.Rect(panel_x + 52, button_y, button_w, button_h),
            ),
            UIButton(
                "cancel_repository_return",
                "Stay",
                pygame.Rect(panel_x + panel_w - button_w - 52, button_y, button_w, button_h),
            ),
        ]

    def _rebuild_system_menu(self, app_width, app_height):
        self.system_menu_buttons = []
        self.system_menu_rect = None

        if not self.system_menu_active:
            return

        panel_w = 320
        panel_h = 476 if self.system_settings_active else 236
        panel_x = (app_width - panel_w) // 2
        panel_y = (app_height - panel_h) // 2
        self.system_menu_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        button_w = 220
        button_h = 34
        button_x = panel_x + (panel_w - button_w) // 2
        button_y = panel_y + 78
        gap = 14

        if self.system_settings_active:
            clade_count = getattr(self.knowledge_ui, "phylogeny_clade_member_count", 3)
            species_count = getattr(self.knowledge_ui, "phylogeny_species_relative_count", 4)
            debug_enabled = bool(getattr(self.knowledge_ui, "performance_debug_enabled", False))
            checkpoint_confirm = bool(getattr(self.knowledge_ui, "ontology_checkpoint_confirm", False))
            half_w = (button_w - gap) // 2
            self.system_menu_buttons.extend([
                UIButton("system_toggle_grid", "Toggle Grid", pygame.Rect(button_x, button_y, button_w, button_h)),
                UIButton("system_toggle_fps", "Toggle FPS", pygame.Rect(button_x, button_y + (button_h + gap), button_w, button_h)),
                UIButton("phylogeny_clade_members_dec", f"Clade - ({clade_count})", pygame.Rect(button_x, button_y + (button_h + gap) * 2, half_w, button_h)),
                UIButton("phylogeny_clade_members_inc", "Clade +", pygame.Rect(button_x + half_w + gap, button_y + (button_h + gap) * 2, half_w, button_h)),
                UIButton("phylogeny_species_relatives_dec", f"Species - ({species_count})", pygame.Rect(button_x, button_y + (button_h + gap) * 3, half_w, button_h)),
                UIButton("phylogeny_species_relatives_inc", "Species +", pygame.Rect(button_x + half_w + gap, button_y + (button_h + gap) * 3, half_w, button_h)),
                UIButton("system_toggle_debug", f"Performance Debug: {'On' if debug_enabled else 'Off'}", pygame.Rect(button_x, button_y + (button_h + gap) * 4, button_w, button_h)),
                UIButton("system_save_ontology", "Confirm Save Ontology" if checkpoint_confirm else "Save Ontology", pygame.Rect(button_x, button_y + (button_h + gap) * 5, button_w, button_h)),
                UIButton("system_menu_back", "Back", pygame.Rect(button_x, button_y + (button_h + gap) * 6, button_w, button_h)),
            ])
            return

        self.system_menu_buttons.extend([
            UIButton("system_menu_continue", "Continue", pygame.Rect(button_x, button_y, button_w, button_h)),
            UIButton("system_menu_settings", "Settings", pygame.Rect(button_x, button_y + (button_h + gap), button_w, button_h)),
            UIButton("system_menu_quit", "Quit", pygame.Rect(button_x, button_y + (button_h + gap) * 2, button_w, button_h)),
        ])

    def _rebuild_selection_inspector(self, active_sim, app_width, app_height):
        if active_sim is not None and hasattr(active_sim, "consume_pending_inspector_target"):
            target = active_sim.consume_pending_inspector_target()
            if target:
                target_kind = target.get("kind")
                target_id = target.get("id")
                record = None

                if target_kind == "spatial_feature" and hasattr(active_sim, "get_spatial_feature"):
                    record = active_sim.get_spatial_feature(target_id)
                elif target_kind == "location" and hasattr(active_sim, "get_location"):
                    record = active_sim.get_location(target_id)
                elif target_kind == "person" and hasattr(active_sim, "get_person"):
                    record = active_sim.get_person(target_id)

                if record is not None:
                    self._clear_map_history_reanchor_target()
                    self.selection_inspector.open(
                        target_kind=target_kind,
                        target_id=target_id,
                        record=record,
                    )

        self.selection_inspector.rebuild(app_width, app_height)

    def _draw_simulation_bar(self, screen, font):
        if self.simulation_bar_rect is None:
            return

        pygame.draw.rect(screen, (22, 24, 30), self.simulation_bar_rect)
        pygame.draw.rect(screen, (200, 200, 200), self.simulation_bar_rect, 1)

        if self.simulation_bar_resize_hitbox is not None:
            line_y = self.simulation_bar_rect.y
            pygame.draw.line(
                screen,
                (150, 150, 160),
                (self.simulation_bar_rect.x + 2, line_y),
                (self.simulation_bar_rect.right - 2, line_y),
                2,
            )

        if self.simulation_bar_title:
            title_surface = self._render_text(font, self.simulation_bar_title, (240, 240, 240))
            screen.blit(title_surface, (self.simulation_bar_rect.x + 12, self.simulation_bar_rect.y + 10))

        self._draw_simulation_panel_tabs(screen, font)

        if self.simulation_panel_active_tab_id == "catalog" and self.simulation_bar_catalog_entries:
            self._draw_simulation_bar_catalog(screen, font)
        elif self.simulation_panel_active_tab_id == "selection":
            self._draw_simulation_panel_lines(screen, font, self.simulation_bar_panel_lines)
        elif self.simulation_panel_active_tab_id == "layout":
            self._draw_simulation_panel_lines(screen, font, self.simulation_bar_panel_lines)
        elif self.simulation_bar_catalog_entries:
            self._draw_simulation_bar_catalog(screen, font)

        hint_x = self.simulation_bar_rect.x + int(self.simulation_bar_rect.width * 0.66)
        hint_y = self.simulation_bar_rect.y + 42
        for line in self.simulation_bar_hint_lines:
            text_surface = self._render_text(font, line, (185, 185, 185))
            screen.blit(text_surface, (hint_x, hint_y))
            hint_y += 18

    def _draw_simulation_panel_tabs(self, screen, font):
        if self.simulation_bar_rect is None or not self.simulation_panel_tabs:
            return

        hitbox_by_id = {
            tab_id: rect
            for tab_id, rect in self.simulation_panel_tab_hitboxes
        }

        for tab in self.simulation_panel_tabs:
            tab_id = tab.get("id")
            rect = hitbox_by_id.get(tab_id)
            if rect is None:
                continue

            label = tab.get("label", tab_id or "tab")
            text_surface = self._render_text(font, label, (240, 240, 240))
            active = tab_id == self.simulation_panel_active_tab_id

            fill = (70, 70, 90) if active else (36, 40, 48)
            border = (230, 230, 230) if active else (170, 170, 170)

            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, border, rect, 1)
            screen.blit(
                text_surface,
                (rect.x + 10, rect.y + (rect.height - text_surface.get_height()) // 2),
            )

    def _draw_simulation_panel_lines(self, screen, font, lines):
        if self.simulation_bar_rect is None:
            return

        if not lines:
            return

        x = self.simulation_bar_rect.x + 14
        y = self.simulation_bar_rect.y + 68
        max_width = max(80, int(self.simulation_bar_rect.width * 0.62) - 20)

        for index, line in enumerate(lines):
            color = (238, 242, 248) if index == 0 else (186, 194, 208)
            text = self._ellipsize_text(str(line), font, max_width)
            text_surface = self._render_text(font, text, color)
            screen.blit(text_surface, (x, y))
            y += 22 if index == 0 else 18

    def _draw_simulation_bar_catalog(self, screen, font):
        mouse_pos = pygame.mouse.get_pos()
        hovered_catalog_id = None

        for catalog_id, hitbox, row in self.simulation_bar_catalog_hitboxes:
            if catalog_id is None:
                continue
            if hitbox.collidepoint(mouse_pos):
                hovered_catalog_id = catalog_id
                break

        active_catalog_id = self.simulation_bar_active_catalog_id

        for catalog_id, hitbox, row in self.simulation_bar_catalog_hitboxes:
            kind = row.get("kind")

            if kind == "section":
                pygame.draw.rect(screen, (40, 44, 54), hitbox)
                pygame.draw.rect(screen, (130, 130, 140), hitbox, 1)
                text_surface = self._render_text(font, row.get("label", "Section"), (220, 220, 220))
                screen.blit(text_surface, (hitbox.x + 6, hitbox.y + 2))
                continue

            border_color = (170, 170, 170)
            fill_color = (34, 38, 46)

            if row.get("entry_type") == "assembly":
                fill_color = (46, 40, 58)

            if catalog_id == hovered_catalog_id:
                border_color = (120, 220, 255)
                fill_color = (52, 66, 82)

            if catalog_id == active_catalog_id:
                border_color = (255, 230, 120)
                fill_color = (92, 84, 50)

            pygame.draw.rect(screen, fill_color, hitbox)
            pygame.draw.rect(screen, border_color, hitbox, 2)

            body_height = int(row.get("body_height", max(20, hitbox.height - 26)))
            body_rect = pygame.Rect(hitbox.x + 4, hitbox.y + 4, max(8, hitbox.width - 8), max(8, body_height - 4))
            pygame.draw.rect(screen, (70, 74, 86), body_rect, 1)

            dims = row.get("dimensions_m", {})
            line_1 = row.get("label", catalog_id or "component")
            line_2 = row.get("entry_type", "component")
            line_3 = f"{dims.get('x', '?')} x {dims.get('y', '?')}"

            text_surface_1 = self._render_text(font, line_1, (240, 240, 240))
            text_surface_2 = self._render_text(font, line_2, (185, 185, 195))
            text_surface_3 = self._render_text(font, line_3, (165, 165, 175))

            text_y = hitbox.bottom - 34
            screen.blit(text_surface_1, (hitbox.x + 6, text_y))
            screen.blit(text_surface_2, (hitbox.x + 6, text_y + 14))
            screen.blit(text_surface_3, (hitbox.x + 6, text_y + 28))

    def _ellipsize_text(self, text, font, max_width):
        text = str(text or "")
        if max_width <= 0 or font.size(text)[0] <= max_width:
            return text

        ellipsis = "..."
        ellipsis_width = font.size(ellipsis)[0]
        if ellipsis_width >= max_width:
            return ""

        low = 0
        high = len(text)
        while low < high:
            mid = (low + high + 1) // 2
            candidate = text[:mid].rstrip() + ellipsis
            if font.size(candidate)[0] <= max_width:
                low = mid
            else:
                high = mid - 1

        return text[:low].rstrip() + ellipsis

    def _draw_button(self, screen, font, button):
        is_map_layer_active = bool(getattr(button, "map_layer_active", False))
        if is_map_layer_active and button.enabled:
            fill_color = (68, 78, 110)
            border_color = (232, 218, 154)
        else:
            fill_color = (52, 56, 66) if button.enabled else (34, 36, 42)
            border_color = (210, 210, 210) if button.enabled else (100, 100, 100)
        text_color = (245, 245, 245) if button.enabled else (140, 140, 140)

        pygame.draw.rect(screen, fill_color, button.rect)
        pygame.draw.rect(screen, border_color, button.rect, 2)

        clip = screen.get_clip()
        screen.set_clip(button.rect.clip(screen.get_rect()))
        checkbox_width = 0
        if getattr(button, "check_button", False):
            checkbox_size = max(12, min(16, button.rect.height - 10))
            checkbox_rect = pygame.Rect(
                button.rect.x + 7,
                button.rect.centery - checkbox_size // 2,
                checkbox_size,
                checkbox_size,
            )
            pygame.draw.rect(screen, (22, 24, 30), checkbox_rect)
            pygame.draw.rect(screen, border_color, checkbox_rect, 1)
            if getattr(button, "checked", False):
                pygame.draw.line(screen, text_color, (checkbox_rect.x + 3, checkbox_rect.centery), (checkbox_rect.centerx - 1, checkbox_rect.bottom - 4), 2)
                pygame.draw.line(screen, text_color, (checkbox_rect.centerx - 1, checkbox_rect.bottom - 4), (checkbox_rect.right - 3, checkbox_rect.y + 3), 2)
            checkbox_width = checkbox_size + 8

        text_area = pygame.Rect(
            button.rect.x + 7 + checkbox_width,
            button.rect.y + 3,
            max(0, button.rect.width - 14 - checkbox_width),
            max(0, button.rect.height - 6),
        )
        words = str(button.label or "").split()
        lines = [str(button.label or "")]
        line_height = max(1, font.get_linesize())
        if font.size(lines[0])[0] > text_area.width and text_area.height >= line_height * 2 and len(words) > 1:
            lines = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and font.size(candidate)[0] > text_area.width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            max_lines = max(1, text_area.height // line_height)
            lines = lines[:max_lines]
        lines = [self._ellipsize_text(line, font, text_area.width) for line in lines]
        total_text_h = len(lines) * line_height
        text_y = text_area.centery - total_text_h // 2
        for line in lines:
            text_surface = self._render_text(font, line, text_color)
            text_rect = text_surface.get_rect(centerx=text_area.centerx, y=text_y)
            screen.blit(text_surface, text_rect)
            text_y += line_height
        screen.set_clip(clip)

    def _draw_info_panel(self, screen, font, x, y, lines, max_width=None):
        if not lines:
            return 0

        padding = 8
        line_gap = 4
        if max_width is None:
            max_width = screen.get_width() - x - 20
        max_width = max(120, min(int(max_width), screen.get_width() - x - 20))

        display_lines = [
            self._ellipsize_text(str(line), font, max_width - padding * 2)
            for line in lines
        ]
        rendered = [self._render_text(font, line, (240, 240, 240)) for line in display_lines]
        panel_width = min(max_width, max(text.get_width() for text in rendered) + padding * 2)
        panel_height = (
            sum(text.get_height() for text in rendered)
            + line_gap * (len(rendered) - 1)
            + padding * 2
        )

        panel_rect = pygame.Rect(x, y, panel_width, panel_height)
        pygame.draw.rect(screen, (28, 28, 32), panel_rect)
        pygame.draw.rect(screen, (200, 200, 200), panel_rect, 1)

        current_y = panel_rect.y + padding
        clip = screen.get_clip()
        screen.set_clip(panel_rect.clip(screen.get_rect()))
        for text_surface in rendered:
            screen.blit(text_surface, (panel_rect.x + padding, current_y))
            current_y += text_surface.get_height() + line_gap
        screen.set_clip(clip)
        return panel_height

    def _info_panel_height(self, font, lines):
        if not lines:
            return 0
        padding = 8
        line_gap = 4
        line_height = font.get_height()
        return line_height * len(lines) + line_gap * (len(lines) - 1) + padding * 2

    def _simulation_selection_panel_rect(self, font, x, y):
        payload = self.simulation_selection_payload
        if not payload:
            return None

        lines = [
            "Selection",
            str(payload.get("title") or "Unnamed selection"),
            str(payload.get("kind") or "Simulation object"),
        ]
        lines.extend(str(line) for line in payload.get("details", []) if line not in (None, ""))

        padding = 10
        line_gap = 4
        button_h = 28
        button_gap = 6
        rendered = [self._render_text(font, line, (240, 240, 240)) for line in lines]
        actions = payload.get("actions", [])
        content_width = min(480, max([280] + [surface.get_width() for surface in rendered]))
        panel_width = content_width + padding * 2
        text_height = (
            sum(surface.get_height() for surface in rendered)
            + line_gap * (len(rendered) - 1)
        )
        actions_height = len(actions) * button_h + max(0, len(actions) - 1) * button_gap
        panel_height = padding * 2 + text_height + (10 + actions_height if actions else 0)
        return pygame.Rect(x, y, panel_width, panel_height)

    def _simulation_selection_layout_rect(self, font):
        info_lines = []
        if self.scope_label:
            info_lines.append(self.scope_label)
        if self.breadcrumb_label:
            info_lines.append(self.breadcrumb_label)

        current_info_y = 170
        if info_lines:
            current_info_y += self._info_panel_height(font, info_lines) + 12

        if self.vehicle_requirement_lines:
            requirement_lines = ["Requirements"] + self.vehicle_requirement_lines
            current_info_y += self._info_panel_height(font, requirement_lines) + 12

        return self._simulation_selection_panel_rect(font, 20, current_info_y)

    def _draw_simulation_selection_inspector(self, screen, font, x, y):
        payload = self.simulation_selection_payload
        if not payload:
            self.simulation_selection_buttons = []
            self.simulation_selection_rect = None
            return 0

        lines = [
            "Selection",
            str(payload.get("title") or "Unnamed selection"),
            str(payload.get("kind") or "Simulation object"),
        ]
        lines.extend(str(line) for line in payload.get("details", []) if line not in (None, ""))

        padding = 10
        line_gap = 4
        button_h = 28
        button_gap = 6
        rendered = [self._render_text(font, line, (240, 240, 240)) for line in lines]
        actions = payload.get("actions", [])
        panel_rect = self._simulation_selection_panel_rect(font, x, y)
        self.simulation_selection_rect = panel_rect
        content_width = panel_rect.width - padding * 2

        pygame.draw.rect(screen, (24, 28, 36), panel_rect)
        pygame.draw.rect(screen, (154, 174, 208), panel_rect, 1)

        current_y = panel_rect.y + padding
        for index, text_surface in enumerate(rendered):
            text_color = (245, 245, 245) if index < 2 else (185, 194, 210)
            display_line = self._ellipsize_text(lines[index], font, content_width)
            if text_color != (240, 240, 240) or display_line != lines[index]:
                text_surface = self._render_text(font, display_line, text_color)
            screen.blit(text_surface, (panel_rect.x + padding, current_y))
            current_y += text_surface.get_height() + line_gap

        self.simulation_selection_buttons = []
        if actions:
            current_y += 6
            for action in actions:
                button = UIButton(
                    action.get("id"),
                    action.get("label", action.get("id", "Action")),
                    pygame.Rect(panel_rect.x + padding, current_y, content_width, button_h),
                    enabled=bool(action.get("id")) and action.get("enabled", True),
                )
                self.simulation_selection_buttons.append(button)
                self._draw_button(screen, font, button)
                current_y += button_h + button_gap

        return panel_rect.height

    def _draw_hover_tooltip(self, screen, font):
        if not self.hover_tooltip_lines or not self.hover_tooltip_pos:
            return

        padding = 8
        line_gap = 4
        rendered = [self._render_text(font, line, (240, 240, 240)) for line in self.hover_tooltip_lines]
        panel_width = max(text.get_width() for text in rendered) + padding * 2
        panel_height = (
            sum(text.get_height() for text in rendered)
            + line_gap * (len(rendered) - 1)
            + padding * 2
        )

        anchor_x, anchor_y = self.hover_tooltip_pos
        tooltip_x = anchor_x + 14
        tooltip_y = anchor_y + 14

        screen_width = screen.get_width()
        screen_height = screen.get_height()
        margin = 10

        if tooltip_x + panel_width > screen_width - margin:
            tooltip_x = anchor_x - panel_width - 14

        if tooltip_y + panel_height > screen_height - margin:
            tooltip_y = anchor_y - panel_height - 14

        tooltip_x = max(margin, min(tooltip_x, screen_width - panel_width - margin))
        tooltip_y = max(margin, min(tooltip_y, screen_height - panel_height - margin))

        tooltip_rect = pygame.Rect(int(tooltip_x), int(tooltip_y), int(panel_width), int(panel_height))
        pygame.draw.rect(screen, (24, 24, 28), tooltip_rect)
        pygame.draw.rect(screen, (210, 210, 210), tooltip_rect, 1)

        current_y = tooltip_rect.y + padding
        for text_surface in rendered:
            screen.blit(text_surface, (tooltip_rect.x + padding, current_y))
            current_y += text_surface.get_height() + line_gap

    def _draw_tab_strip(self, screen, font):
        x_offset = 20
        y_offset = 5
        padding = 8
        gap = 5
        max_right = screen.get_width() - 20

        self.tab_hitboxes = []

        for i, label in enumerate(self.tab_labels):
            remaining_tabs = max(1, len(self.tab_labels) - i)
            remaining_width = max_right - x_offset
            if remaining_width <= 42:
                break

            if remaining_tabs > 1:
                max_tab_width = max(92, min(220, int((remaining_width - 48) / remaining_tabs) - gap))
            else:
                max_tab_width = min(260, remaining_width)

            text_label = self._ellipsize_text(label, font, max_tab_width - padding * 2)
            text_surface = self._render_text(font, text_label, (255, 255, 255))

            rect = pygame.Rect(
                x_offset,
                y_offset,
                min(max_tab_width, text_surface.get_width() + padding * 2),
                text_surface.get_height() + padding
            )

            if rect.right > max_right:
                hidden_count = len(self.tab_labels) - i
                more_label = f"+{hidden_count}"
                more_surface = self._render_text(font, more_label, (198, 204, 216))
                more_rect = pygame.Rect(
                    x_offset,
                    y_offset,
                    more_surface.get_width() + padding * 2,
                    more_surface.get_height() + padding,
                )
                pygame.draw.rect(screen, (32, 34, 42), more_rect)
                pygame.draw.rect(screen, (138, 146, 164), more_rect, 1)
                screen.blit(more_surface, (more_rect.x + padding, more_rect.y + padding // 2))
                break

            if i == self.active_tab_index:
                pygame.draw.rect(screen, (78, 88, 122), rect)
            else:
                pygame.draw.rect(screen, (36, 38, 46), rect)

            pygame.draw.rect(screen, (200, 200, 200), rect, 1)
            clip = screen.get_clip()
            screen.set_clip(rect.clip(screen.get_rect()))
            screen.blit(text_surface, (rect.x + padding, rect.y + padding // 2))
            screen.set_clip(clip)

            self.tab_hitboxes.append((i, rect))
            x_offset += rect.width + gap

    def _draw_time_panel(self, screen, font):
        lines = list(self.time_lines)

        if self.mouse_world_label:
            lines.append(self.mouse_world_label)

        if not lines:
            return

        self._draw_info_panel(screen, font, 20, 40, lines)

    def _draw_map_empty_state(self, screen, font):
        if not self.map_empty_state_lines:
            return

        padding = 18
        line_gap = 7
        max_panel_w = min(660, max(360, screen.get_width() - 680))
        rendered = []
        for index, line in enumerate(self.map_empty_state_lines):
            color = (242, 244, 250) if index == 0 else (188, 198, 214)
            display_line = self._ellipsize_text(str(line), font, max_panel_w - padding * 2)
            rendered.append(self._render_text(font, display_line, color))

        panel_rect = self.map_empty_state_rect
        if panel_rect is None:
            self._layout_map_empty_state(screen.get_width(), screen.get_height(), font)
            panel_rect = self.map_empty_state_rect
        if panel_rect is None:
            return

        pygame.draw.rect(screen, (18, 22, 30), panel_rect)
        pygame.draw.rect(screen, (112, 130, 164), panel_rect, 1)
        accent_rect = pygame.Rect(panel_rect.x, panel_rect.y, 4, panel_rect.height)
        pygame.draw.rect(screen, (218, 185, 90), accent_rect)

        y = panel_rect.y + padding
        for surface in rendered:
            screen.blit(surface, (panel_rect.x + padding, y))
            y += surface.get_height() + line_gap

        for button in self.map_empty_state_buttons:
            self._draw_button(screen, font, button)

    def _draw_map_layer_selector(self, screen, font):
        if self.map_layer_selector_rect is None:
            return

        title = self._render_text(font, "Layer View", (176, 184, 202))
        screen.blit(title, (self.map_layer_selector_rect.x, self.map_layer_selector_rect.y))

        for item in self.map_layer_selector_items:
            rect = item.get("rect")
            if rect is None:
                continue
            active = bool(item.get("active"))
            fill = (54, 60, 76) if active else (30, 35, 46)
            border = (240, 218, 112) if active else (104, 118, 146)
            pygame.draw.rect(screen, fill, rect, border_radius=2)
            pygame.draw.rect(screen, border, rect, 1, border_radius=2)

            swatch = pygame.Rect(rect.x + 8, rect.y + 8, 12, 12)
            pygame.draw.rect(screen, item.get("color", (120, 130, 150)), swatch)
            pygame.draw.rect(screen, (210, 216, 228), swatch, 1)

            label = self._short_button_label(item.get("label"), max_chars=11)
            text = self._render_text(font, label, (242, 244, 250) if active else (204, 210, 222))
            screen.blit(text, (rect.x + 26, rect.y + 6))

    def _draw_map_location_browser(self, screen, font, x, y):
        if not self.map_location_browser_items:
            return 0

        row_h = max(20, font.get_height() + 6)
        if self.map_location_browser_rect is None:
            self._layout_map_location_browser(x, y, font)
        rect = self.map_location_browser_rect
        if rect is None:
            return 0
        pygame.draw.rect(screen, (14, 18, 28), rect)
        pygame.draw.rect(screen, (92, 108, 136), rect, 1)

        title = self._render_text(font, "Map Locations", (238, 242, 250))
        screen.blit(title, (rect.x + 10, rect.y + 10))

        row_y = rect.y + 34
        hitboxes_by_id = {entity_id: hitbox for entity_id, hitbox in self.map_location_browser_hitboxes}
        for item in self.map_location_browser_items[:len(self.map_location_browser_hitboxes)]:
            entity_id = str(item.get("id") or "")
            if not entity_id:
                continue
            depth = max(0, int(item.get("depth", 0) or 0))
            row_rect = hitboxes_by_id.get(entity_id, pygame.Rect(rect.x + 8, row_y, rect.width - 16, row_h))
            if item.get("active"):
                pygame.draw.rect(screen, (58, 66, 94), row_rect)
                pygame.draw.rect(screen, (218, 204, 134), row_rect, 1)
            else:
                pygame.draw.rect(screen, (24, 28, 38), row_rect)
                pygame.draw.rect(screen, (70, 78, 96), row_rect, 1)

            label_prefix = ""
            if item.get("role") == "parent":
                label_prefix = "Parent: "
            elif item.get("role") == "root":
                label_prefix = "Root: "
            label = self._ellipsize_text(
                label_prefix + str(item.get("label") or entity_id),
                font,
                row_rect.width - 18 - depth * 16,
            )
            text_color = (246, 246, 246) if item.get("active") else (204, 212, 226)
            text = self._render_text(font, label, text_color)
            screen.blit(text, (row_rect.x + 8 + depth * 16, row_rect.y + 3))
            row_y += row_h

        return rect.height

    def _draw_map_legend(self, screen, font, x, y):
        if not self.map_legend_items:
            self.map_legend_rect = None
            return 0
        row_h = max(19, font.get_height() + 3)
        width = min(330, max(270, screen.get_width() // 5))
        height = 34 + row_h * len(self.map_legend_items) + 8
        rect = pygame.Rect(x, y, width, height)
        self.map_legend_rect = rect
        pygame.draw.rect(screen, (14, 18, 28), rect)
        pygame.draw.rect(screen, (92, 108, 136), rect, 1)
        screen.blit(self._render_text(font, "Map Legend", (238, 242, 250)), (rect.x + 10, rect.y + 9))
        row_y = rect.y + 33
        for item in self.map_legend_items:
            swatch = pygame.Rect(rect.x + 10, row_y + 3, 13, 13)
            pygame.draw.rect(screen, item.get("color", (140, 145, 150)), swatch)
            pygame.draw.rect(screen, (214, 220, 230), swatch, 1)
            label = self._ellipsize_text(str(item.get("label") or "Legend item"), font, rect.width - 42)
            screen.blit(self._render_text(font, label, (202, 212, 226)), (rect.x + 31, row_y + 1))
            row_y += row_h
        return rect.height

    def _draw_map_workspace(self, screen, font):
        context_lines = list(self.map_context_lines)
        if self.map_status_lines:
            if context_lines:
                context_lines.append("")
            context_lines.extend(self.map_status_lines)

        current_y = 44
        if context_lines:
            map_context_w = min(380, max(300, screen.get_width() // 4))
            self.map_context_rect = pygame.Rect(
                20,
                current_y,
                map_context_w,
                self._info_panel_height(font, context_lines),
            )
            current_y += self._draw_info_panel(
                screen,
                font,
                20,
                current_y,
                context_lines,
                max_width=map_context_w,
            ) + 12
        else:
            self.map_context_rect = None

        selection_height = self._draw_simulation_selection_inspector(
            screen,
            font,
            20,
            current_y,
        )
        if selection_height:
            current_y += selection_height + 12

        if self.map_location_browser_items:
            current_y += self._draw_map_location_browser(screen, font, 20, current_y) + 12

        if self.map_legend_items:
            current_y += self._draw_map_legend(screen, font, 20, current_y) + 12

        self._draw_map_empty_state(screen, font)

        if self.map_sidebar_rect is not None:
            pygame.draw.rect(screen, (18, 22, 30), self.map_sidebar_rect)
            pygame.draw.rect(screen, (104, 118, 146), self.map_sidebar_rect, 1)
            title = self._render_text(font, "Map Tools", (242, 244, 250))
            screen.blit(title, (self.map_sidebar_rect.x + 12, self.map_sidebar_rect.y + 10))
            self._draw_map_layer_selector(screen, font)
            for section in self.map_sidebar_sections:
                rect = section.get("rect")
                if rect is None:
                    continue
                pygame.draw.line(screen, (70, 82, 104), (rect.x, rect.centery), (rect.right, rect.centery), 1)
                label = self._render_text(font, section.get("label", ""), (150, 166, 194))
                label_bg = pygame.Rect(rect.x + 8, rect.y, label.get_width() + 12, rect.height)
                pygame.draw.rect(screen, (18, 22, 30), label_bg)
                screen.blit(label, (label_bg.x + 6, rect.y + 1))

        for button in self.buttons:
            if not button.visible:
                continue
            self._draw_button(screen, font, button)

        if self.map_history_timeline_visible:
            self.map_history_timeline.draw(screen, font)

        self.selection_inspector.draw(screen, font)
        self._draw_hover_tooltip(screen, font)
        self._draw_system_menu(screen, font)
        self._draw_repository_return_confirm(screen, font)

    def _draw_system_menu(self, screen, font):
        if not self.system_menu_active or self.system_menu_rect is None:
            return

        overlay = pygame.Surface((screen.get_width(), screen.get_height()), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        screen.blit(overlay, (0, 0))

        pygame.draw.rect(screen, (24, 26, 32), self.system_menu_rect)
        pygame.draw.rect(screen, (210, 210, 210), self.system_menu_rect, 1)

        title = "Settings" if self.system_settings_active else "Menu"
        if self.system_settings_active:
            subtitle = getattr(self.knowledge_ui, "ontology_checkpoint_status", "") or "Display / phylogeny / ontology options"
        else:
            subtitle = "Simulation paused"
        title_surface = self._render_text(font, title, (245, 245, 245))
        subtitle_surface = self._render_text(font, subtitle, (175, 175, 180))
        screen.blit(title_surface, (self.system_menu_rect.x + 22, self.system_menu_rect.y + 20))
        screen.blit(subtitle_surface, (self.system_menu_rect.x + 22, self.system_menu_rect.y + 42))

        if self.system_settings_active:
            checkpoint_progress = getattr(self.knowledge_ui, "ontology_checkpoint_progress", None)
            if checkpoint_progress is not None:
                checkpoint_progress = max(0.0, min(1.0, float(checkpoint_progress)))
                bar_rect = pygame.Rect(
                    self.system_menu_rect.x + 22,
                    self.system_menu_rect.y + 64,
                    self.system_menu_rect.width - 84,
                    8,
                )
                fill_rect = pygame.Rect(
                    bar_rect.x + 1,
                    bar_rect.y + 1,
                    int(round((bar_rect.width - 2) * checkpoint_progress)),
                    bar_rect.height - 2,
                )
                pygame.draw.rect(screen, (38, 42, 52), bar_rect)
                pygame.draw.rect(screen, (105, 116, 136), bar_rect, 1)
                if fill_rect.width > 0:
                    fill_color = (104, 190, 132) if checkpoint_progress >= 1.0 else (112, 166, 218)
                    pygame.draw.rect(screen, fill_color, fill_rect)
                percent_surface = self._render_text(
                    font,
                    f"{int(round(checkpoint_progress * 100))}%",
                    (192, 204, 220),
                )
                screen.blit(
                    percent_surface,
                    percent_surface.get_rect(midleft=(bar_rect.right + 8, bar_rect.centery)),
                )

        for button in self.system_menu_buttons:
            self._draw_button(screen, font, button)

    def _draw_repository_return_confirm(self, screen, font):
        if (
            not self.repository_return_confirm_active
            or self.repository_return_confirm_rect is None
        ):
            return

        overlay = pygame.Surface((screen.get_width(), screen.get_height()), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 145))
        screen.blit(overlay, (0, 0))

        rect = self.repository_return_confirm_rect
        pygame.draw.rect(screen, (24, 26, 32), rect)
        pygame.draw.rect(screen, (220, 220, 220), rect, 1)

        title_surface = self._render_text(font, "Return to Repository?", (245, 245, 245))
        detail_surface = self._render_text(
            font,
            "Press Esc again to confirm, or choose Stay.",
            (180, 184, 194),
        )
        screen.blit(title_surface, (rect.x + 22, rect.y + 22))
        screen.blit(detail_surface, (rect.x + 22, rect.y + 50))

        for button in self.repository_return_confirm_buttons:
            self._draw_button(screen, font, button)

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
            text_surface = self._render_text(font, label, (220, 220, 220))

            if i == 0:
                draw_x = lx
            elif i == len(labels) - 1:
                draw_x = lx - text_surface.get_width()
            else:
                draw_x = lx - text_surface.get_width() // 2

            screen.blit(text_surface, (draw_x, y))

    def _draw_person_panel_icons(self, screen, font):
        for item in self.person_panel_icons:
            rect = item["rect"]
            active = item["id"] == self.person_panel_mode
            fill = (54, 62, 78) if active else (28, 32, 40)
            border = (230, 207, 126) if active else (142, 153, 173)
            pygame.draw.rect(screen, fill, rect, border_radius=5)
            pygame.draw.rect(screen, border, rect, 2, border_radius=5)

            cx, cy = rect.center
            if item["id"] == "needs":
                for row in range(3):
                    width = 10 + row * 7
                    y = cy - 11 + row * 9
                    pygame.draw.polygon(
                        screen,
                        (203, 184, 119),
                        [(cx - width // 2, y + 6), (cx + width // 2, y + 6), (cx, y)],
                    )
            else:
                points = []
                for index in range(5):
                    angle = -math.pi / 2 + index * math.tau / 5
                    points.append((cx + math.cos(angle) * 14, cy + math.sin(angle) * 14))
                pygame.draw.polygon(screen, (111, 157, 188), points, 2)
                pygame.draw.circle(screen, (184, 211, 225), (cx, cy), 3)

            if self.person_panel_mode is None:
                label = self._render_text(font, item["label"], (220, 225, 232))
                label_x = rect.x - label.get_width() - 8
                screen.blit(label, (label_x, rect.centery - label.get_height() // 2))

    def _draw_panel_heading(self, screen, font, text, x, y, color=(231, 232, 235)):
        heading_font = pygame.font.SysFont("consolas", max(17, font.get_height() + 2), bold=True)
        screen.blit(self._render_text(heading_font, text, color), (x, y))

    def _draw_person_needs_panel(self, screen, font, rect, model):
        content = rect.inflate(-28, -64)
        content.y += 34
        content.height -= 34
        left_w = max(250, int(content.width * 0.53))
        pyramid_rect = pygame.Rect(content.x, content.y + 20, left_w, content.height - 34)
        right_rect = pygame.Rect(
            pyramid_rect.right + 22,
            content.y,
            max(170, content.right - pyramid_rect.right - 22),
            content.height,
        )

        tiers = list(model.get("tiers") or [])[:5]
        if tiers:
            apex_y = pyramid_rect.y + 22
            base_y = pyramid_rect.bottom - 18
            total_h = max(100, base_y - apex_y)
            tier_h = total_h / len(tiers)
            center_x = pyramid_rect.centerx
            max_half = max(90, pyramid_rect.width * 0.47)
            for tier_index, tier in enumerate(tiers):
                top_y = base_y - (tier_index + 1) * tier_h
                bottom_y = base_y - tier_index * tier_h
                top_half = max_half * ((top_y - apex_y) / total_h)
                bottom_half = max_half * ((bottom_y - apex_y) / total_h)
                score = max(0.0, min(1.0, float(tier.get("score", 0.0) or 0.0)))
                deprived = (164, 88, 80)
                satisfied = (78, 145, 132)
                fill = tuple(
                    int(deprived[channel] + (satisfied[channel] - deprived[channel]) * score)
                    for channel in range(3)
                )
                polygon = [
                    (int(center_x - top_half), int(top_y)),
                    (int(center_x + top_half), int(top_y)),
                    (int(center_x + bottom_half), int(bottom_y)),
                    (int(center_x - bottom_half), int(bottom_y)),
                ]
                pygame.draw.polygon(screen, fill, polygon)
                pygame.draw.polygon(screen, (196, 199, 202), polygon, 1)
                label = f"{tier.get('label', 'Need')}  {score * 100:.0f}"
                label_surface = self._render_text(font, label, (246, 246, 240))
                label_y = int((top_y + bottom_y) / 2 - label_surface.get_height() / 2)
                if label_surface.get_width() < bottom_half * 1.75:
                    screen.blit(
                        label_surface,
                        (center_x - label_surface.get_width() // 2, label_y),
                    )
                else:
                    compact_label = tier.get("label", "Need").replace("Self-actualization", "Self-actual.")
                    compact = self._render_text(font, f"{compact_label} {score * 100:.0f}", (220, 224, 226))
                    compact_x = pyramid_rect.x + 2
                    screen.blit(compact, (compact_x, label_y))
                    line_start = (compact_x + compact.get_width() + 5, int((top_y + bottom_y) / 2))
                    line_end = (int(center_x - (top_half + bottom_half) / 2 - 4), line_start[1])
                    if line_end[0] > line_start[0]:
                        pygame.draw.line(screen, (134, 145, 157), line_start, line_end, 1)

            note = self._render_text(
                font,
                "Current fulfillment (0 deprived - 100 fulfilled)",
                (153, 163, 177),
            )
            screen.blit(note, (pyramid_rect.centerx - note.get_width() // 2, pyramid_rect.bottom - 4))

        section_y = right_rect.y
        for title, key, accent in (
            ("Wishes", "wishes", (191, 151, 105)),
            ("Goals", "goals", (112, 164, 130)),
        ):
            section_h = max(150, (right_rect.height - 16) // 2)
            section_rect = pygame.Rect(right_rect.x, section_y, right_rect.width, section_h)
            pygame.draw.rect(screen, (24, 28, 36), section_rect, border_radius=6)
            pygame.draw.rect(screen, (83, 92, 108), section_rect, 1, border_radius=6)
            pygame.draw.rect(screen, accent, (section_rect.x, section_rect.y, 5, section_rect.height), border_radius=3)
            self._draw_panel_heading(screen, font, title, section_rect.x + 14, section_rect.y + 10, accent)
            row_y = section_rect.y + 42
            rows = list(model.get(key) or [])
            if not rows:
                rows = [{"label": "None currently recorded", "source": ""}]
            for item in rows[:5]:
                label = self._ellipsize_text(item.get("label", ""), font, section_rect.width - 32)
                screen.blit(self._render_text(font, f"- {label}", (223, 226, 231)), (section_rect.x + 14, row_y))
                source = str(item.get("source") or "").strip()
                if source:
                    source_text = self._ellipsize_text(source, font, section_rect.width - 42)
                    screen.blit(self._render_text(font, source_text, (130, 141, 157)), (section_rect.x + 28, row_y + 19))
                    row_y += 42
                else:
                    row_y += 25
                if row_y > section_rect.bottom - 24:
                    break
            section_y += section_h + 16

    def _draw_personality_panel(self, screen, font, rect, model):
        axes = list(model.get("axes") or [])[:5]
        chart_center = (rect.x + int(rect.width * 0.36), rect.y + int(rect.height * 0.53))
        radius = min(165, int(rect.height * 0.29), int(rect.width * 0.25))
        angles = [-math.pi / 2 + index * math.tau / 5 for index in range(5)]

        for fraction in (0.25, 0.5, 0.75, 1.0):
            ring = [
                (
                    chart_center[0] + math.cos(angle) * radius * fraction,
                    chart_center[1] + math.sin(angle) * radius * fraction,
                )
                for angle in angles
            ]
            pygame.draw.polygon(screen, (67, 76, 91), ring, 1)
        for angle in angles:
            endpoint = (
                chart_center[0] + math.cos(angle) * radius,
                chart_center[1] + math.sin(angle) * radius,
            )
            pygame.draw.line(screen, (67, 76, 91), chart_center, endpoint, 1)

        if len(axes) == 5:
            value_points = []
            for axis, angle in zip(axes, angles):
                value = max(0.0, min(1.0, float(axis.get("value", 0.5) or 0.0)))
                value_points.append(
                    (
                        chart_center[0] + math.cos(angle) * radius * value,
                        chart_center[1] + math.sin(angle) * radius * value,
                    )
                )
            fill_surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            pygame.draw.polygon(fill_surface, (76, 144, 179, 82), value_points)
            screen.blit(fill_surface, (0, 0))
            pygame.draw.polygon(screen, (132, 194, 221), value_points, 3)
            for axis, point in zip(axes, value_points):
                pygame.draw.circle(
                    screen,
                    (204, 225, 232) if axis.get("authored") else (116, 122, 134),
                    (int(point[0]), int(point[1])),
                    5,
                    0 if axis.get("authored") else 2,
                )

        list_x = rect.x + int(rect.width * 0.69)
        for index, (axis, angle) in enumerate(zip(axes, angles)):
            label_radius = radius + 34
            x = chart_center[0] + math.cos(angle) * label_radius
            y = chart_center[1] + math.sin(angle) * label_radius
            label = self._render_text(font, axis.get("label", "Axis"), (218, 222, 229))
            if math.cos(angle) < -0.2:
                x -= label.get_width()
            elif abs(math.cos(angle)) <= 0.2:
                x -= label.get_width() // 2
            if math.sin(angle) < -0.2:
                y -= label.get_height()
            x = min(x, list_x - label.get_width() - 16)
            screen.blit(label, (int(x), int(y)))

        list_y = rect.y + 86
        for axis in axes:
            value = float(axis.get("value", 0.5) or 0.0)
            authored = bool(axis.get("authored"))
            name = axis.get("label", "Axis")
            screen.blit(self._render_text(font, name, (224, 226, 232)), (list_x, list_y))
            bar_rect = pygame.Rect(list_x, list_y + 22, max(90, rect.right - list_x - 34), 10)
            pygame.draw.rect(screen, (45, 50, 60), bar_rect, border_radius=4)
            pygame.draw.rect(
                screen,
                (105, 166, 190) if authored else (92, 96, 106),
                (bar_rect.x, bar_rect.y, int(bar_rect.width * value), bar_rect.height),
                border_radius=4,
            )
            score_text = f"{value * 100:.0f}" if authored else "50 preview - not authored"
            screen.blit(self._render_text(font, score_text, (145, 155, 170)), (list_x, list_y + 36))
            list_y += 69

        markers = list(model.get("adjective_markers") or [])
        footer = "Markers: " + (", ".join(markers[:5]) if markers else "none authored")
        footer = self._ellipsize_text(footer, font, rect.width - 50)
        screen.blit(self._render_text(font, footer, (153, 162, 176)), (rect.x + 24, rect.bottom - 36))

    def _draw_person_panel(self, screen, font):
        rect = self.person_panel_rect
        model = self.person_panel_model
        if rect is None or model is None or self.person_panel_mode not in {"needs", "personality"}:
            return

        shadow = rect.move(7, 8)
        pygame.draw.rect(screen, (4, 5, 8), shadow, border_radius=8)
        pygame.draw.rect(screen, (18, 22, 29), rect, border_radius=8)
        pygame.draw.rect(screen, (151, 161, 178), rect, 2, border_radius=8)
        title = "Needs, wishes & goals" if self.person_panel_mode == "needs" else "Personality - Big Five"
        self._draw_panel_heading(screen, font, title, rect.x + 20, rect.y + 16)
        subtitle = self._ellipsize_text(model.get("person_name", "Person"), font, rect.width - 100)
        screen.blit(self._render_text(font, subtitle, (137, 149, 166)), (rect.x + 21, rect.y + 44))
        if self.person_panel_close_rect is not None:
            pygame.draw.rect(screen, (39, 44, 54), self.person_panel_close_rect, border_radius=4)
            pygame.draw.rect(screen, (119, 130, 146), self.person_panel_close_rect, 1, border_radius=4)
            close = self._render_text(font, "x", (225, 228, 232))
            screen.blit(close, close.get_rect(center=self.person_panel_close_rect.center))

        if self.person_panel_mode == "needs":
            self._draw_person_needs_panel(screen, font, rect, model)
        else:
            self._draw_personality_panel(screen, font, rect, model)

    def draw(self, screen, font):
        self.app_font = font
        self._draw_tab_strip(screen, font)

        if self.menu_active:
            self.knowledge_ui.draw(screen, font, self._draw_button)
            self._draw_system_menu(screen, font)
            return

        if self.map_ui_active:
            self._draw_map_workspace(screen, font)
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
        self._draw_person_panel_icons(screen, font)

        info_lines = []
        if self.scope_label:
            info_lines.append(self.scope_label)
        if self.breadcrumb_label:
            info_lines.append(self.breadcrumb_label)

        current_info_y = 170
        if info_lines:
            current_info_y += self._draw_info_panel(screen, font, 20, current_info_y, info_lines) + 12

        if self.vehicle_requirement_lines:
            requirement_lines = ["Requirements"] + self.vehicle_requirement_lines
            current_info_y += self._draw_info_panel(screen, font, 20, current_info_y, requirement_lines) + 12

        selection_height = self._draw_simulation_selection_inspector(
            screen,
            font,
            20,
            current_info_y,
        )
        if selection_height:
            current_info_y += selection_height + 12

        if self.person_dossier_lines:
            dossier_lines = ["Dossier"] + self.person_dossier_lines
            self._draw_info_panel(screen, font, 20, current_info_y, dossier_lines)

        if self.map_history_timeline_visible:
            self.map_history_timeline.draw(screen, font)

        self._draw_simulation_bar(screen, font)
        self.selection_inspector.draw(screen, font)
        self._draw_hover_tooltip(screen, font)
        self._draw_person_panel(screen, font)
        self._draw_system_menu(screen, font)
        self._draw_repository_return_confirm(screen, font)

    def _reset_map_history_timeline_drag(self):
        self.map_history_timeline_drag_mode = None
        self.map_history_timeline_drag_start_pos = None
        self.map_history_timeline_drag_last_x = None

    def _set_map_history_reanchor_target(self, action):
        target_kind = action.get("target_kind")
        target_id = action.get("target_id")
        if target_kind not in {"spatial_feature", "location", "person"} or not target_id:
            return False

        self.map_history_timeline_reanchor_target = {
            "target_kind": target_kind,
            "target_id": target_id,
        }
        self.selection_inspector.set_time_anchor_active(
            True,
            target_kind=target_kind,
            target_id=target_id,
        )
        self.map_history_timeline.set_picker_target(
            "map entity anchor",
            preview_year=action.get("preview_year"),
        )
        return True

    def _clear_map_history_reanchor_target(self):
        if self.map_history_timeline_reanchor_target is None:
            return False

        self.map_history_timeline_reanchor_target = None
        self.selection_inspector.set_time_anchor_active(False)
        self.map_history_timeline.clear_picker_target()
        return True

    def _map_history_year_action(self, timeline_action):
        if timeline_action is None:
            return "__ui_consumed__"

        if timeline_action.get("kind") == "selected_year_changed":
            if self.map_history_timeline_reanchor_target is not None:
                target = dict(self.map_history_timeline_reanchor_target)
                self._clear_map_history_reanchor_target()
                return {
                    "id": "selection_inspector_reanchor_time",
                    "target_kind": target.get("target_kind"),
                    "target_id": target.get("target_id"),
                    "year": timeline_action.get("year"),
                }

            self.map_history_selected_year = timeline_action.get("year")
            return {
                "id": "map_history_year_select",
                "year": timeline_action.get("year"),
            }

        return "__ui_consumed__"

    def _handle_map_history_timeline_event(self, event):
        if not self.map_history_timeline_visible or self.map_history_timeline_rect is None:
            self._reset_map_history_timeline_drag()
            return None

        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            if self.map_history_timeline_rect.collidepoint(mouse_pos):
                self.map_history_timeline.handle_event(event)
                return "__ui_consumed__"

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            drag_mode = self.map_history_timeline_drag_mode
            self._reset_map_history_timeline_drag()

            if drag_mode == "pending":
                return self._map_history_year_action(
                    self.map_history_timeline.select_year_from_pos(event.pos)
                )

            if drag_mode is not None:
                return "__ui_consumed__"

            return None

        if event.type == pygame.MOUSEMOTION:
            drag_mode = self.map_history_timeline_drag_mode
            if drag_mode is None:
                return None

            if drag_mode == "pending":
                start_x, start_y = self.map_history_timeline_drag_start_pos
                dx = event.pos[0] - start_x
                dy = event.pos[1] - start_y
                if abs(dx) < 5 and abs(dy) < 5:
                    return "__ui_consumed__"

                self.map_history_timeline_drag_mode = "panning"
                self.map_history_timeline_drag_last_x = event.pos[0]
                if dx:
                    self.map_history_timeline.pan_by_pixels(-dx)
                return "__ui_consumed__"

            if drag_mode == "scrubbing":
                return self._map_history_year_action(
                    self.map_history_timeline.select_year_from_drag_pos(event.pos)
                )

            if drag_mode == "panning":
                if self.map_history_timeline_drag_last_x is None:
                    self.map_history_timeline_drag_last_x = event.pos[0]
                    return "__ui_consumed__"

                dx = event.pos[0] - self.map_history_timeline_drag_last_x
                self.map_history_timeline_drag_last_x = event.pos[0]
                if dx:
                    self.map_history_timeline.pan_by_pixels(-dx)

            return "__ui_consumed__"

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        mouse_pos = event.pos
        if not self.map_history_timeline_rect.collidepoint(mouse_pos):
            return None

        filter_action = self.map_history_timeline.handle_filter_click(mouse_pos)
        if filter_action is not None:
            return "__ui_consumed__"

        if self.map_history_timeline.is_selected_year_marker_hit(mouse_pos):
            self.map_history_timeline_drag_mode = "scrubbing"
            self.map_history_timeline_drag_start_pos = mouse_pos
            self.map_history_timeline_drag_last_x = mouse_pos[0]
            return self._map_history_year_action(
                self.map_history_timeline.select_year_from_drag_pos(mouse_pos)
            )

        self.map_history_timeline_drag_mode = "pending"
        self.map_history_timeline_drag_start_pos = mouse_pos
        self.map_history_timeline_drag_last_x = mouse_pos[0]
        return "__ui_consumed__"

    def _map_layer_button_action(self, button_id):
        button_id = str(button_id or "")
        if button_id == "map_layer_menu_root":
            self.map_layer_menu_mode = "root"
            return "__ui_consumed__"
        if button_id.startswith("map_set_layer:"):
            layer_kind = button_id.split(":", 1)[1]
            self.map_layer_menu_mode = "root"
            return {
                "id": "set_map_layer",
                "layer_kind": layer_kind,
            }
        if button_id.startswith("map_open_layer_menu:"):
            mode = button_id.split(":", 1)[1]
            if mode == "materials":
                self.map_layer_menu_mode = "materials"
                return {
                    "id": "set_map_layer",
                    "layer_kind": "material_heatmaps",
                }
            if mode == "locations":
                self.map_layer_menu_mode = "locations"
                return {
                    "id": "set_map_layer",
                    "layer_kind": "locations",
                }
            self.map_layer_menu_mode = "root"
            return "__ui_consumed__"
        if button_id.startswith("map_select_material:"):
            material_id = button_id.split(":", 1)[1]
            self.map_layer_menu_mode = "materials"
            return {
                "id": "set_map_material_distribution_item",
                "material_id": material_id,
            }
        if button_id.startswith("map_select_climate:"):
            climate_id = button_id.split(":", 1)[1]
            self.map_layer_menu_mode = "root"
            return {
                "id": "set_map_climate_display_item",
                "climate_id": climate_id,
            }
        if button_id.startswith("map_select_location:"):
            location_id = button_id.split(":", 1)[1]
            self.map_layer_menu_mode = "locations"
            return {
                "id": "select_map_location",
                "entity_id": location_id,
            }
        return None

    def handle_event(self, event):
        if self.repository_return_confirm_active:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_pos = event.pos

                for button in self.repository_return_confirm_buttons:
                    if not button.visible or not button.enabled:
                        continue
                    if button.rect.collidepoint(mouse_pos):
                        return button.id

                return "__ui_consumed__"

            if event.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.MOUSEWHEEL, pygame.KEYDOWN):
                return "__ui_consumed__"

        if self.system_menu_active:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_pos = event.pos

                for button in self.system_menu_buttons:
                    if not button.visible or not button.enabled:
                        continue

                    if button.rect.collidepoint(mouse_pos):
                        return button.id

                return "__ui_consumed__"

            if event.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.MOUSEWHEEL, pygame.KEYDOWN):
                return "__ui_consumed__"

        if self.menu_active:
            return self.knowledge_ui.handle_event(event)

        if (
            event.type == pygame.KEYDOWN
            and event.key == pygame.K_ESCAPE
            and self.person_panel_mode is not None
        ):
            self.person_panel_mode = None
            self.person_panel_model = None
            self.person_panel_rect = None
            self.person_panel_close_rect = None
            return "__ui_consumed__"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pos = event.pos
            for item in self.person_panel_icons:
                if item["rect"].collidepoint(mouse_pos):
                    mode = item["id"]
                    self.person_panel_mode = None if self.person_panel_mode == mode else mode
                    self.person_panel_model = None
                    self.person_panel_rect = None
                    self.person_panel_close_rect = None
                    return "__ui_consumed__"

            if self.person_panel_mode is not None:
                if self.person_panel_close_rect and self.person_panel_close_rect.collidepoint(mouse_pos):
                    self.person_panel_mode = None
                    self.person_panel_model = None
                    self.person_panel_rect = None
                    self.person_panel_close_rect = None
                    return "__ui_consumed__"
                if self.person_panel_rect is None or not self.person_panel_rect.collidepoint(mouse_pos):
                    self.person_panel_mode = None
                    self.person_panel_model = None
                    self.person_panel_rect = None
                    self.person_panel_close_rect = None
                return "__ui_consumed__"

        if self.person_panel_rect is not None and event.type in (
            pygame.MOUSEBUTTONUP,
            pygame.MOUSEMOTION,
            pygame.MOUSEWHEEL,
        ):
            event_pos = getattr(event, "pos", pygame.mouse.get_pos())
            if self.person_panel_rect.collidepoint(event_pos):
                return "__ui_consumed__"

        if (
            event.type == pygame.KEYDOWN
            and event.key == pygame.K_ESCAPE
            and self.map_history_timeline_reanchor_target is not None
        ):
            self._clear_map_history_reanchor_target()
            return "__ui_consumed__"

        inspector_action = self.selection_inspector.handle_event(event)
        if inspector_action is not None:
            if isinstance(inspector_action, dict):
                if inspector_action.get("id") == "selection_inspector_reanchor_time_start":
                    self._set_map_history_reanchor_target(inspector_action)
                    return "__ui_consumed__"

                if not self.selection_inspector.is_open:
                    self._clear_map_history_reanchor_target()
            elif not self.selection_inspector.is_open:
                self._clear_map_history_reanchor_target()

            return inspector_action

        map_history_action = self._handle_map_history_timeline_event(event)
        if map_history_action is not None:
            return map_history_action

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pos = event.pos

            if self.simulation_bar_resize_hitbox and self.simulation_bar_resize_hitbox.collidepoint(mouse_pos):
                self.simulation_bar_is_resizing = True
                self.simulation_bar_resize_start_y = mouse_pos[1]
                self.simulation_bar_resize_start_height = self.simulation_bar_height
                return "ui_consumed"

            for tab_id, hitbox in self.simulation_panel_tab_hitboxes:
                if hitbox.collidepoint(mouse_pos):
                    return {
                        "id": "simulation_panel_tab_select",
                        "tab_id": tab_id,
                    }

            for catalog_id, hitbox, row in self.simulation_bar_catalog_hitboxes:
                if catalog_id is None:
                    continue
                if hitbox.collidepoint(mouse_pos):
                    return {
                        "id": "vehicle_catalog_select",
                        "catalog_id": catalog_id,
                    }

            for tab_index, hitbox in self.tab_hitboxes:
                if hitbox.collidepoint(mouse_pos):
                    return {
                        "id": "activate_tab",
                        "tab_index": tab_index,
                    }

            for item in self.map_layer_selector_items:
                rect = item.get("rect")
                if rect is not None and rect.collidepoint(mouse_pos):
                    if item.get("action_id"):
                        return {"id": item.get("action_id")}
                    layer_kind = item.get("layer_kind")
                    if layer_kind == "material_heatmaps":
                        self.map_layer_menu_mode = "materials"
                    else:
                        self.map_layer_menu_mode = "root"
                    return {
                        "id": "set_map_layer",
                        "layer_kind": layer_kind,
                    }

            for button in self.buttons:
                if not button.visible or not button.enabled:
                    continue

                if button.rect.collidepoint(mouse_pos):
                    map_layer_action = self._map_layer_button_action(button.id)
                    if map_layer_action is not None:
                        return map_layer_action
                    return button.id

            for button in self.simulation_selection_buttons:
                if button.visible and button.enabled and button.rect.collidepoint(mouse_pos):
                    return button.id

            for button in self.map_empty_state_buttons:
                if button.visible and button.enabled and button.rect.collidepoint(mouse_pos):
                    return button.id

            for entity_id, hitbox in self.map_location_browser_hitboxes:
                if hitbox.collidepoint(mouse_pos):
                    return {
                        "id": "select_map_location",
                        "entity_id": entity_id,
                    }

            return None

        if event.type == pygame.MOUSEMOTION and self.simulation_bar_is_resizing:
            delta_y = self.simulation_bar_resize_start_y - event.pos[1]
            new_height = self.simulation_bar_resize_start_height + delta_y
            self.simulation_bar_height = max(
                self.simulation_bar_min_height,
                min(self.simulation_bar_max_height, new_height),
            )
            return "ui_consumed"

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.simulation_bar_is_resizing:
            self.simulation_bar_is_resizing = False
            return "ui_consumed"

        return None
