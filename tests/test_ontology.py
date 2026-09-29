import json
from pathlib import Path

import pytest

from shuzifensheng.ontology import NotFoundError, OntologyStore, SchemaError, ValidationError
from shuzifensheng.ontology.builtin import CLASSES, DISJOINT_GROUP
from shuzifensheng.ontology.cli import main

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo.triples"


def test_builtin_ontology_has_avatar_and_self():
    with OntologyStore(":memory:") as store:
        ids = {item.id for item in store.list_classes()}
        assert ids == {item.id for item in CLASSES}
        assert store.is_subclass("Experience", "Event")
        assert store.is_subclass("Experience", "Thing")
        assert not store.is_subclass("Skill", "Event")
        knows = store.get_object_property("knows")
        assert knows.symmetric and knows.inverse == "knows"
        located = store.get_object_property("located_in")
        assert located.transitive and located.inverse == "contains"
        assert store.get_object_property("has_skill").inverse == "skill_of"
        person = store.get_class("Person")
        assert set(DISJOINT_GROUP) - {"Person"} <= set(person.disjoint_with)
        self_view = store.get("self")
        assert self_view.types == ("Agent",)
        assert "Thing" in self_view.inferred_types
        assert self_view.labels["zh"] == "我"
        assert store.check() == ()


def test_disjoint_types_and_inherited_conflict():
    with OntologyStore(":memory:") as store:
        with pytest.raises(ValidationError):
            store.add_individual("mix", types=["Experience", "Place"])
        store.add_type("self", "Person")
        assert "Person" in store.get("self").types


def test_domain_range_functional_and_bounds():
    with OntologyStore(":memory:") as store:
        store.add_individual("org:x", types=["Organization"], labels={"zh": "某组织"})
        store.add_individual("skill:x", types=["Skill"], labels={"zh": "某技能"})
        with pytest.raises(ValidationError):
            store.assert_object("org:x", "has_skill", "skill:x")
        assert "has_skill" not in store.get("org:x").relations
        store.assert_object("self", "has_skill", "skill:x")
        with pytest.raises(ValidationError):
            store.assert_object("self", "has_skill", "org:x")
        store.assert_data("skill:x", "proficiency", 0.5)
        with pytest.raises(ValidationError):
            store.assert_data("skill:x", "proficiency", 1.2)
        with pytest.raises(ValidationError):
            store.assert_data("skill:x", "proficiency", 1)
        assert store.get("skill:x").attributes["proficiency"][0].value == 0.5
        first = store.assert_data("skill:x", "name", "某技能", confidence=0.4)
        second = store.assert_data("skill:x", "name", "某技能", confidence=0.9)
        assert first.id == second.id
        assert second.confidence == 0.9


def test_lenient_mode_reports_violations():
    with OntologyStore(":memory:", strict=False) as store:
        store.add_individual("mix", types=["Person", "Skill"])
        store.add_individual("org:x", types=["Organization"])
        store.add_individual("skill:x", types=["Skill"])
        store.assert_object("org:x", "has_skill", "skill:x")
        codes = {item.code for item in store.check()}
        assert "disjoint_individual" in codes
        assert "domain_violation" in codes


def test_open_world_then_incompatible_type():
    with OntologyStore(":memory:") as store:
        store.import_triples("self 掌握 skill:temp\n", ensure_individuals=True)
        assert store.check() == ()
        with pytest.raises(ValidationError):
            store.add_type("skill:temp", "Organization")


def test_schema_rules_and_rollback():
    with OntologyStore(":memory:") as store:
        with pytest.raises(SchemaError):
            store.define_class("Loop", parents=("Loop",))
        with pytest.raises(NotFoundError):
            store.add_individual("bad", types=["Person", "NoSuch"])
        with pytest.raises(NotFoundError):
            store.get("bad")
        store.define_class("Craft", labels={"zh": "技艺"}, description="一种手艺")
        assert store.is_subclass("Craft", "Thing")
        with pytest.raises(ValidationError):
            store.add_individual("1bad", types=["Craft"])


