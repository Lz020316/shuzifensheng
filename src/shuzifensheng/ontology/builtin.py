"""数字分身自带的知识本体。"""

from __future__ import annotations

from typing import NamedTuple


class ClassSpec(NamedTuple):
    id: str
    labels: dict[str, str]
    description: str
    parents: tuple[str, ...]


class DatatypeSpec(NamedTuple):
    id: str
    labels: dict[str, str]
    description: str
    domain: tuple[str, ...]
    value_type: str
    functional: bool
    minimum: float | None = None
    maximum: float | None = None


class ObjectSpec(NamedTuple):
    id: str
    labels: dict[str, str]
    description: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    symmetric: bool = False
    transitive: bool = False
    functional: bool = False


CLASSES: tuple[ClassSpec, ...] = (
    ClassSpec("Thing", {"zh": "事物", "en": "Thing"}, "本体中的一切事物。", ()),
    ClassSpec("Agent", {"zh": "主体", "en": "Agent"}, "数字分身自身，知识的持有者。", ("Thing",)),
    ClassSpec("Person", {"zh": "人物", "en": "Person"}, "一个具体的人。", ("Thing",)),
    ClassSpec("Organization", {"zh": "组织", "en": "Organization"}, "公司、团队、社群或其他组织。", ("Thing",)),
    ClassSpec("Place", {"zh": "地点", "en": "Place"}, "地理位置或场所。", ("Thing",)),
    ClassSpec("Event", {"zh": "事件", "en": "Event"}, "在时间中发生的事情。", ("Thing",)),
    ClassSpec("Experience", {"zh": "经历", "en": "Experience"}, "主体亲身参与的事件。", ("Event",)),
    ClassSpec("Project", {"zh": "项目", "en": "Project"}, "有目标、可交付的一段工作。", ("Thing",)),
    ClassSpec("Skill", {"zh": "技能", "en": "Skill"}, "可施展的能力或技艺。", ("Thing",)),
    ClassSpec("Preference", {"zh": "偏好", "en": "Preference"}, "稳定的喜好或表达风格。", ("Thing",)),
    ClassSpec("Goal", {"zh": "目标", "en": "Goal"}, "希望达成的状态。", ("Thing",)),
    ClassSpec("Belief", {"zh": "观点", "en": "Belief"}, "主体持有的判断或立场。", ("Thing",)),
    ClassSpec("Memory", {"zh": "记忆", "en": "Memory"}, "可被召回的一段记忆。", ("Thing",)),
    ClassSpec("Topic", {"zh": "主题", "en": "Topic"}, "知识所谈论的主题。", ("Thing",)),
)

# 这些类别不能同时套在同一个体上。子类继承父类的不相交约束。
# 主体不在此列，因此「我」可以同时是主体和人物。
DISJOINT_GROUP: tuple[str, ...] = (
    "Belief",
    "Event",
    "Goal",
    "Memory",
    "Organization",
    "Person",
    "Place",
    "Preference",
    "Project",
    "Skill",
    "Topic",
)

DATATYPE_PROPERTIES: tuple[DatatypeSpec, ...] = (
    DatatypeSpec("name", {"zh": "名称", "en": "name"}, "用于称呼该个体的名称。", (), "string", True),
    DatatypeSpec("alias", {"zh": "别名", "en": "alias"}, "名称以外的叫法。", (), "string", False),
    DatatypeSpec("summary", {"zh": "摘要", "en": "summary"}, "一段可阅读的简述。", (), "text", True),
    DatatypeSpec(
        "proficiency",
        {"zh": "熟练度", "en": "proficiency"},
        "对一项技能的熟练程度，0 到 1。",
        ("Skill",),
        "number",
        True,
        0,
        1,
    ),
    DatatypeSpec(
        "intensity",
        {"zh": "强度", "en": "intensity"},
        "偏好、观点或目标的强度，0 到 1。",
        ("Preference", "Belief", "Goal"),
        "number",
        True,
        0,
        1,
    ),
    DatatypeSpec(
        "started_at",
        {"zh": "开始时间", "en": "started at"},
        "事件、项目或目标的开始时间。",
        ("Event", "Project", "Goal"),
        "datetime",
        True,
    ),
    DatatypeSpec(
        "ended_at",
        {"zh": "结束时间", "en": "ended at"},
        "事件或项目的结束时间。",
        ("Event", "Project"),
        "datetime",
        True,
    ),
    DatatypeSpec(
        "priority",
        {"zh": "优先级", "en": "priority"},
        "目标的优先级，0 到 100，数值越大越优先。",
        ("Goal",),
        "integer",
        True,
        0,
        100,
    ),
)

_ABOUT_DOMAIN = ("Belief", "Experience", "Goal", "Memory", "Preference")

