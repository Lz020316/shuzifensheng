"""Generate test cases from normalized input artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import InputArtifact, TestCase

_REQ_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s*(.+)$")


@dataclass(slots=True)
class TestCaseGenerator:
    """Heuristic test case generation for websites and documents."""

    max_cases: int = 12

    def generate(self, artifact: InputArtifact) -> list[TestCase]:
        """Generate actionable test cases from an input artifact."""
        if artifact.kind == "website":
            return self._generate_for_website(artifact)
        return self._generate_for_requirement_text(artifact)

    def _generate_for_website(self, artifact: InputArtifact) -> list[TestCase]:
        title = artifact.metadata.get("title", "")
        cases: list[TestCase] = [
            TestCase(
                case_id="TC-001",
                title="页面可访问",
                steps=["打开网站首页"],
                expected_result="页面加载成功且返回可见内容",
                source_ref=artifact.identifier,
            ),
            TestCase(
                case_id="TC-002",
                title="页面包含核心文案",
                steps=["打开网站首页", "核对页面文本"],
                expected_result="页面包含至少一个核心业务关键词",
                source_ref=artifact.identifier,
            ),
        ]
        if title:
            cases.append(
                TestCase(
                    case_id="TC-003",
                    title="页面标题正确渲染",
                    steps=["打开网站首页", "读取页面标题"],
                    expected_result=f"页面标题包含“{title}”",
                    source_ref=artifact.identifier,
                )
            )
        return cases[: self.max_cases]

    def _generate_for_requirement_text(self, artifact: InputArtifact) -> list[TestCase]:
        extracted = self._extract_requirement_lines(artifact.content)
        if not extracted:
            extracted = self._extract_sentence_candidates(artifact.content)

        cases: list[TestCase] = []
        for idx, requirement in enumerate(extracted[: self.max_cases], start=1):
            case_id = f"TC-{idx:03d}"
            cases.append(
                TestCase(
                    case_id=case_id,
                    title=f"需求校验: {requirement[:30]}",
                    steps=["根据需求执行关键业务路径", "检查系统反馈"],
                    expected_result=requirement,
                    source_ref=artifact.identifier,
                )
            )
        return cases

    @staticmethod
    def _extract_requirement_lines(content: str) -> list[str]:
        lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            match = _REQ_LINE_RE.match(stripped)
            candidate = match.group(1).strip() if match else stripped
            if any(token in candidate for token in ("应", "需要", "必须", "支持", "must", "should")):
                lines.append(candidate)
        return lines

    @staticmethod
    def _extract_sentence_candidates(content: str) -> list[str]:
        candidates: list[str] = []
        normalized = re.sub(r"\s+", " ", content)
        for chunk in re.split(r"[。！？.!?;；]", normalized):
            text = chunk.strip()
            if len(text) < 8:
                continue
            candidates.append(text)
        return candidates
