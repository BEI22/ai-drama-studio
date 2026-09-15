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

# Phase 4 prompts embed machine-readable JSON blocks so a deterministic provider
# can answer them without an LLM: the roster carries the real database ids that
# the script must echo back, and <script> carries the scenes the storyboard must
# cover. Parsing them is what lets the mock satisfy PRD section 10's id-binding
# rule instead of inventing identifiers.
_EPISODE_COUNT_RE = re.compile(r"拆解为\s*(\d+)\s*集")


def _block(prompt: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", prompt, re.DOTALL)
    return match.group(1).strip() if match else None


def _json_block(prompt: str, tag: str) -> Any | None:
    raw = _block(prompt, tag)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


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

# Phase 4 fixtures. Deterministic so a re-run produces byte-identical episodes,
# which is what makes the acceptance script's re-run checks meaningful.
_EMOTION_PALETTE = (
    "压抑的平静",
    "迟疑",
    "故作轻松",
    "克制的愤怒",
    "疲惫",
    "下定决心",
)

_MOVEMENT_TEXT = {
    "static": "固定",
    "slow_push": "缓慢推近",
    "push_in": "推近",
    "pull_out": "拉远",
    "pan_left": "向左摇",
    "pan_right": "向右摇",
    "tilt_up": "向上摇",
    "tilt_down": "向下摇",
    "tracking": "跟随移动",
    "crane": "升降移动",
    "handheld": "手持轻微晃动",
}

_ACTION_BY_SIZE = {
    "extreme_wide": "在广阔空间中孤身伫立",
    "wide": "身处环境之中，交代空间关系",
    "medium": "与对手形成对峙站位",
    "medium_close_up": "上半身入画，做出关键动作",
    "close_up": "面部特写，情绪在眼神中变化",
    "extreme_close_up": "极近距离捕捉细节微动",
}


def _dialogue_for(beat: str, name: str | None) -> str:
    """A short, plausible line derived from the beat -- never a real quote."""
    speaker = name or "我"
    cleaned = beat.strip().rstrip("。！？!?")
    if not cleaned:
        return f"{speaker}：这次我不会再退。"
    return f"{cleaned[:40]}。" if len(cleaned) <= 40 else f"{cleaned[:40]}……"


def _action_for(shot_size: str) -> str:
    return _ACTION_BY_SIZE.get(shot_size, "自然地完成动作")


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
        elif schema_title == "EpisodePlanList":
            payload = self._build_episode_plan(request.prompt, story)
        elif schema_title == "ScriptContent":
            payload = self._build_script(request.prompt)
        elif schema_title == "StoryboardContent":
            payload = self._build_storyboard(request.prompt)
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

    # ------------------------------------------------------- Phase 4 builders
    def _build_episode_plan(self, prompt: str, story: str) -> dict[str, Any]:
        """Split the story into N episodes, titled from real sentences."""
        match = _EPISODE_COUNT_RE.search(prompt)
        desired = int(match.group(1)) if match else 6
        desired = max(1, min(desired, len(h.split_sentences(story)) or 1, 12))

        sentences = h.split_sentences(story)
        if not sentences:
            sentences = ["故事开始"]

        episodes: list[dict[str, Any]] = []
        for index in range(desired):
            # Spread the summary across the story so later episodes are not all
            # copies of the opening line.
            position = int(index * len(sentences) / desired)
            closing = int((index + 1) * len(sentences) / desired)
            chunk = sentences[position : max(closing, position + 1)]

            episodes.append(
                {
                    "episode_number": index + 1,
                    "title": h.episode_title(chunk, index),
                    "summary": " ".join(chunk)[:300] or sentences[position][:200],
                    "duration": 180,
                }
            )

        return {"episodes": episodes, "_mock": True}

    def _build_script(self, prompt: str) -> dict[str, Any]:
        """Write a script that binds to the *real* roster ids from the prompt.

        This is the point of parsing ``<roster>``: PRD section 10 forbids invented
        identifiers, and a mock that made up ids would make the node's binding
        check untestable offline.
        """
        roster = _json_block(prompt, "roster") or {}
        characters = [c for c in (roster.get("characters") or []) if c.get("id")]
        locations = [loc for loc in (roster.get("locations") or []) if loc.get("id")]
        episode = _json_block(prompt, "episode") or {}

        if not characters or not locations:
            # The node raises before reaching here; raise a ProviderError so the
            # failure is attributed to provider input rather than a KeyError.
            raise ProviderError("MockLLMProvider: script 生成需要 roster 中的 characters/locations")

        summary = str(episode.get("summary") or "")
        beats = h.split_sentences(summary) or [summary or "本集开始"]
        scene_total = max(3, min(len(beats), 14))

        scenes: list[dict[str, Any]] = []
        for index in range(scene_total):
            location = locations[index % len(locations)]
            # A rotating pair of speakers keeps every scene's cast plausible
            # without needing to parse who is actually in the summary.
            speaker = characters[index % len(characters)]
            partner = characters[(index + 1) % len(characters)]
            present = [speaker["id"]]
            if partner["id"] != speaker["id"]:
                present.append(partner["id"])

            beat = beats[index] if index < len(beats) else beats[-1]
            scenes.append(
                {
                    "scene_id": f"S{index + 1}",
                    "location_id": location["id"],
                    "time": location.get("time") or "白天",
                    "description": beat[:400],
                    "characters": present,
                    "dialogues": [
                        {
                            "character_id": speaker["id"],
                            "text": _dialogue_for(beat, speaker.get("name")),
                            "emotion": _EMOTION_PALETTE[index % len(_EMOTION_PALETTE)],
                        }
                    ],
                }
            )

        return {
            "title": episode.get("title") or "本集",
            "summary": summary[:400] or None,
            "scenes": scenes,
            "_mock": True,
        }

    def _build_storyboard(self, prompt: str) -> dict[str, Any]:
        """Build one storyboard section per script scene, reusing its dialogue."""
        script = _json_block(prompt, "script") or {}
        roster = _json_block(prompt, "roster") or {}
        locations = {loc["id"]: loc for loc in (roster.get("locations") or []) if loc.get("id")}
        characters = {c["id"]: c for c in (roster.get("characters") or []) if c.get("id")}
        style = h.infer_style("", self._hints(prompt)[1]) or "写实"

        scenes: list[dict[str, Any]] = []
        for scene in script.get("scenes") or []:
            if not scene.get("scene_id"):
                continue
            location = locations.get(str(scene.get("location_id")), {})
            environment = location.get("description") or "剧情发生的场景"
            lighting = location.get("lighting") or "自然光"
            scene_characters = scene.get("characters") or []
            names = [
                str(characters[cid]["name"])
                for cid in scene_characters
                if cid in characters and characters[cid].get("name")
            ]
            dialogues = scene.get("dialogues") or []

            shots: list[dict[str, Any]] = []
            # Opening establishing shot, then one shot per dialogue, then a
            # closing beat -- enough shots to be realistic and to exercise the
            # consistency checker's per-shot rules.
            plan: list[dict[str, Any]] = [
                {
                    "size": "wide",
                    "movement": "slow_push",
                    "duration": 5,
                    "dialogue": None,
                    "characters": names,
                }
            ]
            for index, line in enumerate(dialogues[:6]):
                speaker = line.get("character_id")
                speaker_name = (
                    str(characters[speaker]["name"])
                    if speaker in characters and characters[speaker].get("name")
                    else None
                )
                plan.append(
                    {
                        "size": "medium_close_up" if index % 2 == 0 else "close_up",
                        "movement": "static" if index % 2 == 0 else "push_in",
                        "duration": 4,
                        "dialogue": line.get("text"),
                        "characters": [speaker_name] if speaker_name else names,
                    }
                )
            plan.append(
                {
                    "size": "medium",
                    "movement": "pull_out",
                    "duration": 5,
                    "dialogue": None,
                    "characters": names,
                }
            )

            for index, shot_plan in enumerate(plan, start=1):
                prompted = [
                    name
                    for name in (shot_plan["characters"] or [])
                    if name in {str(c.get("name")) for c in characters.values()}
                ]
                appearance = "；".join(
                    filter(
                        None,
                        (
                            str(characters[cid].get("appearance") or "")
                            for cid in scene_characters
                            if cid in characters and characters[cid].get("name") in prompted
                        ),
                    )
                )
                shots.append(
                    {
                        "shot_number": index,
                        "duration": shot_plan["duration"],
                        "shot_size": shot_plan["size"],
                        "camera_movement": shot_plan["movement"],
                        "characters": prompted,
                        "action": _action_for(shot_plan["size"]),
                        "expression": _EMOTION_PALETTE[index % len(_EMOTION_PALETTE)],
                        "dialogue": shot_plan["dialogue"],
                        "visual_description": (
                            f"{environment}，{lighting}，"
                            f"{'、'.join(prompted) or '无人物'}{_action_for(shot_plan['size'])}"
                        )[:400],
                        # Deliberately mentions style + lighting + appearance, so
                        # the consistency checker's substring evidence has
                        # something real to find on a clean storyboard.
                        "image_prompt": (
                            f"{style}风格漫剧分镜，{shot_plan['size']}景别，"
                            f"{environment}，{lighting}，"
                            f"{'、'.join(prompted) or '空镜'}，"
                            f"{appearance or '环境为主体'}，画面氛围沉静"
                        )[:2000],
                        "video_prompt": (
                            f"镜头{_MOVEMENT_TEXT.get(shot_plan['movement'], '固定')}，"
                            "画面内人物动作自然衔接，无闪烁"
                        ),
                    }
                )

            scenes.append({"scene_id": str(scene["scene_id"]), "shots": shots})

        return {"scenes": scenes, "_mock": True}


__all__ = ["MockLLMProvider"]
