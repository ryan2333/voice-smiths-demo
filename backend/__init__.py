"""Backend package for the novel voice-over application."""

from .core import (
    Chapter,
    DEFAULT_VOICES,
    Segment,
    TTSGenerator,
    VoiceProfile,
    assign_voices,
    detect_roles,
    parse_chapters,
    parse_segments,
)

__all__ = [
    "Chapter",
    "DEFAULT_VOICES",
    "Segment",
    "TTSGenerator",
    "VoiceProfile",
    "assign_voices",
    "detect_roles",
    "parse_chapters",
    "parse_segments",
]
