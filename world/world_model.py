"""Application-facing projection of the ontology-backed world.

Architecture invariants: all entities and their ontological/semantic facts are
stored in the ontology. Python mappings are disposable startup/query caches.
Worldgen currently has no planets intended for durable persistence, so changed
generation contracts invalidate old products rather than requiring migration.
"""

import re

from world.entity_loader import EntityLoader
from world.dione_reference_models import apply_dione_reference_models
from world.component_host import apply_component_host_schema
from world.earth_reference_models import apply_earth_reference_models
from world.orbital_space_reference_models import apply_orbital_space_reference_models
from world.periods import apply_period_reference_models
from world.technology_schema import apply_technology_schema
from world.relationship_graph import TouchDegrees
from world.schema_loader import SchemaLoader
from world.species_inheritance import (
    refresh_species_inheritance,
    resolved_species_entity,
    resolve_species_field,
)
from world.yearer import Yearer


class WorldModel:
    """
    Central world interface used by UI systems.

    Combines:
    * entity loading
    * schema loading
    * relationship graph construction
    * year-based entity filtering
    """

    # Canonical macro-era bounds are deduced from the lore references in
    # text/ideas.txt. Some older notes in text/timeline.txt still use
    # superseded boundaries (for example 6013 vs 6034 for the start of the
    # Planetary Period), so the ideas reference is treated as the stronger
    # source here.
    @property
    def plant_catalogue(self):
        return self.loader.plant_catalogue

    def is_plant(self, entity_id):
        return self.plant_catalogue.contains(entity_id)

    def is_plant_species(self, entity_id):
        return self.plant_catalogue.is_species(entity_id)

    MAJOR_PERIODS = [
        {
            "entity_id": "period_siderian",
            "label": "Siderian Period",
            "start_year": -2500000000,
            "end_year": -2300000000,
        },
        {
            "entity_id": "period_rhyacian",
            "label": "Rhyacian Period",
            "start_year": -2300000000,
            "end_year": -2050000000,
        },
        {
            "entity_id": "period_orosirian",
            "label": "Orosirian Period",
            "start_year": -2050000000,
            "end_year": -1800000000,
        },
        {
            "entity_id": "period_statherian",
            "label": "Statherian Period",
            "start_year": -1800000000,
            "end_year": -1600000000,
        },
        {
            "entity_id": "period_calymmian",
            "label": "Calymmian Period",
            "start_year": -1600000000,
            "end_year": -1400000000,
        },
        {
            "entity_id": "period_ectasian",
            "label": "Ectasian Period",
            "start_year": -1400000000,
            "end_year": -1200000000,
        },
        {
            "entity_id": "period_stenian",
            "label": "Stenian Period",
            "start_year": -1200000000,
            "end_year": -1000000000,
        },
        {
            "entity_id": "period_tonian",
            "label": "Tonian Period",
            "start_year": -1000000000,
            "end_year": -720000000,
        },
        {
            "entity_id": "period_cryogenian",
            "label": "Cryogenian Period",
            "start_year": -720000000,
            "end_year": -635000000,
        },
        {
            "entity_id": "period_ediacaran",
            "label": "Ediacaran Period",
            "start_year": -635000000,
            "end_year": -538800000,
        },
        {
            "entity_id": "period_cambrian",
            "label": "Cambrian Period",
            "start_year": -538800000,
            "end_year": -486850000,
        },
        {
            "entity_id": "period_ordovician",
            "label": "Ordovician Period",
            "start_year": -486850000,
            "end_year": -443100000,
        },
        {
            "entity_id": "period_silurian",
            "label": "Silurian Period",
            "start_year": -443100000,
            "end_year": -419620000,
        },
        {
            "entity_id": "period_devonian",
            "label": "Devonian Period",
            "start_year": -419620000,
            "end_year": -358900000,
        },
        {
            "entity_id": "period_carboniferous",
            "label": "Carboniferous Period",
            "start_year": -358900000,
            "end_year": -298900000,
        },
        {
            "entity_id": "period_permian",
            "label": "Permian Period",
            "start_year": -298900000,
            "end_year": -251902000,
        },
        {
            "entity_id": "period_triassic",
            "label": "Triassic Period",
            "start_year": -251902000,
            "end_year": -201400000,
        },
        {
            "entity_id": "period_jurassic",
            "label": "Jurassic Period",
            "start_year": -201400000,
            "end_year": -143100000,
        },
        {
            "entity_id": "period_cretaceous",
            "label": "Cretaceous Period",
            "start_year": -143100000,
            "end_year": -66000000,
        },
        {
            "entity_id": "period_paleogene",
            "label": "Paleogene Period",
            "start_year": -66000000,
            "end_year": -23040000,
        },
        {
            "entity_id": "period_neogene",
            "label": "Neogene Period",
            "start_year": -23040000,
            "end_year": -2580000,
        },
        {
            "entity_id": "period_quaternary",
            "label": "Quaternary Period",
            "start_year": -2580000,
            "end_year": 2026,
        },
        {
            "entity_id": "period_postmodernist",
            "label": "Postmodernist Period",
            "start_year": 2000,
            "end_year": 2090,
        },
        {
            "entity_id": "period_superpower_wars",
            "label": "Superpower Wars",
            "start_year": 2024,
            "end_year": 2090,
        },
        {
            "entity_id": "period_race_for_sol",
            "label": "Race for Sol",
            "start_year": 2090,
            "end_year": 2440,
        },
        {
            "entity_id": "period_ggo_hegemony",
            "label": "GGO Hegemony Period",
            "start_year": 2440,
            "end_year": 5954,
        },
        {
            "entity_id": "period_second_modernity_earth",
            "label": "Second Modernity (Earth)",
            "start_year": 5954,
            "end_year": 6034,
        },
        {
            "entity_id": "period_planetary",
            "label": "Planetary Period",
            "start_year": 6034,
            "end_year": 14195,
        },
        {
            "entity_id": "period_trifecta_dominion",
            "label": "Trifecta Dominion Period",
            "start_year": 14195,
            "end_year": 20219,
        },
        {
            "entity_id": "period_intersector_assembly",
            "label": "Intersector Assembly Period",
            "start_year": 20219,
            "end_year": 35101,
        },
    ]

    def __init__(self, entries_directory=None, ontology_path=None, use_ontology=None):
        self.loader = EntityLoader(
            entries_directory=entries_directory,
            ontology_path=ontology_path,
            use_ontology=use_ontology,
        )
        # World-gen reads the ontology material dataset through one fast
        # process-local cache. There is no separately authored material list.
        from simulations.world_gen.natural_materials import configure_material_catalog
        material_count = configure_material_catalog(
            self.loader.get_dataset("materials")
        )
        if material_count <= 0:
            raise RuntimeError(
                "The ontology material dataset is required; compatibility "
                "JSON directories cannot supply world-generation materials"
            )
        apply_earth_reference_models(self.loader)
        apply_dione_reference_models(self.loader)
        apply_orbital_space_reference_models(self.loader)
        apply_period_reference_models(self.loader, self.MAJOR_PERIODS)
        apply_component_host_schema(self.loader)
        apply_technology_schema(self.loader)
        # Reuse schemas already decoded by EntityLoader. Parsing the complete
        # ontology a second time is especially costly once generated maps are
        # persisted in the repository.
        self.schemas = SchemaLoader(schema_entities=self.loader.get_dataset("schemas"))
        self.touch_degrees = TouchDegrees(self.loader, self.schemas)
        self.graph = self.touch_degrees
        self.yearer = Yearer(self.loader)
        refresh_species_inheritance(self.loader, persist=False)
        self.repository_revision = 0

    def get_entity(self, entity_id):
        return self.loader.get(entity_id)

    def set_literal(self, entity_id, field_name, value, persist=True):
        changed_entity_ids = self.loader.set_literal(entity_id, field_name, value, persist=persist)
        self._refresh_after_repository_mutation(changed_entity_ids)
        return changed_entity_ids

    def set_relation(self, source_id, field_name, target_id, reciprocal_field=None, persist=True):
        changed_entity_ids = self.loader.set_relation(
            source_id,
            field_name,
            target_id,
            reciprocal_field=reciprocal_field,
            persist=persist,
        )
        self._refresh_after_repository_mutation(changed_entity_ids)
        return changed_entity_ids

    def remove_relation(self, source_id, field_name, target_id, reciprocal_field=None, persist=True):
        changed_entity_ids = self.loader.remove_relation(
            source_id,
            field_name,
            target_id,
            reciprocal_field=reciprocal_field,
            persist=persist,
        )
        self._refresh_after_repository_mutation(changed_entity_ids)
        return changed_entity_ids

    def _refresh_after_repository_mutation(self, changed_entity_ids):
        if not changed_entity_ids:
            return
        apply_orbital_space_reference_models(self.loader)
        apply_period_reference_models(self.loader, self.MAJOR_PERIODS)
        apply_component_host_schema(self.loader)
        apply_technology_schema(self.loader)
        if hasattr(self.touch_degrees, "refresh"):
            self.touch_degrees.refresh()
        self.yearer = Yearer(self.loader)
        self.repository_revision += 1

    def mark_repository_changed(self, changed_entity_ids=None):
        apply_orbital_space_reference_models(self.loader)
        apply_period_reference_models(self.loader, self.MAJOR_PERIODS)
        apply_component_host_schema(self.loader)
        apply_technology_schema(self.loader)
        if hasattr(self.touch_degrees, "refresh"):
            self.touch_degrees.refresh()
        self.yearer = Yearer(self.loader)
        if self._change_may_affect_species_inheritance(changed_entity_ids):
            refresh_species_inheritance(self.loader, persist=True)
        self.repository_revision += 1

    def _change_may_affect_species_inheritance(self, changed_entity_ids):
        """Species inheritance only derives fields for species/cladistics
        entities from their cladistic descendants. Editing any other entity
        (a planet, vehicle, idea, ...) cannot change it, so the full
        tree-wide re-derivation — which is very expensive — can be skipped.

        ``None`` means "caller does not know what changed"; stay safe and
        refresh.
        """
        if changed_entity_ids is None:
            return True
        entities = getattr(self.loader, "entities", {})
        for entity_id in changed_entity_ids:
            entity = entities.get(entity_id)
            if not isinstance(entity, dict):
                # Deleted/renamed/unknown: cannot rule it out.
                return True
            dataset = entity.get("_dataset")
            entity_type = entity.get("type")
            if dataset in {"species", "cladistics"} or entity_type in {"species", "cladistics"}:
                return True
        return False

    def resolve_species_field(self, entity_id, field_key):
        entity = self.get_entity(entity_id)
        return resolve_species_field(self.loader, entity, field_key)

    def resolved_species_entity(self, entity_id):
        entity = self.get_entity(entity_id)
        return resolved_species_entity(self.loader, entity)

    def get_dataset(self, dataset_name):
        if dataset_name == "systems":
            return [
                entity
                for entity in self.loader.get_dataset("locations")
                if entity.get("system_role") == "star_system"
                or entity.get("location_class") == "star_system"
            ]
        if dataset_name == "spatial_features":
            return [
                entity
                for entity in self.loader.get_dataset("locations")
                if entity.get("location_class") in {"region", "state", "quarter"}
                and (entity.get("geometry") or entity.get("layer_kind"))
            ]
        return self.loader.get_dataset(dataset_name)

    def get_dataset_names(self):
        names = list(self.loader.datasets.keys())
        return names

    def get_entities_by_dataset(self, dataset_name):
        dataset = self.get_dataset(dataset_name)

        if isinstance(dataset, dict):
            return list(dataset.values())

        if isinstance(dataset, list):
            return dataset

        return []

    def get_entities_by_type(self, entity_type):
        return [
            entity
            for entity in self.loader.entities.values()
            if entity.get("type") == entity_type
        ]

    def get_neighbors(self, entity_id):
        return self.touch_degrees.get_neighbors(entity_id)

    def get_relationships(self, entity_id):
        return self.touch_degrees.get_touches(entity_id)

    def get_touches(self, entity_id):
        return self.touch_degrees.get_touches(entity_id)

    def get_incoming_touches(self, entity_id):
        return self.touch_degrees.get_incoming_touches(entity_id)

    def get_events(self):
        return self.loader.get_dataset("events")

    def get_events_in_range(self, start, end):
        events = []

        for event in self.get_events().values():
            year = event.get("year")

            if year is None:
                continue

            if start <= year <= end:
                events.append(event)

        return events

    def resolve_entity(self, entity_id, year):
        return self.yearer.resolve(entity_id, year)

    def entities_active(self, year):
        return self.yearer.entities_active(year)

    def get_active_entities(self, year, dataset_name=None, entity_type=None):
        active_entities = list(self.yearer.entities_active(year).values())

        if dataset_name is not None:
            active_entities = [
                entity
                for entity in active_entities
                if entity.get("_dataset") == dataset_name
            ]

        if entity_type is not None:
            active_entities = [
                entity
                for entity in active_entities
                if entity.get("type") == entity_type
            ]

        return active_entities

    def get_active_dataset(self, dataset_name, year):
        return self.get_active_entities(year, dataset_name=dataset_name)

    def get_active_locations(self, year):
        return self.get_active_entities(
            year,
            dataset_name="locations",
            entity_type="location"
        )

    def _get_major_period_timeline_items(self):
        items = []

        for period in self.MAJOR_PERIODS:
            period_entity = self.loader.entities.get(period["entity_id"], {})
            items.append(
                {
                    "entity_id": period["entity_id"],
                    "label": period["label"],
                    "dataset": "timeline_periods",
                    "entity_type": "major_period",
                    "timeline_kind": "major_period",
                    "start_year": period["start_year"],
                    "end_year": period["end_year"],
                    "is_point": False,
                    "card_color": period_entity.get("card_color", ""),
                }
            )

        return items

    def _is_technology_entity(self, entity):
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "technologies" or entity.get("type") == "technology"
        )

    def _technology_supersede_years(self):
        """Map ``technology_id -> earliest successor invention year``.

        A technology is superseded once the technology that replaces it is
        invented. Edges come from either direction: this entity's ``successor``
        / ``successors``, or another technology naming this one in its
        ``predecessor`` / ``predecessors``.
        """
        successors_by_tech = {}
        invention_year_by_tech = {}
        for entity_id, entity in self.loader.entities.items():
            if not self._is_technology_entity(entity):
                continue
            invention_year_by_tech[entity_id] = self.yearer.normalize_year(entity.get("start_year"))
            for field_key in ("successor", "successors"):
                for successor_id in self.loader._relation_ids(entity.get(field_key)):
                    if successor_id and successor_id != entity_id:
                        successors_by_tech.setdefault(entity_id, set()).add(successor_id)
            for field_key in ("predecessor", "predecessors"):
                for predecessor_id in self.loader._relation_ids(entity.get(field_key)):
                    if predecessor_id and predecessor_id != entity_id:
                        successors_by_tech.setdefault(predecessor_id, set()).add(entity_id)

        supersede_years = {}
        for tech_id, successor_ids in successors_by_tech.items():
            years = [
                invention_year_by_tech.get(successor_id)
                for successor_id in successor_ids
            ]
            years = [year for year in years if year is not None]
            if years:
                supersede_years[tech_id] = min(years)
        return supersede_years

    def get_timeline_items(self):
        """
        Collect repository entities that define temporal information.

        Returns a list of timeline-ready dictionaries with normalized years.
        Minimal prototype rules:
        * include any entity with an explicit start_year
        * if end_year is missing, treat start_year as a point entry
        * keep output flat and UI-friendly
        """
        items = self._get_major_period_timeline_items()
        technology_supersede_years = self._technology_supersede_years()

        for entity_id, entity in self.loader.entities.items():
            start_year = self.yearer.normalize_year(entity.get("start_year"))
            end_year = self.yearer.normalize_year(entity.get("end_year"))
            dataset_name = entity.get("_dataset", entity.get("type", "entity"))
            if entity.get("period_reference_generated"):
                continue
            if dataset_name == "species" or entity.get("type") == "species":
                common_name = str(entity.get("common_name") or "").strip()
                binomial_name = str(entity.get("binomial_name") or "").strip()
                if common_name and binomial_name:
                    label = f"{common_name} - {binomial_name}"
                else:
                    label = common_name or binomial_name or entity.get("pretty_name") or entity.get("name") or entity_id
            else:
                label = entity.get("pretty_name") or entity.get("name") or entity_id
            card_color = entity.get("card_color", "")

            if start_year is None:
                continue
            if end_year is None:
                end_year = start_year

            is_technology = dataset_name == "technologies" or entity.get("type") == "technology"
            forgotten_year = None
            superseded_year = None
            technology_open_ended = False
            if is_technology:
                # A technology's start_year is its invention date. It stays
                # available (an "availability rail") until it is forgotten;
                # being superseded dims the rail but does not end it.
                forgotten_year = self.yearer.normalize_year(entity.get("forgotten_year"))
                superseded_year = technology_supersede_years.get(entity_id)
                if forgotten_year is not None:
                    end_year = forgotten_year
                else:
                    end_year = start_year
                    technology_open_ended = True

            start_commentary = str(entity.get("start_commentary") or "").strip()
            end_commentary = str(entity.get("end_commentary") or "").strip()
            commentary_parts = []
            if start_commentary:
                commentary_parts.append(f"Start: {start_commentary}")
            if end_commentary:
                commentary_parts.append(f"End: {end_commentary}")

            item = {
                "entity_id": entity_id,
                "label": str(label),
                "dataset": dataset_name,
                "entity_type": entity.get("type", "entity"),
                "start_year": start_year,
                "end_year": end_year,
                "is_point": start_year == end_year,
                "card_color": card_color,
                "commentary": " / ".join(commentary_parts),
                "start_commentary": start_commentary,
                "end_commentary": end_commentary,
            }
            if is_technology:
                item["timeline_kind"] = "technology"
                item["invention_year"] = start_year
                item["forgotten_year"] = forgotten_year
                item["superseded_year"] = superseded_year
                item["technology_open_ended"] = technology_open_ended
            items.append(item)

        return items

    def _timeline_snapshot_items(self, entity_id, entity, label, dataset_name, card_color):
        raw_entries = entity.get("timeline_snapshots")
        if not isinstance(raw_entries, list):
            return []

        items = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            start_year = self.yearer.normalize_year(entry.get("start_year"))
            if start_year is None:
                continue
            end_year = self.yearer.normalize_year(entry.get("end_year")) or start_year
            if end_year < start_year:
                start_year, end_year = end_year, start_year
            wiki_text = str(entry.get("wiki_entry") or "").strip()
            commentary = "Wiki entry in this year"
            if wiki_text:
                commentary = wiki_text.splitlines()[0][:120]
            base_item = {
                "entity_id": entity_id,
                "label": str(label),
                "dataset": dataset_name,
                "entity_type": entity.get("type", "entity"),
                "start_year": start_year,
                "end_year": end_year,
                "is_point": start_year == end_year,
                "card_color": card_color,
                "timeline_kind": "wiki_snapshot",
                "commentary": commentary,
                "source_entity_id": entity_id,
            }
            items.append(base_item)
            for ref in self._wiki_link_refs(wiki_text):
                if ref == entity_id or self.get_entity(ref) is None:
                    continue
                mentioned_item = dict(base_item)
                mentioned_item["entity_id"] = ref
                mentioned_item["timeline_kind"] = "mentioned_wiki_snapshot"
                mentioned_item["source_entity_id"] = entity_id
                items.append(mentioned_item)
        return items

    def _wiki_link_refs(self, text):
        refs = []
        for match in re.finditer(r"\[\[([^\]]+)\]\]", str(text or "")):
            ref = match.group(1).split("|", 1)[0].strip()
            if ref:
                refs.append(ref)
        return refs

    def refresh(self):
        self.loader.refresh()
        apply_earth_reference_models(self.loader)
        apply_dione_reference_models(self.loader)
        apply_orbital_space_reference_models(self.loader)
        apply_period_reference_models(self.loader, self.MAJOR_PERIODS)
        apply_component_host_schema(self.loader)
        apply_technology_schema(self.loader)
        self.schemas = SchemaLoader(schema_entities=self.loader.get_dataset("schemas"))
        self.touch_degrees.schemas = self.schemas
        self.touch_degrees.refresh()
        self.yearer = Yearer(self.loader)
        self.repository_revision += 1
