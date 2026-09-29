"""知识本体命令行。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shuzifensheng.ontology.builtin import resolve_predicate
from shuzifensheng.ontology.errors import OntologyError
from shuzifensheng.ontology.model import view_to_dict
from shuzifensheng.ontology.store import OntologyStore
from shuzifensheng.ontology.validate import strip_quotes


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except OntologyError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ontology",
        description="数字分身知识本体",
        epilog=(
            "示例：ontology init && "
            "ontology import-triples examples/demo.triples && "
            "ontology show self"
        ),
    )
    parser.add_argument("--db", default=_default_db(), help="SQLite 知识库路径，默认 ontology.db")
    parser.add_argument("--lenient", action="store_true", help="放宽定义域、值域、不相交和函数性约束")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="创建知识库并写入内置本体")
    init.set_defaults(handler=_init)

    stats = sub.add_parser("stats", help="查看规模与不一致数量")
    stats.set_defaults(handler=_stats)

    classes = sub.add_parser("classes", help="列出类别")
    classes.set_defaults(handler=_classes)

    show = sub.add_parser("show", help="查看一个个体")
    show.add_argument("id")
    show.set_defaults(handler=_show)

    query = sub.add_parser("query", help="按类型、名称或关系查询")
    query.add_argument("--type")
    query.add_argument("--label")
    query.add_argument("--attr", action="append", default=[])
    query.add_argument("--link", action="append", default=[])
    query.add_argument("--exact-type", action="store_true")
    query.add_argument("--limit", type=int)
    query.set_defaults(handler=_query)

    paths = sub.add_parser("paths", help="查找两个个体之间的关系路径")
    paths.add_argument("start")
    paths.add_argument("goal")
    paths.add_argument("--max-depth", type=int, default=4)
    paths.set_defaults(handler=_paths)

    check = sub.add_parser("check", help="检查一致性")
    check.set_defaults(handler=_check)

    add = sub.add_parser("add", help="添加个体")
    add.add_argument("id")
    add.add_argument("--type", action="append", required=True)
    add.add_argument("--label-zh")
    add.add_argument("--label-en")
    add.add_argument("--description", default="")
    add.add_argument("--source")
    add.set_defaults(handler=_add)

    assertion = sub.add_parser("assert", help="添加类型、标签、属性或关系")
    assertion.add_argument("subject")
    assertion.add_argument("predicate")
    assertion.add_argument("object", nargs="+")
    assertion.add_argument("--confidence", type=float, default=1.0)
    assertion.add_argument("--source")
    assertion.set_defaults(handler=_assert)

    retract = sub.add_parser("retract", help="撤回一条断言")
    retract.add_argument("assertion_id")
    retract.set_defaults(handler=_retract)

    delete = sub.add_parser("delete", help="删除个体及其断言")
    delete.add_argument("id")
    delete.set_defaults(handler=_delete)

    export = sub.add_parser("export", help="导出 JSON")
    export.add_argument("-o", "--output")
    export.set_defaults(handler=_export)

    import_json = sub.add_parser("import", help="导入 JSON")
    import_json.add_argument("file")
    import_json.add_argument("--replace", action="store_true")
    import_json.set_defaults(handler=_import_json)

    triples = sub.add_parser("import-triples", help="导入三元组文本")
    triples.add_argument("file")
    triples.add_argument("--ensure", action="store_true", help="自动补上尚未出现的个体")
    triples.set_defaults(handler=_import_triples)
    return parser


def _default_db() -> str:
    import os

    return os.environ.get("ONTOLOGY_DB", "ontology.db")


def _open(args: argparse.Namespace, *, create: bool = False) -> OntologyStore:
    path = Path(args.db)
    if not create and args.db != ":memory:" and not path.exists():
        raise OntologyError(f"知识库不存在：{args.db}。请先执行 ontology init")
    return OntologyStore(args.db, seed=True, strict=not args.lenient)


def _init(args: argparse.Namespace) -> int:
    existed = args.db != ":memory:" and Path(args.db).exists()
    with _open(args, create=True):
        pass
    print(f"{'知识库已就绪' if existed else '已创建知识库'}：{args.db}")
    return 0


def _stats(args: argparse.Namespace) -> int:
    with _open(args) as store:
        _print_json(store.stats())
    return 0


def _classes(args: argparse.Namespace) -> int:
    with _open(args) as store:
        for item in store.list_classes():
            label = item.labels.get("zh") or item.labels.get("en") or ""
            parents = "、".join(item.parents) if item.parents else "—"
            print(f"{item.id}\t{label}\t{parents}")
    return 0


def _show(args: argparse.Namespace) -> int:
    with _open(args) as store:
        _print_json(view_to_dict(store.get(args.id)))
    return 0


def _query(args: argparse.Namespace) -> int:
    attributes = dict(_split_pair(item, "--attr") for item in args.attr)
    links = dict(_split_pair(item, "--link") for item in args.link)
    with _open(args) as store:
        found = store.query(
            type=args.type,
            label=args.label,
            attributes=attributes or None,
            links=links or None,
            include_subclasses=not args.exact_type,
            limit=args.limit,
        )
        _print_json([view_to_dict(item) for item in found])
    return 0


def _paths(args: argparse.Namespace) -> int:
    with _open(args) as store:
        found = store.paths(args.start, args.goal, max_depth=args.max_depth)
    if not found:
        print("未找到路径")
        return 1
    for route in found:
        parts = [args.start]
        for step in route:
            mark = "≈" if step.inferred else "-"
            parts.append(f"{mark}{step.predicate}{mark}> {step.target}")
        print(" ".join(parts))
    return 0


def _check(args: argparse.Namespace) -> int:
    with _open(args) as store:
        found = store.check()
    if not found:
        print("未发现不一致")
        return 0
    for item in found:
        print(f"{item.code}\t{item.message}")
    return 1


def _add(args: argparse.Namespace) -> int:
    labels = {}
    if args.label_zh:
        labels["zh"] = args.label_zh
    if args.label_en:
        labels["en"] = args.label_en
    with _open(args) as store:
        store.add_individual(
            args.id,
            types=args.type,
            labels=labels,
            description=args.description,
            source=args.source,
        )
    print(f"已添加：{args.id}")
    return 0


def _assert(args: argparse.Namespace) -> int:
    predicate = resolve_predicate(args.predicate)
    raw = strip_quotes(" ".join(args.object))
    with _open(args) as store:
        if predicate == "a":
            store.add_type(args.subject, raw)
            print(f"已添加类型：{args.subject} a {raw}")
            return 0
        if predicate.startswith("label."):
            lang = predicate.split(".", 1)[1]
            store.set_labels(args.subject, {lang: raw})
            print(f"已更新标签：{args.subject}")
            return 0
        try:
            prop = store.get_datatype_property(predicate)
        except OntologyError:
            prop = None
        if prop is not None:
            assertion = store.assert_data(
                args.subject,
                predicate,
                raw,
                confidence=args.confidence,
                source=args.source,
            )
        else:
            assertion = store.assert_object(
                args.subject,
                predicate,
                raw,
                confidence=args.confidence,
                source=args.source,
            )
    print(assertion.id)
    return 0


def _retract(args: argparse.Namespace) -> int:
    with _open(args) as store:
        store.retract(args.assertion_id)
    print(f"已撤回：{args.assertion_id}")
    return 0


def _delete(args: argparse.Namespace) -> int:
    with _open(args) as store:
        store.delete_individual(args.id)
    print(f"已删除：{args.id}")
    return 0


def _export(args: argparse.Namespace) -> int:
    with _open(args) as store:
        payload = json.dumps(store.export_dict(), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
        print(f"已导出：{args.output}")
    else:
        print(payload)
    return 0


def _import_json(args: argparse.Namespace) -> int:
    document = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
    with _open(args) as store:
        store.import_dict(document, replace=args.replace)
    print(f"已导入：{args.file}")
    return 0


def _import_triples(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8-sig")
    with _open(args) as store:
        count = store.import_triples(text, ensure_individuals=args.ensure)
    print(f"已导入 {count} 条")
    return 0


def _split_pair(raw: str, flag: str) -> tuple[str, str]:
    if "=" not in raw:
        raise OntologyError(f"{flag} 需要 key=value")
    key, value = raw.split("=", 1)
    if not key or not value:
        raise OntologyError(f"{flag} 需要 key=value")
    return key, value


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
