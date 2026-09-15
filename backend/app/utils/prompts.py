"""Prompt loading and versioning (PRD section 20).

Prompts must not live inside Python business code; they are files under
``prompts/<domain>/<name>_v<N>.md``. Each file starts with a ``# Title`` heading
and a ``Version: <id>`` line, keeps its template under a ``## User`` section, and
may be rendered with ``str.format`` style placeholders.

The version id is recorded on every generation so prompt changes can be A/B
tested later (PRD section 20: "数据库记录 prompt_version").
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.core.config import REPO_DIR
from app.core.exceptions import NotFoundError

PROMPTS_DIR = REPO_DIR / "prompts"

_VERSION_RE = re.compile(r"^Version:\s*`?([A-Za-z0-9_\-]+)`?\s*$", re.MULTILINE)
_USER_SECTION_RE = re.compile(r"^##\s+User\s*$(.*)", re.MULTILINE | re.DOTALL)
_SYSTEM_SECTION_RE = re.compile(r"^##\s+System\s*$(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class Prompt:
    """A loaded, renderable prompt template."""

    __slots__ = ("version", "path", "system", "user_template")

    def __init__(self, *, version: str, path: Path, system: str, user_template: str) -> None:
        self.version = version
        self.path = path
        self.system = system
        self.user_template = user_template

    @property
    def placeholders(self) -> frozenset[str]:
        """The ``{name}`` variables this prompt expects.

        Lets callers and tests assert the call signature without invoking
        ``render`` -- useful when bumping a prompt version, where an accidental
        placeholder change would otherwise only surface at runtime.
        """
        found = _PLACEHOLDER_RE.findall(self.system) + _PLACEHOLDER_RE.findall(self.user_template)
        return frozenset(found)

    def render(self, **values: object) -> tuple[str, str]:
        """Return ``(system, user)`` with placeholders substituted.

        Missing keys raise ``KeyError`` on purpose: a typo in a prompt variable
        should fail loudly in tests, not silently ship `{story_text}` to the LLM.
        """
        return self.system, self.user_template.format(**values)


@lru_cache(maxsize=64)
def load_prompt(relative_path: str) -> Prompt:
    """Load ``prompts/<relative_path>.md`` (cache-friendly, no extension)."""
    path = PROMPTS_DIR / f"{relative_path}.md"
    if not path.exists():
        raise NotFoundError(f"Prompt 不存在：{relative_path}")

    text = path.read_text(encoding="utf-8")

    version_match = _VERSION_RE.search(text)
    version = version_match.group(1) if version_match else path.stem

    system_match = _SYSTEM_SECTION_RE.search(text)
    system = system_match.group(1).strip() if system_match else ""

    user_match = _USER_SECTION_RE.search(text)
    user_template = user_match.group(1).strip() if user_match else text.strip()

    return Prompt(version=version, path=path, system=system, user_template=user_template)


def prompt_version(relative_path: str) -> str:
    return load_prompt(relative_path).version


def clear_cache() -> None:
    """Used by tests that edit prompt files."""
    load_prompt.cache_clear()


__all__ = ["PROMPTS_DIR", "Prompt", "clear_cache", "load_prompt", "prompt_version"]
