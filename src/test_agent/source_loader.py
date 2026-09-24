"""Load and normalize user-provided input artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import re
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import InputArtifact

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_FILE_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "latin-1")


@dataclass(slots=True)
class SourceLoader:
    """Normalize URL/file/text input into a common artifact model."""

    timeout_seconds: int = 12
    max_chars: int = 20_000
    allow_private_network: bool = False
    allowed_domains: tuple[str, ...] = ()

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
        self._validate_url_safety(url)
        request = Request(
            url=url,
            headers={"User-Agent": "auto-test-agent/0.2"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                content = raw.decode(charset, errors="replace")
        except URLError as exc:
            raise ValueError(f"无法访问 URL: {url}") from exc
        except OSError as exc:
            raise ValueError(f"URL 读取失败: {url}") from exc

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
        raw = path.read_bytes()
        encoding = "utf-8"
        content = ""
        for candidate in _FILE_ENCODINGS:
            try:
                content = raw.decode(candidate)
                encoding = candidate
                break
            except UnicodeDecodeError:
                continue
        if not content:
            content = raw.decode("utf-8", errors="replace")
            encoding = "utf-8(replace)"

        extension = path.suffix.lower().lstrip(".")
        kind = "prd" if extension in {"prd", "md", "txt", "rst"} else "file"
        return InputArtifact(
            kind=kind,
            identifier=str(path),
            content=content[: self.max_chars],
            metadata={
                "extension": extension or "none",
                "length": str(len(content)),
                "encoding": encoding,
            },
        )

    @staticmethod
    def _extract_title(html: str) -> str:
        match = _TITLE_RE.search(html)
        if not match:
            return ""
        return re.sub(r"\s+", " ", match.group(1)).strip()

    def _validate_url_safety(self, url: str) -> None:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL 缺少主机名")

        if self.allowed_domains:
            if not any(
                hostname == domain or hostname.endswith(f".{domain}")
                for domain in self.allowed_domains
            ):
                raise ValueError(f"URL 主机不在允许列表中: {hostname}")

        if self.allow_private_network:
            return

        if hostname in {"localhost"} or hostname.endswith(".local"):
            raise ValueError(f"出于安全原因，禁止访问内网主机: {hostname}")

        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            return
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError(f"出于安全原因，禁止访问内网地址: {hostname}")
