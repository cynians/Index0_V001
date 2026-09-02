"""Persistent storage boundary for ontology-owned entity and semantic truth.

All semantic registries belong in the ontology; returned dictionaries and
indexes are disposable projections. Current generated planets have no durable
compatibility contract and may be regenerated after worldgen changes.
"""

import hashlib
import json
import logging
import os
import pickle
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


class LazyEntity(dict):
    """Dictionary-compatible entity with separately cached heavy fields.

    Startup and relationship indexing only need identity, schema and relation
    fields. Large generated-world models are loaded from their cache shard the
    first time a map or simulation actually asks for one of them.
    """

    def __init__(self, values, *, payload_path, lazy_fields):
        super().__init__(values or {})
        self._payload_path = Path(payload_path)
        self._lazy_fields = set(lazy_fields or ())
        self._payload_lock = threading.RLock()

    @property
    def is_hydrated(self):
        return not self._lazy_fields

    def _hydrate(self):
        if not self._lazy_fields:
            return
        with self._payload_lock:
            if not self._lazy_fields:
                return
            try:
                with self._payload_path.open("rb") as handle:
                    payload = pickle.load(handle)
                if not isinstance(payload, dict):
                    raise ValueError("lazy entity payload is not a mapping")
            except (OSError, ValueError, TypeError, pickle.PickleError, EOFError) as exc:
                logger.warning(
                    "Could not hydrate ontology cache payload %s: %s",
                    self._payload_path,
                    exc,
                )
                payload = {}
            dict.update(self, payload)
            self._lazy_fields.clear()

    def materialize(self):
        self._hydrate()
        return self

    def loaded_items(self):
        """Items already resident in memory, for startup graph indexing."""
        return dict.items(self)

    def loaded_values(self):
        return dict.values(self)

    def __contains__(self, key):
        return key in self._lazy_fields or dict.__contains__(self, key)

    def __getitem__(self, key):
        if key in self._lazy_fields:
            self._hydrate()
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        if key in self._lazy_fields:
            self._hydrate()
        return dict.get(self, key, default)

    def __setitem__(self, key, value):
        if key in self._lazy_fields:
            self._hydrate()
        dict.__setitem__(self, key, value)

    def __delitem__(self, key):
        if key in self._lazy_fields:
            self._hydrate()
        dict.__delitem__(self, key)

    def items(self):
        self._hydrate()
        return dict.items(self)

    def values(self):
        self._hydrate()
        return dict.values(self)

    def keys(self):
        self._hydrate()
        return dict.keys(self)

    def __iter__(self):
        self._hydrate()
        return dict.__iter__(self)

    def copy(self):
        self._hydrate()
        return dict.copy(self)


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
    PROJECTION_CACHE_VERSION = 2
    LAZY_LOCATION_FIELDS = {
        "map_layers",
        "regional_material_occurrences",
    }

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
        self.projection_cache_path = self.database_path.with_suffix(
            ".decoded-projection.pickle"
        )
        self.projection_manifest_path = self.database_path.with_suffix(
            ".decoded-projection.manifest.json"
        )
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
                try:
                    return owlready2.World(
                        filename=str(self.database_path),
                        exclusive=False,
                        read_only=bool(read_only),
                        connection=connection,
                    )
                except TypeError as exc:
                    # Owlready2 added Graph(connection=...) after 0.45.  The
                    # application's established Python environment still uses
                    # 0.45, whose World accepts arbitrary kwargs but only
                    # rejects this one when constructing the backend Graph.
                    # Let that version open the identical SQLite file itself.
                    if "unexpected keyword argument 'connection'" not in str(exc):
                        raise
                    connection.close()
                    connection = None
                    return owlready2.World(
                        filename=str(self.database_path),
                        exclusive=False,
                        read_only=bool(read_only),
                    )
            except sqlite3.OperationalError as exc:
                if connection is not None:
                    connection.close()
                if not self._is_locked_database_error(exc):
                    raise
                last_error = exc
                time.sleep(min(0.8, 0.06 * (2 ** attempt)))
        raise last_error or sqlite3.OperationalError("ontology database remained locked")

    def _save_world(self, world, *, invalidate_projection_cache=True):
        """Commit an Owlready2 world, retrying transient SQLite writer locks."""
        last_error = None
        for attempt in range(self.LOCK_RETRY_ATTEMPTS):
            try:
                world.save()
                if invalidate_projection_cache:
                    self._invalidate_projection_cache()
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

    @staticmethod
    def _file_signature(path):
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        return {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }

    def _projection_source_signature(self):
        """Identify the complete transactional SQLite state cheaply."""
        database_path = Path(self.database_path)
        return {
            "version": self.PROJECTION_CACHE_VERSION,
            "database": self._file_signature(database_path),
            "wal": self._file_signature(Path(f"{database_path}-wal")),
        }

    def _projection_payload_root(self):
        cache_path = Path(self.projection_cache_path)
        return cache_path.with_suffix(".payloads")

    @classmethod
    def _is_lazy_projection_field(cls, dataset_name, field_name):
        return dataset_name == "locations" and (
            str(field_name).endswith("_model")
            or field_name in cls.LAZY_LOCATION_FIELDS
        )

    def _split_projection_entity(self, dataset_name, entity):
        light = {}
        payload = {}
        for field_name, value in entity.items():
            target = (
                payload
                if self._is_lazy_projection_field(dataset_name, field_name)
                else light
            )
            target[field_name] = value
        return light, payload

    def _invalidate_projection_cache(self):
        for path in (
            getattr(self, "projection_cache_path", None),
            getattr(self, "projection_manifest_path", None),
        ):
            if path is None:
                continue
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                # The source signature still prevents reuse after a write.
                pass
        payload_root = self._projection_payload_root()
        try:
            if payload_root.exists() and payload_root.parent == Path(self.projection_cache_path).parent:
                shutil.rmtree(payload_root)
        except OSError:
            pass

    def _wrap_lazy_projection_entities(self, datasets, manifest):
        lazy_entities = manifest.get("lazy_entities", {})
        if not isinstance(lazy_entities, dict):
            return datasets
        payload_root = self._projection_payload_root()
        for dataset_name, dataset in datasets.items():
            if not isinstance(dataset, list):
                continue
            for index, entity in enumerate(dataset):
                if not isinstance(entity, dict):
                    continue
                metadata = lazy_entities.get(str(entity.get("id") or ""))
                if not isinstance(metadata, dict) or metadata.get("dataset") != dataset_name:
                    continue
                filename = str(metadata.get("file") or "")
                fields = metadata.get("fields") or []
                if filename and fields:
                    dataset[index] = LazyEntity(
                        entity,
                        payload_path=payload_root / filename,
                        lazy_fields=fields,
                    )
        return datasets

    def _load_projection_cache(self):
        cache_path = Path(self.projection_cache_path)
        manifest_path = Path(self.projection_manifest_path)
        if not cache_path.exists() or not manifest_path.exists():
            return None
        started_at = time.perf_counter()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("version") != self.PROJECTION_CACHE_VERSION:
                old_signature = manifest.get("source_signature") or {}
                current_signature = self._projection_source_signature()
                if (
                    manifest.get("version") == 1
                    and old_signature.get("database") == current_signature.get("database")
                    and old_signature.get("wal") == current_signature.get("wal")
                ):
                    logger.info("Migrating monolithic ontology projection cache to lazy shards")
                    with cache_path.open("rb") as handle:
                        legacy_datasets = pickle.load(handle)
                    if not isinstance(legacy_datasets, dict):
                        raise ValueError("legacy projection cache is not a dataset mapping")
                    if self._write_projection_cache(legacy_datasets):
                        return self._load_projection_cache()
                self._invalidate_projection_cache()
                return None
            if manifest.get("source_signature") != self._projection_source_signature():
                return None
            with cache_path.open("rb") as handle:
                datasets = pickle.load(handle)
            if not isinstance(datasets, dict):
                raise ValueError("decoded projection cache is not a dataset mapping")
            datasets = self._wrap_lazy_projection_entities(datasets, manifest)
        except (OSError, ValueError, TypeError, pickle.PickleError, EOFError) as exc:
            logger.warning("Ignoring invalid ontology projection cache: %s", exc)
            self._invalidate_projection_cache()
            return None
        logger.info(
            "Loaded decoded ontology projection in %.2fs (%d datasets)",
            time.perf_counter() - started_at,
            len(datasets),
        )
        return datasets

    def _write_projection_cache(self, datasets):
        cache_path = Path(self.projection_cache_path)
        manifest_path = Path(self.projection_manifest_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        temporary_cache = cache_path.with_name(f".{cache_path.name}.{token}.tmp")
        temporary_manifest = manifest_path.with_name(
            f".{manifest_path.name}.{token}.tmp"
        )
        payload_root = self._projection_payload_root()
        temporary_payload_root = payload_root.with_name(f".{payload_root.name}.{token}.tmp")
        started_at = time.perf_counter()
        try:
            temporary_payload_root.mkdir(parents=True, exist_ok=False)
            startup_datasets = {}
            lazy_entities = {}
            for dataset_name, dataset in datasets.items():
                startup_dataset = []
                for entity in dataset or []:
                    if not isinstance(entity, dict):
                        startup_dataset.append(entity)
                        continue
                    light, payload = self._split_projection_entity(dataset_name, entity)
                    startup_dataset.append(light)
                    if payload:
                        entity_id = str(entity.get("id") or "")
                        filename = f"{hashlib.sha256(entity_id.encode('utf-8')).hexdigest()}.pickle"
                        with (temporary_payload_root / filename).open("wb") as handle:
                            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
                        lazy_entities[entity_id] = {
                            "dataset": dataset_name,
                            "file": filename,
                            "fields": sorted(payload),
                        }
                startup_datasets[dataset_name] = startup_dataset
            with temporary_cache.open("wb") as handle:
                pickle.dump(startup_datasets, handle, protocol=pickle.HIGHEST_PROTOCOL)
                handle.flush()
                os.fsync(handle.fileno())
            signature = self._projection_source_signature()
            temporary_manifest.write_text(
                json.dumps(
                    {
                        "version": self.PROJECTION_CACHE_VERSION,
                        "source_signature": signature,
                        "cache_size": int(temporary_cache.stat().st_size),
                        "lazy_entities": lazy_entities,
                    },
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            # Publish data first and its validity marker last. An interrupted
            # write can therefore never make a partial pickle discoverable.
            if payload_root.exists():
                shutil.rmtree(payload_root)
            temporary_payload_root.replace(payload_root)
            temporary_cache.replace(cache_path)
            temporary_manifest.replace(manifest_path)
            logger.info(
                "Cached decoded ontology projection in %.2fs (%.1f MiB)",
                time.perf_counter() - started_at,
                cache_path.stat().st_size / (1024.0 * 1024.0),
            )
            return True
        except OSError as exc:
            logger.warning("Could not cache decoded ontology projection: %s", exc)
            return False
        finally:
            temporary_cache.unlink(missing_ok=True)
            temporary_manifest.unlink(missing_ok=True)
            if temporary_payload_root.exists():
                shutil.rmtree(temporary_payload_root, ignore_errors=True)

    def _patch_projection_cache(
        self,
        *,
        entities=(),
        remove_entity_ids=(),
        previous_entity_ids=None,
        field_names_by_id=None,
        previous_signature=None,
    ):
        """Incrementally update the disposable cache after an ontology commit."""
        cache_path = Path(self.projection_cache_path)
        manifest_path = Path(self.projection_manifest_path)
        if not cache_path.exists() or not manifest_path.exists():
            return False
        previous_entity_ids = previous_entity_ids or {}
        field_names_by_id = field_names_by_id or {}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("version") != self.PROJECTION_CACHE_VERSION
                or manifest.get("source_signature") != previous_signature
            ):
                self._invalidate_projection_cache()
                return False
            with cache_path.open("rb") as handle:
                datasets = pickle.load(handle)
            lazy_entities = manifest.get("lazy_entities", {})
            payload_root = self._projection_payload_root()
            payload_root.mkdir(parents=True, exist_ok=True)

            removals = set(str(value) for value in remove_entity_ids if value)
            removals.update(
                str(value) for value in previous_entity_ids.values() if value
            )

            def remove_cached(entity_id):
                for dataset in datasets.values():
                    if isinstance(dataset, list):
                        dataset[:] = [
                            item for item in dataset
                            if not isinstance(item, dict) or str(item.get("id") or "") != entity_id
                        ]
                metadata = lazy_entities.pop(entity_id, None)
                if isinstance(metadata, dict) and metadata.get("file"):
                    (payload_root / metadata["file"]).unlink(missing_ok=True)

            def find_cached(entity_id):
                for dataset_name, dataset in datasets.items():
                    for item in dataset or []:
                        if isinstance(item, dict) and str(item.get("id") or "") == entity_id:
                            return dataset_name, item
                return None, None

            for entity_id in removals:
                remove_cached(entity_id)

            for entity in entities:
                entity_id = str(entity.get("id") or "")
                if not entity_id:
                    continue
                existing_dataset, existing_light = find_cached(entity_id)
                dataset_name = str(entity.get("_dataset") or existing_dataset or entity.get("type") or "")
                if dataset_name not in datasets and f"{dataset_name}s" in datasets:
                    dataset_name = f"{dataset_name}s"
                if not dataset_name:
                    continue

                selected_fields = field_names_by_id.get(entity_id)
                if selected_fields is not None and existing_light is not None:
                    complete = dict(existing_light)
                    metadata = lazy_entities.get(entity_id, {})
                    filename = metadata.get("file") if isinstance(metadata, dict) else None
                    if filename:
                        with (payload_root / filename).open("rb") as handle:
                            payload = pickle.load(handle)
                        if isinstance(payload, dict):
                            complete.update(payload)
                    for field_name in selected_fields:
                        if field_name in entity:
                            complete[field_name] = entity.get(field_name)
                        else:
                            complete.pop(field_name, None)
                else:
                    complete = dict(entity.items())

                remove_cached(entity_id)
                light, payload = self._split_projection_entity(dataset_name, complete)
                datasets.setdefault(dataset_name, []).append(light)
                if payload:
                    filename = f"{hashlib.sha256(entity_id.encode('utf-8')).hexdigest()}.pickle"
                    temporary_payload = payload_root / f".{filename}.{uuid.uuid4().hex}.tmp"
                    with temporary_payload.open("wb") as handle:
                        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
                    temporary_payload.replace(payload_root / filename)
                    lazy_entities[entity_id] = {
                        "dataset": dataset_name,
                        "file": filename,
                        "fields": sorted(payload),
                    }

            token = uuid.uuid4().hex
            temporary_cache = cache_path.with_name(f".{cache_path.name}.{token}.tmp")
            temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.{token}.tmp")
            with temporary_cache.open("wb") as handle:
                pickle.dump(datasets, handle, protocol=pickle.HIGHEST_PROTOCOL)
                handle.flush()
                os.fsync(handle.fileno())
            new_manifest = {
                "version": self.PROJECTION_CACHE_VERSION,
                "source_signature": self._projection_source_signature(),
                "cache_size": int(temporary_cache.stat().st_size),
                "lazy_entities": lazy_entities,
            }
            temporary_manifest.write_text(
                json.dumps(new_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary_cache.replace(cache_path)
            temporary_manifest.replace(manifest_path)
            return True
        except (OSError, ValueError, TypeError, pickle.PickleError, EOFError) as exc:
            logger.warning("Could not patch ontology projection cache: %s", exc)
            self._invalidate_projection_cache()
            return False

    def load_datasets(self):
        with self._operation_lock:
            cached = self._load_projection_cache()
            if cached is not None:
                return cached
            started_at = time.perf_counter()
            world = self._open_world(read_only=True)
            try:
                ontology = world.get_ontology(BASE_IRI)
                datasets = OntologyRepository({})._datasets_from_ontology(ontology)
            finally:
                world.close()
            logger.info(
                "Decoded ontology quadstore in %.2fs; building startup projection cache",
                time.perf_counter() - started_at,
            )
            self._write_projection_cache(datasets)
            return datasets

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
            previous_signature = self._projection_source_signature()
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
                self._save_world(world, invalidate_projection_cache=False)
                self._patch_projection_cache(
                    entities=[entity],
                    field_names_by_id={entity_id: field_names},
                    previous_signature=previous_signature,
                )
                return True
            finally:
                world.close()

    def persist_entities(self, entities, previous_entity_ids=None):
        entities = [entity for entity in entities or [] if isinstance(entity, dict) and entity.get("id")]
        if not entities:
            return False
        previous_entity_ids = previous_entity_ids or {}
        with self._operation_lock:
            previous_signature = self._projection_source_signature()
            world = self._open_world()
            try:
                for entity in entities:
                    entity_id = str(entity.get("id") or "").strip()
                    previous_id = previous_entity_ids.get(entity_id)
                    self._replace_entity(world, entity, previous_entity_id=previous_id)
                self._save_world(world, invalidate_projection_cache=False)
                self._patch_projection_cache(
                    entities=entities,
                    previous_entity_ids=previous_entity_ids,
                    previous_signature=previous_signature,
                )
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
            previous_signature = self._projection_source_signature()
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
                self._save_world(world, invalidate_projection_cache=False)
                self._patch_projection_cache(
                    entities=entities,
                    remove_entity_ids=remove_entity_ids,
                    previous_signature=previous_signature,
                )
                return {"upserted": len(entities), "removed": removed}
            finally:
                world.close()

    def remove_entity(self, entity_id):
        entity_id = str(entity_id or "").strip()
        if not entity_id:
            return False
        with self._operation_lock:
            previous_signature = self._projection_source_signature()
            owlready2 = self._import_owlready2()
            world = self._open_world()
            try:
                individual = world[f"{ENTITY_IRI}{quote(entity_id, safe='')}"]
                if individual is None:
                    return False
                owlready2.destroy_entity(individual)
                self._save_world(world, invalidate_projection_cache=False)
                self._patch_projection_cache(
                    remove_entity_ids=[entity_id],
                    previous_signature=previous_signature,
                )
                return True
            finally:
                world.close()

    @staticmethod
    def _report_export_progress(progress_callback, progress, message):
        if not callable(progress_callback):
            return
        try:
            progress_callback(max(0.0, min(1.0, float(progress))), str(message or ""))
        except Exception as exc:
            logger.debug("Ontology export progress callback failed: %s", exc)

    def export_rdfxml(self, output_path=None, progress_callback=None):
        self._report_export_progress(progress_callback, 0.04, "Preparing ontology checkpoint")
        output_path = Path(output_path or self.ontology_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
        self._report_export_progress(progress_callback, 0.12, "Waiting for ontology store")
        with self._operation_lock:
            self._report_export_progress(progress_callback, 0.20, "Opening ontology store")
            world = self._open_world(read_only=True)
            try:
                ontology = world.get_ontology(BASE_IRI)
                self._report_export_progress(progress_callback, 0.32, "Writing RDF/XML checkpoint")
                ontology.save(file=str(temp_path), format="rdfxml")
                self._report_export_progress(progress_callback, 0.78, "RDF/XML checkpoint written")
            finally:
                world.close()
        self._report_export_progress(progress_callback, 0.84, "Replacing previous checkpoint")
        replace_error = None
        for attempt in range(24):
            try:
                temp_path.replace(output_path)
                replace_error = None
                break
            except OSError as exc:
                replace_error = exc
                retry_progress = min(0.91, 0.84 + (attempt + 1) * 0.003)
                self._report_export_progress(progress_callback, retry_progress, "Waiting for checkpoint file")
                time.sleep(min(0.75, 0.08 * (attempt + 1)))
        if replace_error is not None:
            self._replace_locked_file(temp_path, output_path)
        self._report_export_progress(progress_callback, 0.94, "Recording checkpoint metadata")
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
        self._report_export_progress(progress_callback, 1.0, "Ontology checkpoint saved")
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
            self._invalidate_projection_cache()
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
        # Older imports can leave Owlready's allocator below the highest
        # resource already present in the quadstore. Synchronize it before
        # creating a new individual so authoring does not reuse a storid.
        world.graph.execute(
            "UPDATE store SET current_resource = MAX(current_resource, "
            "(SELECT MAX(storid) FROM resources))"
        )
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