def test_demo_reasoning_roundtrip_and_persistence(tmp_path: Path):
    db_path = tmp_path / "avatar.db"
    with OntologyStore(db_path) as store:
        count = store.import_triples(DEMO.read_text(encoding="utf-8"))
        assert count > 0
        assert store.check() == ()
        me = store.get("self")
        assert "Person" in me.types
        assert me.relations["knows"][0].target == "person:lin"
        assert me.relations["knows"][0].inferred is False
        assert store.get("person:lin").relations["knows"][0].inferred is True
        assert store.get("skill:python").relations["skill_of"][0].target == "self"
        places = {item.target for item in store.expand("self", "located_in")}
        assert places == {"place:xihu", "place:hangzhou", "place:zhejiang"}
        contained = {item.target for item in store.expand("place:zhejiang", "contains")}
        assert {"place:hangzhou", "place:xihu", "org:lab", "self"} <= contained
        parts = {item.target for item in store.expand("exp:first", "part_of")}
        assert parts == {"proj:onto", "org:lab"}
        routes = store.paths("self", "place:zhejiang")
        assert routes
        assert routes[0][-1].target == "place:zhejiang"
        events = {item.id for item in store.query(type="Event")}
        assert events == {"exp:first"}
        assert store.query(type="Event", include_subclasses=False) == ()
        skills = store.query(type="Skill", attributes={"name": "Python"})
        assert [item.id for item in skills] == ["skill:python"]
        named = {item.id for item in store.query(label="林")}
        assert named == {"person:lin"}
        started = store.get("exp:first").attributes["started_at"][0].value
        assert started == "2026-09-28T16:00:00+00:00"
        snapshot = store.export_dict()

    with OntologyStore(db_path) as reopened:
        assert reopened.get("self").attributes["summary"][0].value.startswith("把经历")
        exported = json.loads(json.dumps(reopened.export_dict()))
        fresh = OntologyStore(":memory:", seed=False)
        fresh.import_dict(exported, replace=True)
        assert fresh.export_dict() == exported
        fresh.close()

    assert snapshot["format"] == "shuzifensheng.ontology"


def test_retract_delete_and_bad_time():
    with OntologyStore(":memory:") as store:
        store.add_individual("skill:x", types=["Skill"], labels={"zh": "某技能"})
        assertion = store.assert_object("self", "has_skill", "skill:x")
        store.retract(assertion.id)
        assert "has_skill" not in store.get("self").relations
        store.add_individual("person:a", types=["Person"], labels={"zh": "甲"})
        store.assert_object("self", "knows", "person:a")
        store.delete_individual("person:a")
        assert "knows" not in store.get("self").relations
        store.add_individual("exp:x", types=["Experience"])
        with pytest.raises(ValidationError):
            store.assert_data("exp:x", "started_at", "2026-09-29T00:00:00")


def test_cli_demo_flow(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    db = tmp_path / "cli.db"
    common = ["--db", str(db)]
    assert main([*common, "init"]) == 0
    assert main([*common, "import-triples", str(DEMO)]) == 0
    assert main([*common, "check"]) == 0
    assert "未发现不一致" in capsys.readouterr().out
    assert main([*common, "query", "--type", "Skill"]) == 0
    skills = json.loads(capsys.readouterr().out)
    assert skills[0]["id"] == "skill:python"
    assert main([*common, "paths", "self", "place:zhejiang"]) == 0
    assert "place:zhejiang" in capsys.readouterr().out
    exported = tmp_path / "onto.json"
    assert main([*common, "export", "-o", str(exported)]) == 0
    other = tmp_path / "other.db"
    assert main(["--db", str(other), "init"]) == 0
    assert main(["--db", str(other), "import", str(exported)]) == 0
    capsys.readouterr()
    assert main(["--db", str(other), "show", "self"]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["attributes"]["name"][0]["value"] == "我"
    assert main([*common, "assert", "self", "别名", "数字分身"]) == 0
    capsys.readouterr()
    assert main([*common, "show", "self"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["attributes"]["alias"][0]["value"] == "数字分身"
    assert main(["--db", str(tmp_path / "missing.db"), "stats"]) == 1
