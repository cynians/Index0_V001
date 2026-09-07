import pygame

from engine.simulation_instance import SimulationInstance
from engine.tab import Tab
from simulations.space.space_simulation import SpaceSimulation
from simulations.map.map_simulation import MapSimulation
from simulations.bioregion.bioregion_simulation import BioregionSimulation
from simulations.vehicle.vehicle_design_simulation import VehicleDesignSimulation
from simulations.person.person_simulation import PersonSimulation
from simulations.person.site_simulation import SiteSimulation
from simulations.pop.pop_simulation import PopSimulation
from simulations.world_gen.world_gen_sim import WorldGenSimulation
from simulations.building.building_sim import BuildingSimulation
from simulations.phylogeny.phylogeny_simulation import PhylogenySimulation
from simulations.formation.formation_simulation import FormationSimulation
from simulations.species.species_simulation import SpeciesSimulation
from world.temporal import DEFAULT_SIMULATION_YEAR

try:
    from .launch_affordance_resolver import LaunchAffordanceResolver
except ImportError:
    from launch_affordance_resolver import LaunchAffordanceResolver


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
        self.launch_resolver = LaunchAffordanceResolver()

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

    def launch_space_root_tab(self, root_system_id="system_sol"):
        """
        Open or focus the root space simulation tab.
        """
        tab_key = ("space", root_system_id)

        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return

        root_system_entity = self.app.world_model.get_entity(root_system_id)
        root_system_name = (
            root_system_entity.get("name", root_system_id)
            if root_system_entity
            else root_system_id
        )

        new_tab = Tab(
            SimulationInstance(SpaceSimulation(
                world_model=self.app.world_model,
                root_system_id=root_system_id,
            )),
            name=f"System: {root_system_name}",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_tab.sim_instance.simulation)

    def launch_planet_space_tab(self, body_entity_id):
        """
        Open or focus a local space simulation rooted on one planet body.
        """
        if not body_entity_id:
            return False

        body_entity = self.app.world_model.get_entity(body_entity_id)
        if not body_entity:
            return False

        root_system_id = body_entity.get("star_system")
        if not root_system_id:
            return False

        tab_key = ("space_body", body_entity_id)

        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return True

        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400
        body_name = body_entity.get("name", body_entity_id)

        new_space_sim = SpaceSimulation(
            world_model=self.app.world_model,
            root_system_id=root_system_id,
            root_body_id=body_entity_id,
            year=year,
        )
        new_tab = Tab(
            SimulationInstance(new_space_sim),
            name=f"Local Space: {body_name}",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_space_sim)
        return True

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

    def launch_biosphere_design_tab(self, active_sim):
        if active_sim is None:
            return False

        context = getattr(active_sim, "get_biosphere_launch_context", lambda: None)()
        if not isinstance(context, dict):
            return False

        patch_id = context.get("patch_location_id")
        if not patch_id:
            return False

        tab_key = ("biosphere", patch_id)
        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return True

        new_bioregion_sim = BioregionSimulation(
            world_model=self.app.world_model,
            biosphere_context=context,
            biosphere_id=context.get("biosphere_id"),
        )
        patch_name = context.get("patch_name") or patch_id
        new_tab = Tab(
            SimulationInstance(new_bioregion_sim),
            name=f"Biosphere: {patch_name}",
            tab_key=tab_key,
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_bioregion_sim)
        return True

    def launch_biosphere_tab(self, location_entity_id):
        """
        Open or focus the Biosphere overlaying a location, from a plain
        location-card launch affordance -- no active MapSimulation required
        (unlike launch_biosphere_design_tab, which drives the in-progress
        polygon-draft/create flow from an already-open Map tab).
        """
        if not location_entity_id:
            return False

        location = self.app.world_model.get_entity(location_entity_id)
        if not isinstance(location, dict):
            return False

        biosphere_id = location.get("biosphere_entity_id")
        if not biosphere_id:
            return False

        tab_key = ("biosphere", biosphere_id)
        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return True

        parent_id = location.get("parent_location") or location.get("parent_entity")
        parent = self.app.world_model.get_entity(parent_id) if parent_id else None
        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400
        patch_name = location.get("name") or location.get("pretty_name") or location_entity_id

        context = {
            "patch_location_id": location_entity_id,
            "patch_name": patch_name,
            "parent_location_id": parent_id,
            "root_location_id": parent_id,
            "root_name": (parent or {}).get("name") or (parent or {}).get("pretty_name") or parent_id,
            "year": year,
            "source_bounds": location.get("bounds") or location.get("geometry"),
            "biosphere_shape": location.get("biosphere_shape"),
            "biosphere_area_m2": location.get("biosphere_area_m2"),
            "biosphere_width_m": location.get("biosphere_width_m"),
            "biosphere_height_m": location.get("biosphere_height_m"),
            "map_size_m": location.get("biosphere_map_size_m") or 10.0,
            "species_collection_id": location.get("biosphere_species_collection"),
            "biosphere_id": biosphere_id,
        }

        new_bioregion_sim = BioregionSimulation(
            world_model=self.app.world_model,
            biosphere_context=context,
            biosphere_id=biosphere_id,
        )
        new_tab = Tab(
            SimulationInstance(new_bioregion_sim),
            name=f"Biosphere: {patch_name}",
            tab_key=tab_key,
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_bioregion_sim)
        return True

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
        is_station = bool(
            vehicle_entity
            and vehicle_entity.get("location_class") in {"space_station", "station"}
        )

        new_vehicle_sim = VehicleDesignSimulation(
            world_model=self.app.world_model,
            vehicle_entity_id=vehicle_entity_id,
        )
        new_tab = Tab(
            SimulationInstance(new_vehicle_sim),
            name=(f"Station Design: {vehicle_name}" if is_station else f"Vehicle Design: {vehicle_name}"),
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

    def launch_person_tab(self, person_entity_id):
        """
        Open or focus a repository-backed person dossier simulation tab.
        """
        if not person_entity_id:
            return

        tab_key = ("person", person_entity_id)

        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return

        person_entity = self.app.world_model.get_entity(person_entity_id)
        if not person_entity:
            return

        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400
        person_name = person_entity.get("name", person_entity_id)

        new_person_sim = PersonSimulation(
            world_model=self.app.world_model,
            person_entity_id=person_entity_id,
            year=year,
        )
        new_tab = Tab(
            SimulationInstance(new_person_sim),
            name=f"Person: {person_name}",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_person_sim)

    def launch_pop_tab(self, pop_entity_id):
        """
        Open or focus a population composition view.
        """
        if not pop_entity_id:
            return

        tab_key = ("pop", pop_entity_id)

        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return

        pop_entity = self.app.world_model.get_entity(pop_entity_id)
        if not pop_entity:
            return

        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400
        pop_name = pop_entity.get("pretty_name") or pop_entity.get("name") or pop_entity_id

        new_pop_sim = PopSimulation(
            world_model=self.app.world_model,
            pop_entity_id=pop_entity_id,
            year=year,
        )
        new_tab = Tab(
            SimulationInstance(new_pop_sim),
            name=f"Pop: {pop_name}",
            tab_key=tab_key,
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False

    def launch_site_simulation_tab(self, site_entity_id):
        """Open the local person/population runtime for an authored location."""
        if not site_entity_id:
            return False
        site = self.app.world_model.get_entity(site_entity_id)
        if not site or not (
            site.get("_dataset") == "locations"
            or site.get("type") == "location"
            or site.get("location_class")
        ):
            return False

        tab_key = ("site_people", site_entity_id)
        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return True

        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400
        site_name = site.get("pretty_name") or site.get("name") or site_entity_id
        simulation = SiteSimulation(self.app.world_model, site_entity_id, year=year)
        new_tab = Tab(
            SimulationInstance(simulation),
            name=f"Site Sim: {site_name}",
            tab_key=tab_key,
        )
        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(simulation)
        return True

    def launch_phylogeny_tab(self, clade_entity_id):
        """
        Open or focus the full cladistics tree view.
        """
        if not clade_entity_id:
            return False

        clade_entity = self.app.world_model.get_entity(clade_entity_id)
        if not clade_entity or clade_entity.get("_dataset") not in {"cladistics", "species"}:
            return False

        tab_key = ("phylogeny", clade_entity_id)
        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return True

        clade_name = clade_entity.get("pretty_name") or clade_entity.get("name") or clade_entity_id
        new_phylogeny_sim = PhylogenySimulation(
            world_model=self.app.world_model,
            focus_clade_id=clade_entity_id,
        )
        new_tab = Tab(
            SimulationInstance(new_phylogeny_sim),
            name=f"Phylogeny: {clade_name}",
            tab_key=tab_key,
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_phylogeny_sim)
        return True

    def launch_species_sim_tab(self, species_entity_id, diagnostic_tab=None):
        """Open the standalone biological growth lab for one species."""
        if not species_entity_id:
            return False

        species_entity = self.app.world_model.get_entity(species_entity_id)
        if not isinstance(species_entity, dict):
            return False
        if species_entity.get("_dataset") != "species" and species_entity.get("type") != "species":
            return False
        if not self.app.world_model.is_plant_species(species_entity_id):
            return False

        tab_key = ("species", species_entity_id)
        if self.focus_existing_tab_by_key(tab_key):
            existing = self.app.get_active_simulation()
            if diagnostic_tab:
                getattr(existing, "set_active_simulation_panel_tab", lambda _tab: False)(diagnostic_tab)
            self.app.knowledge_layer_active = False
            return True

        simulation = SpeciesSimulation(
            world_model=self.app.world_model,
            species_id=species_entity_id,
            species_entity=species_entity,
            seed=1,
        )
        label = (
            species_entity.get("common_name")
            or species_entity.get("binomial_name")
            or species_entity.get("pretty_name")
            or species_entity_id
        )
        new_tab = Tab(
            SimulationInstance(simulation),
            name=f"Species Sim: {label}",
            tab_key=tab_key,
        )
        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(simulation)
        if diagnostic_tab:
            simulation.set_active_simulation_panel_tab(diagnostic_tab)
        return True

    def open_species_asset_editor(self, active_sim, entity_id, asset_role):
        """Open a plant module in Pixel Studio directly from Species Editor."""
        entity = self.app.world_model.get_entity(entity_id) if entity_id else None
        if not isinstance(entity, dict):
            return False
        self.app.repository_scope_entity_id = entity_id
        self.open_repository_workspace(active_sim)
        knowledge_ui = getattr(self.app.ui_manager, "knowledge_ui", None)
        surface = pygame.display.get_surface()
        if knowledge_ui is None or surface is None:
            return False
        knowledge_ui.rebuild(
            app_width=surface.get_width(),
            app_height=surface.get_height(),
            world_model=self.app.world_model,
            repository_scope_entity_id=entity_id,
            font=self.app.ui_manager.app_font,
        )
        card = next((card for card in knowledge_ui.cards if card.get("entity_id") == entity_id), None)
        if card is None:
            return False
        return bool(knowledge_ui._create_or_open_plant_asset(card, asset_role))

    def launch_world_gen_tab(self, planet_location_id):
        """
        Open or focus a planetary world-generation workspace.
        """
        if not planet_location_id:
            return False

        entity = self.app.world_model.get_entity(planet_location_id)
        if not entity:
            return False

        location_class = entity.get("location_class")
        is_star_system = location_class in {"star_system", "stellar_system"} or entity.get("system_role") == "star_system"
        is_planet = location_class == "planet"
        if not is_planet and not is_star_system:
            return False

        tab_key = ("world_gen", planet_location_id)
        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return True

        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400
        entity_name = entity.get("name", planet_location_id)

        new_world_gen_sim = WorldGenSimulation(
            world_model=self.app.world_model,
            planet_location_id=planet_location_id if is_planet else None,
            parent_system_id=planet_location_id if is_star_system else None,
            year=year,
        )
        new_tab = Tab(
            SimulationInstance(new_world_gen_sim),
            name=f"World Gen: {entity_name}",
            tab_key=tab_key,
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_world_gen_sim)
        return True

    def launch_building_tab(self, building_location_id):
        """
        Open or focus a building workspace for room layout authoring.
        """
        if not building_location_id:
            return False

        building = self.app.world_model.get_entity(building_location_id)
        if not building or building.get("location_class") not in {"building", "space_station", "station"}:
            return False

        tab_key = ("building", building_location_id)
        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return True

        from world.simulation_context import SimulationContext

        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400

        context = SimulationContext(
            year=year,
            root_entity_id=building_location_id,
            world_model=self.app.world_model,
        )
        new_building_sim = BuildingSimulation(context)
        is_station = building.get("location_class") in {"space_station", "station"}
        new_tab = Tab(
            SimulationInstance(new_building_sim),
            name=(
                f"Station Interior: {building.get('name', building_location_id)}"
                if is_station
                else f"Building: {building.get('name', building_location_id)}"
            ),
            tab_key=tab_key,
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_building_sim)
        return True

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

        if entity.get("location_class") in {"building", "space_station", "station"}:
            return self.launch_building_tab(entity_id)

        if entity.get("location_class") == "room":
            parent_location_id = entity.get("parent_location")
            parent_location = self.app.world_model.get_entity(parent_location_id)
            if parent_location and parent_location.get("location_class") in {"building", "space_station", "station"}:
                return self.launch_building_tab(parent_location_id)

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
        is_refinement = entity.get("location_class") == "generated_region" or entity.get("location_role") == "map_refinement_region"
        new_tab = Tab(
            SimulationInstance(new_map_sim),
            name=f"Region Gen: {entity.get('name', entity_id)}" if is_refinement else f"Map: {entity.get('name', entity_id)}",
            tab_key=tab_key
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_map_sim)
        return True

    def launch_entity_mode(self, entity_id, launch_mode=None):
        entity = self.app.world_model.get_entity(entity_id)
        if entity is None:
            return False

        mode = launch_mode or self.launch_resolver.default_mode_for_entity(
            entity, getattr(self.app.world_model, "plant_catalogue", None))
        if not mode:
            return False

        if mode == "space":
            location_class = entity.get("location_class")
            system_role = entity.get("system_role")
            body_class = entity.get("body_class") or location_class

            if system_role == "star_system" or location_class in {"star_system", "stellar_system"}:
                self.launch_space_root_tab(entity_id)
                return True

            if body_class == "planet" and entity.get("star_system"):
                return self.launch_planet_space_tab(entity_id)

            star_system_id = entity.get("star_system")
            if star_system_id:
                self.launch_space_root_tab(star_system_id)
                return True

            if entity.get("_dataset") == "systems" and system_role == "orbital_body":
                if body_class == "planet":
                    return self.launch_planet_space_tab(entity_id)
                self.launch_space_root_tab()
                return True

            return False

        if mode == "map":
            location_entity_id = entity.get("location_entity") or entity_id
            return bool(self.open_region_map_tab(location_entity_id))

        if mode == "world_gen":
            return self.launch_world_gen_tab(entity_id)

        if mode == "place_parent":
            return self.open_location_parent_placement_tab(entity_id)

        if mode == "building":
            if entity.get("location_class") == "room":
                parent_location_id = entity.get("parent_location")
                parent_location = self.app.world_model.get_entity(parent_location_id)
                if parent_location and parent_location.get("location_class") in {"building", "space_station", "station"}:
                    return self.launch_building_tab(parent_location_id)
                return False
            return self.launch_building_tab(entity_id)

        if mode == "vehicle":
            self.launch_vehicle_tab(entity_id)
            return True

        if mode == "person":
            self.launch_person_tab(entity_id)
            return True

        if mode == "pop":
            self.launch_pop_tab(entity_id)
            return True

        if mode == "formation":
            return self.launch_formation_tab(entity_id)

        if mode == "formation_create":
            if not self.launch_formation_tab(entity_id):
                return False
            simulation = self.app.get_active_simulation()
            return bool(simulation and simulation.open_creation_menu())

        if mode == "site_people":
            return self.launch_site_simulation_tab(entity_id)

        if mode == "biosphere":
            return self.launch_biosphere_tab(entity_id)

        if mode == "phylogeny":
            return self.launch_phylogeny_tab(entity_id)

        if mode == "species":
            return self.launch_species_sim_tab(entity_id)

        return False

    def launch_formation_tab(self, formation_id):
        """Open or focus the first Formation Sim workspace."""
        if not formation_id:
            return False

        formation = self.app.world_model.get_entity(formation_id)
        if not formation:
            return False
        if formation.get("_dataset") != "formations" and formation.get("type") != "formation":
            return False

        tab_key = ("formation", formation_id)
        if self.focus_existing_tab_by_key(tab_key):
            self.app.knowledge_layer_active = False
            return True

        active_simulation = self.app.get_active_simulation()
        year = getattr(active_simulation, "year", DEFAULT_SIMULATION_YEAR)
        simulation = FormationSimulation(
            world_model=self.app.world_model,
            formation_id=formation_id,
            year=year,
        )
        formation_name = formation.get("pretty_name") or formation.get("name") or formation_id
        new_tab = Tab(
            SimulationInstance(simulation),
            name=f"Formation: {formation_name}",
            tab_key=tab_key,
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(simulation)
        return True

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

    def _refresh_generated_map_views(self):
        """Reload generated entities and invalidate open parent/child map caches."""
        if hasattr(self.app.world_model, "refresh"):
            self.app.world_model.refresh()
        for tab in getattr(self.app.tab_manager, "tabs", []):
            sim_instance = getattr(tab, "sim_instance", None)
            simulation = getattr(sim_instance, "simulation", None)
            refresh_layers = getattr(simulation, "refresh_generated_map_layers", None)
            if callable(refresh_layers):
                refresh_layers()

    def open_location_parent_placement_tab(self, location_entity_id):
        if not location_entity_id:
            return False

        location = self.app.world_model.get_entity(location_entity_id)
        if not location or location.get("_dataset") != "locations":
            return False

        parent_entity_id = self._structural_location_parent_id(location)
        if not parent_entity_id:
            # An unparented location cannot be placed on a map yet. Move into
            # the existing parent-assignment workflow instead of making the
            # button appear unresponsive.
            self.app.parent_assignment_request = {
                "target_entity_id": location_entity_id,
                "target_label": location.get("name") or location.get("pretty_name") or location_entity_id,
            }
            self.app.repository_scope_entity_id = location_entity_id
            self.app.knowledge_layer_active = True
            self.app.repository_return_confirm_active = False
            self.app.system_menu_active = False
            self.app.system_settings_active = False
            return True

        parent_entity = self.app.world_model.get_entity(parent_entity_id)
        if not parent_entity:
            return False

        from world.simulation_context import SimulationContext

        active_sim = self.app.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400

        context = SimulationContext(
            year=year,
            root_entity_id=parent_entity_id,
            world_model=self.app.world_model,
        )
        new_map_sim = MapSimulation(context)
        if not new_map_sim.begin_location_parent_polygon_placement(
            location_entity_id,
            return_to_repository=True,
        ):
            return False

        tab_key = ("map_place_parent", location_entity_id)
        placement_name = location.get("name", location_entity_id)
        parent_name = parent_entity.get("name", parent_entity_id)
        new_tab = Tab(
            SimulationInstance(new_map_sim),
            name=f"Place: {placement_name} on {parent_name}",
            tab_key=tab_key,
        )

        self.app.tab_manager.add_tab(new_tab)
        self.app.tab_manager.active_index = len(self.app.tab_manager.tabs) - 1
        self.app.knowledge_layer_active = False
        self.app.camera_controller.setup_for_sim(new_map_sim)
        return True

    def _relation_entity_ids(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            candidate = value.get("location_id") or value.get("id") or value.get("entity_id") or value.get("target")
            return [candidate] if candidate else []
        if isinstance(value, (list, tuple, set)):
            ids = []
            for item in value:
                ids.extend(self._relation_entity_ids(item))
            return ids
        return []

    def _structural_location_parent_id(self, location):
        if not isinstance(location, dict):
            return None

        location_id = location.get("id")
        for field_key in ("parent_location", "parent_entity", "parent_body"):
            for parent_id in self._relation_entity_ids(location.get(field_key)):
                parent = self.app.world_model.get_entity(parent_id)
                if parent_id and parent_id != location_id and self._is_location_entity(parent):
                    return parent_id

        for parent_id in self._relation_entity_ids(location.get("parents")):
            parent = self.app.world_model.get_entity(parent_id)
            if parent_id and parent_id != location_id and self._is_location_entity(parent):
                return parent_id

        entities = getattr(getattr(self.app.world_model, "loader", None), "entities", {}) or {}
        if not entities and hasattr(self.app.world_model, "entities"):
            entities = getattr(self.app.world_model, "entities", {}) or {}
        for candidate_id, candidate in entities.items():
            if candidate_id == location_id or not self._is_location_entity(candidate):
                continue
            if location_id in self._relation_entity_ids(candidate.get("constituents")):
                return candidate_id

        return None

    def _is_location_entity(self, entity):
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "locations"
            or entity.get("type") == "location"
        )

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

        # ``ensure_location_anchor_for_body_entity`` persists into the active
        # loader and updates its in-memory entity index synchronously.  A full
        # WorldModel.refresh() here used to reopen the large ontology, rebuild
        # every repository index, and reapply all reference models on every
        # Space -> Map click—even when the anchor already existed.
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
            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            if selected_entity_id and self.app.world_model.get_entity(selected_entity_id):
                return selected_entity_id
            selected_spatial_feature_id = getattr(active_sim, "selected_spatial_feature_id", None)
            if selected_spatial_feature_id and self.app.world_model.get_entity(selected_spatial_feature_id):
                return selected_spatial_feature_id
            context = getattr(active_sim, "context", None)
            if context is not None:
                return getattr(context, "root_entity_id", None)

        context = getattr(active_sim, "context", None)
        if context is not None and getattr(context, "root_entity_id", None):
            return getattr(context, "root_entity_id", None)

        if render_mode == "space":
            if hasattr(active_sim, "get_selected_body_entity"):
                body_entity = active_sim.get_selected_body_entity()
                if body_entity:
                    return body_entity.get("location_entity") or body_entity.get("id")

            return "system_sol"

        if render_mode == "vehicle":
            return getattr(active_sim, "vehicle_entity_id", None) or self.app.repository_scope_entity_id

        if render_mode == "person":
            return getattr(active_sim, "person_entity_id", None) or self.app.repository_scope_entity_id

        if render_mode == "pop":
            return getattr(active_sim, "pop_entity_id", None) or self.app.repository_scope_entity_id

        if render_mode == "species":
            return getattr(active_sim, "species_id", None) or self.app.repository_scope_entity_id

        return self.app.repository_scope_entity_id

    def open_repository_workspace(self, active_sim):
        """
        Return from a simulation into the repository workspace using a stub scope.
        """
        self.app.repository_scope_entity_id = self._infer_repository_scope_entity_id(active_sim)
        self.app.knowledge_layer_active = True
        self.app.repository_return_confirm_active = False
        self.app.system_menu_active = False
        self.app.system_settings_active = False
        return True

    def begin_parent_assignment_workspace(self, active_sim):
        target_entity_id = self._infer_repository_scope_entity_id(active_sim)
        target = self.app.world_model.get_entity(target_entity_id) if target_entity_id else None
        if not isinstance(target, dict):
            return False

        self.app.parent_assignment_request = {
            "target_entity_id": target_entity_id,
            "target_label": target.get("name") or target.get("pretty_name") or target_entity_id,
        }
        self.app.repository_scope_entity_id = target_entity_id
        self.app.knowledge_layer_active = True
        self.app.repository_return_confirm_active = False
        self.app.system_menu_active = False
        self.app.system_settings_active = False
        return True

    def confirm_parent_assignment(self, target_entity_id, parent_entity_id):
        if not target_entity_id or not parent_entity_id or target_entity_id == parent_entity_id:
            return False

        target = self.app.world_model.get_entity(target_entity_id)
        parent = self.app.world_model.get_entity(parent_entity_id)
        if not isinstance(target, dict) or not isinstance(parent, dict):
            return False
        if parent.get("_dataset") != "locations" and parent.get("type") != "location":
            return False

        loader = getattr(self.app.world_model, "loader", None)
        if loader is not None and hasattr(loader, "set_literal"):
            loader.set_literal(target_entity_id, "parent_location", parent_entity_id, persist=True)
            if hasattr(loader, "set_relation"):
                loader.set_relation(parent_entity_id, "constituents", target_entity_id, persist=True)
        else:
            target["parent_location"] = parent_entity_id
            constituents = parent.get("constituents")
            if not isinstance(constituents, list):
                constituents = []
            if target_entity_id not in constituents:
                constituents.append(target_entity_id)
            parent["constituents"] = constituents

        target["parent_location"] = parent_entity_id
        constituents = parent.get("constituents")
        if not isinstance(constituents, list):
            constituents = []
        if target_entity_id not in constituents:
            constituents.append(target_entity_id)
        parent["constituents"] = constituents

        if hasattr(self.app.world_model, "mark_repository_changed"):
            self.app.world_model.mark_repository_changed()
        elif hasattr(self.app.world_model, "refresh"):
            self.app.world_model.refresh()

        self.app.parent_assignment_request = None
        self.app.repository_scope_entity_id = target_entity_id
        return True

    def open_selection_wiki_entry(self, active_sim):
        get_selection_payload = getattr(active_sim, "get_selection_inspector_payload", None)
        if get_selection_payload is None:
            return False

        payload = get_selection_payload()
        entity_id = payload.get("entity_id") if isinstance(payload, dict) else None
        if not entity_id or self.app.world_model.get_entity(entity_id) is None:
            return False

        self.app.repository_scope_entity_id = entity_id
        self.app.knowledge_layer_active = True
        self.app.repository_return_confirm_active = False
        self.app.system_menu_active = False
        self.app.system_settings_active = False
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

        if action_id == "launch_species_sim":
            entity_id = action.get("entity_id") or self.app.repository_scope_entity_id
            return self.launch_species_sim_tab(entity_id)

        if action_id == "launch_species_editor":
            entity_id = action.get("entity_id") or self.app.repository_scope_entity_id
            return self.launch_species_sim_tab(entity_id, diagnostic_tab="editor")

        if action_id == "open_species_asset_editor":
            return self.open_species_asset_editor(
                active_sim,
                action.get("entity_id") or getattr(active_sim, "species_id", None),
                action.get("asset_role"),
            )

        if action_id == "activate_tab":
            tab_index = action.get("tab_index")
            return self.activate_tab_index(tab_index)

        if action_id == "open_space_from_world_gen":
            system_id = action.get("system_id") or getattr(active_sim, "parent_system_id", None) or "system_sol"
            self.launch_space_root_tab(system_id)
            return True

        if action_id == "simulation_panel_tab_select" and active_sim is not None:
            tab_id = action.get("tab_id")
            return bool(
                getattr(active_sim, "set_active_simulation_panel_tab", lambda _tab_id: False)(tab_id)
            )

        if action_id == "map_history_year_select" and active_sim is not None:
            set_year = getattr(active_sim, "set_year", None)
            if set_year is not None:
                set_year(action.get("year"))
            return True

        if action_id == "set_map_layer" and active_sim is not None:
            return bool(
                getattr(active_sim, "set_active_layer_kind", lambda _layer_kind: False)(
                    action.get("layer_kind")
                )
            )

        if action_id == "toggle_map_atmosphere" and active_sim is not None:
            return bool(
                getattr(active_sim, "toggle_atmosphere_visibility", lambda: False)()
            )

        if action_id == "toggle_map_height_contours" and active_sim is not None:
            return bool(
                getattr(active_sim, "toggle_height_contours_visibility", lambda: False)()
            )

        if action_id == "set_map_material_distribution_item" and active_sim is not None:
            return bool(
                getattr(active_sim, "set_active_material_distribution_item", lambda _item_id: False)(
                    action.get("material_id")
                )
            )

        if action_id == "set_map_climate_display_item" and active_sim is not None:
            return bool(
                getattr(
                    active_sim,
                    "set_active_climate_display_item",
                    lambda _item_id: False,
                )(action.get("climate_id"))
            )

        if action_id == "select_map_location" and active_sim is not None:
            return bool(
                getattr(active_sim, "select_location_from_layer_tree", lambda _entity_id: False)(
                    action.get("entity_id")
                )
            )

        if action_id == "selection_inspector_reanchor_time" and active_sim is not None:
            return bool(
                getattr(active_sim, "reanchor_selection_time", lambda *_args: False)(
                    action.get("target_kind"),
                    action.get("target_id"),
                    action.get("year"),
                )
            )

        if action_id == "selection_inspector_save" and active_sim is not None:
            return bool(
                getattr(active_sim, "save_selection_inspector_updates", lambda *_args: False)(
                    action.get("target_kind"),
                    action.get("target_id"),
                    action.get("updates", {}),
                )
            )

        if action_id == "selection_inspector_edit_polygon" and active_sim is not None:
            return bool(
                getattr(active_sim, "begin_spatial_feature_polygon_edit", lambda *_args: False)(
                    action.get("target_kind"),
                    action.get("target_id"),
                )
            )

        if action_id == "selection_inspector_evolve_region" and active_sim is not None:
            return bool(
                getattr(active_sim, "begin_spatial_feature_evolution", lambda *_args: False)(
                    action.get("target_kind"),
                    action.get("target_id"),
                )
            )

        if action_id == "selection_inspector_delete_region" and active_sim is not None:
            return bool(
                getattr(active_sim, "delete_selection_inspector_target", lambda *_args: False)(
                    action.get("target_kind"),
                    action.get("target_id"),
                )
            )

        if (
            action_id in {
                "selection_inspector_edit_rectangle",
                "selection_inspector_edit_square",
            }
            and active_sim is not None
        ):
            return bool(
                getattr(active_sim, "begin_location_square_edit", lambda *_args: False)(
                    action.get("target_kind"),
                    action.get("target_id"),
                )
            )

        if action_id == "vehicle_catalog_select" and active_sim is not None:
            catalog_id = action.get("catalog_id")
            return bool(
                getattr(active_sim, "begin_design_catalog_drag", lambda _catalog_id: False)(catalog_id)
            )

        if action_id == "open_person_inspector" and active_sim is not None:
            return bool(getattr(active_sim, "open_person_inspector", lambda: False)())

        if action_id == "open_person_character_editor" and active_sim is not None:
            return bool(getattr(active_sim, "open_character_editor", lambda: False)())

        if action_id == "knowledge_launch_entry":
            return self.launch_entity_mode(action.get("entity_id"))

        if action_id == "knowledge_launch_mode":
            return self.launch_entity_mode(action.get("entity_id"), action.get("launch_mode"))

        if action_id == "knowledge_place_location_on_parent":
            return self.open_location_parent_placement_tab(action.get("entity_id"))

        if action_id == "knowledge_launch_world_gen":
            return self.launch_world_gen_tab(action.get("entity_id"))

        if action_id == "parent_assignment_confirm":
            return self.confirm_parent_assignment(
                action.get("target_entity_id"),
                action.get("parent_entity_id"),
            )

        if action_id == "parent_assignment_cancel":
            self.app.parent_assignment_request = None
            return True

        return False

    def _handle_simple_ui_action(self, action_id, active_sim):
        """
        Route simple string-based UI action ids.
        """
        if action_id == "ui_consumed":
            return True

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

        if action_id == "open_person_inspector" and active_sim is not None:
            return bool(getattr(active_sim, "open_person_inspector", lambda: False)())

        if action_id == "open_person_character_editor" and active_sim is not None:
            return bool(getattr(active_sim, "open_character_editor", lambda: False)())

        if action_id == "person_mode_autonomous" and active_sim is not None:
            return bool(getattr(active_sim, "set_control_mode", lambda _mode: False)("autonomous"))

        if action_id == "person_mode_direct" and active_sim is not None:
            return bool(getattr(active_sim, "set_control_mode", lambda _mode: False)("direct"))

        if action_id == "vehicle_mode_design" and active_sim is not None:
            return bool(getattr(active_sim, "set_view_mode", lambda mode: False)("design"))

        if action_id == "vehicle_mode_interior" and active_sim is not None:
            return bool(getattr(active_sim, "set_view_mode", lambda mode: False)("interior"))

        if action_id == "vehicle_mode_operational" and active_sim is not None:
            return bool(getattr(active_sim, "set_view_mode", lambda mode: False)("operational"))

        if action_id == "launch_species_sim":
            entity_id = self.app.repository_scope_entity_id
            if not entity_id:
                entity_id = getattr(active_sim, "species_id", None)
            return self.launch_species_sim_tab(entity_id)

        if action_id == "species_sim_age_down" and active_sim is not None:
            changed = bool(getattr(active_sim, "adjust_age", lambda _days: False)(-30.0))
            if changed:
                self.app.camera_controller.setup_for_sim(active_sim)
            return changed

        if action_id == "species_sim_age_up" and active_sim is not None:
            changed = bool(getattr(active_sim, "adjust_age", lambda _days: False)(30.0))
            if changed:
                self.app.camera_controller.setup_for_sim(active_sim)
            return changed

        if action_id == "species_sim_lod" and active_sim is not None:
            current_lod = int(getattr(active_sim, "lod", 0) or 0)
            changed = bool(getattr(active_sim, "set_lod", lambda _lod: False)((current_lod + 1) % 3))
            if changed:
                self.app.camera_controller.setup_for_sim(active_sim)
            return changed

        if action_id == "open_repository":
            return self.open_repository_workspace(active_sim)

        if action_id == "choose_parent_in_repository":
            return self.begin_parent_assignment_workspace(active_sim)

        if action_id == "open_selection_wiki" and active_sim is not None:
            return self.open_selection_wiki_entry(active_sim)

        if action_id == "confirm_open_repository":
            return self.open_repository_workspace(active_sim)

        if action_id == "cancel_repository_return":
            self.app.repository_return_confirm_active = False
            return True

        if action_id == "system_menu_continue":
            self.app.system_menu_active = False
            self.app.system_settings_active = False
            return True

        if action_id == "system_menu_settings":
            self.app.system_settings_active = True
            return True

        if action_id == "system_menu_back":
            self.app.system_settings_active = False
            return True

        if action_id == "system_toggle_grid":
            self.app.show_grid = not self.app.show_grid
            self.app.input_controller.show_grid = self.app.show_grid
            return True

        if action_id == "system_toggle_fps":
            self.app.show_fps = not self.app.show_fps
            self.app.input_controller.show_fps = self.app.show_fps
            return True

        if action_id == "system_toggle_debug":
            knowledge_ui = getattr(self.app.ui_manager, "knowledge_ui", None)
            if knowledge_ui is None:
                return False
            knowledge_ui._set_performance_debug_enabled(
                not bool(getattr(knowledge_ui, "performance_debug_enabled", False))
            )
            return True

        if action_id == "system_save_ontology":
            knowledge_ui = getattr(self.app.ui_manager, "knowledge_ui", None)
            if knowledge_ui is None:
                return False

            def redraw_save_progress(_progress, _message):
                if pygame.get_init():
                    pygame.event.pump()
                render_frame = getattr(self.app, "_render_frame", None)
                if callable(render_frame):
                    render_frame()

            return bool(
                knowledge_ui._handle_ontology_checkpoint_request(
                    progress_callback=redraw_save_progress,
                )
            )

        if action_id in {
            "phylogeny_clade_members_dec",
            "phylogeny_clade_members_inc",
            "phylogeny_species_relatives_dec",
            "phylogeny_species_relatives_inc",
        }:
            knowledge_ui = getattr(self.app.ui_manager, "knowledge_ui", None)
            if knowledge_ui is None:
                return False
            if action_id == "phylogeny_clade_members_dec":
                return bool(knowledge_ui._set_phylogeny_clade_member_count(knowledge_ui.phylogeny_clade_member_count - 1))
            if action_id == "phylogeny_clade_members_inc":
                return bool(knowledge_ui._set_phylogeny_clade_member_count(knowledge_ui.phylogeny_clade_member_count + 1))
            if action_id == "phylogeny_species_relatives_dec":
                return bool(knowledge_ui._set_phylogeny_species_relative_count(knowledge_ui.phylogeny_species_relative_count - 1))
            return bool(knowledge_ui._set_phylogeny_species_relative_count(knowledge_ui.phylogeny_species_relative_count + 1))

        if action_id == "system_menu_quit":
            self.app.running = False
            self.app.input_controller.running = False
            return True

        if action_id == "open_region_map" and active_sim is not None:
            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            self.open_region_map_tab(selected_entity_id)
            return True

        if action_id == "regenerate_current_region" and active_sim is not None:
            loading = getattr(self.app, "_draw_startup_loading_screen", None)
            if callable(loading):
                loading(0.22, "Regenerating this region from parent boundary conditions")
            region = getattr(active_sim, "regenerate_current_region", lambda: None)()
            if not isinstance(region, dict) or not region.get("id"):
                return False
            if callable(loading):
                loading(0.84, "Feeding refreshed detail into the parent map")
            self._refresh_generated_map_views()
            return True

        if action_id == "regenerate_visible_region" and active_sim is not None:
            loading = getattr(self.app, "_draw_startup_loading_screen", None)
            if callable(loading):
                loading(0.28, "Refining regional terrain and drainage")
            region = getattr(active_sim, "regenerate_visible_region", lambda *_args, **_kwargs: None)(
                self.app.camera,
                self.app.width,
                self.app.height,
                viewport_rect=getattr(self.app.ui_manager, "get_map_content_viewport_rect", lambda *_args: None)(
                    self.app.width, self.app.height,
                ),
            )
            if not isinstance(region, dict) or not region.get("id"):
                return False
            if callable(loading):
                loading(0.86, "Persisting hierarchical map detail")
            self._refresh_generated_map_views()
            return bool(self.open_region_map_tab(region.get("id")))

        if action_id == "reset_planet_map_view" and active_sim is not None:
            if not bool(getattr(active_sim, "reset_planet_view", lambda: False)()):
                return False
            self.app.camera_controller.setup_for_sim(active_sim)
            return True

        if action_id == "cycle_map_layer" and active_sim is not None:
            return bool(getattr(active_sim, "cycle_active_layer_kind", lambda: False)())

        if action_id == "import_map_image" and active_sim is not None:
            return bool(getattr(active_sim, "import_map_image_for_current_target", lambda: False)())

        if action_id == "new_biosphere_patch" and active_sim is not None:
            return bool(getattr(active_sim, "begin_biosphere_patch_draft", lambda: False)())

        if action_id == "create_biosphere" and active_sim is not None:
            return self.launch_biosphere_design_tab(active_sim)

        if str(action_id).startswith("biosphere_toggle_species:") and active_sim is not None:
            species_id = str(action_id).split(":", 1)[1]
            return bool(getattr(active_sim, "toggle_species_selection", lambda _species_id: False)(species_id))

        if action_id == "new_map_selection" and active_sim is not None:
            if (
                getattr(active_sim, "get_active_layer_kind", lambda: None)()
                == getattr(active_sim, "LOCATION_LAYER_KIND", "locations")
            ):
                return bool(getattr(active_sim, "begin_location_draft", lambda: False)())
            return bool(getattr(active_sim, "begin_spatial_feature_draft", lambda: False)())

        if str(action_id).startswith("new_location:") and active_sim is not None:
            location_class = str(action_id).split(":", 1)[1] or "region"
            return bool(
                getattr(active_sim, "begin_location_draft", lambda _location_class="region": False)(
                    location_class
                )
            )

        if str(action_id).startswith("new_point_location:") and active_sim is not None:
            location_class = str(action_id).split(":", 1)[1] or "site"
            return bool(
                getattr(active_sim, "begin_point_location_draft", lambda _location_class="site": False)(
                    location_class
                )
            )

        if action_id == "link_existing_map_location" and active_sim is not None:
            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            root_entity_id = getattr(getattr(active_sim, "context", None), "root_entity_id", None)
            if selected_entity_id and selected_entity_id != root_entity_id:
                if self.open_location_parent_placement_tab(selected_entity_id):
                    return True

            self.app.repository_scope_entity_id = root_entity_id
            self.app.knowledge_layer_active = True
            return True

        if action_id in {"new_map_rectangle", "new_map_square"} and active_sim is not None:
            return bool(getattr(active_sim, "begin_map_square_draft", lambda: False)())

        if action_id == "finish_map_selection" and active_sim is not None:
            finished = bool(getattr(active_sim, "finish_map_editor", lambda: False)())
            if not finished:
                return True

            return_entity_id = getattr(
                active_sim,
                "consume_repository_return_entity_id",
                lambda: None,
            )()
            if return_entity_id:
                if hasattr(self.app.world_model, "refresh"):
                    self.app.world_model.refresh()
                self.app.repository_scope_entity_id = return_entity_id
                self.app.knowledge_layer_active = True
                return True

            return True

        if action_id == "cancel_map_selection" and active_sim is not None:
            return bool(getattr(active_sim, "cancel_map_editor", lambda: False)())

        if action_id == "open_parent_region_map" and active_sim is not None:
            self.open_parent_region_map_tab(active_sim)
            return True

        if action_id == "place_current_root_on_parent" and active_sim is not None:
            root_entity_id = getattr(getattr(active_sim, "context", None), "root_entity_id", None)
            if root_entity_id:
                return self.open_location_parent_placement_tab(root_entity_id)
            return False

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
        if getattr(self.app.ui_manager, "is_text_input_active", lambda: False)():
            return

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
