"""Repository boundary for the sole durable entity and semantic authority.

All entity identity and ontological/semantic information belongs in the
ontology; returned mappings are disposable projections. No generated planets
are currently intended to persist, so worldgen model changes may invalidate
their derived products without compatibility migration.
"""

import copy
import json
import logging
import os
import pickle
import re
import shutil
import time
import types
import uuid
from pathlib import Path
from urllib.parse import quote, unquote


BASE_IRI = "https://index0.local/ontology.owl#"
ENTITY_IRI = "https://index0.local/entity/"
logger = logging.getLogger(__name__)


class OntologyDependencyError(RuntimeError):
    pass


class OntologyRepository:
    """
    Owlready2-backed bridge for the current entry repository.

    The current UI still expects loader.datasets and loader.entities style
    dictionaries, so this class keeps a projection while building a real OWL
    ontology for semantic storage and inference.
    """

    SPECIAL_OBJECT_PROPERTIES = {
        "parents": "hasParent",
        "related": "relatedTo",
    }
    SYMMETRIC_RELATION_FIELDS = {
        "related",
    }

    DERIVED_FIELDS = {
        "offspring",
    }

    DATASET_CACHE_VERSION = 1
    _memory_dataset_cache = {}

    def __init__(self, datasets=None, *, copy_datasets=True):
        self.datasets = copy.deepcopy(datasets or {}) if copy_datasets else (datasets or {})
        self.entities = {}
        self._build_index()

    @classmethod
    def from_loader(cls, loader):
        return cls(getattr(loader, "datasets", {}) or {})

    @classmethod
    def from_owl(cls, path):
        path = Path(path).resolve()
        signature = cls._source_signature(path)
        cached_datasets = cls._memory_dataset_cache.get(signature)
        if cached_datasets is not None:
            return cls(cached_datasets)
        cached_datasets = cls._read_dataset_cache(path, signature)
        if cached_datasets is not None:
            # The cache payload has just been deserialized and is private to
            # this repository. Adopting it avoids a full copy of every stored
            # generated heightmap during startup.
            return cls(cached_datasets, copy_datasets=False)

        repository = cls({})
        ontology = repository._load_ontology(path)
        datasets = repository._datasets_from_ontology(ontology)
        materialized = cls(datasets).materialized_repository()
        cls._memory_dataset_cache[signature] = materialized.datasets
        cls._write_dataset_cache(path, signature, materialized.datasets)
        return materialized

    @classmethod
    def _source_signature(cls, path):
        stat = Path(path).stat()
        return (cls.DATASET_CACHE_VERSION, str(Path(path).resolve()), int(stat.st_size), int(stat.st_mtime_ns))

    @classmethod
    def _dataset_cache_path(cls, path):
        path = Path(path).resolve()
        return path.parent.parent / ".cache" / "ontology" / f"{path.name}.datasets-v{cls.DATASET_CACHE_VERSION}.pickle"

    @classmethod
    def _read_dataset_cache(cls, path, signature):
        cache_path = cls._dataset_cache_path(path)
        try:
            with cache_path.open("rb") as handle:
                payload = pickle.load(handle)
            if payload.get("signature") != list(signature):
                return None
            datasets = payload.get("datasets")
            return datasets if isinstance(datasets, dict) else None
        except (OSError, ValueError, TypeError, pickle.PickleError, EOFError):
            return None

    @classmethod
    def _write_dataset_cache(cls, path, signature, datasets):
        cache_path = cls._dataset_cache_path(path)
        temp_path = cache_path.with_name(f".{cache_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("wb") as handle:
                pickle.dump(
                    {"signature": list(signature), "datasets": datasets},
                    handle,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            temp_path.replace(cache_path)
        except (OSError, TypeError, ValueError) as exc:
            logger.debug("Could not write ontology dataset cache %s: %s", cache_path, exc)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _build_index(self):
        self.entities = {}
        for dataset_name, entries in self.datasets.items():
            if not isinstance(entries, list):
                continue
            for entity in entries:
                if not isinstance(entity, dict):
                    continue
                entity_id = str(entity.get("id") or "").strip()
                if not entity_id:
                    continue
                entity.setdefault("_dataset", dataset_name)
                self.entities[entity_id] = entity

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return self.datasets.get(dataset_name, [])

    def set_literal(self, entity_id, field_name, value):
        entity = self.entities.get(str(entity_id or "").strip())
        field_name = str(field_name or "").strip()
        if not isinstance(entity, dict) or not field_name or field_name in {"id", "_dataset"}:
            return set()
        if entity.get(field_name) == value:
            return set()
        entity[field_name] = value
        return {str(entity.get("id"))}

    def set_relation(self, source_id, field_name, target_id, reciprocal_field=None):
        source_id = str(source_id or "").strip()
        target_id = str(target_id or "").strip()
        field_name = str(field_name or "").strip()
        reciprocal_field = str(reciprocal_field or "").strip()
        if not source_id or not target_id or not field_name:
            return set()
        source = self.entities.get(source_id)
        target = self.entities.get(target_id)
        if not isinstance(source, dict) or not isinstance(target, dict) or source_id == target_id:
            return set()

        changed = set()
        if self._add_relation_id(source, field_name, target_id):
            changed.add(source_id)
        reciprocal_field = reciprocal_field or (
            field_name if field_name in self.SYMMETRIC_RELATION_FIELDS else ""
        )
        if reciprocal_field and self._add_relation_id(target, reciprocal_field, source_id):
            changed.add(target_id)
        return changed

    def remove_relation(self, source_id, field_name, target_id, reciprocal_field=None):
        source_id = str(source_id or "").strip()
        target_id = str(target_id or "").strip()
        field_name = str(field_name or "").strip()
        reciprocal_field = str(reciprocal_field or "").strip()
        if not source_id or not target_id or not field_name:
            return set()

        changed = set()
        source = self.entities.get(source_id)
        if isinstance(source, dict) and self._remove_relation_id(source, field_name, target_id):
            changed.add(source_id)
        target = self.entities.get(target_id)
        reciprocal_field = reciprocal_field or (
            field_name if field_name in self.SYMMETRIC_RELATION_FIELDS else ""
        )
        if reciprocal_field and isinstance(target, dict) and self._remove_relation_id(target, reciprocal_field, source_id):
            changed.add(target_id)
        return changed

    def _set_relation_ids(self, entity, field_name, relation_ids):
        normalized = []
        entity_id = str(entity.get("id") or "")
        for relation_id in relation_ids or []:
            relation_id = str(relation_id or "").strip()
            if relation_id and relation_id != entity_id and relation_id not in normalized:
                normalized.append(relation_id)
        if entity.get(field_name) == normalized:
            return False
        entity[field_name] = normalized
        return True

    def _add_relation_id(self, entity, field_name, target_id):
        relation_ids = self._relation_ids(entity.get(field_name))
        if target_id in relation_ids:
            return False
        relation_ids.append(target_id)
        return self._set_relation_ids(entity, field_name, relation_ids)

    def _remove_relation_id(self, entity, field_name, target_id):
        relation_ids = self._relation_ids(entity.get(field_name))
        if target_id not in relation_ids and field_name not in entity:
            return False
        return self._set_relation_ids(
            entity,
            field_name,
            [relation_id for relation_id in relation_ids if relation_id != target_id],
        )

    def materialized_datasets(self):
        datasets = copy.deepcopy(self.datasets)
        projected = OntologyRepository(datasets)
        projected.materialize_inverse_relations()
        return projected.datasets

    def materialized_entities(self):
        datasets = self.materialized_datasets()
        projected = OntologyRepository(datasets)
        return projected.entities

    def materialized_repository(self):
        return OntologyRepository(self.materialized_datasets())

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
        parent_ids = self._relation_ids(entity.get("parents"))
        parent_entity = entity.get("parent_entity")
        if entity.get("type") == "idea":
            for entity_id in self._relation_ids(parent_entity):
                if entity_id not in parent_ids:
                    parent_ids.append(entity_id)
        return parent_ids

    def _build_offspring_tree(self, entity_id, children_by_parent, ancestry=None):
        ancestry = set(ancestry or [])
        if entity_id in ancestry:
            return []

        next_ancestry = set(ancestry)
        next_ancestry.add(entity_id)
        offspring = []
        for child_id in children_by_parent.get(entity_id, []):
            node = {"id": child_id}
            child_offspring = self._build_offspring_tree(
                child_id,
                children_by_parent,
                ancestry=next_ancestry,
            )
            if child_offspring:
                node["offspring"] = child_offspring
            offspring.append(node)
        return offspring

    def materialize_inverse_relations(self):
        self._materialize_symmetric_relations()

        children_by_parent = {}
        for entity_id, entity in self.entities.items():
            for parent_id in self._parent_ids_for_entity(entity):
                if parent_id not in self.entities:
                    continue
                children_by_parent.setdefault(parent_id, [])
                if entity_id not in children_by_parent[parent_id]:
                    children_by_parent[parent_id].append(entity_id)

        for entity_id, entity in self.entities.items():
            entity["offspring"] = self._build_offspring_tree(entity_id, children_by_parent)

    def _materialize_symmetric_relations(self):
        for field_name in self.SYMMETRIC_RELATION_FIELDS:
            pairs = []
            for entity_id, entity in self.entities.items():
                for target_id in self._relation_ids(entity.get(field_name)):
                    if target_id in self.entities and target_id != entity_id:
                        pairs.append((entity_id, target_id))

            for source_id, target_id in pairs:
                self._add_relation_id(self.entities[target_id], field_name, source_id)

    def build_ontology(self, iri=BASE_IRI):
        owlready2 = self._import_owlready2()
        world = owlready2.World()
        onto = world.get_ontology(iri)

        with onto:
            class Entry(owlready2.Thing):
                pass

            class Dataset(owlready2.Thing):
                pass

            class hasParent(owlready2.ObjectProperty):
                pass

            class hasOffspring(owlready2.ObjectProperty):
                inverse_property = hasParent

            hasParent.inverse_property = hasOffspring

            class relatedTo(owlready2.ObjectProperty, owlready2.SymmetricProperty):
                pass

            class hasAncestor(owlready2.ObjectProperty, owlready2.TransitiveProperty):
                pass

            class hasDescendant(owlready2.ObjectProperty, owlready2.TransitiveProperty):
                pass

            class entryId(owlready2.DataProperty):
                pass

            class datasetName(owlready2.DataProperty):
                pass

            class entityType(owlready2.DataProperty):
                pass

            class listFieldName(owlready2.DataProperty):
                pass

            class jsonFieldName(owlready2.DataProperty):
                pass

        object_properties = self._create_object_properties(onto)
        type_classes = self._create_type_classes(onto, Entry)
        field_properties = self._create_field_properties(onto, object_properties)
        individuals = self._create_individuals(onto, Entry, type_classes)
        self._assign_data_properties(individuals, field_properties)
        self._assign_object_properties(individuals, object_properties)
        return onto

    def save_owl(self, path, iri=BASE_IRI, file_format="rdfxml"):
        path = Path(str(path).strip().strip('"')).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        ontology = self.build_ontology(iri=iri)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        last_error = None
        for attempt in range(5):
            try:
                ontology.save(file=str(temp_path), format=file_format)
                break
            except OSError as exc:
                last_error = exc
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                if attempt == 4:
                    raise
                time.sleep(0.12 * (attempt + 1))
        else:
            if last_error is not None:
                raise last_error

        replace_error = None
        for attempt in range(24):
            try:
                temp_path.replace(path)
                replace_error = None
                break
            except OSError as exc:
                replace_error = exc
                time.sleep(min(0.75, 0.08 * (attempt + 1)))

        if replace_error is not None:
            logger.warning(
                "Atomic ontology replacement remained locked; using protected in-place update for %s",
                path,
            )
            self._replace_locked_ontology_in_place(temp_path, path)

        signature = self._source_signature(path)
        # The cache is a loader projection, so it must contain the same
        # inverse/symmetric relations that reading the RDF graph would
        # materialize.  Caching raw authored rows made a fresh save behave
        # differently from a cache miss.
        self._write_dataset_cache(
            path,
            signature,
            self.materialized_repository().datasets,
        )

    def _replace_locked_ontology_in_place(self, temp_path, path):
        """Safely overwrite a Windows-locked target while retaining a rollback copy."""
        temp_path = Path(temp_path).resolve()
        path = Path(path).resolve()
        if temp_path.parent != path.parent:
            raise OSError("Ontology replacement files must share a directory")
        backup_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.rollback")
        backup_created = False
        try:
            if path.exists():
                shutil.copyfile(path, backup_path)
                backup_created = True
            expected_size = temp_path.stat().st_size
            with temp_path.open("rb") as source, path.open("wb") as target:
                shutil.copyfileobj(source, target, length=4 * 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            if path.stat().st_size != expected_size:
                raise OSError("Ontology replacement size verification failed")
            temp_path.unlink(missing_ok=True)
            if backup_created:
                backup_path.unlink(missing_ok=True)
        except OSError:
            if backup_created and backup_path.exists():
                try:
                    with backup_path.open("rb") as source, path.open("wb") as target:
                        shutil.copyfileobj(source, target, length=4 * 1024 * 1024)
                        target.flush()
                        os.fsync(target.fileno())
                    backup_path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Ontology rollback retained at %s", backup_path)
            raise
        finally:
            temp_path.unlink(missing_ok=True)

    def _create_type_classes(self, onto, Entry):
        type_classes = {}
        for type_name in sorted(self._entity_type_names()):
            class_name = self._owl_name(f"{type_name}_entry")
            with onto:
                type_classes[type_name] = types.new_class(class_name, (Entry,))
        return type_classes

    def _entity_type_names(self):
        names = {
            str(entity.get("type") or "entity").strip()
            for entity in self.entities.values()
            if str(entity.get("type") or "").strip()
        }
        return names or {"entity"}

    def _create_object_properties(self, onto):
        owlready2 = self._import_owlready2()
        properties = {}
        for field_name, property_name in sorted(self._object_property_names().items()):
            if property_name in properties.values():
                continue
            existing_property = getattr(onto, property_name, None)
            if existing_property is not None:
                properties[field_name] = existing_property
                continue
            with onto:
                properties[field_name] = types.new_class(property_name, (owlready2.ObjectProperty,))
        return properties

    def _object_property_names(self):
        names = {}
        for field_name in self._object_relation_fields():
            names[field_name] = self.SPECIAL_OBJECT_PROPERTIES.get(
                field_name,
                self._relation_property_name(field_name),
            )
        return names

    def _object_relation_fields(self):
        fields = set()
        for entity in self.entities.values():
            for field_name, value in entity.items():
                if field_name in {"id", "_dataset"} or field_name in self.DERIVED_FIELDS:
                    continue
                if str(field_name).startswith("_"):
                    continue
                if self._object_relation_ids_for_field(field_name, value):
                    fields.add(field_name)
        fields.update(self.SPECIAL_OBJECT_PROPERTIES)
        return fields

    def _create_field_properties(self, onto, object_properties):
        owlready2 = self._import_owlready2()
        properties = {}
        field_names = sorted({
            key
            for entity in self.entities.values()
            for key in entity
            if key not in {"id", "_dataset"}
            and key not in object_properties
            and key not in self.DERIVED_FIELDS
            and not str(key).startswith("_")
        })

        for field_name in field_names:
            property_name = self._field_property_name(field_name)
            with onto:
                properties[field_name] = types.new_class(property_name, (owlready2.DataProperty,))
        return properties

    def _create_individuals(self, onto, Entry, type_classes):
        individuals = {}
        for entity_id, entity in sorted(self.entities.items()):
            type_name = str(entity.get("type") or "entity").strip() or "entity"
            entity_class = type_classes.get(type_name, Entry)
            individual = entity_class(self._individual_name(entity_id))
            individual.iri = f"{ENTITY_IRI}{quote(entity_id, safe='')}"
            individual.entryId.append(entity_id)
            individual.datasetName.append(str(entity.get("_dataset") or ""))
            individual.entityType.append(type_name)
            individuals[entity_id] = individual
        return individuals

    def _assign_data_properties(self, individuals, field_properties):
        for entity_id, entity in self.entities.items():
            individual = individuals.get(entity_id)
            if individual is None:
                continue

            for field_name, value in entity.items():
                property_class = field_properties.get(field_name)
                if property_class is None:
                    continue
                if isinstance(value, list):
                    individual.listFieldName.append(field_name)
                if self._field_uses_json(value):
                    individual.jsonFieldName.append(field_name)
                for data_value in self._data_values(value):
                    getattr(individual, property_class.python_name).append(data_value)

    def _assign_object_properties(self, individuals, object_properties):
        for entity_id, entity in self.entities.items():
            individual = individuals.get(entity_id)
            if individual is None:
                continue

            for field_name, value in entity.items():
                property_class = object_properties.get(field_name)
                if property_class is None:
                    continue
                if isinstance(value, list):
                    individual.listFieldName.append(field_name)
                targets = getattr(individual, property_class.python_name)
                for target_id in self._object_relation_ids_for_field(field_name, value):
                    target = individuals.get(target_id)
                    if target is not None and target not in targets:
                        targets.append(target)

    def _data_values(self, value):
        if value in (None, "", []):
            return []
        if isinstance(value, (str, int, float, bool)):
            return [value]
        if isinstance(value, list):
            # RDF data-property values are an unordered set: repeated values
            # are collapsed and channel/order semantics are lost.  Persist a
            # data list as one JSON literal so RGB triples, coordinate arrays,
            # ordered steps, and deliberate duplicates round-trip exactly.
            return [json.dumps(value, ensure_ascii=False)]
        if isinstance(value, dict):
            return [json.dumps(value, ensure_ascii=False)]
        return [str(value)]

    def _field_uses_json(self, value):
        return isinstance(value, (dict, list))

    def _object_relation_ids_for_field(self, field_name, value):
        ids = self._relation_ids(value)
        return [entity_id for entity_id in ids if entity_id in self.entities]

    def _load_ontology(self, path):
        owlready2 = self._import_owlready2()
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        world = owlready2.World()
        ontology = world.get_ontology(BASE_IRI)
        with path.open("rb") as handle:
            return ontology.load(fileobj=handle)

    def _datasets_from_ontology(self, ontology):
        datasets = {}
        for individual in sorted(self._entry_individuals(ontology), key=self._individual_entity_id):
            entity = self._entity_from_individual(individual)
            dataset_name = entity.get("_dataset") or "entries"
            datasets.setdefault(dataset_name, []).append(entity)
        return datasets

    def _entry_individuals(self, ontology):
        return [
            individual
            for individual in ontology.individuals()
            if self._individual_entity_id(individual)
        ]

    def _entity_from_individual(self, individual):
        entity_id = self._individual_entity_id(individual)
        entity = {
            "id": entity_id,
            "_dataset": self._first_property_value(individual, "datasetName") or "entries",
            "type": self._first_property_value(individual, "entityType") or self._type_from_individual(individual),
        }
        list_fields = set(self._property_values(individual, "listFieldName"))
        json_fields = set(self._property_values(individual, "jsonFieldName"))

        for prop in individual.get_properties():
            property_name = prop.python_name or prop.name
            if property_name in {
                "entryId",
                "datasetName",
                "entityType",
                "listFieldName",
                "jsonFieldName",
                "hasParent",
                "hasOffspring",
                "relatedTo",
            }:
                continue
            relation_field_name = self._field_name_from_relation_property(property_name)
            if relation_field_name:
                values = [
                    self._individual_entity_id(target)
                    for target in getattr(individual, property_name, [])
                    if self._individual_entity_id(target)
                ]
                if values:
                    entity[relation_field_name] = (
                        values
                        if relation_field_name in list_fields or len(values) != 1
                        else values[0]
                    )
                continue
            if not property_name.startswith("field_"):
                continue

            field_name = property_name.removeprefix("field_")
            values = list(getattr(individual, property_name))
            values = [
                self._decode_json_value(value) if field_name in json_fields else value
                for value in values
            ]
            if field_name in list_fields:
                # New ontologies store a complete ordered list as one JSON
                # literal.  Continue accepting legacy files that stored each
                # member as a separate property value.
                if (
                    field_name in json_fields
                    and len(values) == 1
                    and isinstance(values[0], list)
                ):
                    entity[field_name] = values[0]
                else:
                    entity[field_name] = values
            elif len(values) == 1:
                entity[field_name] = values[0]
            elif values:
                entity[field_name] = values

        parents = [
            self._individual_entity_id(target)
            for target in getattr(individual, "hasParent", [])
            if self._individual_entity_id(target)
        ]
        if parents:
            entity["parents"] = parents

        related = [
            self._individual_entity_id(target)
            for target in getattr(individual, "relatedTo", [])
            if self._individual_entity_id(target)
        ]
        if related:
            entity["related"] = related

        return entity

    def _field_name_from_relation_property(self, property_name):
        for field_name, special_property in self.SPECIAL_OBJECT_PROPERTIES.items():
            if property_name == special_property:
                return field_name
        if property_name.startswith("relation_"):
            return property_name.removeprefix("relation_")
        return ""

    def _property_values(self, individual, property_name):
        if not hasattr(individual, property_name):
            return []
        return list(getattr(individual, property_name))

    def _first_property_value(self, individual, property_name):
        values = self._property_values(individual, property_name)
        return values[0] if values else ""

    def _individual_entity_id(self, individual):
        entry_id = self._first_property_value(individual, "entryId")
        if entry_id:
            return str(entry_id)
        iri = str(getattr(individual, "iri", "") or "")
        if iri.startswith(ENTITY_IRI):
            return unquote(iri[len(ENTITY_IRI):])
        name = str(getattr(individual, "name", "") or "")
        return name.removeprefix("entry_")

    def _type_from_individual(self, individual):
        for class_ref in getattr(individual, "is_a", []):
            class_name = str(getattr(class_ref, "name", "") or "")
            if class_name.endswith("_entry") and class_name != "Entry":
                return class_name[:-6]
        return "entity"

    def _decode_json_value(self, value):
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _field_property_name(self, field_name):
        return self._owl_name(f"field_{field_name}")

    def _relation_property_name(self, field_name):
        return self._owl_name(f"relation_{field_name}")

    def _individual_name(self, entity_id):
        return self._owl_name(f"entry_{entity_id}")

    def _owl_name(self, value):
        text = re.sub(r"[^0-9A-Za-z_]", "_", str(value or "entity"))
        text = re.sub(r"_+", "_", text).strip("_")
        if not text:
            text = "entity"
        if text[0].isdigit():
            text = f"n_{text}"
        return text

    def _import_owlready2(self):
        try:
            import owlready2
        except ModuleNotFoundError as exc:
            raise OntologyDependencyError(
                "owlready2 is required for ontology operations. Install requirements.txt first."
            ) from exc
        return owlready2
