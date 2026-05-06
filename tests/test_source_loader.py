from pathlib import Path

from test_agent.source_loader import SourceLoader


def test_source_loader_reads_local_prd_file(tmp_path: Path) -> None:
    prd = tmp_path / "sample.prd"
    prd.write_text("- 系统需要支持用户登录\n- 系统应支持关键词搜索\n", encoding="utf-8")

    loader = SourceLoader()
    artifact = loader.load(str(prd))

    assert artifact.kind == "prd"
    assert artifact.identifier == str(prd)
    assert "系统需要支持用户登录" in artifact.content
    assert artifact.metadata["extension"] == "prd"


def test_source_loader_uses_inline_text_when_path_not_exists() -> None:
    loader = SourceLoader()
    artifact = loader.load("用户应可以提交订单并查看订单状态")

    assert artifact.kind == "text"
    assert artifact.identifier == "inline-text"
    assert "提交订单" in artifact.content
