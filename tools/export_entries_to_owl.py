import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.entity_loader import EntityLoader
from world.ontology_repository import OntologyRepository


def parse_args():
    parser = argparse.ArgumentParser(description="Export Index0 YAML entries to an Owlready2 OWL file.")
    parser.add_argument(
        "--entries",
        default=str(PROJECT_ROOT / "entries"),
        help="Path to the current YAML/JSON entries directory.",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "ontology" / "index0.owl"),
        help="Output OWL file.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    loader = EntityLoader(entries_directory=args.entries)
    ontology = OntologyRepository.from_loader(loader)
    ontology.save_owl(args.output)
    print(f"Exported {len(ontology.entities)} entities to {args.output}")


if __name__ == "__main__":
    main()
