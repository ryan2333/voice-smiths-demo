"""Thin, JSON-friendly facade over :mod:`backend.core`."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.core import (
    Chapter,
    DEFAULT_VOICES,
    Segment,
    TTSGenerator,
    VoiceProfile,
    assign_voices,
    parse_chapters,
)


def _chapter_dict(chapter: Chapter) -> dict[str, Any]:
    return asdict(chapter)


def _segment_from_dict(value: Mapping[str, Any]) -> Segment:
    return Segment(
        id=int(value.get("id", 0)),
        text=str(value.get("text", "")),
        speaker=str(value.get("speaker", "旁白")),
        is_dialogue=bool(value.get("is_dialogue", False)),
        voice=value.get("voice"),
        rate=str(value.get("rate", "+0%")),
        pitch=str(value.get("pitch", "+0Hz")),
        volume=str(value.get("volume", "+0%")),
    )


def _chapter_from_dict(value: Mapping[str, Any]) -> Chapter:
    return Chapter(
        number=int(value.get("number", 1)),
        title=str(value.get("title", "正文")),
        text=str(value.get("text", "")),
        segments=[_segment_from_dict(item) for item in value.get("segments", [])],
    )


def parse_novel(
    text: str,
    *,
    voice_map: Mapping[str, str | VoiceProfile] | None = None,
    available_voices: Sequence[str] = DEFAULT_VOICES,
) -> dict[str, Any]:
    """Parse novel text and return a complete JSON-ready project dictionary."""

    chapters = parse_chapters(text)
    serialized_chapters: list[dict[str, Any]] = []
    role_names: set[str] = set()
    segment_count = 0
    for chapter in chapters:
        chapter.segments = assign_voices(chapter.segments, voice_map, available_voices=available_voices)
        serialized = _chapter_dict(chapter)
        serialized_chapters.append(serialized)
        segment_count += len(chapter.segments)
        role_names.update(segment.speaker for segment in chapter.segments)
    return {
        "version": 1,
        "title": "未命名小说",
        "chapters": serialized_chapters,
        "roles": sorted(role_names),
        "stats": {
            "chapter_count": len(serialized_chapters),
            "segment_count": segment_count,
            "dialogue_count": sum(
                sum(1 for segment in chapter["segments"] if segment["is_dialogue"])
                for chapter in serialized_chapters
            ),
        },
    }


def assign_novel_voices(
    project: Mapping[str, Any],
    voice_map: Mapping[str, str | VoiceProfile],
    *,
    available_voices: Sequence[str] = DEFAULT_VOICES,
) -> dict[str, Any]:
    """Apply role voice changes to an existing project dictionary."""

    result = json.loads(json.dumps(project, ensure_ascii=False))
    for chapter in result.get("chapters", []):
        assigned = assign_voices(
            [_segment_from_dict(item) for item in chapter.get("segments", [])],
            voice_map,
            available_voices=available_voices,
        )
        chapter["segments"] = [asdict(item) for item in assigned]
    return result


def create_project(
    text: str,
    project_dir: str | Path,
    *,
    title: str = "未命名小说",
    voice_map: Mapping[str, str | VoiceProfile] | None = None,
    available_voices: Sequence[str] = DEFAULT_VOICES,
) -> dict[str, Any]:
    """Parse and persist a project source plus its JSON metadata."""

    target = Path(project_dir)
    target.mkdir(parents=True, exist_ok=True)
    project = parse_novel(text, voice_map=voice_map, available_voices=available_voices)
    project["title"] = title
    (target / "source.txt").write_text(text, encoding="utf-8")
    (target / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    project["project_dir"] = str(target)
    return project


def render_project(
    project: Mapping[str, Any] | str | Path,
    output_dir: str | Path | None = None,
) -> dict[int, list[str]]:
    """Render a parsed project through optional ``edge-tts``.

    ``project`` may be the dictionary returned by :func:`parse_novel` or the
    path to a saved ``project.json``.  The return value contains string paths,
    with one merged MP3 per chapter, making it suitable for JSON responses.
    """

    if isinstance(project, (str, Path)):
        project_path = Path(project)
        project_data = json.loads(project_path.read_text(encoding="utf-8"))
        if output_dir is None:
            output_dir = project_path.parent / "audio"
    else:
        project_data = project
    if output_dir is None:
        output_dir = Path(project_data.get("project_dir", ".")) / "audio"
    chapters = [_chapter_from_dict(item) for item in project_data.get("chapters", [])]
    rendered = TTSGenerator(output_dir).generate_novel_sync(chapters)
    return {number: [str(path) for path in paths] for number, paths in rendered.items()}


__all__ = ["assign_novel_voices", "create_project", "parse_novel", "render_project"]
