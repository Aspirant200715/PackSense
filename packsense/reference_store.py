"""Versioned private workbook storage for a hosted evidence-gated evaluation."""

import argparse
import hashlib
import os
from pathlib import Path

from packsense.masters import load_food_references, load_material_grades


def _connect(database_url: str):
    import psycopg

    if not database_url:
        raise ValueError("PACKSENSE_DATABASE_URL is required")
    return psycopg.connect(database_url, connect_timeout=10)


def import_bundle(database_url: str, food_path: Path, material_path: Path, *, activate: bool = False) -> str:
    """Audit, insert once, and optionally atomically activate an exact source pair."""
    food = load_food_references(food_path)
    material = load_material_grades(material_path)
    if food.issues or material.issues or not food.entries or not material.entries:
        raise ValueError("both reference workbooks must import without rejected rows")
    food_data = food_path.read_bytes()
    material_data = material_path.read_bytes()
    if (hashlib.sha256(food_data).hexdigest() != food.source_sha256
            or hashlib.sha256(material_data).hexdigest() != material.source_sha256):
        raise ValueError("a reference workbook changed during import")
    bundle_id = hashlib.sha256(f"{food.source_sha256}:{material.source_sha256}".encode()).hexdigest()
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """insert into packsense_private.reference_bundles
                   (bundle_id, food_sha256, material_sha256, food_data, material_data, food_rows, material_rows)
                   values (%s, %s, %s, %s, %s, %s, %s) on conflict (bundle_id) do nothing""",
                (bundle_id, food.source_sha256, material.source_sha256,
                 food_data, material_data, len(food.entries), len(material.entries)),
            )
            if activate:
                cursor.execute(
                    """insert into packsense_private.active_reference_bundle (singleton, bundle_id)
                       values (true, %s) on conflict (singleton) do update
                       set bundle_id = excluded.bundle_id, activated_at = now()""",
                    (bundle_id,),
                )
    return bundle_id


def load_active_bundle(database_url: str) -> tuple[bytes, bytes, str]:
    """Retrieve only the active pair and verify its stored source hashes."""
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """select b.food_data, b.material_data, b.food_sha256, b.material_sha256,
                          b.bundle_id
                   from packsense_private.active_reference_bundle a
                   join packsense_private.reference_bundles b on b.bundle_id = a.bundle_id
                   where a.singleton = true"""
            )
            row = cursor.fetchone()
    if row is None:
        raise ValueError("no active PackSense reference bundle is configured")
    food_data, material_data = bytes(row[0]), bytes(row[1])
    if (hashlib.sha256(food_data).hexdigest() != row[2]
            or hashlib.sha256(material_data).hexdigest() != row[3]):
        raise ValueError("active PackSense reference bundle failed hash verification")
    return food_data, material_data, row[4]


def main() -> None:
    parser = argparse.ArgumentParser(description="Import approved PackSense references into private PostgreSQL")
    parser.add_argument("food", type=Path)
    parser.add_argument("material", type=Path)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    bundle_id = import_bundle(os.environ.get("PACKSENSE_DATABASE_URL", ""), args.food, args.material,
                              activate=args.activate)
    print(f"Imported bundle {bundle_id}; active={args.activate}")


if __name__ == "__main__":
    main()
