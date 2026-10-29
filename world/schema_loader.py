from pathlib import Path

from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_traits import PLANT_LEGACY_FIELDS, PLANT_TRAIT_SCHEMA_FIELDS


class SchemaLoader:
    """
    Loads schema definitions from the ontology repository.

    Schemas are stored as regular ontology entities in the ``schemas`` dataset.
    The public API intentionally mirrors the old loader so UI and relationship
    code can keep asking for resolved schemas by name.
    """

    def __init__(self, ontology_path=None, schema_directory=None, schema_entities=None):
        project_root = Path(__file__).resolve().parents[1]
        self.ontology_path = Path(ontology_path or project_root / "ontology" / "index0.owl")
        self.schema_directory = Path(schema_directory) if schema_directory is not None else None
        self._provided_schema_entities = schema_entities
        self.schemas = {}
        self.schema_files = {}
        self._resolved_schemas = {}
        self.load_schemas()

    def load_schemas(self):
        self.schemas = {}
        self.schema_files = {}
        self._resolved_schemas = {}

        if self._provided_schema_entities is not None:
            schema_entities = self._provided_schema_entities
        else:
            if not self.ontology_path.exists():
                return
            datasets = PersistentOntologyStore(self.ontology_path).load_datasets()
            schema_entities = datasets.get("schemas", [])

        for entity in schema_entities:
            if not isinstance(entity, dict):
                continue
            schema = self._schema_from_entity(entity)
            schema_name = self._schema_name_for(schema, entity)
            if schema_name:
                self.schemas[schema_name] = schema

    def _schema_from_entity(self, entity):
        schema = {
            key: value
            for key, value in entity.items()
            if key not in {"id", "_dataset", "type", "name", "pretty_name"}
            and not str(key).startswith("_")
        }
        schema.setdefault("schema", entity.get("schema") or entity.get("name") or entity.get("id"))
        schema.setdefault("fields", {})
        if schema.get("schema") == "species":
            # The species schema is intentionally code-owned for this pass.
            # Existing ontology rows are artefacts and are not migrated.
            fields = dict(schema.get("fields") or {})
            fields = {
                key: value
                for key, value in fields.items()
                if key not in PLANT_TRAIT_SCHEMA_FIELDS and key not in PLANT_LEGACY_FIELDS
            }
            fields.update({key: dict(value) for key, value in PLANT_TRAIT_SCHEMA_FIELDS.items()})
            schema["fields"] = fields
        return schema

    def _schema_name_for(self, schema, entity):
        name = schema.get("schema") or entity.get("name") or entity.get("id")
        name = str(name or "").strip()
        if name.startswith("schema_"):
            name = name[len("schema_"):]
        return name

    def _resolve_schema(self, schema_name, seen=None):
        if schema_name in self._resolved_schemas:
            return self._resolved_schemas[schema_name]

        schema = self.schemas.get(schema_name)
        if not schema:
            return None

        seen = set(seen or [])
        if schema_name in seen:
            return schema
        seen.add(schema_name)

        resolved = dict(schema)
        fields = {}

        core_schema = None
        if schema_name != "entity_core":
            core_schema = self._resolve_schema("entity_core", seen=seen)
        if core_schema:
            fields.update(core_schema.get("fields", {}))

        extends_value = schema.get("extends")
        extends_names = (
            list(extends_value)
            if isinstance(extends_value, (list, tuple, set))
            else [extends_value]
        )
        for extends_name in extends_names:
            if not extends_name or extends_name == "entity_core":
                continue
            parent_schema = self._resolve_schema(str(extends_name), seen=set(seen))
            if parent_schema:
                fields.update(parent_schema.get("fields", {}))

        mixins_value = schema.get("mixins") or []
        mixin_names = (
            list(mixins_value)
            if isinstance(mixins_value, (list, tuple, set))
            else [mixins_value]
        )
        for mixin_name in mixin_names:
            if not mixin_name:
                continue
            mixin_schema = self._resolve_schema(str(mixin_name), seen=set(seen))
            if mixin_schema:
                fields.update(mixin_schema.get("fields", {}))

        fields.update(schema.get("fields", {}))
        resolved["fields"] = fields
        self._resolved_schemas[schema_name] = resolved
        return resolved

    def get_schema(self, schema_name):
        return self._resolve_schema(schema_name)

    def get_schema_file(self, schema_name):
        return self.schema_files.get(schema_name)

    def get_all_schemas(self):
        return {
            schema_name: self._resolve_schema(schema_name)
            for schema_name in self.schemas
        }
