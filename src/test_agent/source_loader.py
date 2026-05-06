"""Load and normalize user-provided input artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import InputArtifact

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass(slots=True)
class SourceLoader:
    """Normalize URL/file/text input into a common artifact model."""

    timeout_seconds: int = 12
    max_chars: int = 20_000

    def load(self, source: str) -> InputArtifact:
        """Load artifact by automatically detecting source type."""
        normalized = source.strip()
        if not normalized:
            raise ValueError("source must not be empty")

        if self._is_url(normalized):
            return self._load_url(normalized)

        candidate = Path(normalized)
        if candidate.exists() and candidate.is_file():
            return self._load_file(candidate)

        return InputArtifact(
            kind="text",
            identifier="inline-text",
            content=normalized[: self.max_chars],
            metadata={"length": str(len(normalized))},
        )

    @staticmethod
    def _is_url(source: str) -> bool:
        parsed = urlparse(source)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _load_url(self, url: str) -> InputArtifact:
        request = Request(
            url=url,
            headers={"User-Agent": "auto-test-agent/0.2"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            content = raw.decode(charset, errors="replace")

        title = self._extract_title(content)
        return InputArtifact(
            kind="website",
            identifier=url,
            content=content[: self.max_chars],
            metadata={
                "title": title,
                "length": str(len(content)),
            },
        )

    def _load_file(self, path: Path) -> InputArtifact:
        content = path.read_text(encoding="utf-8")
        extension = path.suffix.lower().lstrip(".")
        kind = "prd" if extension in {"prd", "md", "txt"} else "file"
        return InputArtifact(
            kind=kind,
            identifier=str(path),
            content=content[: self.max_chars],
            metadata={"extension": extension or "none", "length": str(len(content))},
        )

    @staticmethod
    def _extract_title(html: str) -> str:
        match = _TITLE_RE.search(html)
        if not match:
            return ""
        return re.sub(r"\s+", " ", match.group(1)).strip()
