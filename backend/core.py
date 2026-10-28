"""Core novel-to-speech building blocks.

The module deliberately keeps parsing and voice assignment independent from the
web framework.  A UI can parse a novel first, let a user adjust role voices,
and then pass the resulting segments to :class:`TTSGenerator`.

``edge-tts`` is an optional dependency.  Importing this module does not require
it; audio generation reports a useful installation message when it is missing.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


NARRATOR = "旁白"
UNKNOWN_SPEAKER = "未识别角色"


@dataclass
class VoiceProfile:
    """Voice settings passed to a TTS provider."""

    voice: str
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"


@dataclass
class Segment:
    """A narration or dialogue unit that can be rendered independently."""

    id: int
    text: str
    speaker: str = NARRATOR
    is_dialogue: bool = False
    voice: str | None = None
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"


@dataclass
class Chapter:
    """A chapter and its parsed speech segments."""

    number: int
    title: str
    text: str
    segments: list[Segment] = field(default_factory=list)


_CHAPTER_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:"
    r"第\s*(?P<cn>[零〇一二三四五六七八九十百千万两\d]+)\s*[章节回](?:\s*[-:：.]?\s*(?P<cn_title>.*))?"
    r"|(?:chapter|chap\.)\s*(?P<en>\d+)\s*[-:：.]?\s*(?P<en_title>.*)"
    r")\s*$",
    re.IGNORECASE,
)

_QUOTE_RE = re.compile(r"“(?P<cjk>[^”]*)”|「(?P<book>[^」]*)」|『(?P<corner>[^』]*)』|\"(?P<double>[^\"]*)\"|‘(?P<single>[^’]*)’")
_ROLE_LINE_RE = re.compile(r"^\s*(?P<speaker>[^\s:：]{1,30})\s*[：:]\s*(?P<text>.+?)\s*$")
_SPEECH_VERBS = (
    "说道",
    "说着",
    "说",
    "道",
    "问道",
    "答道",
    "喊道",
    "叫道",
    "喝道",
    "怒道",
    "笑道",
    "喃喃道",
    "低声道",
    "轻声道",
    "冷冷地说",
    "回答",
    "问",
    "答",
)
_SPEECH_VERB_RE = "(?:" + "|".join(map(re.escape, sorted(_SPEECH_VERBS, key=len, reverse=True))) + ")"
_BEFORE_ATTRIBUTION_RE = re.compile(
    rf"(?P<speaker>[\u4e00-\u9fffA-Za-z][\w·\u4e00-\u9fff]{{0,20}}?)\s*{_SPEECH_VERB_RE}\s*[:：]?$"
)
_AFTER_ATTRIBUTION_RE = re.compile(
    rf"^\s*(?P<speaker>[\u4e00-\u9fffA-Za-z][\w·\u4e00-\u9fff]{{0,20}}?)\s*{_SPEECH_VERB_RE}"
)
_RELATION_ATTRIBUTION_RE = re.compile(
    rf"(?:对|向)\s*(?P<speaker>[\u4e00-\u9fffA-Za-z][\w·\u4e00-\u9fff]{{0,20}}?)\s*{_SPEECH_VERB_RE}\s*[:：]?"
)


def _chinese_number(value: str) -> int:
    """Convert the common Chinese chapter number forms to an integer."""

    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    section = 0
    number = 0
    for char in value:
        if char in digits:
            number = digits[char]
        elif char in units:
            unit = units[char]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
    return total + section + number


def _chapter_header(match: re.Match[str]) -> tuple[int, str]:
    if match.group("cn") is not None:
        number = _chinese_number(match.group("cn"))
        title = (match.group("cn_title") or "").strip()
        return number, title or f"第{match.group('cn')}章"
    number = int(match.group("en"))
    title = (match.group("en_title") or "").strip()
    return number, title or f"Chapter {number}"


def parse_chapters(text: str, *, parse_speech: bool = True) -> list[Chapter]:
    """Split a novel into chapters using Chinese or English chapter headings.

    If no heading is present, the whole input is returned as chapter 1.  The
    heading itself is omitted from ``Chapter.text``.  Empty chapters are kept,
    which lets a UI show the source structure faithfully.
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    lines = normalized.split("\n") if normalized else []
    starts: list[tuple[int, int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = _CHAPTER_RE.match(line)
        if match:
            starts.append((index, index, match))

    if not starts:
        body = normalized.strip()
        chapter = Chapter(number=1, title="正文", text=body)
        if parse_speech and body:
            chapter.segments = parse_segments(body)
        return [chapter]

    chapters: list[Chapter] = []
    # Text before the first heading is useful as a prologue and should not be lost.
    first_index = starts[0][0]
    if first_index:
        prologue = "\n".join(lines[:first_index]).strip()
        if prologue:
            chapter = Chapter(number=0, title="序章", text=prologue)
            if parse_speech:
                chapter.segments = parse_segments(prologue)
            chapters.append(chapter)

    for position, (start, _, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        number, title = _chapter_header(match)
        body = "\n".join(lines[start + 1 : end]).strip()
        chapter = Chapter(number=number, title=title, text=body)
        if parse_speech and body:
            chapter.segments = parse_segments(body)
        chapters.append(chapter)
    return chapters


def _clean_dialogue(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _append_segment(segments: list[Segment], text: str, *, speaker: str, is_dialogue: bool) -> None:
    cleaned = _clean_dialogue(text)
    if not cleaned or not re.search(r"[\w\u3400-\u9fff]", cleaned, flags=re.UNICODE):
        return
    segments.append(
        Segment(
            id=len(segments) + 1,
            text=cleaned,
            speaker=speaker.strip() or (UNKNOWN_SPEAKER if is_dialogue else NARRATOR),
            is_dialogue=is_dialogue,
        )
    )


def _append_role_dialogue(text: str, default_speaker: str, segments: list[Segment]) -> None:
    """Append a colon-prefixed role line, including multiple quoted utterances."""

    matches = list(_QUOTE_RE.finditer(text))
    if not matches:
        _append_segment(segments, text, speaker=default_speaker, is_dialogue=True)
        return
    cursor = 0
    for index, match in enumerate(matches):
        prefix = text[cursor : match.start()]
        speaker = default_speaker
        attribution = _RELATION_ATTRIBUTION_RE.search(prefix) or _BEFORE_ATTRIBUTION_RE.search(prefix)
        if attribution:
            speaker = attribution.group("speaker")
            leading = prefix[: attribution.start()]
            if re.sub(r"[\s，,、；;]", "", leading):
                _append_segment(segments, leading, speaker=default_speaker, is_dialogue=False)
        elif prefix.strip():
            _append_segment(segments, prefix, speaker=default_speaker, is_dialogue=True)
        content = next((group for group in match.groups() if group is not None), "")
        _append_segment(segments, content, speaker=speaker, is_dialogue=True)
        cursor = match.end()
    _append_segment(segments, text[cursor:], speaker=default_speaker, is_dialogue=False)


def _split_line(line: str, segments: list[Segment]) -> None:
    role_line = _ROLE_LINE_RE.match(line)
    if role_line and len(role_line.group("speaker")) <= 20:
        speaker = role_line.group("speaker")
        attribution = _BEFORE_ATTRIBUTION_RE.fullmatch(f"{speaker}：")
        if attribution:
            speaker = attribution.group("speaker")
            _append_role_dialogue(role_line.group("text"), speaker, segments)
            return
        _append_segment(segments, role_line.group("text"), speaker=speaker, is_dialogue=True)
        return

    matches = list(_QUOTE_RE.finditer(line))
    if not matches:
        _append_segment(segments, line, speaker=NARRATOR, is_dialogue=False)
        return

    cursor = 0
    for match in matches:
        prefix = line[cursor : match.start()]
        content = next((group for group in match.groups() if group is not None), "")
        before = _BEFORE_ATTRIBUTION_RE.search(prefix)
        speaker = before.group("speaker") if before else UNKNOWN_SPEAKER
        if before:
            leading = prefix[: before.start()]
            _append_segment(segments, leading, speaker=NARRATOR, is_dialogue=False)
        else:
            _append_segment(segments, prefix, speaker=NARRATOR, is_dialogue=False)

        suffix_start = match.end()
        next_match_start = matches[matches.index(match) + 1].start() if match is not matches[-1] else len(line)
        suffix = line[suffix_start:next_match_start]
        after = _AFTER_ATTRIBUTION_RE.match(suffix)
        if after:
            speaker = after.group("speaker")
        _append_segment(segments, content, speaker=speaker, is_dialogue=True)
        if after:
            remainder = suffix[after.end() :]
            _append_segment(segments, remainder, speaker=NARRATOR, is_dialogue=False)
            cursor = next_match_start
        else:
            cursor = match.end()

    # If the final quote had no attribution, cursor is already at its end.
    _append_segment(segments, line[cursor:], speaker=NARRATOR, is_dialogue=False)


def parse_segments(text: str) -> list[Segment]:
    """Extract narration and dialogue units from chapter text.

    Supported dialogue forms include quoted Chinese text (``“...”``/``「...」``),
    English quotes, and explicit lines such as ``林黛玉：你来了。``.  Speaker
    attribution before or after a quote is recognized for common Chinese speech
    verbs; ambiguous dialogue is labelled ``未识别角色`` for manual correction.
    """

    segments: list[Segment] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            _split_line(line.strip(), segments)
    return segments


DEFAULT_VOICES: tuple[str, ...] = (
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-XiaoyiNeural",
    "zh-CN-YunjianNeural",
    "zh-CN-XiaoxuanNeural",
    "zh-CN-YunyangNeural",
)


def assign_voices(
    segments: Sequence[Segment],
    voice_map: Mapping[str, str | VoiceProfile] | None = None,
    *,
    available_voices: Sequence[str] = DEFAULT_VOICES,
) -> list[Segment]:
    """Return copies of ``segments`` with stable voices assigned by speaker.

    ``voice_map`` takes precedence.  Unmapped speakers receive voices in first
    appearance order, so the same novel gets the same assignments between runs.
    ``VoiceProfile`` values can also set rate, pitch, and volume per role.
    """

    if not available_voices:
        raise ValueError("available_voices cannot be empty")
    configured = voice_map or {}
    assigned: dict[str, VoiceProfile] = {}
    next_voice = 0
    output: list[Segment] = []

    for segment in segments:
        profile = configured.get(segment.speaker)
        if isinstance(profile, str):
            profile = VoiceProfile(profile)
        if profile is None:
            profile = assigned.get(segment.speaker)
        if profile is None:
            profile = VoiceProfile(available_voices[next_voice % len(available_voices)])
            assigned[segment.speaker] = profile
            next_voice += 1
        output.append(
            Segment(
                id=segment.id,
                text=segment.text,
                speaker=segment.speaker,
                is_dialogue=segment.is_dialogue,
                voice=profile.voice,
                rate=profile.rate,
                pitch=profile.pitch,
                volume=profile.volume,
            )
        )
    return output


def detect_roles(value: str | Sequence[Segment]) -> list[str]:
    """Return speakers in first-appearance order from text or parsed segments."""

    segments = parse_segments(value) if isinstance(value, str) else value
    roles: list[str] = []
    for segment in segments:
        if segment.speaker not in roles:
            roles.append(segment.speaker)
    return roles


class TTSGenerator:
    """Render parsed segments to MP3 files with optional ``edge-tts``.

    The provider is imported lazily so parsing works in a minimal Python
    installation.  Generated files are accompanied by a JSON manifest that a
    player can use to preserve chapter and role boundaries.
    """

    def __init__(self, output_dir: str | Path, *, default_voice: str = DEFAULT_VOICES[0]):
        self.output_dir = Path(output_dir)
        self.default_voice = default_voice

    @staticmethod
    def _safe_name(value: str) -> str:
        value = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", value, flags=re.UNICODE).strip("_")
        return value or "audio"

    async def generate_segment(self, segment: Segment, output_path: str | Path) -> Path:
        """Generate one MP3 file and return its path."""

        try:
            import edge_tts  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError("Audio generation requires optional dependency 'edge-tts'. Install it with: pip install edge-tts") from exc

        voice = segment.voice or self.default_voice
        communicate = edge_tts.Communicate(
            segment.text,
            voice,
            rate=segment.rate,
            volume=segment.volume,
            pitch=segment.pitch,
        )
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await communicate.save(str(path))
        return path

    async def generate_chapter(
        self,
        chapter: Chapter,
        *,
        segments: Sequence[Segment] | None = None,
        chapter_dir: str | Path | None = None,
    ) -> list[Path]:
        """Render all segments in one chapter, returning paths in playback order."""

        chapter_segments = list(segments if segments is not None else chapter.segments)
        target_dir = Path(chapter_dir) if chapter_dir is not None else self.output_dir / f"chapter_{chapter.number:03d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for index, segment in enumerate(chapter_segments, start=1):
            filename = f"{index:04d}_{self._safe_name(segment.speaker)}.mp3"
            paths.append(await self.generate_segment(segment, target_dir / filename))

        manifest = {
            "number": chapter.number,
            "title": chapter.title,
            "segments": [
                {**asdict(segment), "audio": str(path.name)}
                for segment, path in zip(chapter_segments, paths)
            ],
        }
        (target_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return paths

    async def generate_novel(self, chapters: Iterable[Chapter]) -> dict[int, list[Path]]:
        """Render chapters sequentially and return paths keyed by chapter number."""

        result: dict[int, list[Path]] = {}
        for chapter in chapters:
            result[chapter.number] = await self.generate_chapter(chapter)
        return result

    def generate_novel_sync(self, chapters: Iterable[Chapter]) -> dict[int, list[Path]]:
        """Synchronous convenience wrapper for rendering every chapter."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.generate_novel(chapters))
        raise RuntimeError("generate_novel_sync cannot run inside an active event loop; await generate_novel instead")

    def generate_chapter_sync(self, chapter: Chapter, **kwargs: Any) -> list[Path]:
        """Synchronous convenience wrapper for scripts and simple APIs."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.generate_chapter(chapter, **kwargs))
        raise RuntimeError("generate_chapter_sync cannot run inside an active event loop; await generate_chapter instead")


__all__ = [
    "Chapter",
    "DEFAULT_VOICES",
    "NARRATOR",
    "Segment",
    "TTSGenerator",
    "UNKNOWN_SPEAKER",
    "VoiceProfile",
    "assign_voices",
    "detect_roles",
    "parse_chapters",
    "parse_segments",
]
