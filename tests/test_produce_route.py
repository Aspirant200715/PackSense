"""Exact route-registry tests use identifiers that are not training rows."""

import json
import unittest

from packsense.produce_route import ProduceRoute, parse_route_register


class RouteRegisterTests(unittest.TestCase):
    def test_exact_reviewed_entry(self) -> None:
        raw = json.dumps({"schema_version": 1, "routes": [{
            "food_reference_id": "TEST-FOOD", "route": "non_respiring",
            "source_id": "TEST-SOURCE", "source_locator": "page 1",
            "approval_id": "TEST-REVIEW",
        }]}).encode()
        entry, = parse_route_register(raw)
        self.assertEqual(entry.food_reference_id, "TEST-FOOD")
        self.assertIs(entry.route, ProduceRoute.NON_RESPIRING)

    def test_duplicate_and_unreviewed_entries_rejected(self) -> None:
        entry = {
            "food_reference_id": "TEST-FOOD", "route": "respiring",
            "source_id": "TEST-SOURCE", "source_locator": "page 1",
            "approval_id": "TEST-REVIEW",
        }
        for payload in (
            {"schema_version": 1, "routes": [entry, entry]},
            {"schema_version": 1, "routes": [{**entry, "approval_id": ""}]},
            {"schema_version": 1, "routes": [{**entry, "route": "unknown"}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_route_register(json.dumps(payload).encode())

    def test_duplicate_json_key_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse_route_register(b'{"schema_version":1,"routes":[],"routes":[]}')


if __name__ == "__main__":
    unittest.main()
