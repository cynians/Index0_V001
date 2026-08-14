import unittest

from tools.author_person_psychology_model import (
    PERSON_PSYCHOLOGY_FIELDS,
    build_changes,
)


class AuthorPersonPsychologyModelTests(unittest.TestCase):
    def test_extends_person_schema_without_replacing_existing_fields(self):
        datasets = {
            "schemas": [
                {
                    "id": "schema_person",
                    "schema": "person",
                    "fields": {"birth_year": {"type": "year"}},
                }
            ]
        }

        changes = build_changes(datasets)
        fields = changes[0]["fields"]

        self.assertIn("birth_year", fields)
        self.assertEqual(set(PERSON_PSYCHOLOGY_FIELDS), set(fields) - {"birth_year"})
        self.assertEqual("number", fields["big_five_openness"]["type"])
        self.assertEqual("string_list", fields["wishes"]["type"])


if __name__ == "__main__":
    unittest.main()