OBJECT_PROPERTIES: tuple[ObjectSpec, ...] = (
    ObjectSpec(
        "knows",
        {"zh": "认识", "en": "knows"},
        "双方互相认识。",
        ("Agent", "Person"),
        ("Agent", "Person"),
        symmetric=True,
    ),
    ObjectSpec(
        "related_to",
        {"zh": "相关", "en": "related to"},
        "两个事物相关。",
        (),
        (),
        symmetric=True,
    ),
    ObjectSpec("has_skill", {"zh": "掌握", "en": "has skill"}, "人物掌握某项技能。", ("Agent", "Person"), ("Skill",)),
    ObjectSpec("skill_of", {"zh": "技能属于", "en": "skill of"}, "技能被某人物掌握。", ("Skill",), ("Agent", "Person")),
    ObjectSpec(
        "participated_in",
        {"zh": "参与", "en": "participated in"},
        "人物参与了事件或项目。",
        ("Agent", "Person"),
        ("Event", "Project"),
    ),
    ObjectSpec(
        "has_participant",
        {"zh": "参与者", "en": "has participant"},
        "事件或项目的参与者。",
        ("Event", "Project"),
        ("Agent", "Person"),
    ),
    ObjectSpec("member_of", {"zh": "隶属于", "en": "member of"}, "人物隶属于组织。", ("Agent", "Person"), ("Organization",)),
    ObjectSpec("has_member", {"zh": "拥有成员", "en": "has member"}, "组织的成员。", ("Organization",), ("Agent", "Person")),
    ObjectSpec("located_in", {"zh": "位于", "en": "located in"}, "事物所在的地点。沿地点链传递。", (), ("Place",), transitive=True),
    ObjectSpec("contains", {"zh": "包含", "en": "contains"}, "地点所包含的事物。沿地点链传递。", ("Place",), (), transitive=True),
    ObjectSpec(
        "prefers",
        {"zh": "偏好", "en": "prefers"},
        "人物偏好某种风格或主题。",
        ("Agent", "Person"),
        ("Preference", "Topic"),
    ),
    ObjectSpec(
        "preferred_by",
        {"zh": "被偏好", "en": "preferred by"},
        "偏好或主题被哪个人物所偏好。",
        ("Preference", "Topic"),
        ("Agent", "Person"),
    ),
    ObjectSpec("pursues", {"zh": "追求", "en": "pursues"}, "主体追求某个目标。", ("Agent",), ("Goal",)),
    ObjectSpec("pursued_by", {"zh": "被追求", "en": "pursued by"}, "目标被哪个主体追求。", ("Goal",), ("Agent",)),
    ObjectSpec("holds_belief", {"zh": "持有", "en": "holds belief"}, "主体持有某个观点。", ("Agent",), ("Belief",)),
    ObjectSpec("held_by", {"zh": "观点属于", "en": "held by"}, "观点被哪个主体持有。", ("Belief",), ("Agent",)),
    ObjectSpec("recalls", {"zh": "记得", "en": "recalls"}, "主体记得某段记忆。", ("Agent",), ("Memory",)),
    ObjectSpec("recalled_by", {"zh": "被记得", "en": "recalled by"}, "记忆被哪个主体记得。", ("Memory",), ("Agent",)),
    ObjectSpec("about", {"zh": "关于", "en": "about"}, "这段知识在谈论什么。", _ABOUT_DOMAIN, ()),
    ObjectSpec("mentioned_in", {"zh": "被提及于", "en": "mentioned in"}, "事物被哪段知识提及。", (), _ABOUT_DOMAIN),
    ObjectSpec(
        "part_of",
        {"zh": "从属于", "en": "part of"},
        "项目、事件或组织从属于更大的项目或组织。",
        ("Event", "Organization", "Project"),
        ("Organization", "Project"),
        transitive=True,
    ),
    ObjectSpec(
        "has_part",
        {"zh": "含有", "en": "has part"},
        "项目或组织所含有的部分。",
        ("Organization", "Project"),
        ("Event", "Organization", "Project"),
        transitive=True,
    ),
)

INVERSE_PAIRS: tuple[tuple[str, str], ...] = (
    ("has_skill", "skill_of"),
    ("participated_in", "has_participant"),
    ("member_of", "has_member"),
    ("located_in", "contains"),
    ("prefers", "preferred_by"),
    ("pursues", "pursued_by"),
    ("holds_belief", "held_by"),
    ("recalls", "recalled_by"),
    ("about", "mentioned_in"),
    ("part_of", "has_part"),
)

ALIASES: dict[str, str] = {
    "类型": "a",
    "是一个": "a",
    "名称": "name",
    "别名": "alias",
    "摘要": "summary",
    "熟练度": "proficiency",
    "强度": "intensity",
    "开始时间": "started_at",
    "结束时间": "ended_at",
    "优先级": "priority",
    "认识": "knows",
    "相关": "related_to",
    "掌握": "has_skill",
    "参与": "participated_in",
    "隶属于": "member_of",
    "位于": "located_in",
    "包含": "contains",
    "偏好": "prefers",
    "追求": "pursues",
    "持有": "holds_belief",
    "记得": "recalls",
    "关于": "about",
    "从属于": "part_of",
    "含有": "has_part",
}


def resolve_predicate(token: str) -> str:
    if token.startswith("标签."):
        return "label." + token.split(".", 1)[1]
    return ALIASES.get(token, token)
