"""Mock LLM provider (PRD section 37 item 8).

Lets the entire Story Agent pipeline run end to end with **no API key and no
network**, which is what makes the Phase 3 tests deterministic and the demo
runnable offline.

How it works: the provider inspects ``LLMRequest.json_schema["title"]`` to learn
which node is calling, extracts ``<story>...</story>`` from the prompt, and runs
the deterministic heuristics in :mod:`app.providers.llm.heuristics`.

This is explicitly **not** AI. Every payload carries ``"_mock": true`` so the API
and UI can label it, and a real provider is selected with ``LLM_PROVIDER=openai``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

from app.core.exceptions import ProviderError
from app.providers.base import LLMProvider, LLMRequest, LLMResult
from app.providers.llm import heuristics as h

logger = logging.getLogger(__name__)

_STORY_RE = re.compile(r"<story>(.*?)</story>", re.DOTALL)
_GENRE_RE = re.compile(r"题材：\s*(\S+)")
_STYLE_RE = re.compile(r"画风：\s*(\S+)")

# Deterministic palettes: the same name always yields the same look, which keeps
# re-runs stable and makes the later consistency work testable.
_HAIR_PALETTE = (
    "黑色短发，发梢微微翘起",
    "深棕色齐肩发",
    "黑色中长发，用发圈束起",
    "短发利落，额前碎发",
    "黑色马尾",
    "微卷的栗色短发",
)
_CLOTHING_PALETTE = (
    "简约白色衬衫配深色长裤",
    "浅灰连帽卫衣与牛仔裤",
    "深蓝色校服外套",
    "黑色长风衣",
    "米色针织衫配半身裙",
    "运动夹克与运动鞋",
)
_TRAIT_PALETTE = (
    ("冷静", "隐忍", "观察力强"),
    ("热血", "直率", "重情义"),
    ("谨慎", "务实", "擅长算计"),
    ("温和", "固执", "不轻易放弃"),
    ("孤傲", "自律", "对自己要求极高"),
)
_AGE_BY_ROLE = {
    "PROTAGONIST": "20 岁上下",
    "ANTAGONIST": "30 岁上下",
    "MENTOR": "50 岁上下",
    "LOVE_INTEREST": "20 岁上下",
    "SUPPORTING": "20-30 岁",
    "OTHER": "不详",
}


def _stable_index(seed: str, modulo: int) -> int:
    """Deterministic index so repeated runs produce identical output."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def _infer_gender(name: str, story: str) -> str | None:
    """Guess from pronouns near the name, or return ``None`` when unclear.

    Deliberately conservative: a wrong gender propagates into later image and TTS
    prompts, so a single ambiguous pronoun yields ``None`` ("—" in the UI) rather
    than a coin-flip. Requires a net majority of at least two.
    """
    index = story.find(name)
    if index < 0:
        return None

    window = story[max(0, index - 40) : index + 80]
    female = window.count("她")
    male = window.count("他") - female

    if female - male >= 2:
        return "女"
    if male - female >= 2:
        return "男"
    return None


