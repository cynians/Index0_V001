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

        self.load_schemas()

    # --------------------------------------------------

    def load_schemas(self):

        self.schemas = {}

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

    def get_schema(self, schema_name):

        return self.schemas.get(schema_name)

    # --------------------------------------------------

    def get_all_schemas(self):

        return self.schemas