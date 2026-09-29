"""标识、标签与字面量校验。"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from shuzifensheng.ontology.errors import SchemaError, ValidationError

VALUE_TYPES = frozenset({"string", "text", "integer", "number", "boolean", "datetime"})
RESERVED_IDS = frozenset({"a", "type", "类型"})
_ID = re.compile(r"^[^\W\d][\w:.\-]{0,127}$", re.UNICODE)
_LANG = re.compile(r"^[a-z]{2}$")
_INT = re.compile(r"[+-]?\d+")


def validate_id(value: str, *, what: str = "标识") -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValidationError(f"{what}无效：{value!r}")
    return value


def normalize_labels(labels: dict[str, str] | None) -> dict[str, str]:
    if not labels:
        return {}
    if not isinstance(labels, dict):
        raise ValidationError("标签需要是语言到文本的映射")
    normalized: dict[str, str] = {}
    for key, raw in labels.items():
        if not isinstance(key, str) or _LANG.fullmatch(key) is None:
            raise ValidationError(f"语言代码无效：{key!r}")
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError(f"标签不能为空：{key}")
        normalized[key] = raw.strip()
    return normalized


def normalize_description(text: str) -> str:
    if not isinstance(text, str):
        raise ValidationError("描述需要是文本")
    cleaned = text.strip()
    if len(cleaned) > 4000:
        raise ValidationError("描述过长")
    return cleaned


def normalize_source(source: str | None) -> str | None:
    if source is None:
        return None
    if not isinstance(source, str):
        raise ValidationError("来源需要是文本")
    cleaned = source.strip()
    if not cleaned:
        return None
    if len(cleaned) > 500:
        raise ValidationError("来源过长")
    return cleaned


def normalize_confidence(value: Any) -> float:
    number = _as_float(value, message="置信度需要是 0 到 1 之间的数值")
    if number < 0 or number > 1:
        raise ValidationError("置信度需要在 0 到 1 之间")
    return number


def strip_quotes(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1]
    return raw


def coerce_value(
    value: Any,
    value_type: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Any:
    if value_type not in VALUE_TYPES:
        raise SchemaError(f"未知数据类型：{value_type}")
    if value_type in {"string", "text"}:
        if not isinstance(value, str):
            raise ValidationError("需要文本")
        cleaned = value.strip()
        if not cleaned:
            raise ValidationError("文本不能为空")
        limit = 20000 if value_type == "text" else 500
        if len(cleaned) > limit:
            raise ValidationError("文本过长")
        return cleaned
    if value_type == "boolean":
        return _as_bool(value)
    if value_type == "integer":
        number = _as_int(value)
        _check_bounds(number, minimum, maximum)
        return number
    if value_type == "number":
        number = _as_float(value, message="需要数值")
        _check_bounds(number, minimum, maximum)
        return number
    return _as_datetime(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in {"true", "yes", "是"}:
            return True
        if token in {"false", "no", "否"}:
            return False
    raise ValidationError("需要布尔值（true/false、yes/no、是/否）")


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValidationError("需要整数")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and _INT.fullmatch(value.strip()):
        return int(value.strip())
    raise ValidationError("需要整数")


def _as_float(value: Any, *, message: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(message)
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise ValidationError(message) from exc
    else:
        raise ValidationError(message)
    if not math.isfinite(number):
        raise ValidationError(message)
    return number


def _check_bounds(number: float, minimum: float | None, maximum: float | None) -> None:
    if minimum is not None and number < minimum:
        raise ValidationError(f"数值不能小于 {minimum:g}")
    if maximum is not None and number > maximum:
        raise ValidationError(f"数值不能大于 {maximum:g}")


def _as_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        token = value.strip()
        if token.endswith(("Z", "z")):
            token = token[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(token)
        except ValueError as exc:
            raise ValidationError("时间格式无效，请使用带时区的 ISO 时间") from exc
    else:
        raise ValidationError("需要时间")
    if moment.tzinfo is None:
        raise ValidationError("时间需要带时区")
    return moment.astimezone(timezone.utc).isoformat()
