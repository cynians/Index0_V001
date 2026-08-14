"""Report ontology startup-index and lazy-payload costs without changing state."""

import pickle
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / ".cache" / "ontology"


def main():
    cache_path = next(CACHE_ROOT.glob("*.decoded-projection.pickle"))
    payload_root = cache_path.with_suffix(".payloads")
    started = time.perf_counter()
    with cache_path.open("rb") as handle:
        datasets = pickle.load(handle)
    print(f"projection load: {time.perf_counter() - started:.2f}s")

    started = time.perf_counter()
    rows = []
    for dataset_name, entities in datasets.items():
        encoded = pickle.dumps(entities, protocol=pickle.HIGHEST_PROTOCOL)
        rows.append((len(encoded), dataset_name, len(entities)))
    print(f"dataset measurement: {time.perf_counter() - started:.2f}s")
    for size, dataset_name, entity_count in sorted(rows, reverse=True):
        print(f"{size / (1024 * 1024):9.1f} MiB  {entity_count:8d}  {dataset_name}")

    location_rows = []
    for entity in datasets.get("locations", []):
        if not isinstance(entity, dict):
            continue
        encoded_size = len(pickle.dumps(entity, protocol=pickle.HIGHEST_PROTOCOL))
        location_rows.append((encoded_size, entity))
    print("largest eager location records:")
    for encoded_size, entity in sorted(location_rows, key=lambda row: row[0], reverse=True)[:12]:
        field_rows = []
        for field_name, value in entity.items():
            field_rows.append((
                len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)),
                field_name,
            ))
        largest_fields = ", ".join(
            f"{field_name}={field_size / (1024 * 1024):.1f}MiB"
            for field_size, field_name in sorted(field_rows, reverse=True)[:6]
        )
        print(
            f"{encoded_size / (1024 * 1024):9.1f} MiB  "
            f"{entity.get('id', '<missing>')}  {largest_fields}"
        )

    payload_files = list(payload_root.glob("*.pickle")) if payload_root.exists() else []
    payload_bytes = sum(path.stat().st_size for path in payload_files)
    print(
        f"lazy payloads: {len(payload_files)} files, "
        f"{payload_bytes / (1024 * 1024):.1f} MiB"
    )


if __name__ == "__main__":
    main()
