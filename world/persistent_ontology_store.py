import hashlib
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
import types
import uuid
from pathlib import Path
from urllib.parse import quote

from world.ontology_repository import BASE_IRI, ENTITY_IRI, OntologyRepository


logger = logging.getLogger(__name__)


class PersistentOntologyStore:
    """SQLite-backed Owlready2 store used for transactional point edits.

    RDF/XML is imported once and remains an interchange/checkpoint format. The
    SQLite quadstore is authoritative between explicit exports.
    """

    SPECIAL_OBJECT_PROPERTIES = dict(OntologyRepository.SPECIAL_OBJECT_PROPERTIES)
    DERIVED_FIELDS = set(OntologyRepository.DERIVED_FIELDS)
    _DATABASE_LOCKS = {}
    _DATABASE_LOCKS_GUARD = threading.Lock()
    LOCK_RETRY_ATTEMPTS = 5
    SQLITE_BUSY_TIMEOUT_MS = 1_500

    def __init__(self, ontology_path, database_path=None):
        self.ontology_path = Path(ontology_path).resolve()
        digest = hashlib.sha256(str(self.ontology_path).encode("utf-8")).hexdigest()[:12]
        if database_path is None:
            database_path = (
                self.ontology_path.parent.parent
                / ".cache"
                / "ontology"
                / f"{self.ontology_path.stem}-{digest}.quadstore.sqlite3"
            )
        self.database_path = Path(database_path).resolve()
        self.manifest_path = self.database_path.with_suffix(".manifest.json")
        database_key = str(self.database_path).casefold()
        with self._DATABASE_LOCKS_GUARD:
            self._operation_lock = self._DATABASE_LOCKS.setdefault(
                database_key, threading.RLock(),
            )
        self._ensure_initialized()

    def _import_owlready2(self):
        return OntologyRepository({})._import_owlready2()

    @staticmethod
    def _is_locked_database_error(exc):
        message = str(exc or "").casefold()
        return isinstance(exc, sqlite3.OperationalError) and (
            "database is locked" in message or "database is busy" in message
        )

    def _open_world(self, *, read_only=False):
        owlready2 = self._import_owlready2()
        last_error = None
        for attempt in range(self.LOCK_RETRY_ATTEMPTS):
            connection = None
            try:
                uri = f"file:{self.database_path}"
                if read_only:
                    uri += "?mode=ro"
                connection = sqlite3.connect(
                    uri,
                    isolation_level="DEFERRED",
                    check_same_thread=False,
                    uri=True,
                    timeout=self.SQLITE_BUSY_TIMEOUT_MS / 1000.0,
                )
                connection.execute(f"PRAGMA busy_timeout = {self.SQLITE_BUSY_TIMEOUT_MS}")
                return owlready2.World(
                    filename=str(self.database_path),
                    exclusive=False,
                    read_only=bool(read_only),
                    connection=connection,
                )
            except sqlite3.OperationalError as exc:
                if connection is not None:
                    connection.close()
                if not self._is_locked_database_error(exc):
                    raise
                last_error = exc
                time.sleep(min(0.8, 0.06 * (2 ** attempt)))
        raise last_error or sqlite3.OperationalError("ontology database remained locked")

    def _save_world(self, world):
        """Commit an Owlready2 world, retrying transient SQLite writer locks."""
        last_error = None
        for attempt in range(self.LOCK_RETRY_ATTEMPTS):
            try:
                world.save()
                return True
            except sqlite3.OperationalError as exc:
                if not self._is_locked_database_error(exc):
                    raise
                last_error = exc
                if attempt + 1 < self.LOCK_RETRY_ATTEMPTS:
                    time.sleep(min(0.8, 0.06 * (2 ** attempt)))
        raise last_error or sqlite3.OperationalError(
            "ontology database remained locked during commit"
        )

    def _ensure_initialized(self):
        with self._operation_lock:
            if self.database_path.exists() and self.manifest_path.exists():
                return
            if not self.ontology_path.exists():
                raise FileNotFoundError(self.ontology_path)
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self.database_path.unlink(missing_ok=True)
            self.manifest_path.unlink(missing_ok=True)
            world = self._open_world()
            try:
                ontology = world.get_ontology(BASE_IRI)
                with self.ontology_path.open("rb") as source:
                    ontology.load(fileobj=source)
                self._save_world(world)
            except Exception:
                world.close()
                self.database_path.unlink(missing_ok=True)
                raise
            else:
                world.close()
            stat = self.ontology_path.stat()
            self._write_manifest(
                {
                    "version": 1,
                    "source_path": str(self.ontology_path),
                    "source_size": int(stat.st_size),
                    "source_mtime_ns": int(stat.st_mtime_ns),
                    "database_authoritative": True,
                }
            )

    def _write_manifest(self, payload):
        temp_path = self.manifest_path.with_name(f".{self.manifest_path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.manifest_path)

    def load_datasets(self):
        with self._operation_lock:
            world = self._open_world(read_only=True)
            try:
                ontology = world.get_ontology(BASE_IRI)
                return OntologyRepository({})._datasets_from_ontology(ontology)
            finally:
                world.close()

    def persist_entity(self, entity, previous_entity_id=None):
        return self.persist_entities([entity], previous_entity_ids={str(entity.get("id") or ""): previous_entity_id})

    def persist_entity_fields(self, entity, field_names):
        """Replace selected fields on one individual without rebuilding the entity."""
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

        with self._operation_lock:
            world = self._open_world()
            try:
                ontology = world.get_ontology(BASE_IRI)
                individual = world[f"{ENTITY_IRI}{quote(entity_id, safe='')}"]
                if individual is None:
                    self._replace_entity(world, entity)
                else:
                    list_fields = set(self._property_values(individual, "listFieldName"))
                    json_fields = set(self._property_values(individual, "jsonFieldName"))
                    for field_name in field_names:
                        value = entity.get(field_name)
                        self._set_metadata_membership(list_fields, field_name, isinstance(value, list))
                        self._set_metadata_membership(json_fields, field_name, self._field_uses_json(value))

                        relation_property = self._relation_property(
                            world,
                            ontology,
                            field_name,
                            value,
                        )
                        if relation_property is not None:
                            targets = []
                            for target_id in self._relation_ids(value):
                                target = world[
                                    f"{ENTITY_IRI}{quote(target_id, safe='')}"
                                ]
                                if target is not None and target not in targets:
                                    targets.append(target)
                            relation_property[individual] = targets
                            continue

                        property_name = self._owl_name(f"field_{field_name}")
                        self._ensure_data_property(
                            world,
                            ontology,
                            property_name,
                        )[individual] = self._data_values(value)
                    self._ensure_data_property(world, ontology, "listFieldName")[individual] = sorted(list_fields)
                    self._ensure_data_property(world, ontology, "jsonFieldName")[individual] = sorted(json_fields)
                self._save_world(world)
                return True
            finally:
                world.close()

    def persist_entities(self, entities, previous_entity_ids=None):
        entities = [entity for entity in entities or [] if isinstance(entity, dict) and entity.get("id")]
        if not entities:
            return False
        previous_entity_ids = previous_entity_ids or {}
        with self._operation_lock:
            world = self._open_world()
            try:
                for entity in entities:
                    entity_id = str(entity.get("id") or "").strip()
                    previous_id = previous_entity_ids.get(entity_id)
                    self._replace_entity(world, entity, previous_entity_id=previous_id)
                self._save_world(world)
                return True
            finally:
                world.close()

    def apply_changes(self, entities=None, remove_entity_ids=None):
        """Apply a mixed upsert/delete set in one quadstore transaction.

        Cleanup and migration jobs often need to remove a graph branch while
        repairing references on surviving entities.  Committing each change
        separately is both slow and exposes partially migrated repository
        states, so keep the whole operation under one world commit.
        """
        entities = [
            entity
            for entity in (entities or [])
            if isinstance(entity, dict) and entity.get("id")
        ]
        remove_entity_ids = list(dict.fromkeys(
            str(entity_id or "").strip()
            for entity_id in (remove_entity_ids or [])
            if str(entity_id or "").strip()
        ))
        if not entities and not remove_entity_ids:
            return {"upserted": 0, "removed": 0}

        with self._operation_lock:
            owlready2 = self._import_owlready2()
            world = self._open_world()
            try:
                removed = 0
                for entity_id in remove_entity_ids:
                    individual = world[f"{ENTITY_IRI}{quote(entity_id, safe='')}"]
                    if individual is None:
                        continue
                    owlready2.destroy_entity(individual)
                    removed += 1
                for entity in entities:
                    self._replace_entity(world, entity)
                self._save_world(world)
                return {"upserted": len(entities), "removed": removed}
            finally:
                world.close()

    def remove_entity(self, entity_id):
        entity_id = str(entity_id or "").strip()
        if not entity_id:
            return False
        with self._operation_lock:
            owlready2 = self._import_owlready2()
            world = self._open_world()
            try:
                individual = world[f"{ENTITY_IRI}{quote(entity_id, safe='')}"]
                if individual is None:
                    return False
                owlready2.destroy_entity(individual)
                self._save_world(world)
                return True
            finally:
                world.close()

    def export_rdfxml(self, output_path=None):
        output_path = Path(output_path or self.ontology_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
        with self._operation_lock:
            world = self._open_world(read_only=True)
            try:
                ontology = world.get_ontology(BASE_IRI)
                ontology.save(file=str(temp_path), format="rdfxml")
            finally:
                world.close()
        replace_error = None
        for attempt in range(24):
            try:
                temp_path.replace(output_path)
                replace_error = None
                break
            except OSError as exc:
                replace_error = exc
                time.sleep(min(0.75, 0.08 * (attempt + 1)))
        if replace_error is not None:
            self._replace_locked_file(temp_path, output_path)
        stat = output_path.stat()
        self._write_manifest(
            {
                "version": 1,
                "source_path": str(output_path),
                "source_size": int(stat.st_size),
                "source_mtime_ns": int(stat.st_mtime_ns),
                "database_authoritative": True,
            }
        )
        return True

    def compact_database(self):
        """Reclaim pages left behind by large ontology cleanup transactions."""
        with self._operation_lock:
            connection = sqlite3.connect(
                str(self.database_path),
                isolation_level=None,
                check_same_thread=False,
                timeout=self.SQLITE_BUSY_TIMEOUT_MS / 1000.0,
            )
            try:
                connection.execute(
                    f"PRAGMA busy_timeout = {self.SQLITE_BUSY_TIMEOUT_MS}"
                )
                connection.execute("VACUUM")
            finally:
                connection.close()
        return self.database_path

    def reimport_rdfxml(self):
        """Deliberately replace the working quadstore from the RDF/XML checkpoint."""
        with self._operation_lock:
            self.database_path.unlink(missing_ok=True)
            self.manifest_path.unlink(missing_ok=True)
            self._ensure_initialized()
        return True

    def _replace_entity(self, world, entity, previous_entity_id=None):
        owlready2 = self._import_owlready2()
        ontology = world.get_ontology(BASE_IRI)
        entity_id = str(entity.get("id") or "").strip()
        previous_entity_id = str(previous_entity_id or "").strip()
        if previous_entity_id and previous_entity_id != entity_id:
            previous = world[f"{ENTITY_IRI}{quote(previous_entity_id, safe='')}"]
            if previous is not None:
                owlready2.destroy_entity(previous)

        individual = world[f"{ENTITY_IRI}{quote(entity_id, safe='')}"]
        if individual is None:
            individual = self._create_individual(world, ontology, entity)
        for prop in list(individual.get_properties()):
            if prop.name == "hasOffspring":
                continue
            prop[individual] = []

        self._ensure_data_property(world, ontology, "entryId")[individual] = [entity_id]
        self._ensure_data_property(world, ontology, "datasetName")[individual] = [
            str(entity.get("_dataset") or entity.get("type") or "entries")
        ]
        entity_type = str(entity.get("type") or "entity").strip() or "entity"
        self._ensure_data_property(world, ontology, "entityType")[individual] = [entity_type]

        list_fields = []
        json_fields = []
        for field_name, value in entity.items():
            if (
                field_name in {"id", "_dataset"}
                or field_name in self.DERIVED_FIELDS
                or str(field_name).startswith("_")
            ):
                continue
            if isinstance(value, list):
                list_fields.append(field_name)
            if self._field_uses_json(value):
                json_fields.append(field_name)

            relation_property = self._relation_property(world, ontology, field_name, value)
            if relation_property is not None:
                targets = []
                for target_id in self._relation_ids(value):
                    target = world[f"{ENTITY_IRI}{quote(target_id, safe='')}"]
                    if target is not None and target not in targets:
                        targets.append(target)
                relation_property[individual] = targets
                continue

            property_name = self._owl_name(f"field_{field_name}")
            data_property = self._ensure_data_property(world, ontology, property_name)
            data_property[individual] = self._data_values(value)

        self._ensure_data_property(world, ontology, "listFieldName")[individual] = list_fields
        self._ensure_data_property(world, ontology, "jsonFieldName")[individual] = json_fields

    def _create_individual(self, world, ontology, entity):
        owlready2 = self._import_owlready2()
        entity_type = str(entity.get("type") or "entity").strip() or "entity"
        class_name = self._owl_name(f"{entity_type}_entry")
        entity_class = world[f"{BASE_IRI}{class_name}"] or world[f"{BASE_IRI}Entry"]
        if entity_class is None:
            with ontology:
                entity_class = types.new_class(class_name, (owlready2.Thing,))
        individual = entity_class(self._owl_name(f"entry_{entity.get('id')}"))
        individual.iri = f"{ENTITY_IRI}{quote(str(entity.get('id')), safe='')}"
        return individual

    def _ensure_data_property(self, world, ontology, property_name):
        owlready2 = self._import_owlready2()
        property_name = self._owl_name(property_name)
        prop = world[f"{BASE_IRI}{property_name}"]
        if prop is None:
            with ontology:
                prop = types.new_class(property_name, (owlready2.DataProperty,))
        return prop

    def _relation_property(self, world, ontology, field_name, value):
        owlready2 = self._import_owlready2()
        property_name = self.SPECIAL_OBJECT_PROPERTIES.get(
            field_name,
            self._owl_name(f"relation_{field_name}"),
        )
        prop = world[f"{BASE_IRI}{property_name}"]
        if prop is not None and isinstance(prop, owlready2.ObjectPropertyClass):
            return prop
        if any(world[f"{ENTITY_IRI}{quote(target_id, safe='')}"] is not None for target_id in self._relation_ids(value)):
            with ontology:
                return types.new_class(property_name, (owlready2.ObjectProperty,))
        return None

    def _replace_locked_file(self, temp_path, output_path):
        backup_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.rollback")
        backup_created = False
        try:
            if output_path.exists():
                shutil.copyfile(output_path, backup_path)
                backup_created = True
            expected_size = temp_path.stat().st_size
            with temp_path.open("rb") as source, output_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=4 * 1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
            if output_path.stat().st_size != expected_size:
                raise OSError("Ontology export size verification failed")
            if backup_created:
                backup_path.unlink(missing_ok=True)
        except OSError:
            if backup_created and backup_path.exists():
                with backup_path.open("rb") as source, output_path.open("wb") as target:
                    shutil.copyfileobj(source, target, length=4 * 1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                backup_path.unlink(missing_ok=True)
            raise
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _set_metadata_membership(field_names, field_name, included):
        if included:
            field_names.add(field_name)
        else:
            field_names.discard(field_name)

    @staticmethod
    def _property_values(individual, property_name):
        if not hasattr(individual, property_name):
            return []
        return list(getattr(individual, property_name))

    @staticmethod
    def _relation_ids(value):
        return OntologyRepository({})._relation_ids(value)

    @staticmethod
    def _data_values(value):
        return OntologyRepository({})._data_values(value)

    @staticmethod
    def _field_uses_json(value):
        return OntologyRepository({})._field_uses_json(value)

    @staticmethod
    def _owl_name(value):
        return OntologyRepository({})._owl_name(value)
