"""Reviewed, exact-food respiration-route classifications.

No food name or food group is used to infer a route. An absent classification
is unresolved, and a declaration conflicts with a reported respiration rate
when it calls that food non-respiring.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class ProduceRoute(StrEnum):
    RESPIRING = "respiring"
    NON_RESPIRING = "non_respiring"


@dataclass(frozen=True, slots=True)
class RouteEvidence:
    food_reference_id: str
    route: ProduceRoute
    source_id: str
    source_locator: str
    approval_id: str

    def __post_init__(self) -> None:
        for name in ("food_reference_id", "source_id", "source_locator", "approval_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty text")
        if not isinstance(self.route, ProduceRoute):
            raise ValueError("route must be respiring or non_respiring")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_route_register(raw: bytes) -> tuple[RouteEvidence, ...]:
    payload = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "routes"}:
        raise ValueError("route register needs schema_version and routes only")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("unsupported route-register schema")
    if not isinstance(payload["routes"], list):
        raise ValueError("routes must be an array")
    fields = set(RouteEvidence.__dataclass_fields__)
    accepted = []
    seen = set()
    for index, item in enumerate(payload["routes"], start=1):
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError(f"route {index}: missing or unexpected fields")
        try:
            entry = RouteEvidence(**{**item, "route": ProduceRoute(item["route"])})
        except (TypeError, ValueError) as exc:
            raise ValueError(f"route {index}: {exc}") from exc
        if entry.food_reference_id in seen:
            raise ValueError(f"route {index}: duplicate food_reference_id")
        seen.add(entry.food_reference_id)
        accepted.append(entry)
    return tuple(accepted)


def load_route_register(path: Path) -> tuple[RouteEvidence, ...]:
    return parse_route_register(path.read_bytes())
