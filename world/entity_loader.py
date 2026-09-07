"""Load ontology entities into disposable application query caches.

Architecture invariants: the ontology alone owns entity identity and semantic
facts; loaded dictionaries are projections, never an independent registry.
Generated planets are not current persistence targets, so worldgen contract
changes do not require legacy-product accommodation.
"""

import json
import sqlite3
import uuid
from pathlib import Path
import logging
from world.ontology_repository import OntologyRepository
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue

logger = logging.getLogger(__name__)


class EntityLoader:
    """
    Loads entity datasets from the ontology repository.

    A JSON file-import path remains for explicit compatibility imports, but the
    normal application path is ontology-backed.
    """

    CORE_DEFAULTS = {
        "tags": [],
        "start_year": None,
        "end_year": None,
        "parents": [],
        "related": [],
        "offspring": [],
        "entry_status": "",
    }
    IDEA_DEFAULTS = {
        "tags": [],
        "start_year": None,
        "end_year": None,
        "parents": [],
        "related": [],
        "offspring": [],
        "entry_status": "",
    }
    FAST_PALETTE_FIELDS = {
        "card_color",
        "card_header_color",
        "wiki_field_colors",
        "card_color_source",
        "wiki_link_color",
        "geological_map_color",
    }
    LEGACY_IDEA_FIELDS = {
        "related_entities",
        "parent_entity",
        "source",
        "decision_status",
        "card_image",
        "design_image",
        "card_image_front",
        "card_image_side",
        "card_image_top",
        "image_path",
        "image",
        "derived_from_ideas",
        "parent_ideas",
        "related_ideas",
        "media_layers",
    }
    CORE_RELATION_RENAMES = {
        "derived_from_ideas": "related",
        "parent_ideas": "parents",
        "related_ideas": "related",
    }

    def __init__(self, entries_directory=None, auto_save_normalized=False, ontology_path=None, use_ontology=None):

        if entries_directory is None:
            project_root = Path(__file__).resolve().parents[1]
            entries_directory = project_root / "entries"
        else:
            project_root = Path(entries_directory).resolve().parent

        if ontology_path is None:
            ontology_path = project_root / "ontology" / "index0.owl"

        self.entries_directory = Path(entries_directory)
        self.ontology_path = Path(ontology_path)
        self.use_ontology = True if use_ontology is None else bool(use_ontology)
        self.auto_save_normalized = auto_save_normalized

        self.datasets = {}
        self.entities = {}
        self.entity_aliases = {}
        self.edges = {}
        self._dataset_file_records = []
        self._persistent_store = None

        self.refresh()

    # --------------------------------------------------

    def _is_blank_value(self, value):
        return value is None or value == "" or value == []

    def _copy_missing_fields(self, target, source, fields):
        for field in fields:
            if field not in source:
                continue
            if field not in target or self._is_blank_value(target.get(field)):
                target[field] = source.get(field)

    def _merge_relation_values(self, entity, source_field, target_field="related", remove_source=True):
        if source_field not in entity:
            return False

        source_value = entity.get(source_field)
        if isinstance(source_value, list):
            source_values = list(source_value)
        elif source_value in (None, "", []):
            source_values = []
        else:
            source_values = [source_value]

        target_value = entity.get(target_field)
        if isinstance(target_value, list):
            target_values = list(target_value)
        elif target_value in (None, "", []):
            target_values = []
        else:
            target_values = [target_value]

        changed = False
        for value in source_values:
            if not isinstance(value, str):
                continue
            value = value.strip()
            if value and value not in target_values:
                target_values.append(value)
                changed = True

        if target_values or target_field in entity:
            if entity.get(target_field) != target_values:
                entity[target_field] = target_values
                changed = True

        if remove_source:
            entity.pop(source_field, None)
            changed = True

        return changed

    def _converted_system_location_class(self, entity):
        system_role = entity.get("system_role")
        if system_role == "star_system":
            return entity.get("system_class") or "star_system"
        if system_role == "orbital_body":
            return entity.get("body_class") or "orbital_body"
        return entity.get("system_class") or entity.get("body_class") or "system"

    def _convert_system_entity_to_location(self, entity):
        converted = dict(entity)
        converted["_legacy_dataset"] = converted.get("_dataset", "systems")
        converted["_dataset"] = "locations"
        converted["type"] = "location"
        if not converted.get("location_class"):
            converted["location_class"] = self._converted_system_location_class(entity)
        if not converted.get("location_role"):
            converted["location_role"] = entity.get("system_role") or "system"
        return converted

    def _fold_system_entities_into_locations(self):
        """
        Present legacy system rows as location-class entries.

        Orbital bodies with an explicit location_entity are merged into that
        canonical location so planets do not appear twice in the repository
        browser. Bodies without a map/location anchor remain visible as
        location entries using their legacy id.
        """
        system_entities = self.datasets.get("systems")
        if not system_entities:
            return

        location_entities = self.datasets.setdefault("locations", [])
        location_by_id = {
            entity.get("id"): entity
            for entity in location_entities
            if isinstance(entity, dict) and entity.get("id")
        }

        system_fields = [
            "system_role",
            "system_class",
            "parent_cluster",
            "star_system",
            "body_class",
            "parent_body",
            "location_entity",
            "mass_kg",
            "radius_m",
            "semi_major_axis_m",
            "eccentricity",
            "inclination_deg",
            "longitude_of_ascending_node_deg",
            "argument_of_periapsis_deg",
            "mean_anomaly_deg_at_epoch",
            "display_color",
            "star_class",
            "spectral_class",
            "luminosity_solar",
            "habitable_zone_inner_au",
            "habitable_zone_outer_au",
        ]

        for system_entity in list(system_entities):
            if not isinstance(system_entity, dict):
                continue

            system_id = system_entity.get("id")
            converted = self._convert_system_entity_to_location(system_entity)
            canonical_id = system_entity.get("location_entity")

            if canonical_id and canonical_id in location_by_id:
                canonical = location_by_id[canonical_id]
                self._copy_missing_fields(canonical, converted, system_fields)
                if not canonical.get("location_class"):
                    canonical["location_class"] = converted.get("location_class")
                if not canonical.get("location_role"):
                    canonical["location_role"] = converted.get("location_role")
                if not canonical.get("derived_from_system_body") and system_id:
                    canonical["derived_from_system_body"] = system_id
                if system_id:
                    canonical["legacy_system_entity_id"] = system_id
                    self.entity_aliases[system_id] = canonical_id
                continue

            if converted.get("id") in location_by_id:
                canonical = location_by_id[converted["id"]]
                self._copy_missing_fields(canonical, converted, system_fields)
                if not canonical.get("location_class"):
                    canonical["location_class"] = converted.get("location_class")
                if not canonical.get("location_role"):
                    canonical["location_role"] = converted.get("location_role")
                continue

            location_entities.append(converted)
            if converted.get("id"):
                location_by_id[converted["id"]] = converted

        self.datasets.pop("systems", None)

    def _convert_spatial_feature_to_location(self, entity):
        converted = dict(entity)
        converted["_legacy_dataset"] = converted.get("_dataset", "spatial_features")
        converted["_dataset"] = "locations"
        converted["type"] = "location"
        converted.setdefault("location_class", "region")
        converted.setdefault("location_role", "map_region")

        layer_kind = converted.get("layer_kind")
        if layer_kind and not converted.get("region_class"):
            converted["region_class"] = layer_kind

        parent_entity = converted.get("parent_entity")
        if parent_entity and not converted.get("parent_location"):
            converted["parent_location"] = parent_entity

        geometry = converted.get("geometry")
        if isinstance(geometry, dict) and not converted.get("bounds"):
            converted["bounds"] = dict(geometry)

        return converted

    def _fold_spatial_features_into_locations(self):
        spatial_features = self.datasets.get("spatial_features")
        if not spatial_features:
            return

        location_entities = self.datasets.setdefault("locations", [])
        location_by_id = {
            entity.get("id"): entity
            for entity in location_entities
            if isinstance(entity, dict) and entity.get("id")
        }

        for feature in spatial_features:
            if not isinstance(feature, dict) or not feature.get("id"):
                continue

            converted = self._convert_spatial_feature_to_location(feature)
            existing = location_by_id.get(converted.get("id"))
            if existing is not None:
                self._copy_missing_fields(
                    existing,
                    converted,
                    [
                        "location_class",
                        "location_role",
                        "region_class",
                        "parent_location",
                        "parent_entity",
                        "owner_entity",
                        "layer_kind",
                        "geometry",
                        "bounds",
                        "coverage_mode",
                        "resolution_m_per_pixel",
                        "draw_order",
                    ],
                )
                continue

            location_entities.append(converted)
            location_by_id[converted["id"]] = converted

        self.datasets.pop("spatial_features", None)

    def _ensure_standard_relations(self, entity, dataset_name=None):
        changed = False

        is_species = dataset_name == "species" or entity.get("type") == "species"
        if is_species:
            pretty_name = str(entity.get("pretty_name") or "").strip()
            legacy_name = str(entity.get("name") or "").strip()

            if "common_name" not in entity:
                if " - " in pretty_name:
                    entity["common_name"] = pretty_name.split(" - ", 1)[0].strip()
                elif pretty_name and pretty_name != entity.get("id"):
                    entity["common_name"] = pretty_name
                else:
                    entity["common_name"] = ""
                changed = True

            if "binomial_name" not in entity:
                if legacy_name:
                    entity["binomial_name"] = legacy_name
                elif " - " in pretty_name:
                    entity["binomial_name"] = pretty_name.split(" - ", 1)[1].strip()
                else:
                    entity["binomial_name"] = ""
                changed = True

        if not is_species and "pretty_name" not in entity:
            entity["pretty_name"] = entity.get("name") or entity.get("id") or ""
            changed = True

        if not is_species and "name" not in entity:
            entity["name"] = entity.get("pretty_name") or entity.get("id") or ""
            changed = True

        for old_field, new_field in self.CORE_RELATION_RENAMES.items():
            if old_field not in entity:
                continue
            old_value = entity.get(old_field)
            new_value = entity.get(new_field)
            if new_value in (None, "", []):
                entity[new_field] = old_value
            elif isinstance(new_value, list) and isinstance(old_value, list):
                for item in old_value:
                    if item not in new_value:
                        new_value.append(item)
            entity.pop(old_field, None)
            changed = True

        for obsolete_relation_field in ("derived_from", "wiki_mentions"):
            changed = self._merge_relation_values(
                entity,
                obsolete_relation_field,
                target_field="related",
                remove_source=True,
            ) or changed

        is_idea = dataset_name == "ideas" or entity.get("type") == "idea"
        defaults = self.IDEA_DEFAULTS if is_idea else self.CORE_DEFAULTS

        for field, default_value in defaults.items():
            if field not in entity:
                if isinstance(default_value, list):
                    entity[field] = list(default_value)
                elif isinstance(default_value, dict):
                    entity[field] = dict(default_value)
                else:
                    entity[field] = default_value
                changed = True

        if "child_ideas" in entity:
            entity.pop("child_ideas", None)
            changed = True

        if is_idea:
            for field in self.LEGACY_IDEA_FIELDS:
                if field in entity:
                    entity.pop(field, None)
                    changed = True

        return changed

    def _serializable_data(self, data):
        cleaned = []

        for entity in data:
            if not isinstance(entity, dict):
                cleaned.append(entity)
                continue

            cleaned.append({
                key: value
                for key, value in entity.items()
                if not str(key).startswith("_")
            })

        return cleaned

    def _save_dataset_file(self, file, data):
        data = self._serializable_data(data)

        with file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def load_datasets(self):
        """
        Load all entity datasets.

        Behavior
        --------
        * Uses the ontology by default.
        * For explicit compatibility imports, recurses through a JSON directory.
        * Treats files inside a locations/ subdirectory as one logical dataset
          named 'locations'.
        """
        self.datasets = {}
        self.entity_aliases = {}
        self._dataset_file_records = []

        if self.use_ontology:
            if not self.ontology_path.exists():
                raise FileNotFoundError(
                    f"Ontology repository not found: {self.ontology_path}. "
                    "Create ontology/index0.owl before starting the app."
                )
            self.load_ontology_datasets()
            return

        if not self.entries_directory.exists():
            logger.warning("Entries path does not exist: %s", self.entries_directory)
            return

        files = sorted(
            [
                p for p in self.entries_directory.rglob("*")
                if p.is_file() and p.suffix.lower() == ".json"
            ]
        )

        for file in files:
            rel_parts = file.relative_to(self.entries_directory).parts

            # Compatibility rule:
            # locations/*.json -> one logical dataset named "locations"
            if len(rel_parts) >= 2 and rel_parts[0] == "locations":
                dataset_name = "locations"
            else:
                dataset_name = file.stem

            try:
                with file.open("r", encoding="utf-8") as f:
                    data = json.load(f) or []

                if not isinstance(data, list):
                    logger.warning("Dataset file is not a list: %s", file)
                    continue

                changed = False
                for entity in data:
                    if isinstance(entity, dict):
                        changed = self._ensure_standard_relations(entity, dataset_name=dataset_name) or changed

                self._dataset_file_records.append({
                    "file": file,
                    "data": data,
                    "changed": changed,
                })

                if dataset_name not in self.datasets:
                    self.datasets[dataset_name] = []

                for entity in data:
                    if isinstance(entity, dict):
                        entity["_dataset"] = dataset_name
                        self.datasets[dataset_name].append(entity)

                logger.debug(
                    "Loaded dataset %s from %s | entities=%d",
                    dataset_name,
                    file,
                    len(data),
                )

            except Exception as exc:
                logger.exception("Failed to load dataset from %s: %s", file, exc)

        self._fold_system_entities_into_locations()
        self._fold_spatial_features_into_locations()

    def load_ontology_datasets(self):
        self._persistent_store = PersistentOntologyStore(self.ontology_path)
        self.datasets = self._persistent_store.load_datasets()
        # RDF multi-value properties do not preserve insertion order. Stellar
        # neighbourhoods are a set semantically, but the UI and repository
        # snapshots need a stable presentation order after migrations.
        for entity in self.datasets.get("locations", []):
            rows = entity.get("stellar_neighbours") if isinstance(entity, dict) else None
            if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                entity["stellar_neighbours"] = sorted(
                    rows,
                    key=lambda row: (
                        str(row.get("system") or ""),
                        float(row.get("distance_ly", 0.0) or 0.0),
                    ),
                )
        self._reconcile_deletion_overrides()
        self._apply_palette_overrides()
        palette_overrides = self._load_palette_overrides()
        if palette_overrides:
            changed_entities = [
                entity
                for entity_id in palette_overrides
                for entity in [next(
                    (
                        candidate
                        for dataset in self.datasets.values()
                        for candidate in (dataset or [])
                        if isinstance(candidate, dict) and str(candidate.get("id")) == str(entity_id)
                    ),
                    None,
                )]
                if entity is not None
            ]
            if changed_entities and self._persistent_store.persist_entities(changed_entities):
                self._clear_palette_overrides()

    # --------------------------------------------------

    def _relation_ids(self, value):
        if isinstance(value, str):
            stripped = value.strip()
            return [stripped] if stripped else []
        if isinstance(value, dict):
            entity_id = str(value.get("id") or "").strip()
            return [entity_id] if entity_id else []
        if isinstance(value, list):
            ids = []
            for item in value:
                for entity_id in self._relation_ids(item):
                    if entity_id not in ids:
                        ids.append(entity_id)
            return ids
        return []

    def _parent_ids_for_entity(self, entity):
        parent_ids = self._relation_ids(entity.get("parents", entity.get("parent_ideas", [])))
        if entity.get("type") == "idea":
            for entity_id in self._relation_ids(entity.get("parent_entity")):
                if entity_id not in parent_ids:
                    parent_ids.append(entity_id)
        return [
            parent_id
            for parent_id in parent_ids
            if parent_id in self.entities
        ]

    def _build_offspring_tree(self, entity_id, children_by_parent, ancestry=None):
        ancestry = set(ancestry or [])
        if entity_id in ancestry:
            return []

        next_ancestry = set(ancestry)
        next_ancestry.add(entity_id)
        nodes = []

        for child_id in children_by_parent.get(entity_id, []):
            node = {"id": child_id}
            child_offspring = self._build_offspring_tree(
                child_id,
                children_by_parent,
                ancestry=next_ancestry,
            )
            if child_offspring:
                node["offspring"] = child_offspring
            nodes.append(node)

        return nodes

    def populate_offspring(self):
        children_by_parent = {}
        for entity_id, entity in self.entities.items():
            for parent_id in self._parent_ids_for_entity(entity):
                children = children_by_parent.setdefault(parent_id, [])
                if entity_id not in children:
                    children.append(entity_id)

        changed_entities = set()

        for entity_id, entity in self.entities.items():
            offspring = self._build_offspring_tree(entity_id, children_by_parent)
            if entity.get("offspring") != offspring:
                entity["offspring"] = offspring
                changed_entities.add(entity_id)

        return changed_entities

    def populate_employment_rosters(self):
        """Derive each employer's employed_people roster from person-side
        is_employed_by references -- the same reciprocal-projection pattern
        as populate_offspring()/parent_location, so employment is a plain
        relationship (person authors is_employed_by once) rather than a
        mediating employment entity that both sides have to keep in sync."""
        people_by_employer = {}
        for entity_id, entity in self.entities.items():
            if entity.get("_dataset") != "people" and entity.get("type") != "person":
                continue
            for employer_id in self._relation_ids(entity.get("is_employed_by")):
                roster = people_by_employer.setdefault(employer_id, [])
                if entity_id not in roster:
                    roster.append(entity_id)

        changed_entities = set()
        for entity_id, entity in self.entities.items():
            roster = people_by_employer.get(entity_id, [])
            if entity.get("employed_people") != roster:
                entity["employed_people"] = roster
                changed_entities.add(entity_id)

        return changed_entities

    def populate_category_members(self):
        """Derive each category's ``members`` list from every item/component's
        ``categories`` relation -- the same reciprocal-projection pattern as
        populate_offspring()/populate_employment_rosters(), so an item authors
        its categories once rather than both sides keeping a link in sync."""
        members_by_category = {}
        for entity_id, entity in self.entities.items():
            for category_id in self._relation_ids(entity.get("categories")):
                roster = members_by_category.setdefault(category_id, [])
                if entity_id not in roster:
                    roster.append(entity_id)

        changed_entities = set()
        for entity_id, entity in self.entities.items():
            if entity.get("_dataset") != "categories" and entity.get("type") != "category":
                continue
            members = members_by_category.get(entity_id, [])
            if entity.get("members") != members:
                entity["members"] = members
                changed_entities.add(entity_id)

        return changed_entities

    def save_changed_dataset_files(self, changed_entity_ids=None):
        if self.use_ontology:
            changed_entity_ids = set(changed_entity_ids or [])
            entities = [
                self.entities[entity_id]
                for entity_id in changed_entity_ids
                if entity_id in self.entities
            ]
            if entities:
                self._persistent_store.persist_entities(entities)
            return

        changed_entity_ids = set(changed_entity_ids or [])

        for record in self._dataset_file_records:
            changed = record.get("changed", False)

            if not changed:
                for entity in record["data"]:
                    if isinstance(entity, dict) and entity.get("id") in changed_entity_ids:
                        changed = True
                        break

            if changed:
                self._save_dataset_file(record["file"], record["data"])

    def save_ontology_file(self, progress_callback=None):
        if self._persistent_store is None:
            self._persistent_store = PersistentOntologyStore(self.ontology_path)
        self._persistent_store.export_rdfxml(
            self.ontology_path,
            progress_callback=progress_callback,
        )
        self._clear_palette_overrides()

    def export_ontology_checkpoint(self, progress_callback=None):
        self.save_ontology_file(progress_callback=progress_callback)
        return True

    def reimport_ontology_checkpoint(self):
        if self._persistent_store is None:
            self._persistent_store = PersistentOntologyStore(self.ontology_path)
        self._persistent_store.reimport_rdfxml()
        self.refresh()
        return True

    def persist_entity(self, entity, previous_entity_id=None):
        if not isinstance(entity, dict):
            return False

        entity_id = str(entity.get("id") or "").strip()
        if not entity_id:
            return False

        previous_entity_id = str(previous_entity_id or "").strip()
        if previous_entity_id and previous_entity_id != entity_id:
            self.entities.pop(previous_entity_id, None)
            for dataset in self.datasets.values():
                if not isinstance(dataset, list):
                    continue
                dataset[:] = [
                    item
                    for item in dataset
                    if not (isinstance(item, dict) and item.get("id") == previous_entity_id)
                ]

        dataset_name = str(entity.get("_dataset") or entity.get("type") or "entries").strip() or "entries"
        entity["_dataset"] = dataset_name
        dataset = self.datasets.setdefault(dataset_name, [])
        for index, existing in enumerate(dataset):
            if isinstance(existing, dict) and existing.get("id") == entity_id:
                dataset[index] = entity
                break
        else:
            dataset.append(entity)

        self.entities[entity_id] = entity
        catalogued = getattr(getattr(self, "plant_catalogue", None), "entity_ids", ())
        if (dataset_name in {"species", "cladistics"}
            or entity_id in catalogued or previous_entity_id in catalogued):
            self.rebuild_plant_catalogue()
        if self.use_ontology:
            try:
                if self._persistent_store is None:
                    self._persistent_store = PersistentOntologyStore(self.ontology_path)
                persisted = self._persistent_store.persist_entity(
                    entity,
                    previous_entity_id=previous_entity_id,
                )
            except (OSError, sqlite3.Error) as exc:
                logger.error("Could not persist entity %s to ontology: %s", entity_id, exc)
                return False
            if persisted:
                self._clear_entity_deletion(entity_id)
                if previous_entity_id:
                    self._clear_entity_deletion(previous_entity_id)
        return True

    def persist_entity_palette(self, entity):
        """Journal palette literals atomically without rebuilding the full OWL graph."""
        if not self.use_ontology or not isinstance(entity, dict):
            return False
        entity_id = str(entity.get("id") or "").strip()
        if not entity_id or not self.ontology_path:
            return False
        if getattr(self, "_persistent_store", None) is not None:
            try:
                return self._persistent_store.persist_entity_fields(entity, self.FAST_PALETTE_FIELDS)
            except (OSError, sqlite3.Error) as exc:
                # Keep color editing durable even if another application
                # instance temporarily owns the ontology writer. The journal
                # is merged on load and cleared after the next OWL export.
                logger.warning(
                    "Ontology busy while persisting palette for %s; using override journal: %s",
                    entity_id,
                    exc,
                )
        overrides = self._load_palette_overrides()
        overrides[entity_id] = {
            field_name: (
                None if entity.get(field_name) in (None, "", [], {}) else entity.get(field_name)
            )
            for field_name in sorted(self.FAST_PALETTE_FIELDS)
        }
        path = self._palette_overrides_path()
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(overrides, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(path)
        except OSError:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True

    def persist_entity_fields(self, entity, field_names):
        """Persist only changed fields when the backing store supports point edits."""
        if not isinstance(entity, dict):
            return False
        entity_id = str(entity.get("id") or "").strip()
        field_names = {
            str(field_name)
            for field_name in (field_names or [])
            if str(field_name) and not str(field_name).startswith("_")
        }
        if not entity_id or not field_names:
            return False

        if not self.use_ontology:
            self.save_changed_dataset_files({entity_id})
            if field_names & {"parents","type","_dataset"}:
                self.entities[entity_id] = entity
                self.rebuild_plant_catalogue()
            return True

        try:
            if self._persistent_store is None:
                self._persistent_store = PersistentOntologyStore(self.ontology_path)
            persisted = self._persistent_store.persist_entity_fields(
                entity,
                field_names,
            )
        except (OSError, sqlite3.Error) as exc:
            logger.error(
                "Could not persist fields %s for entity %s: %s",
                sorted(field_names),
                entity_id,
                exc,
            )
            return False
        if persisted:
            self._clear_entity_deletion(entity_id)
            if field_names & {"parents","type","_dataset"}:
                self.entities[entity_id] = entity
                self.rebuild_plant_catalogue()
        return persisted

    def _palette_overrides_path(self):
        ontology_path = Path(self.ontology_path).resolve()
        return ontology_path.parent.parent / ".cache" / "ontology" / f"{ontology_path.name}.palette-overrides.json"

    def _load_palette_overrides(self):
        try:
            data = json.loads(self._palette_overrides_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _apply_palette_overrides(self):
        overrides = self._load_palette_overrides()
        if not overrides:
            return
        entities = {
            str(entity.get("id")): entity
            for dataset in self.datasets.values()
            for entity in (dataset or [])
            if isinstance(entity, dict) and entity.get("id")
        }
        for entity_id, fields in overrides.items():
            entity = entities.get(str(entity_id))
            if not isinstance(entity, dict) or not isinstance(fields, dict):
                continue
            for field_name, value in fields.items():
                if field_name not in self.FAST_PALETTE_FIELDS:
                    continue
                if value is None:
                    entity.pop(field_name, None)
                else:
                    entity[field_name] = value

    def _clear_palette_overrides(self):
        try:
            self._palette_overrides_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _deletion_overrides_path(self):
        ontology_path = Path(self.ontology_path).resolve()
        return (
            ontology_path.parent.parent
            / ".cache"
            / "ontology"
            / f"{ontology_path.name}.deleted-entities.json"
        )

    def _load_deletion_overrides(self):
        try:
            payload = json.loads(
                self._deletion_overrides_path().read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return set()
        if isinstance(payload, dict):
            payload = payload.get("entity_ids") or []
        if not isinstance(payload, list):
            return set()
        return {
            str(entity_id).strip()
            for entity_id in payload
            if str(entity_id).strip()
        }

    def _write_deletion_overrides(self, entity_ids):
        entity_ids = sorted({
            str(entity_id).strip()
            for entity_id in (entity_ids or [])
            if str(entity_id).strip()
        })
        path = self._deletion_overrides_path()
        if not entity_ids:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                return False
            return True
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(
                    {"version": 1, "entity_ids": entity_ids},
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(path)
        except OSError:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True

    def _journal_entity_deletion(self, entity_id):
        entity_ids = self._load_deletion_overrides()
        entity_ids.add(str(entity_id))
        return self._write_deletion_overrides(entity_ids)

    def _clear_entity_deletion(self, entity_id):
        entity_ids = self._load_deletion_overrides()
        entity_ids.discard(str(entity_id))
        return self._write_deletion_overrides(entity_ids)

    def _apply_deletion_overrides(self, entity_ids=None):
        entity_ids = set(entity_ids or self._load_deletion_overrides())
        if not entity_ids:
            return
        for dataset in self.datasets.values():
            if not isinstance(dataset, list):
                continue
            dataset[:] = [
                entity
                for entity in dataset
                if not (
                    isinstance(entity, dict)
                    and str(entity.get("id") or "") in entity_ids
                )
            ]

    def _reconcile_deletion_overrides(self):
        entity_ids = self._load_deletion_overrides()
        if not entity_ids:
            return
        loaded_ids = {
            str(entity.get("id") or "")
            for dataset in self.datasets.values()
            for entity in (dataset or [])
            if isinstance(entity, dict)
        }
        reconciled = set()
        for entity_id in entity_ids:
            if entity_id not in loaded_ids:
                reconciled.add(entity_id)
                continue
            try:
                self._persistent_store.remove_entity(entity_id)
            except (OSError, sqlite3.Error) as exc:
                logger.warning(
                    "Ontology remains busy while reconciling deletion for %s: %s",
                    entity_id,
                    exc,
                )
            else:
                reconciled.add(entity_id)
        self._apply_deletion_overrides(entity_ids)
        if reconciled:
            self._write_deletion_overrides(entity_ids - reconciled)

    def set_literal(self, entity_id, field_name, value, persist=True):
        # Point edits must share the live projection. Deep-copying the full
        # repository here also copies generated maps and can take many seconds.
        repository = OntologyRepository(self.datasets, copy_datasets=False)
        changed_entity_ids = repository.set_literal(entity_id, field_name, value)
        return self._apply_repository_mutation(repository, changed_entity_ids, persist=persist)

    def set_relation(self, source_id, field_name, target_id, reciprocal_field=None, persist=True):
        repository = OntologyRepository(self.datasets, copy_datasets=False)
        changed_entity_ids = repository.set_relation(
            source_id,
            field_name,
            target_id,
            reciprocal_field=reciprocal_field,
        )
        return self._apply_repository_mutation(repository, changed_entity_ids, persist=persist)

    def remove_relation(self, source_id, field_name, target_id, reciprocal_field=None, persist=True):
        repository = OntologyRepository(self.datasets, copy_datasets=False)
        changed_entity_ids = repository.remove_relation(
            source_id,
            field_name,
            target_id,
            reciprocal_field=reciprocal_field,
        )
        return self._apply_repository_mutation(repository, changed_entity_ids, persist=persist)

    def _apply_repository_mutation(self, repository, changed_entity_ids, persist=True):
        changed_entity_ids = set(changed_entity_ids or [])
        if not changed_entity_ids:
            return set()

        self.datasets = repository.datasets
        self.build_entity_index()
        changed_entity_ids.update(self.populate_offspring())
        changed_entity_ids.update(self.populate_employment_rosters())
        changed_entity_ids.update(self.populate_category_members())
        self.build_reference_graph()
        if persist:
            self.save_changed_dataset_files(changed_entity_ids)
        return changed_entity_ids

    def remove_entity(self, entity_id, dataset_name=None):
        entity_id = str(entity_id or "").strip()
        if not entity_id:
            return False

        target_datasets = (
            [dataset_name]
            if dataset_name
            else list(self.datasets.keys())
        )
        removed = entity_id in self.entities
        for candidate_name in target_datasets:
            dataset = self.datasets.get(candidate_name)
            if isinstance(dataset, list) and any(
                isinstance(item, dict) and item.get("id") == entity_id
                for item in dataset
            ):
                removed = True
                break
        if not removed:
            return False

        if self.use_ontology:
            if self._persistent_store is None:
                self._persistent_store = PersistentOntologyStore(self.ontology_path)
            try:
                self._persistent_store.remove_entity(entity_id)
            except (OSError, sqlite3.Error) as exc:
                if not self._journal_entity_deletion(entity_id):
                    logger.error(
                        "Could not delete entity %s or journal its deletion: %s",
                        entity_id,
                        exc,
                    )
                    return False
                logger.warning(
                    "Ontology busy while deleting %s; using deletion journal: %s",
                    entity_id,
                    exc,
                )
            else:
                self._clear_entity_deletion(entity_id)

        self.entities.pop(entity_id, None)
        self.rebuild_plant_catalogue()
        for candidate_name in target_datasets:
            dataset = self.datasets.get(candidate_name)
            if not isinstance(dataset, list):
                continue
            before_count = len(dataset)
            dataset[:] = [
                item
                for item in dataset
                if not (isinstance(item, dict) and item.get("id") == entity_id)
            ]
            removed = removed or len(dataset) != before_count

        return removed

    # --------------------------------------------------

    def build_entity_index(self):

        self.entities = {}

        for dataset in self.datasets.values():
            for entity in dataset:
                if not isinstance(entity, dict):
                    continue

                entity_id = entity.get("id")
                if not entity_id:
                    continue

                self.entities[entity_id] = entity
                legacy_system_entity_id = entity.get("legacy_system_entity_id")
                if legacy_system_entity_id:
                    self.entity_aliases[str(legacy_system_entity_id)] = entity_id

        logger.info("Total entities loaded: %s", len(self.entities))
        self.rebuild_plant_catalogue()

    def rebuild_plant_catalogue(self):
        self.plant_catalogue = PlantCatalogue.build(self.entities)
        return self.plant_catalogue

    # --------------------------------------------------

    def build_reference_graph(self):

        self.edges = {}

        for entity_id, entity in self.entities.items():

            self.edges[entity_id] = []

            values = (
                entity.loaded_values()
                if hasattr(entity, "loaded_values")
                else entity.values()
            )
            for value in values:

                if isinstance(value, str):

                    if value in self.entities:
                        self.edges[entity_id].append(value)

                elif isinstance(value, list):

                    for item in value:

                        if isinstance(item, str) and item in self.entities:
                            self.edges[entity_id].append(item)

    # --------------------------------------------------

    def refresh(self, auto_save_normalized=None):
        """
        Reload repository entities and rebuild runtime indexes.

        Normalization still happens in memory so UI/runtime code can rely on
        standard fields. Writing those normalization changes back to disk is
        opt-in, because constructing or refreshing a world model should not
        mutate repository files by surprise.
        """
        if auto_save_normalized is None:
            auto_save_normalized = self.auto_save_normalized

        self.load_datasets()
        self.build_entity_index()
        changed_entity_ids = self.populate_offspring()
        changed_entity_ids.update(self.populate_employment_rosters())
        changed_entity_ids.update(self.populate_category_members())
        if auto_save_normalized:
            self.save_changed_dataset_files(changed_entity_ids)
        self.build_reference_graph()

    # --------------------------------------------------

    def get(self, entity_id):
        if entity_id in self.entities:
            return self.entities.get(entity_id)

        canonical_id = self.entity_aliases.get(entity_id)
        if canonical_id:
            return self.entities.get(canonical_id)

        return None

    def get_dataset(self, dataset_name):

        return self.datasets.get(dataset_name, [])

    def get_connections(self, entity_id):

        return self.edges.get(entity_id, [])

    # --------------------------------------------------

    def print_summary(self):

        print("\nIndex_0 Database Summary\n")

        for dataset, data in self.datasets.items():
            print(f"{dataset}: {len(data)} entities")

        print(f"\nTotal entities: {len(self.entities)}")
