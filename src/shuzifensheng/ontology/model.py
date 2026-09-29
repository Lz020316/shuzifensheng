"""知识本体的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClassDef:
    id: str
    labels: dict[str, str]
    description: str
    parents: tuple[str, ...]
    disjoint_with: tuple[str, ...]


@dataclass(frozen=True)
class DatatypePropertyDef:
    id: str
    labels: dict[str, str]
    description: str
    domain: tuple[str, ...]
    value_type: str
    functional: bool
    minimum: float | None
    maximum: float | None


@dataclass(frozen=True)
class ObjectPropertyDef:
    id: str
    labels: dict[str, str]
    description: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    inverse: str | None
    symmetric: bool
    transitive: bool
    functional: bool


@dataclass(frozen=True)
class Individual:
    id: str
    labels: dict[str, str]
    description: str
    types: tuple[str, ...]
    source: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DataAssertion:
    id: str
    subject: str
    predicate: str
    value: Any
    confidence: float
    source: str | None
    created_at: str


@dataclass(frozen=True)
class ObjectAssertion:
    id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    source: str | None
    created_at: str


@dataclass(frozen=True)
class AttributeValue:
    assertion_id: str
    value: Any
    confidence: float
    source: str | None


@dataclass(frozen=True)
class RelationValue:
    assertion_id: str
    predicate: str
    target: str
    confidence: float
    source: str | None
    inferred: bool


@dataclass(frozen=True)
class IndividualView:
    id: str
    labels: dict[str, str]
    description: str
    types: tuple[str, ...]
    inferred_types: tuple[str, ...]
    source: str | None
    attributes: dict[str, tuple[AttributeValue, ...]]
    relations: dict[str, tuple[RelationValue, ...]]


@dataclass(frozen=True)
class PathStep:
    predicate: str
    source: str
    target: str
    assertion_id: str
    inferred: bool


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    refs: tuple[str, ...] = ()


def view_to_dict(view: IndividualView) -> dict[str, Any]:
    return {
        "id": view.id,
        "labels": view.labels,
        "description": view.description,
        "types": list(view.types),
        "inferred_types": list(view.inferred_types),
        "source": view.source,
        "attributes": {
            key: [
                {
                    "id": item.assertion_id,
                    "value": item.value,
                    "confidence": item.confidence,
                    "source": item.source,
                }
                for item in items
            ]
            for key, items in view.attributes.items()
        },
        "relations": {
            key: [
                {
                    "id": item.assertion_id,
                    "target": item.target,
                    "confidence": item.confidence,
                    "source": item.source,
                    "inferred": item.inferred,
                }
                for item in items
            ]
            for key, items in view.relations.items()
        },
    }
