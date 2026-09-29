"""知识本体存储、约束与轻量推理。"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shuzifensheng.ontology.builtin import (
    CLASSES,
    DATATYPE_PROPERTIES,
    DISJOINT_GROUP,
    INVERSE_PAIRS,
    OBJECT_PROPERTIES,
    resolve_predicate,
)
from shuzifensheng.ontology.errors import NotFoundError, SchemaError, ValidationError
from shuzifensheng.ontology.model import (
    AttributeValue,
    ClassDef,
    DataAssertion,
    DatatypePropertyDef,
    Individual,
    IndividualView,
    ObjectAssertion,
    ObjectPropertyDef,
    PathStep,
    RelationValue,
    Violation,
)
from shuzifensheng.ontology.triples import RawTriple, parse_triples
from shuzifensheng.ontology.validate import (
    RESERVED_IDS,
    VALUE_TYPES,
    coerce_value,
    normalize_confidence,
    normalize_description,
    normalize_labels,
    normalize_source,
    strip_quotes,
    validate_id,
)

FORMAT = "shuzifensheng.ontology"
VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS classes (
  id TEXT PRIMARY KEY,
  description TEXT NOT NULL DEFAULT '',
  labels_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS class_parents (
  child_id TEXT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  parent_id TEXT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  PRIMARY KEY (child_id, parent_id)
);
CREATE TABLE IF NOT EXISTS class_disjoint (
  left_id TEXT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  right_id TEXT NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  PRIMARY KEY (left_id, right_id)
);
CREATE TABLE IF NOT EXISTS datatype_properties (
  id TEXT PRIMARY KEY,
  description TEXT NOT NULL DEFAULT '',
  labels_json TEXT NOT NULL DEFAULT '{}',
  domain_json TEXT NOT NULL DEFAULT '[]',
  value_type TEXT NOT NULL,
  functional INTEGER NOT NULL DEFAULT 0,
  minimum REAL,
  maximum REAL
);
CREATE TABLE IF NOT EXISTS object_properties (
  id TEXT PRIMARY KEY,
  description TEXT NOT NULL DEFAULT '',
  labels_json TEXT NOT NULL DEFAULT '{}',
  domain_json TEXT NOT NULL DEFAULT '[]',
  range_json TEXT NOT NULL DEFAULT '[]',
  inverse_of TEXT REFERENCES object_properties(id),
  symmetric INTEGER NOT NULL DEFAULT 0,
  transitive INTEGER NOT NULL DEFAULT 0,
  functional INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS individuals (
  id TEXT PRIMARY KEY,
  description TEXT NOT NULL DEFAULT '',
  labels_json TEXT NOT NULL DEFAULT '{}',
  source TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS individual_types (
  individual_id TEXT NOT NULL REFERENCES individuals(id) ON DELETE CASCADE,
  class_id TEXT NOT NULL REFERENCES classes(id),
  PRIMARY KEY (individual_id, class_id)
);
CREATE TABLE IF NOT EXISTS data_assertions (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL REFERENCES individuals(id) ON DELETE CASCADE,
  predicate TEXT NOT NULL REFERENCES datatype_properties(id),
  value_json TEXT NOT NULL,
  confidence REAL NOT NULL,
  source TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS object_assertions (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL REFERENCES individuals(id) ON DELETE CASCADE,
  predicate TEXT NOT NULL REFERENCES object_properties(id),
  object_id TEXT NOT NULL REFERENCES individuals(id) ON DELETE CASCADE,
  confidence REAL NOT NULL,
  source TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_data_subject ON data_assertions(subject_id, predicate);
CREATE INDEX IF NOT EXISTS idx_obj_subject ON object_assertions(subject_id, predicate);
CREATE INDEX IF NOT EXISTS idx_obj_object ON object_assertions(object_id, predicate);
CREATE INDEX IF NOT EXISTS idx_types_class ON individual_types(class_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str) -> Any:
    return json.loads(value)


def _unique(items: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


class OntologyStore:
    """数字分身的知识库。

    默认按开放世界理解类型：个体还没有类型时，不判定定义域或值域违规。
    一旦标了类型，就会检查子类、不相交、定义域、值域和函数性。
    ``strict=False`` 时仍拒绝错误的数据类型，但会收下定义域、值域、
    不相交和函数性方面的问题，留给 :meth:`check` 报告。
    """

    def __init__(self, path: str | Path = ":memory:", *, seed: bool = True, strict: bool = True) -> None:
        self.strict = strict
        self._lock = threading.RLock()
        self._tx_depth = 0
        raw = str(path)
        if raw == ":memory:":
            self.path = raw
        else:
            target = Path(raw).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(target)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        if seed:
            self.seed_builtin()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> OntologyStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def seed_builtin(self) -> None:
        """在空库中写入数字分身本体，并放上主体 ``self``。"""
        with self._lock:
            if self._count("classes"):
                return
            with self._tx():
                for spec in CLASSES:
                    self._define_class(spec.id, spec.labels, spec.description, spec.parents)
                for index, left in enumerate(DISJOINT_GROUP):
                    for right in DISJOINT_GROUP[index + 1 :]:
                        self._add_disjoint(left, right)
                for spec in DATATYPE_PROPERTIES:
                    self._define_datatype_property(
                        spec.id,
                        spec.labels,
                        spec.description,
                        spec.domain,
                        spec.value_type,
                        spec.functional,
                        spec.minimum,
                        spec.maximum,
                    )
                for spec in OBJECT_PROPERTIES:
                    self._define_object_property(
                        spec.id,
                        spec.labels,
                        spec.description,
                        spec.domain,
                        spec.range,
                        spec.symmetric,
                        spec.transitive,
                        spec.functional,
                    )
                for left, right in INVERSE_PAIRS:
                    self._set_inverse(left, right)
                self._insert_individual(
                    "self",
                    labels={"zh": "我", "en": "self"},
                    description="数字分身的知识持有者。",
                    types=("Agent",),
                    source="builtin",
                )

    def define_class(
        self,
        class_id: str,
        *,
        labels: dict[str, str] | None = None,
        description: str = "",
        parents: tuple[str, ...] | list[str] | None = None,
    ) -> ClassDef:
        with self._lock, self._tx():
            self._define_class(class_id, labels or {}, description, tuple(parents or ()))
            return self._class(class_id)

    def add_disjoint(self, left: str, right: str) -> None:
        with self._lock, self._tx():
            self._add_disjoint(left, right)

    def define_datatype_property(
        self,
        property_id: str,
        *,
        labels: dict[str, str] | None = None,
        description: str = "",
        domain: tuple[str, ...] | list[str] = (),
        value_type: str = "string",
        functional: bool = False,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> DatatypePropertyDef:
        with self._lock, self._tx():
            self._define_datatype_property(
                property_id,
                labels or {},
                description,
                tuple(domain),
                value_type,
                functional,
                minimum,
                maximum,
            )
            return self._datatype(property_id)

    def define_object_property(
        self,
        property_id: str,
        *,
        labels: dict[str, str] | None = None,
        description: str = "",
        domain: tuple[str, ...] | list[str] = (),
        range: tuple[str, ...] | list[str] = (),
        symmetric: bool = False,
        transitive: bool = False,
        functional: bool = False,
    ) -> ObjectPropertyDef:
        with self._lock, self._tx():
            self._define_object_property(
                property_id,
                labels or {},
                description,
                tuple(domain),
                tuple(range),
                symmetric,
                transitive,
                functional,
            )
            return self._object_property(property_id)

    def set_inverse(self, left: str, right: str) -> None:
        with self._lock, self._tx():
            self._set_inverse(left, right)

    def add_individual(
        self,
        individual_id: str,
        *,
        types: tuple[str, ...] | list[str],
        labels: dict[str, str] | None = None,
        description: str = "",
        source: str | None = None,
    ) -> Individual:
        with self._lock, self._tx():
            self._insert_individual(
                individual_id,
                labels=labels or {},
                description=description,
                types=tuple(types),
                source=source,
            )
            return self._individual(individual_id)

    def add_type(self, individual_id: str, class_id: str) -> None:
        with self._lock, self._tx():
            self._add_type(individual_id, class_id)

    def set_labels(self, individual_id: str, labels: dict[str, str]) -> None:
        with self._lock, self._tx():
            self._set_labels(individual_id, labels)

    def assert_data(
        self,
        subject: str,
        predicate: str,
        value: Any,
        *,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> DataAssertion:
        with self._lock, self._tx():
            return self._assert_data(subject, predicate, value, confidence=confidence, source=source)

    def assert_object(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> ObjectAssertion:
        with self._lock, self._tx():
            return self._assert_object(subject, predicate, obj, confidence=confidence, source=source)

    def retract(self, assertion_id: str) -> None:
        with self._lock, self._tx():
            data = self._conn.execute("DELETE FROM data_assertions WHERE id=?", (assertion_id,))
            obj = self._conn.execute("DELETE FROM object_assertions WHERE id=?", (assertion_id,))
            if data.rowcount + obj.rowcount == 0:
                raise NotFoundError(f"断言不存在：{assertion_id}")

    def delete_individual(self, individual_id: str) -> None:
        with self._lock, self._tx():
            self._require_individual(individual_id)
            self._conn.execute("DELETE FROM individuals WHERE id=?", (individual_id,))

    def get_class(self, class_id: str) -> ClassDef:
        with self._lock:
            return self._class(class_id)

    def list_classes(self) -> tuple[ClassDef, ...]:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM classes ORDER BY id").fetchall()
            return tuple(self._class(row["id"]) for row in rows)

    def get_datatype_property(self, property_id: str) -> DatatypePropertyDef:
        with self._lock:
            return self._datatype(property_id)

    def list_datatype_properties(self) -> tuple[DatatypePropertyDef, ...]:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM datatype_properties ORDER BY id").fetchall()
            return tuple(self._datatype(row["id"]) for row in rows)

    def get_object_property(self, property_id: str) -> ObjectPropertyDef:
        with self._lock:
            return self._object_property(property_id)

    def list_object_properties(self) -> tuple[ObjectPropertyDef, ...]:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM object_properties ORDER BY id").fetchall()
            return tuple(self._object_property(row["id"]) for row in rows)

    def get_individual(self, individual_id: str) -> Individual:
        with self._lock:
            return self._individual(individual_id)

    def list_individuals(self) -> tuple[Individual, ...]:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM individuals ORDER BY id").fetchall()
            return tuple(self._individual(row["id"]) for row in rows)

    def is_subclass(self, child: str, parent: str) -> bool:
        with self._lock:
            self._require_class(child)
            self._require_class(parent)
            return self._is_subclass(child, parent)

    def get(self, individual_id: str) -> IndividualView:
        with self._lock:
            return self._view(individual_id)

    def expand(self, individual_id: str, predicate: str, *, max_depth: int = 8) -> tuple[RelationValue, ...]:
        with self._lock:
            self._require_individual(individual_id)
            prop = self._object_property(predicate)
            depth_limit = max_depth if prop.transitive else 1
            if depth_limit < 1:
                return ()
            seen = {individual_id}
            queue: list[tuple[str, int]] = [(individual_id, 0)]
            found: list[RelationValue] = []
            while queue:
                node, depth = queue.pop(0)
                if depth >= depth_limit:
                    continue
                for target, assertion, inferred in self._targets(node, predicate):
                    if target in seen:
                        continue
                    seen.add(target)
                    found.append(
                        RelationValue(
                            assertion_id=assertion.id,
                            predicate=predicate,
                            target=target,
                            confidence=assertion.confidence,
                            source=assertion.source,
                            inferred=inferred or depth > 0,
                        )
                    )
                    queue.append((target, depth + 1))
            return tuple(found)

    def paths(
        self,
        start: str,
        goal: str,
        *,
        max_depth: int = 4,
        limit: int = 5,
    ) -> tuple[tuple[PathStep, ...], ...]:
        with self._lock:
            self._require_individual(start)
            self._require_individual(goal)
            if start == goal or max_depth < 1 or limit < 1:
                return ()
            adjacency = self._adjacency()
            queue: list[tuple[str, tuple[PathStep, ...]]] = [(start, ())]
            found: list[tuple[PathStep, ...]] = []
            while queue:
                node, steps = queue.pop(0)
                if len(steps) >= max_depth:
                    continue
                occupied = {start} | {step.target for step in steps}
                for step in adjacency.get(node, ()):
                    if step.target in occupied:
                        continue
                    extended = steps + (step,)
                    if step.target == goal:
                        found.append(extended)
                        if len(found) >= limit:
                            return tuple(found)
                        continue
                    queue.append((step.target, extended))
            return tuple(found)

    def query(
        self,
        *,
        type: str | None = None,
        label: str | None = None,
        attributes: dict[str, Any] | None = None,
        links: dict[str, str] | None = None,
        include_subclasses: bool = True,
        min_confidence: float = 0.0,
        limit: int | None = None,
    ) -> tuple[IndividualView, ...]:
        with self._lock:
            confidence = normalize_confidence(min_confidence)
            candidates = self._candidate_ids(type, include_subclasses=include_subclasses)
            matched: list[str] = []
            for individual_id in candidates:
                if label and not self._matches_label(individual_id, label):
                    continue
                if attributes and not self._matches_attributes(individual_id, attributes, confidence):
                    continue
                if links and not self._matches_links(individual_id, links, confidence):
                    continue
                matched.append(individual_id)
            matched.sort()
            if limit is not None:
                if limit < 0:
                    raise ValidationError("limit 不能为负数")
                matched = matched[:limit]
            return tuple(self._view(individual_id) for individual_id in matched)

    def check(self) -> tuple[Violation, ...]:
        with self._lock:
            return self._check_unlocked()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "classes": self._count("classes"),
                "datatype_properties": self._count("datatype_properties"),
                "object_properties": self._count("object_properties"),
                "individuals": self._count("individuals"),
                "data_assertions": self._count("data_assertions"),
                "object_assertions": self._count("object_assertions"),
                "violations": len(self._check_unlocked()),
            }

    def export_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "format": FORMAT,
                "version": VERSION,
                "classes": [self._class_dict(item) for item in self._list_classes()],
                "datatype_properties": [self._datatype_dict(item) for item in self._list_datatypes()],
                "object_properties": [self._object_dict(item) for item in self._list_object_properties()],
                "individuals": [self._individual_dict(item) for item in self._list_individuals()],
                "data_assertions": [self._data_dict(item) for item in self._all_data_assertions()],
                "object_assertions": [self._object_assertion_dict(item) for item in self._all_object_assertions()],
            }

    def import_dict(self, document: dict[str, Any], *, replace: bool = False) -> None:
        with self._lock, self._tx():
            if replace:
                self._clear()
            self._import_dict(document)

    def import_triples(self, text: str, *, ensure_individuals: bool = False) -> int:
        triples = parse_triples(text)
        with self._lock, self._tx():
            for triple in triples:
                self._apply_triple(triple, ensure_individuals=ensure_individuals)
        return len(triples)

    def _list_classes(self) -> tuple[ClassDef, ...]:
        rows = self._conn.execute("SELECT id FROM classes ORDER BY id").fetchall()
        return tuple(self._class(row["id"]) for row in rows)

    def _list_datatypes(self) -> tuple[DatatypePropertyDef, ...]:
        rows = self._conn.execute("SELECT id FROM datatype_properties ORDER BY id").fetchall()
        return tuple(self._datatype(row["id"]) for row in rows)

    def _list_object_properties(self) -> tuple[ObjectPropertyDef, ...]:
        rows = self._conn.execute("SELECT id FROM object_properties ORDER BY id").fetchall()
        return tuple(self._object_property(row["id"]) for row in rows)

    def _list_individuals(self) -> tuple[Individual, ...]:
        rows = self._conn.execute("SELECT id FROM individuals ORDER BY id").fetchall()
        return tuple(self._individual(row["id"]) for row in rows)

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', '1') ON CONFLICT(key) DO NOTHING"
        )

    def _tx(self):
        return _Transaction(self)

    def _count(self, table: str) -> int:
        row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        return int(row["n"])

    def _define_class(
        self,
        class_id: str,
        labels: dict[str, str],
        description: str,
        parents: tuple[str, ...],
    ) -> None:
        class_id = validate_id(class_id, what="类别")
        if self._class_row(class_id) is not None:
            raise SchemaError(f"类别已存在：{class_id}")
        cleaned_labels = normalize_labels(labels)
        cleaned_description = normalize_description(description)
        parent_ids = _unique(parents)
        if class_id == "Thing":
            if parent_ids:
                raise SchemaError("事物不能有父类")
        elif not parent_ids:
            parent_ids = ("Thing",)
        for parent in parent_ids:
            if parent == class_id:
                raise SchemaError(f"类别循环：{class_id}")
            self._require_class(parent)
            if self._reaches(class_id, parent):
                raise SchemaError(f"类别循环：{class_id} 与 {parent}")
        self._conn.execute(
            "INSERT INTO classes(id, description, labels_json) VALUES (?, ?, ?)",
            (class_id, cleaned_description, _dumps(cleaned_labels)),
        )
        for parent in parent_ids:
            self._conn.execute(
                "INSERT INTO class_parents(child_id, parent_id) VALUES (?, ?)",
                (class_id, parent),
            )

    def _add_disjoint(self, left: str, right: str) -> None:
        left = validate_id(left, what="类别")
        right = validate_id(right, what="类别")
        self._require_class(left)
        self._require_class(right)
        if left == right:
            raise SchemaError("类别不能与自身不相交")
        if "Thing" in {left, right}:
            raise SchemaError("事物是所有类别的父类，不能声明不相交")
        if self._is_subclass(left, right) or self._is_subclass(right, left):
            raise SchemaError(f"{left} 与 {right} 有父子关系，不能不相交")
        pair = tuple(sorted((left, right)))
        existing = self._conn.execute(
            "SELECT 1 FROM class_disjoint WHERE left_id=? AND right_id=?",
            pair,
        ).fetchone()
        if existing:
            return
        for individual_id, types in self._all_type_sets():
            if self._types_conflict(types, extra_disjoint=(left, right)):
                raise SchemaError(f"个体 {individual_id} 已同时属于 {left} 与 {right}")
        self._conn.execute(
            "INSERT INTO class_disjoint(left_id, right_id) VALUES (?, ?)",
            pair,
        )

    def _define_datatype_property(
        self,
        property_id: str,
        labels: dict[str, str],
        description: str,
        domain: tuple[str, ...],
        value_type: str,
        functional: bool,
        minimum: float | None,
        maximum: float | None,
    ) -> None:
        property_id = self._fresh_property_id(property_id)
        if value_type not in VALUE_TYPES:
            raise SchemaError(f"未知数据类型：{value_type}")
        if minimum is not None or maximum is not None:
            if value_type not in {"integer", "number"}:
                raise SchemaError("只有数值属性可以设置上下界")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise SchemaError("下界不能大于上界")
        domain_ids = self._class_tuple(domain)
        self._conn.execute(
            """
            INSERT INTO datatype_properties(
              id, description, labels_json, domain_json, value_type, functional, minimum, maximum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                property_id,
                normalize_description(description),
                _dumps(normalize_labels(labels)),
                _dumps(list(domain_ids)),
                value_type,
                int(functional),
                minimum,
                maximum,
            ),
        )

    def _define_object_property(
        self,
        property_id: str,
        labels: dict[str, str],
        description: str,
        domain: tuple[str, ...],
        range: tuple[str, ...],
        symmetric: bool,
        transitive: bool,
        functional: bool,
    ) -> None:
        property_id = self._fresh_property_id(property_id)
        domain_ids = self._class_tuple(domain)
        range_ids = self._class_tuple(range)
        if symmetric and not _compatible(domain_ids, range_ids):
            raise SchemaError("对称关系的定义域与值域必须兼容")
        self._conn.execute(
            """
            INSERT INTO object_properties(
              id, description, labels_json, domain_json, range_json, inverse_of,
              symmetric, transitive, functional
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                property_id,
                normalize_description(description),
                _dumps(normalize_labels(labels)),
                _dumps(list(domain_ids)),
                _dumps(list(range_ids)),
                int(symmetric),
                int(transitive),
                int(functional),
            ),
        )
        if symmetric:
            self._conn.execute(
                "UPDATE object_properties SET inverse_of=? WHERE id=?",
                (property_id, property_id),
            )

    def _set_inverse(self, left: str, right: str) -> None:
        left_prop = self._object_property(left)
        right_prop = self._object_property(right)
        if left_prop.inverse not in {None, right} or right_prop.inverse not in {None, left}:
            raise SchemaError(f"{left} 与 {right} 的逆关系已绑定到其他关系")
        if not _compatible(left_prop.domain, right_prop.range) or not _compatible(left_prop.range, right_prop.domain):
            raise SchemaError(f"{left} 与 {right} 的定义域和值域对不上")
        symmetric = int(left == right)
        self._conn.execute(
            "UPDATE object_properties SET inverse_of=?, symmetric=? WHERE id=?",
            (right, symmetric, left),
        )
        if left != right:
            self._conn.execute(
                "UPDATE object_properties SET inverse_of=?, symmetric=0 WHERE id=?",
                (left, right),
            )

    def _insert_individual(
        self,
        individual_id: str,
        *,
        labels: dict[str, str],
        description: str,
        types: tuple[str, ...],
        source: str | None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> None:
        individual_id = validate_id(individual_id, what="个体")
        if individual_id in RESERVED_IDS:
            raise ValidationError(f"个体标识被保留：{individual_id}")
        if self._individual_row(individual_id) is not None:
            raise SchemaError(f"个体已存在：{individual_id}")
        type_ids = _unique(types)
        for class_id in type_ids:
            self._require_class(class_id)
        self._reject_type_conflict(individual_id, type_ids)
        moment = created_at or _now()
        self._conn.execute(
            """
            INSERT INTO individuals(id, description, labels_json, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                individual_id,
                normalize_description(description),
                _dumps(normalize_labels(labels)),
                normalize_source(source),
                moment,
                updated_at or moment,
            ),
        )
        for class_id in type_ids:
            self._conn.execute(
                "INSERT INTO individual_types(individual_id, class_id) VALUES (?, ?)",
                (individual_id, class_id),
            )

    def _add_type(self, individual_id: str, class_id: str) -> None:
        self._require_individual(individual_id)
        class_id = validate_id(class_id, what="类别")
        self._require_class(class_id)
        current = self._type_ids(individual_id)
        if class_id in current:
            return
        proposed = current + (class_id,)
        self._reject_type_conflict(individual_id, proposed)
        if self.strict:
            self._reject_role_change(individual_id, proposed)
        self._conn.execute(
            "INSERT INTO individual_types(individual_id, class_id) VALUES (?, ?)",
            (individual_id, class_id),
        )
        self._touch(individual_id)

    def _set_labels(self, individual_id: str, labels: dict[str, str]) -> None:
        current = self._individual(individual_id)
        merged = dict(current.labels)
        merged.update(normalize_labels(labels))
        self._conn.execute(
            "UPDATE individuals SET labels_json=?, updated_at=? WHERE id=?",
            (_dumps(merged), _now(), individual_id),
        )

    def _assert_data(
        self,
        subject: str,
        predicate: str,
        value: Any,
        *,
        confidence: float,
        source: str | None,
        assertion_id: str | None = None,
        created_at: str | None = None,
        touch: bool = True,
    ) -> DataAssertion:
        self._require_individual(subject)
        prop = self._require_datatype(predicate)
        coerced = coerce_value(value, prop.value_type, minimum=prop.minimum, maximum=prop.maximum)
        score = normalize_confidence(confidence)
        origin = normalize_source(source)
        if self.strict and not self._satisfies(subject, prop.domain):
            raise ValidationError(f"{subject} 的类型不在属性 {predicate} 的定义域中")
        existing = self._data_by_value(subject, predicate, coerced)
        if existing is not None:
            self._conn.execute(
                "UPDATE data_assertions SET confidence=?, source=? WHERE id=?",
                (score, origin, existing.id),
            )
            if touch:
                self._touch(subject)
            return self._data_assertion(existing.id)
        if prop.functional and self.strict and self._data_values(subject, predicate):
            raise ValidationError(f"属性 {predicate} 在 {subject} 上只能有一个值")
        new_id = assertion_id or uuid.uuid4().hex
        self._conn.execute(
            """
            INSERT INTO data_assertions(id, subject_id, predicate, value_json, confidence, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id, subject, predicate, _dumps(coerced), score, origin, created_at or _now()),
        )
        if touch:
            self._touch(subject)
        return self._data_assertion(new_id)

    def _assert_object(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        confidence: float,
        source: str | None,
        assertion_id: str | None = None,
        created_at: str | None = None,
        touch: bool = True,
    ) -> ObjectAssertion:
        self._require_individual(subject)
        self._require_individual(obj)
        prop = self._require_object(predicate)
        score = normalize_confidence(confidence)
        origin = normalize_source(source)
        if self.strict and not self._satisfies(subject, prop.domain):
            raise ValidationError(f"{subject} 的类型不在关系 {predicate} 的定义域中")
        if self.strict and not self._satisfies(obj, prop.range):
            raise ValidationError(f"{obj} 的类型不在关系 {predicate} 的值域中")
        existing = self._object_by_triple(subject, predicate, obj)
        if existing is not None:
            self._conn.execute(
                "UPDATE object_assertions SET confidence=?, source=? WHERE id=?",
                (score, origin, existing.id),
            )
            if touch:
                self._touch(subject)
            return self._object_assertion(existing.id)
        if prop.functional and self.strict and self._object_values(subject, predicate):
            raise ValidationError(f"关系 {predicate} 在 {subject} 上只能指向一个个体")
        new_id = assertion_id or uuid.uuid4().hex
        self._conn.execute(
            """
            INSERT INTO object_assertions(
              id, subject_id, predicate, object_id, confidence, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id, subject, predicate, obj, score, origin, created_at or _now()),
        )
        if touch:
            self._touch(subject)
        return self._object_assertion(new_id)

    def _apply_triple(self, triple: RawTriple, *, ensure_individuals: bool) -> None:
        try:
            self._apply_triple_inner(triple, ensure_individuals=ensure_individuals)
        except (ValidationError, SchemaError, NotFoundError) as exc:
            message = str(exc)
            prefix = f"第 {triple.line_no} 行："
            if message.startswith(prefix):
                raise
            raise type(exc)(f"{prefix}{message}") from exc

    def _apply_triple_inner(self, triple: RawTriple, *, ensure_individuals: bool) -> None:
        subject = validate_id(triple.subject, what="主体")
        predicate = resolve_predicate(triple.predicate)
        if not self._has_individual(subject):
            if predicate == "a":
                pass
            elif ensure_individuals:
                self._insert_individual(subject, labels={}, description="", types=(), source="triples")
            else:
                raise NotFoundError(f"个体不存在：{subject}")
        if predicate == "a":
            class_id = validate_id(strip_quotes(triple.raw_object), what="类别")
            self._require_class(class_id)
            if not self._has_individual(subject):
                self._insert_individual(subject, labels={}, description="", types=(class_id,), source="triples")
            else:
                self._add_type(subject, class_id)
            return
        if predicate.startswith("label."):
            lang = predicate.split(".", 1)[1]
            self._set_labels(subject, {lang: strip_quotes(triple.raw_object)})
            return
        if self._datatype_row(predicate) is not None:
            prop = self._datatype(predicate)
            value = coerce_value(
                strip_quotes(triple.raw_object),
                prop.value_type,
                minimum=prop.minimum,
                maximum=prop.maximum,
            )
            self._assert_data(subject, predicate, value, confidence=1.0, source="triples")
            return
        if self._object_row(predicate) is not None:
            obj = validate_id(strip_quotes(triple.raw_object), what="客体")
            if not self._has_individual(obj):
                if ensure_individuals:
                    self._insert_individual(obj, labels={}, description="", types=(), source="triples")
                else:
                    raise NotFoundError(f"个体不存在：{obj}")
            self._assert_object(subject, predicate, obj, confidence=1.0, source="triples")
            return
        raise NotFoundError(f"未知关系或属性：{triple.predicate}")

    def _view(self, individual_id: str) -> IndividualView:
        individual = self._individual(individual_id)
        rows = self._conn.execute(
            "SELECT * FROM data_assertions WHERE subject_id=? ORDER BY predicate, id",
            (individual_id,),
        ).fetchall()
        grouped: dict[str, list[AttributeValue]] = {}
        for row in rows:
            assertion = self._data_from_row(row)
            grouped.setdefault(assertion.predicate, []).append(
                AttributeValue(
                    assertion_id=assertion.id,
                    value=assertion.value,
                    confidence=assertion.confidence,
                    source=assertion.source,
                )
            )
        attributes = {key: tuple(value) for key, value in grouped.items()}
        relations: dict[str, tuple[RelationValue, ...]] = {}
        for prop in self._list_object_properties():
            targets = self._targets(individual_id, prop.id)
            if not targets:
                continue
            relations[prop.id] = tuple(
                RelationValue(
                    assertion_id=assertion.id,
                    predicate=prop.id,
                    target=target,
                    confidence=assertion.confidence,
                    source=assertion.source,
                    inferred=inferred,
                )
                for target, assertion, inferred in sorted(targets, key=lambda item: item[0])
            )
        return IndividualView(
            id=individual.id,
            labels=individual.labels,
            description=individual.description,
            types=individual.types,
            inferred_types=self._inferred_types(individual.types),
            source=individual.source,
            attributes=attributes,
            relations=relations,
        )

    def _targets(
        self, node: str, predicate: str
    ) -> list[tuple[str, ObjectAssertion, bool]]:
        prop = self._object_property(predicate)
        found: dict[str, tuple[ObjectAssertion, bool]] = {}
        for assertion in self._object_from(node, predicate):
            found[assertion.object] = (assertion, False)
        inverse_ids = [
            item.id
            for item in self._list_object_properties()
            if item.inverse == predicate and item.id != predicate
        ]
        if prop.inverse == predicate:
            inverse_ids.append(predicate)
        for inverse_id in inverse_ids:
            for assertion in self._object_to(node, inverse_id):
                found.setdefault(assertion.subject, (assertion, True))
        return [(target, assertion, inferred) for target, (assertion, inferred) in found.items()]

    def _adjacency(self) -> dict[str, tuple[PathStep, ...]]:
        edges: dict[str, dict[tuple[str, str], PathStep]] = {}
        properties = {item.id: item for item in self._list_object_properties()}

        def add(step: PathStep) -> None:
            bucket = edges.setdefault(step.source, {})
            key = (step.predicate, step.target)
            current = bucket.get(key)
            if current is None or (current.inferred and not step.inferred):
                bucket[key] = step

        for assertion in self._all_object_assertions():
            prop = properties[assertion.predicate]
            add(PathStep(prop.id, assertion.subject, assertion.object, assertion.id, False))
            if prop.inverse:
                add(PathStep(prop.inverse, assertion.object, assertion.subject, assertion.id, True))
        return {node: tuple(steps.values()) for node, steps in edges.items()}

    def _candidate_ids(self, type_name: str | None, *, include_subclasses: bool) -> list[str]:
        if type_name is None:
            rows = self._conn.execute("SELECT id FROM individuals").fetchall()
            return [row["id"] for row in rows]
        self._require_class(type_name)
        if include_subclasses:
            allowed = self._subclass_ids(type_name)
        else:
            allowed = {type_name}
        marks = ",".join("?" for _ in allowed)
        rows = self._conn.execute(
            f"SELECT DISTINCT individual_id FROM individual_types WHERE class_id IN ({marks})",
            tuple(sorted(allowed)),
        ).fetchall()
        return [row["individual_id"] for row in rows]

    def _matches_label(self, individual_id: str, label: str) -> bool:
        needle = label.casefold()
        individual = self._individual(individual_id)
        if needle in individual.id.casefold():
            return True
        if any(needle in value.casefold() for value in individual.labels.values()):
            return True
        for predicate in ("name", "alias"):
            for assertion in self._data_values(individual_id, predicate):
                if needle in str(assertion.value).casefold():
                    return True
        return False

    def _matches_attributes(self, individual_id: str, attributes: dict[str, Any], confidence: float) -> bool:
        for key, expected in attributes.items():
            prop = self._require_datatype(key)
            coerced = coerce_value(expected, prop.value_type, minimum=prop.minimum, maximum=prop.maximum)
            matched = False
            for assertion in self._data_values(individual_id, key):
                if assertion.confidence >= confidence and assertion.value == coerced:
                    matched = True
                    break
            if not matched:
                return False
        return True

    def _matches_links(self, individual_id: str, links: dict[str, str], confidence: float) -> bool:
        for predicate, target in links.items():
            matched = False
            for candidate, assertion, _inferred in self._targets(individual_id, predicate):
                if candidate == target and assertion.confidence >= confidence:
                    matched = True
                    break
            if not matched:
                return False
        return True

    def _check_unlocked(self) -> tuple[Violation, ...]:
        found: list[Violation] = []
        found.extend(self._cycle_violations())
        found.extend(self._inverse_violations())
        for individual in self._list_individuals():
            found.extend(self._type_violations(individual.id, individual.types))
        for assertion in self._all_data_assertions():
            found.extend(self._data_violations(assertion))
        for assertion in self._all_object_assertions():
            found.extend(self._object_violations(assertion))
        found.sort(key=lambda item: (item.code, item.message, item.refs))
        unique: list[Violation] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for item in found:
            key = (item.code, item.message, item.refs)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return tuple(unique)

    def _cycle_violations(self) -> list[Violation]:
        found: list[Violation] = []
        for class_id in self._class_ids():
            if self._reaches(class_id, class_id):
                found.append(Violation("class_cycle", f"类别存在循环：{class_id}", (class_id,)))
        return found

    def _inverse_violations(self) -> list[Violation]:
        found: list[Violation] = []
        for prop in self._list_object_properties():
            if prop.inverse is None:
                continue
            other = self._object_row(prop.inverse)
            if other is None:
                found.append(Violation("inverse_mismatch", f"{prop.id} 的逆关系不存在", (prop.id, prop.inverse)))
                continue
            inverse = self._object_property(prop.inverse)
            expected = prop.id
            if inverse.inverse != expected:
                found.append(
                    Violation(
                        "inverse_mismatch",
                        f"{prop.id} 与 {prop.inverse} 没有互为逆关系",
                        (prop.id, prop.inverse),
                    )
                )
        return found

    def _type_violations(self, individual_id: str, types: tuple[str, ...]) -> list[Violation]:
        found: list[Violation] = []
        for class_id in types:
            if self._class_row(class_id) is None:
                found.append(Violation("missing_class", f"类别不存在：{class_id}", (individual_id, class_id)))
        if self._types_conflict(types):
            found.append(
                Violation(
                    "disjoint_individual",
                    f"{individual_id} 同时属于互不相交的类别：{'、'.join(types)}",
                    (individual_id, *types),
                )
            )
        return found

    def _data_violations(self, assertion: DataAssertion) -> list[Violation]:
        found: list[Violation] = []
        prop_row = self._datatype_row(assertion.predicate)
        if prop_row is None:
            return [Violation("missing_property", f"属性不存在：{assertion.predicate}", (assertion.id,))]
        prop = self._datatype(assertion.predicate)
        if not 0 <= assertion.confidence <= 1:
            found.append(Violation("confidence", f"置信度超出范围：{assertion.id}", (assertion.id,)))
        try:
            coerce_value(assertion.value, prop.value_type, minimum=prop.minimum, maximum=prop.maximum)
        except ValidationError as exc:
            found.append(Violation("bad_value", str(exc), (assertion.id, assertion.subject, assertion.predicate)))
        if not self._satisfies(assertion.subject, prop.domain):
            found.append(
                Violation(
                    "domain_violation",
                    f"{assertion.subject} 的类型不在属性 {assertion.predicate} 的定义域中",
                    (assertion.id, assertion.subject, assertion.predicate),
                )
            )
        if prop.functional:
            values = [item.value for item in self._data_values(assertion.subject, assertion.predicate)]
            if len(set(_dumps(item) for item in values)) > 1:
                found.append(
                    Violation(
                        "functional_violation",
                        f"属性 {assertion.predicate} 在 {assertion.subject} 上有多个值",
                        (assertion.subject, assertion.predicate),
                    )
                )
        return found

    def _object_violations(self, assertion: ObjectAssertion) -> list[Violation]:
        found: list[Violation] = []
        if self._object_row(assertion.predicate) is None:
            return [Violation("missing_property", f"关系不存在：{assertion.predicate}", (assertion.id,))]
        prop = self._object_property(assertion.predicate)
        if not 0 <= assertion.confidence <= 1:
            found.append(Violation("confidence", f"置信度超出范围：{assertion.id}", (assertion.id,)))
        if not self._satisfies(assertion.subject, prop.domain):
            found.append(
                Violation(
                    "domain_violation",
                    f"{assertion.subject} 的类型不在关系 {assertion.predicate} 的定义域中",
                    (assertion.id, assertion.subject, assertion.predicate),
                )
            )
        if not self._satisfies(assertion.object, prop.range):
            found.append(
                Violation(
                    "range_violation",
                    f"{assertion.object} 的类型不在关系 {assertion.predicate} 的值域中",
                    (assertion.id, assertion.object, assertion.predicate),
                )
            )
        if prop.functional and len(self._object_values(assertion.subject, assertion.predicate)) > 1:
            found.append(
                Violation(
                    "functional_violation",
                    f"关系 {assertion.predicate} 在 {assertion.subject} 上指向多个个体",
                    (assertion.subject, assertion.predicate),
                )
            )
        return found

    def _import_dict(self, document: dict[str, Any]) -> None:
        if not isinstance(document, dict):
            raise ValidationError("知识本体文件需要是对象")
        if document.get("format") != FORMAT or document.get("version") != VERSION:
            raise ValidationError("无法识别的知识本体文件")
        classes = list(document.get("classes") or [])
        ordered = _topological_classes(classes)
        for item in ordered:
            self._import_class(item)
        for item in ordered:
            for other in item.get("disjoint_with") or []:
                self._add_disjoint(str(item["id"]), str(other))
        for item in document.get("datatype_properties") or []:
            self._import_datatype(item)
        for item in document.get("object_properties") or []:
            self._import_object_property(item)
        for item in document.get("object_properties") or []:
            inverse = item.get("inverse")
            if inverse:
                self._set_inverse(str(item["id"]), str(inverse))
        for item in document.get("individuals") or []:
            self._import_individual(item)
        for item in document.get("data_assertions") or []:
            self._import_data_assertion(item)
        for item in document.get("object_assertions") or []:
            self._import_object_assertion(item)

    def _import_class(self, item: dict[str, Any]) -> None:
        class_id = validate_id(str(item["id"]), what="类别")
        parents = tuple(item.get("parents") or [])
        existing = self._class_row(class_id)
        if existing is None:
            self._define_class(class_id, item.get("labels") or {}, item.get("description") or "", parents)
            return
        current = self._class(class_id)
        if set(current.parents) != set(parents):
            raise SchemaError(f"类别 {class_id} 的父类与知识库不一致")

    def _import_datatype(self, item: dict[str, Any]) -> None:
        property_id = str(item["id"])
        signature = (
            tuple(item.get("domain") or []),
            item.get("value_type"),
            bool(item.get("functional")),
            item.get("minimum"),
            item.get("maximum"),
        )
        if self._datatype_row(property_id) is None:
            self._define_datatype_property(
                property_id,
                item.get("labels") or {},
                item.get("description") or "",
                signature[0],
                str(signature[1]),
                signature[2],
                signature[3],
                signature[4],
            )
            return
        current = self._datatype(property_id)
        current_signature = (current.domain, current.value_type, current.functional, current.minimum, current.maximum)
        if current_signature != signature:
            raise SchemaError(f"属性 {property_id} 的定义与知识库不一致")

    def _import_object_property(self, item: dict[str, Any]) -> None:
        property_id = str(item["id"])
        domain = tuple(item.get("domain") or [])
        range_ids = tuple(item.get("range") or [])
        symmetric = bool(item.get("symmetric"))
        transitive = bool(item.get("transitive"))
        functional = bool(item.get("functional"))
        if self._object_row(property_id) is None:
            self._define_object_property(
                property_id,
                item.get("labels") or {},
                item.get("description") or "",
                domain,
                range_ids,
                symmetric,
                transitive,
                functional,
            )
            return
        current = self._object_property(property_id)
        current_signature = (current.domain, current.range, current.symmetric, current.transitive, current.functional)
        if current_signature != (domain, range_ids, symmetric, transitive, functional):
            raise SchemaError(f"关系 {property_id} 的定义与知识库不一致")

    def _import_individual(self, item: dict[str, Any]) -> None:
        individual_id = str(item["id"])
        types = tuple(item.get("types") or [])
        labels = item.get("labels") or {}
        if not self._has_individual(individual_id):
            self._insert_individual(
                individual_id,
                labels=labels,
                description=item.get("description") or "",
                types=types,
                source=item.get("source"),
                created_at=item.get("created_at"),
                updated_at=item.get("updated_at"),
            )
            return
        if labels:
            self._set_labels(individual_id, labels)
        for class_id in types:
            self._add_type(individual_id, str(class_id))

    def _import_data_assertion(self, item: dict[str, Any]) -> None:
            self._assert_data(
            str(item["subject"]),
            str(item["predicate"]),
            item.get("value"),
            confidence=item.get("confidence", 1),
            source=item.get("source"),
            assertion_id=item.get("id"),
            created_at=item.get("created_at"),
            touch=False,
        )

    def _import_object_assertion(self, item: dict[str, Any]) -> None:
        self._assert_object(
            str(item["subject"]),
            str(item["predicate"]),
            str(item["object"]),
            confidence=item.get("confidence", 1),
            source=item.get("source"),
            assertion_id=item.get("id"),
            created_at=item.get("created_at"),
            touch=False,
        )

    def _clear(self) -> None:
        self._conn.execute("UPDATE object_properties SET inverse_of=NULL")
        for table in (
            "data_assertions",
            "object_assertions",
            "individual_types",
            "individuals",
            "datatype_properties",
            "object_properties",
            "class_disjoint",
            "class_parents",
            "classes",
        ):
            self._conn.execute(f"DELETE FROM {table}")

    def _fresh_property_id(self, property_id: str) -> str:
        property_id = validate_id(property_id, what="关系")
        if property_id in RESERVED_IDS or property_id.startswith("label."):
            raise SchemaError(f"关系标识被保留：{property_id}")
        if self._datatype_row(property_id) is not None or self._object_row(property_id) is not None:
            raise SchemaError(f"关系已存在：{property_id}")
        return property_id

    def _class_tuple(self, class_ids: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = _unique(class_ids)
        for class_id in cleaned:
            self._require_class(class_id)
        return cleaned

    def _reject_type_conflict(self, individual_id: str, types: tuple[str, ...]) -> None:
        if self.strict and self._types_conflict(types):
            raise ValidationError(f"{individual_id} 同时属于互不相交的类别：{'、'.join(types)}")

    def _reject_role_change(self, individual_id: str, types: tuple[str, ...]) -> None:
        for assertion in self._data_of(individual_id):
            prop = self._datatype(assertion.predicate)
            if not _types_satisfy(types, prop.domain, self._is_subclass):
                raise ValidationError(f"加上该类型后，{individual_id} 不再符合属性 {assertion.predicate}")
        for assertion in self._object_of_subject(individual_id):
            prop = self._object_property(assertion.predicate)
            if not _types_satisfy(types, prop.domain, self._is_subclass):
                raise ValidationError(f"加上该类型后，{individual_id} 不再符合关系 {assertion.predicate}")
        for assertion in self._object_of_object(individual_id):
            prop = self._object_property(assertion.predicate)
            if not _types_satisfy(types, prop.range, self._is_subclass):
                raise ValidationError(f"加上该类型后，{individual_id} 不再符合关系 {assertion.predicate} 的值域")

    def _types_conflict(self, types: tuple[str, ...], *, extra_disjoint: tuple[str, str] | None = None) -> bool:
        for index, left in enumerate(types):
            for right in types[index + 1 :]:
                if self._classes_conflict(left, right, extra_disjoint=extra_disjoint):
                    return True
        return False

    def _classes_conflict(
        self,
        left: str,
        right: str,
        *,
        extra_disjoint: tuple[str, str] | None = None,
    ) -> bool:
        if left == right:
            return False
        left_set = self._ancestor_set(left) | {left}
        right_set = self._ancestor_set(right) | {right}
        for ancestor in left_set:
            for other in right_set:
                pair = tuple(sorted((ancestor, other)))
                if extra_disjoint and tuple(sorted(extra_disjoint)) == pair:
                    return True
                row = self._conn.execute(
                    "SELECT 1 FROM class_disjoint WHERE left_id=? AND right_id=?",
                    pair,
                ).fetchone()
                if row:
                    return True
        return False

    def _satisfies(self, individual_id: str, allowed: tuple[str, ...]) -> bool:
        return _types_satisfy(self._type_ids(individual_id), allowed, self._is_subclass)

    def _is_subclass(self, child: str, parent: str) -> bool:
        return child == parent or parent in self._ancestor_set(child)

    def _ancestor_set(self, class_id: str) -> set[str]:
        seen: set[str] = set()
        queue = list(self._parent_ids(class_id))
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self._parent_ids(current))
        return seen

    def _inferred_types(self, types: tuple[str, ...]) -> tuple[str, ...]:
        ordered: list[str] = []
        seen: set[str] = set()
        queue = list(types)
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            ordered.append(current)
            queue.extend(self._parent_ids(current))
        return tuple(ordered)

    def _subclass_ids(self, class_id: str) -> set[str]:
        seen = {class_id}
        queue = [class_id]
        while queue:
            current = queue.pop()
            children = self._conn.execute(
                "SELECT child_id FROM class_parents WHERE parent_id=?",
                (current,),
            ).fetchall()
            for row in children:
                child = row["child_id"]
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
        return seen

    def _reaches(self, start: str, goal: str) -> bool:
        return goal in self._ancestor_set(start) if start != goal else self._walks_to_self(start)

    def _walks_to_self(self, start: str) -> bool:
        seen: set[str] = set()
        queue = list(self._parent_ids(start))
        while queue:
            current = queue.pop(0)
            if current == start:
                return True
            if current in seen:
                continue
            seen.add(current)
            queue.extend(self._parent_ids(current))
        return False

    def _parent_ids(self, class_id: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT parent_id FROM class_parents WHERE child_id=? ORDER BY rowid",
            (class_id,),
        ).fetchall()
        return tuple(row["parent_id"] for row in rows)

    def _type_ids(self, individual_id: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT class_id FROM individual_types WHERE individual_id=? ORDER BY rowid",
            (individual_id,),
        ).fetchall()
        return tuple(row["class_id"] for row in rows)

    def _all_type_sets(self) -> list[tuple[str, tuple[str, ...]]]:
        rows = self._conn.execute("SELECT id FROM individuals").fetchall()
        return [(row["id"], self._type_ids(row["id"])) for row in rows]

    def _class_ids(self) -> list[str]:
        return [row["id"] for row in self._conn.execute("SELECT id FROM classes").fetchall()]

    def _touch(self, individual_id: str) -> None:
        self._conn.execute(
            "UPDATE individuals SET updated_at=? WHERE id=?",
            (_now(), individual_id),
        )

    def _require_class(self, class_id: str) -> None:
        if self._class_row(class_id) is None:
            raise NotFoundError(f"类别不存在：{class_id}")

    def _require_individual(self, individual_id: str) -> None:
        if not self._has_individual(individual_id):
            raise NotFoundError(f"个体不存在：{individual_id}")

    def _require_datatype(self, property_id: str) -> DatatypePropertyDef:
        if self._object_row(property_id) is not None:
            raise ValidationError(f"{property_id} 是关系，不能当作属性赋值")
        if self._datatype_row(property_id) is None:
            raise NotFoundError(f"属性不存在：{property_id}")
        return self._datatype(property_id)

    def _require_object(self, property_id: str) -> ObjectPropertyDef:
        if self._datatype_row(property_id) is not None:
            raise ValidationError(f"{property_id} 是属性，不能当作关系连接")
        if self._object_row(property_id) is None:
            raise NotFoundError(f"关系不存在：{property_id}")
        return self._object_property(property_id)

    def _has_individual(self, individual_id: str) -> bool:
        return self._individual_row(individual_id) is not None

    def _class_row(self, class_id: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM classes WHERE id=?", (class_id,)).fetchone()

    def _datatype_row(self, property_id: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM datatype_properties WHERE id=?", (property_id,)).fetchone()

    def _object_row(self, property_id: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM object_properties WHERE id=?", (property_id,)).fetchone()

    def _individual_row(self, individual_id: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM individuals WHERE id=?", (individual_id,)).fetchone()

    def _class(self, class_id: str) -> ClassDef:
        row = self._class_row(class_id)
        if row is None:
            raise NotFoundError(f"类别不存在：{class_id}")
        disjoint = self._conn.execute(
            """
            SELECT right_id AS other FROM class_disjoint WHERE left_id=?
            UNION
            SELECT left_id AS other FROM class_disjoint WHERE right_id=?
            ORDER BY other
            """,
            (class_id, class_id),
        ).fetchall()
        return ClassDef(
            id=row["id"],
            labels=_loads(row["labels_json"]),
            description=row["description"],
            parents=tuple(sorted(self._parent_ids(class_id))),
            disjoint_with=tuple(item["other"] for item in disjoint),
        )

    def _datatype(self, property_id: str) -> DatatypePropertyDef:
        row = self._datatype_row(property_id)
        if row is None:
            raise NotFoundError(f"属性不存在：{property_id}")
        return DatatypePropertyDef(
            id=row["id"],
            labels=_loads(row["labels_json"]),
            description=row["description"],
            domain=tuple(_loads(row["domain_json"])),
            value_type=row["value_type"],
            functional=bool(row["functional"]),
            minimum=row["minimum"],
            maximum=row["maximum"],
        )

    def _object_property(self, property_id: str) -> ObjectPropertyDef:
        row = self._object_row(property_id)
        if row is None:
            raise NotFoundError(f"关系不存在：{property_id}")
        return ObjectPropertyDef(
            id=row["id"],
            labels=_loads(row["labels_json"]),
            description=row["description"],
            domain=tuple(_loads(row["domain_json"])),
            range=tuple(_loads(row["range_json"])),
            inverse=row["inverse_of"],
            symmetric=bool(row["symmetric"]),
            transitive=bool(row["transitive"]),
            functional=bool(row["functional"]),
        )

    def _individual(self, individual_id: str) -> Individual:
        row = self._individual_row(individual_id)
        if row is None:
            raise NotFoundError(f"个体不存在：{individual_id}")
        return Individual(
            id=row["id"],
            labels=_loads(row["labels_json"]),
            description=row["description"],
            types=self._type_ids(individual_id),
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _data_assertion(self, assertion_id: str) -> DataAssertion:
        row = self._conn.execute("SELECT * FROM data_assertions WHERE id=?", (assertion_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"断言不存在：{assertion_id}")
        return self._data_from_row(row)

    def _object_assertion(self, assertion_id: str) -> ObjectAssertion:
        row = self._conn.execute("SELECT * FROM object_assertions WHERE id=?", (assertion_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"断言不存在：{assertion_id}")
        return self._object_from_row(row)

    def _data_from_row(self, row: sqlite3.Row) -> DataAssertion:
        return DataAssertion(
            id=row["id"],
            subject=row["subject_id"],
            predicate=row["predicate"],
            value=_loads(row["value_json"]),
            confidence=row["confidence"],
            source=row["source"],
            created_at=row["created_at"],
        )

    def _object_from_row(self, row: sqlite3.Row) -> ObjectAssertion:
        return ObjectAssertion(
            id=row["id"],
            subject=row["subject_id"],
            predicate=row["predicate"],
            object=row["object_id"],
            confidence=row["confidence"],
            source=row["source"],
            created_at=row["created_at"],
        )

    def _data_values(self, subject: str, predicate: str) -> tuple[DataAssertion, ...]:
        rows = self._conn.execute(
            "SELECT * FROM data_assertions WHERE subject_id=? AND predicate=? ORDER BY id",
            (subject, predicate),
        ).fetchall()
        return tuple(self._data_from_row(row) for row in rows)

    def _data_by_value(self, subject: str, predicate: str, value: Any) -> DataAssertion | None:
        encoded = _dumps(value)
        for assertion in self._data_values(subject, predicate):
            if _dumps(assertion.value) == encoded:
                return assertion
        return None

    def _data_of(self, subject: str) -> tuple[DataAssertion, ...]:
        rows = self._conn.execute(
            "SELECT * FROM data_assertions WHERE subject_id=? ORDER BY id",
            (subject,),
        ).fetchall()
        return tuple(self._data_from_row(row) for row in rows)

    def _object_values(self, subject: str, predicate: str) -> tuple[ObjectAssertion, ...]:
        return self._object_from(subject, predicate)

    def _object_by_triple(self, subject: str, predicate: str, obj: str) -> ObjectAssertion | None:
        row = self._conn.execute(
            """
            SELECT * FROM object_assertions
            WHERE subject_id=? AND predicate=? AND object_id=?
            """,
            (subject, predicate, obj),
        ).fetchone()
        return self._object_from_row(row) if row else None

    def _object_from(self, subject: str, predicate: str) -> tuple[ObjectAssertion, ...]:
        rows = self._conn.execute(
            "SELECT * FROM object_assertions WHERE subject_id=? AND predicate=? ORDER BY id",
            (subject, predicate),
        ).fetchall()
        return tuple(self._object_from_row(row) for row in rows)

    def _object_to(self, obj: str, predicate: str) -> tuple[ObjectAssertion, ...]:
        rows = self._conn.execute(
            "SELECT * FROM object_assertions WHERE object_id=? AND predicate=? ORDER BY id",
            (obj, predicate),
        ).fetchall()
        return tuple(self._object_from_row(row) for row in rows)

    def _object_of_subject(self, subject: str) -> tuple[ObjectAssertion, ...]:
        rows = self._conn.execute(
            "SELECT * FROM object_assertions WHERE subject_id=? ORDER BY id",
            (subject,),
        ).fetchall()
        return tuple(self._object_from_row(row) for row in rows)

    def _object_of_object(self, obj: str) -> tuple[ObjectAssertion, ...]:
        rows = self._conn.execute(
            "SELECT * FROM object_assertions WHERE object_id=? ORDER BY id",
            (obj,),
        ).fetchall()
        return tuple(self._object_from_row(row) for row in rows)

    def _all_data_assertions(self) -> tuple[DataAssertion, ...]:
        rows = self._conn.execute("SELECT * FROM data_assertions ORDER BY id").fetchall()
        return tuple(self._data_from_row(row) for row in rows)

    def _all_object_assertions(self) -> tuple[ObjectAssertion, ...]:
        rows = self._conn.execute("SELECT * FROM object_assertions ORDER BY id").fetchall()
        return tuple(self._object_from_row(row) for row in rows)

    def _class_dict(self, item: ClassDef) -> dict[str, Any]:
        return {
            "id": item.id,
            "labels": item.labels,
            "description": item.description,
            "parents": list(item.parents),
            "disjoint_with": list(item.disjoint_with),
        }

    def _datatype_dict(self, item: DatatypePropertyDef) -> dict[str, Any]:
        return {
            "id": item.id,
            "labels": item.labels,
            "description": item.description,
            "domain": list(item.domain),
            "value_type": item.value_type,
            "functional": item.functional,
            "minimum": item.minimum,
            "maximum": item.maximum,
        }

    def _object_dict(self, item: ObjectPropertyDef) -> dict[str, Any]:
        return {
            "id": item.id,
            "labels": item.labels,
            "description": item.description,
            "domain": list(item.domain),
            "range": list(item.range),
            "inverse": item.inverse,
            "symmetric": item.symmetric,
            "transitive": item.transitive,
            "functional": item.functional,
        }

    def _individual_dict(self, item: Individual) -> dict[str, Any]:
        return {
            "id": item.id,
            "labels": item.labels,
            "description": item.description,
            "types": list(item.types),
            "source": item.source,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    def _data_dict(self, item: DataAssertion) -> dict[str, Any]:
        return {
            "id": item.id,
            "subject": item.subject,
            "predicate": item.predicate,
            "value": item.value,
            "confidence": item.confidence,
            "source": item.source,
            "created_at": item.created_at,
        }

    def _object_assertion_dict(self, item: ObjectAssertion) -> dict[str, Any]:
        return {
            "id": item.id,
            "subject": item.subject,
            "predicate": item.predicate,
            "object": item.object,
            "confidence": item.confidence,
            "source": item.source,
            "created_at": item.created_at,
        }


def _types_satisfy(types: tuple[str, ...], allowed: tuple[str, ...], is_subclass) -> bool:
    if not allowed or not types:
        return True
    return any(is_subclass(current, expected) for current in types for expected in allowed)


def _compatible(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if not left or not right:
        return True
    return set(left) == set(right)


def _topological_classes(classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item["id"]): item for item in classes}
    if len(by_id) != len(classes):
        raise ValidationError("类别标识重复")
    pending = dict(by_id)
    ordered: list[dict[str, Any]] = []
    while pending:
        ready = [
            item
            for item in pending.values()
            if all(parent not in pending for parent in item.get("parents") or [])
        ]
        if not ready:
            raise SchemaError("类别父子关系存在循环")
        ready.sort(key=lambda item: str(item["id"]))
        for item in ready:
            ordered.append(item)
            del pending[str(item["id"])]
    return ordered


class _Transaction:
    def __init__(self, store: OntologyStore) -> None:
        self._store = store

    def __enter__(self) -> None:
        self._store._tx_depth += 1
        if self._store._tx_depth == 1:
            self._store._conn.execute("BEGIN")

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._store._tx_depth == 1:
                if exc_type is None:
                    self._store._conn.commit()
                else:
                    self._store._conn.rollback()
        finally:
            self._store._tx_depth -= 1
