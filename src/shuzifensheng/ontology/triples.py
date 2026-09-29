"""三元组文本解析。"""

from __future__ import annotations

from dataclasses import dataclass

from shuzifensheng.ontology.errors import ValidationError


@dataclass(frozen=True)
class RawTriple:
    line_no: int
    subject: str
    predicate: str
    raw_object: str


def parse_triples(text: str) -> tuple[RawTriple, ...]:
    if text.startswith("\ufeff"):
        text = text[1:]
    rows: list[RawTriple] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 2)
        if len(parts) < 3 or not parts[2].strip():
            raise ValidationError(f"第 {line_no} 行：需要「主体 关系 客体」")
        rows.append(RawTriple(line_no, parts[0], parts[1], parts[2].strip()))
    return tuple(rows)