class MockLLMProvider(LLMProvider):
    """Offline, deterministic stand-in for a real LLM."""

    name: str = "mock"

    def __init__(
        self,
        *,
        fail_times: int = 0,
        latency_ms: int = 0,
        model: str = "mock-llm-v1",
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(name="mock", model=model, timeout_seconds=timeout_seconds)
        self._fail_times = fail_times
        self._latency_ms = latency_ms
        self._calls = 0

    # ------------------------------------------------------------------ plumbing
    async def health(self) -> bool:
        return True

    @property
    def calls(self) -> int:
        """Number of ``generate`` invocations (used by tests)."""
        return self._calls

    async def generate(self, request: LLMRequest) -> LLMResult:
        self._calls += 1

        if self._latency_ms:
            await asyncio.sleep(self._latency_ms / 1000)

        # Deliberate failures so the retry path is testable without a network.
        if self._calls <= self._fail_times:
            raise ProviderError(f"mock provider 第 {self._calls} 次调用按配置失败")

        story = self._extract_story(request.prompt)
        schema_title = (request.json_schema or {}).get("title") or ""

        if schema_title == "StoryBibleContent":
            payload = self._build_story_bible(request.prompt, story)
        elif schema_title == "CharacterExtraction":
            payload = self._build_characters(story)
        elif schema_title == "LocationExtraction":
            payload = self._build_locations(request.prompt, story)
        else:
            raise ProviderError(f"MockLLMProvider 不支持 schema: {schema_title!r}")

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        return LLMResult(
            text=text,
            model=self.model,
            # Rough stand-in so cost/quota accounting has something to chew on.
            input_tokens=len(request.prompt) // 2,
            output_tokens=len(text) // 2,
            estimated_cost=0.0,
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _extract_story(prompt: str) -> str:
        match = _STORY_RE.search(prompt)
        if match:
            return match.group(1).strip()
        # Fall back to the whole prompt so a malformed template still yields
        # something, rather than silently returning empty content.
        return prompt.strip()

    @staticmethod
    def _hints(prompt: str) -> tuple[str | None, str | None]:
        """Read the genre/style hints, treating the template placeholder as absent."""

        def clean(value: str | None) -> str | None:
            if value is None:
                return None
            stripped = value.strip().strip("（）()")
            if not stripped or stripped in {"未指定", "None", "null", "-", ""}:
                return None
            return stripped

        genre = _GENRE_RE.search(prompt)
        style = _STYLE_RE.search(prompt)
        return clean(genre.group(1) if genre else None), clean(style.group(1) if style else None)

    def _build_story_bible(self, prompt: str, story: str) -> dict[str, Any]:
        genre_hint, style_hint = self._hints(prompt)
        sentences = h.split_sentences(story)

        title = h.infer_title(story)
        genre = h.infer_genre(story, genre_hint)
        style = h.infer_style(story, style_hint)

        logline = sentences[0] if sentences else story[:80]
        background = " ".join(sentences[:3])[:600] if sentences else story[:600]

        world_rules: list[str] = []
        # "重生" rarely appears literally; authors write "回到十年前" / "重回".
        is_regression = any(
            marker in story
            for marker in ("重生", "回到", "重回", "重来", "再活一次", "十年前", "上一世", "前世")
        )
        if is_regression:
            world_rules.extend(
                [
                    "重生者保留前世的完整记忆",
                    "时间线只能沿单一方向推进，已改变的因果不可撤销",
                    "重生的秘密不能被他人知晓，否则会引发不可控的连锁反应",
                ]
            )
        if "穿越" in story:
            world_rules.append("穿越者的现代认知与技术在该世界具有降维优势")
        if "系统" in story:
            world_rules.append("系统任务必须完成，失败将受到惩罚")
        if not world_rules:
            world_rules.append("故事遵循现实世界的基本物理与社会规则")

        main_conflict = "主角试图改变既定命运，却不断遭遇来自现实与他人的阻力"

        timeline = [sentence[:60] for sentence in sentences[:5]]
        if not timeline:
            timeline = ["故事开始"]

        events = [sentence[:60] for sentence in sentences[1:4]] or ["主角做出改变命运的决定"]

        objects: list[str] = []
        for marker in (
            "日记",
            "照片",
            "信件",
            "戒指",
            "手机",
            "项链",
            "笔记",
            "准考证",
            "录取通知书",
        ):
            if marker in story:
                objects.append(marker)

        return {
            "title": title,
            "genre": genre,
            "logline": logline,
            "background": background,
            "main_conflict": main_conflict,
            "style": style,
            "world_rules": world_rules,
            "timeline": timeline,
            "important_objects": objects,
            "important_events": events,
            "_mock": True,
        }

    def _build_characters(self, story: str) -> dict[str, Any]:
        names = h.extract_names(story)

        characters: list[dict[str, Any]] = []
        if not names:
            # No identifiable name in the text. Use honest role labels instead of
            # inventing people -- the UI can show these as "待补充".
            names = ["主角"]

        for index, name in enumerate(names):
            role = h.infer_role(name, story) if index else "PROTAGONIST"
            if index == 0 and role == "SUPPORTING":
                role = "PROTAGONIST"

            seed = f"{name}-{index}"
            traits = _TRAIT_PALETTE[_stable_index(seed, len(_TRAIT_PALETTE))]
            hair = _HAIR_PALETTE[_stable_index(seed + "hair", len(_HAIR_PALETTE))]
            clothing = _CLOTHING_PALETTE[_stable_index(seed + "cloth", len(_CLOTHING_PALETTE))]

            characters.append(
                {
                    "name": name,
                    "role": role,
                    "age": _AGE_BY_ROLE.get(role, "不详"),
                    "gender": _infer_gender(name, story),
                    "description": (
                        "故事的核心人物，全部剧情围绕其选择展开"
                        if role == "PROTAGONIST"
                        else f"与主角产生关键互动的人物（{role}）"
                    ),
                    "appearance": (
                        f"{_AGE_BY_ROLE.get(role, '青年')}，身形匀称，"
                        f"{hair}，常穿{clothing}，神情专注"
                    ),
                    "hair": hair,
                    "clothing": clothing,
                    "personality": list(traits),
                }
            )

        return {"characters": characters, "_mock": True}

    def _build_locations(self, prompt: str, story: str) -> dict[str, Any]:
        _, style_hint = self._hints(prompt)
        style = h.infer_style(story, style_hint)

        names = h.extract_locations(story)
        locations: list[dict[str, Any]] = []

        for name in names:
            sentence = h.sentence_containing(story, name)
            description = sentence or f"故事中反复出现的场景：{name}"

            locations.append(
                {
                    "name": name,
                    "description": description[:400],
                    "time": h.match_time(sentence) or h.match_time(story) or "白天",
                    "lighting": h.match_lighting(sentence) or h.match_lighting(story) or "自然光",
                    "visual_style": style,
                }
            )

        if not locations:
            locations.append(
                {
                    "name": "主要场景",
                    "description": story[:200] or "故事发生的主要场景",
                    "time": "白天",
                    "lighting": "自然光",
                    "visual_style": style,
                }
            )

        return {"locations": locations, "_mock": True}


__all__ = ["MockLLMProvider"]
