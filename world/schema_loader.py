from pathlib import Path
import yaml


class SchemaLoader:
    """
    Loads schema definitions from the schemas directory.

    Supports two formats:

    NEW FORMAT
    ----------
    schema: culture
    fields: ...

    LEGACY FORMAT
    -------------
    metadata:
        name: Index0 Culture Schema
    """

    def __init__(self, schema_directory=None):

        if schema_directory is None:
            project_root = Path(__file__).resolve().parents[1]
            schema_directory = project_root / "schemas"

        self.schema_directory = Path(schema_directory)

        self.schemas = {}
        self._resolved_schemas = {}

        self.load_schemas()

    # --------------------------------------------------

    def load_schemas(self):

        self.schemas = {}
        self._resolved_schemas = {}

        files = list(self.schema_directory.glob("*.yaml"))
        files += list(self.schema_directory.glob("*.yml"))

        for file in files:

            with open(file, "r", encoding="utf-8") as f:
                schema = yaml.safe_load(f)

            # NEW FORMAT
            if "schema" in schema:

                schema_name = schema["schema"]

            # LEGACY FORMAT
            elif "metadata" in schema:

                name = schema["metadata"].get("name", file.stem)

                # normalize name
                schema_name = name.lower().replace("index0", "").replace("schema", "").strip()

                schema_name = schema_name.replace(" ", "_")

            else:

                schema_name = file.stem

            self.schemas[schema_name] = schema

    # --------------------------------------------------

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

        extends_name = schema.get("extends")
        if extends_name and extends_name != "entity_core":
            parent_schema = self._resolve_schema(extends_name, seen=seen)
            if parent_schema:
                fields.update(parent_schema.get("fields", {}))

        fields.update(schema.get("fields", {}))
        resolved["fields"] = fields
        self._resolved_schemas[schema_name] = resolved
        return resolved

    # --------------------------------------------------

    def get_schema(self, schema_name):

        return self._resolve_schema(schema_name)

    # --------------------------------------------------

    def get_all_schemas(self):

        return {
            schema_name: self._resolve_schema(schema_name)
            for schema_name in self.schemas
        }
