import pygame

from engine.simulation_instance import SimulationInstance
from engine.tab import Tab
from simulations.space.space_simulation import SpaceSimulation
from simulations.map.map_simulation import MapSimulation
from simulations.bioregion.bioregion_simulation import BioregionSimulation
from simulations.vehicle.vehicle_simulation import VehicleSimulation


class NavigationController:
    """
    Handles app-level workspace and tab navigation.

    Responsibilities:
    * focus existing tabs
    * launch root space and map tabs
    * open region map tabs
    * open parent / linked tabs from active simulations
    * route UI actions into navigation behavior
    """

    def __init__(self, app):
        self.app = app

    def focus_existing_tab_by_key(self, tab_key):
        """
        Activate an already-open tab by semantic key and reset the camera.
        """
        activated = self.app.tab_manager.activate_tab_by_key(tab_key)
        if not activated:
            return False

        active_sim = self.app.get_active_simulation()
        self.app.camera_controller.setup_for_sim(active_sim)
        return True

    def launch_space_root_tab(self):
        """
        Open or focus the root space simulation tab.
        """
        tab_key = ("space", "root")

        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return

        new_tab = Tab(
            SimulationInstance(SpaceSimulation(world_model=self.app.world_model)),
            name="System: Sol",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_tab.sim_instance.simulation)

    def launch_earth_map_tab(self):
        """
        Open or focus the default Earth map simulation tab.
        """
        tab_key = ("map", "planet_earth")

        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return

        from world.simulation_context import SimulationContext

        context = SimulationContext(
            year=2400,
            root_entity_id="planet_earth",
            world_model=self.app.world_model
        )

        new_map_sim = MapSimulation(context)
        new_tab = Tab(
            SimulationInstance(new_map_sim),
            name="Map: Earth",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_map_sim)

    def launch_bioregion_test_tab(self):
        """
        Open or focus the prototype bioregion simulation tab.
        """
        tab_key = ("bioregion", "test")

        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return

        new_bioregion_sim = BioregionSimulation()
        new_tab = Tab(
            SimulationInstance(new_bioregion_sim),
            name="Bioregion: Test",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_bioregion_sim)

    def launch_vehicle_tab(self, vehicle_entity_id="veh_test_rig_01"):
        """
        Open or focus a repository-backed vehicle simulation tab.
        """
        tab_key = ("vehicle", vehicle_entity_id)

        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return

        vehicle_entity = self.app.world_model.get_entity(vehicle_entity_id)
        vehicle_name = vehicle_entity.get("name", vehicle_entity_id) if vehicle_entity else vehicle_entity_id

        new_vehicle_sim = VehicleSimulation(
            world_model=self.app.world_model,
            vehicle_entity_id=vehicle_entity_id,
        )
        new_tab = Tab(
            SimulationInstance(new_vehicle_sim),
            name=f"Vehicle: {vehicle_name}",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_vehicle_sim)

    def launch_vehicle_test_tab(self):
        """
        Open or focus the prototype vehicle simulation tab.
        """
        self.launch_vehicle_tab("veh_test_rig_01")

    def open_region_map_tab(self, entity_id):
        """
        Open a new map simulation tab rooted at the selected entity,
        or focus the existing one if it is already open.
        """
        if not entity_id:
            return

        entity = self.app.world_model.get_entity(entity_id)
        if not entity:
            return

        tab_key = ("map", entity_id)
        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return

        from world.simulation_context import SimulationContext

        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400

        context = SimulationContext(
            year=year,
            root_entity_id=entity_id,
            world_model=self.app.world_model
        )

        new_map_sim = MapSimulation(context)
        new_tab = Tab(
            SimulationInstance(new_map_sim),
            name=f"Map: {entity.get('name', entity_id)}",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_map_sim)

    def open_parent_region_map_tab(self, map_sim):
        """
        Open the parent root of the given map simulation in a new map tab.
        """
        if map_sim is None:
            return

        if not hasattr(map_sim, "get_parent_root_entity_id"):
            return

        parent_entity_id = map_sim.get_parent_root_entity_id()
        if not parent_entity_id:
            return

        self.open_region_map_tab(parent_entity_id)

    def open_map_for_selected_space_body(self, space_sim):
        """
        Ensure a map anchor exists for the selected space body and open it.
        """
        if space_sim is None:
            return

        if not hasattr(space_sim, "get_selected_body_entity"):
            return

        body_entity = space_sim.get_selected_body_entity()
        if not body_entity:
            return

        location_id, _created = space_sim.system.ensure_location_anchor_for_body_entity(
            body_entity,
            self.app.world_model
        )

        if not location_id:
            return

        self.app.world_model.refresh()
        self.open_region_map_tab(location_id)

    def _infer_repository_scope_entity_id(self, active_sim):
        """
        Infer a stub repository scope from the current simulation.

        This is only a temporary navigation helper until a real
        main-simulation / knowledge-limiting system exists.
        """
        if active_sim is None:
            return self.app.repository_scope_entity_id

        render_mode = getattr(active_sim, "render_mode", None)

        if render_mode == "map":
            context = getattr(active_sim, "context", None)
            if context is not None:
                return getattr(context, "root_entity_id", None)

        if render_mode == "space":
            if hasattr(active_sim, "get_selected_body_entity"):
                body_entity = active_sim.get_selected_body_entity()
                if body_entity:
                    return body_entity.get("location_entity") or body_entity.get("id")

            return "system_sol"

        if render_mode == "vehicle":
            return getattr(active_sim, "vehicle_entity_id", None) or self.app.repository_scope_entity_id

        return self.app.repository_scope_entity_id

    def open_repository_workspace(self, active_sim):
        """
        Return from a simulation into the repository workspace using a stub scope.
        """
        self.app.repository_scope_entity_id = self._infer_repository_scope_entity_id(active_sim)
        self.app.knowledge_layer_active = True
        return True

    def activate_tab_index(self, tab_index):
        """
        Activate an existing simulation tab from the top tab strip.
        """
        if tab_index is None:
            return False

        if not self.app.tab_manager.activate_tab(tab_index):
            return False

        self.app.knowledge_layer_active = False

        active_sim = self.app.get_active_simulation()
        self.app.camera_controller.setup_for_sim(active_sim)
        return True

    def _handle_dict_ui_action(self, action, active_sim):
        """
        Route structured UI action payloads.
        """
        action_id = action.get("id")

        if action_id == "activate_tab":
            tab_index = action.get("tab_index")
            return self.activate_tab_index(tab_index)

        if action_id == "simulation_panel_tab_select" and active_sim is not None:
            tab_id = action.get("tab_id")
            return bool(
                getattr(active_sim, "set_active_simulation_panel_tab", lambda _tab_id: False)(tab_id)
            )

        if action_id == "vehicle_catalog_select" and active_sim is not None:
            catalog_id = action.get("catalog_id")
            return bool(
                getattr(active_sim, "begin_design_catalog_drag", lambda _catalog_id: False)(catalog_id)
            )

        if action_id == "knowledge_launch_entry":
            entity_id = action.get("entity_id")
            entity = self.app.world_model.get_entity(entity_id)

            if entity is None:
                return False

            dataset_name = entity.get("_dataset")

            if dataset_name == "locations":
                self.open_region_map_tab(entity_id)
                return True

            if dataset_name == "vehicles":
                self.launch_vehicle_tab(entity_id)
                return True

            if dataset_name == "systems":
                system_role = entity.get("system_role")

                if system_role == "star_system":
                    self.launch_space_root_tab()
                    return True

                if system_role == "orbital_body":
                    location_entity_id = entity.get("location_entity")

                    if location_entity_id:
                        self.open_region_map_tab(location_entity_id)
                        return True

                    self.launch_space_root_tab()
                    return True

            return False

        return False

    def _handle_simple_ui_action(self, action_id, active_sim):
        """
        Route simple string-based UI action ids.
        """
        if action_id == "launch_space_root":
            self.launch_space_root_tab()
            return True

        if action_id == "launch_earth_map":
            self.launch_earth_map_tab()
            return True

        if action_id == "launch_bioregion_test":
            self.launch_bioregion_test_tab()
            return True

        if action_id == "launch_vehicle_test":
            self.launch_vehicle_test_tab()
            return True

        if action_id == "vehicle_mode_design" and active_sim is not None:
            return bool(getattr(active_sim, "set_view_mode", lambda mode: False)("design"))

        if action_id == "vehicle_mode_interior" and active_sim is not None:
            return bool(getattr(active_sim, "set_view_mode", lambda mode: False)("interior"))

        if action_id == "vehicle_mode_operational" and active_sim is not None:
            return bool(getattr(active_sim, "set_view_mode", lambda mode: False)("operational"))

        if action_id == "open_repository":
            return self.open_repository_workspace(active_sim)

        if action_id == "open_region_map" and active_sim is not None:
            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            self.open_region_map_tab(selected_entity_id)
            return True

        if action_id == "open_parent_region_map" and active_sim is not None:
            self.open_parent_region_map_tab(active_sim)
            return True

        if action_id == "open_space_body_map" and active_sim is not None:
            self.open_map_for_selected_space_body(active_sim)
            return True

        return False

    def handle_ui_action(self, action, active_sim):
        """
        Route UI actions for either the knowledge layer or the active simulation.
        """
        if isinstance(action, dict):
            return self._handle_dict_ui_action(action, active_sim)

        return self._handle_simple_ui_action(action, active_sim)

    def handle_keydown(self, event):
        """
        Handle application-level keyboard controls.
        """
        if self.app.knowledge_layer_active:
            return

        if event.key == pygame.K_TAB:
            self.app.tab_manager.switch_next()

            sim = self.app.get_active_simulation()
            self.app.camera_controller.setup_for_sim(sim)

        sim = self.app.get_active_simulation()

        if sim:
            if event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                sim.sim_clock.set_time_scale(sim.sim_clock.time_scale + 0.25)

            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                sim.sim_clock.set_time_scale(sim.sim_clock.time_scale - 0.25)

            elif event.key == pygame.K_0:
                sim.sim_clock.set_time_scale(1.0)

            elif event.key == pygame.K_SPACE:
                sim.sim_clock.toggle_pause()