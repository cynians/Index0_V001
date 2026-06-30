from world.entity_loader import EntityLoader
from world.relationship_graph import TouchDegrees
from world.schema_loader import SchemaLoader
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
        self.schemas = SchemaLoader()
        self.touch_degrees = TouchDegrees(self.loader, self.schemas)
        self.graph = self.touch_degrees
        self.yearer = Yearer(self.loader)
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
        if hasattr(self.touch_degrees, "refresh"):
            self.touch_degrees.refresh()
        self.repository_revision += 1

    def mark_repository_changed(self):
        if hasattr(self.touch_degrees, "refresh"):
            self.touch_degrees.refresh()
        self.yearer = Yearer(self.loader)
        self.repository_revision += 1

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

        for entity_id, entity in self.loader.entities.items():
            start_year = self.yearer.normalize_year(entity.get("start_year"))
            end_year = self.yearer.normalize_year(entity.get("end_year"))

            if start_year is None:
                continue
            if end_year is None:
                end_year = start_year

            dataset_name = entity.get("_dataset", entity.get("type", "entity"))
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
            commentary_parts = []
            start_commentary = str(entity.get("start_commentary") or entity.get("start_event") or "").strip()
            end_commentary = str(entity.get("end_commentary") or entity.get("end_event") or "").strip()
            if start_commentary:
                commentary_parts.append(f"Start: {start_commentary}")
            if end_commentary:
                commentary_parts.append(f"End: {end_commentary}")

            items.append(
                {
                    "entity_id": entity_id,
                    "label": str(label),
                    "dataset": dataset_name,
                    "entity_type": entity.get("type", "entity"),
                    "start_year": start_year,
                    "end_year": end_year,
                    "is_point": start_year == end_year,
                    "card_color": card_color,
                    "commentary": " / ".join(commentary_parts),
                }
            )

        return items

    def refresh(self):
        self.loader.refresh()
        self.touch_degrees.refresh()
        self.yearer = Yearer(self.loader)
