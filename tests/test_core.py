import asyncio
import builtins
import sys
import unittest
from unittest.mock import patch

from backend.core import (
    UNKNOWN_SPEAKER,
    Segment,
    TTSGenerator,
    VoiceProfile,
    assign_voices,
    detect_roles,
    parse_chapters,
    parse_segments,
)


class CoreParsingTests(unittest.TestCase):
    def test_parse_chinese_and_english_chapters(self) -> None:
        chapters = parse_chapters("序言\n\n第一章 初见\n正文一\n\nChapter 2: Return\n正文二")
        self.assertEqual([chapter.number for chapter in chapters], [0, 1, 2])
        self.assertEqual(chapters[1].title, "初见")
        self.assertEqual(chapters[2].text, "正文二")

    def test_parse_dialogue_attribution_and_role_lines(self) -> None:
        segments = parse_segments('林黛玉：你来了。\n宝玉说：“我来了。”\n“真的？”她问。')
        self.assertEqual(segments[0].speaker, "林黛玉")
        self.assertTrue(segments[0].is_dialogue)
        self.assertEqual(segments[1].speaker, "宝玉")
        self.assertEqual(segments[2].speaker, "她")
        self.assertTrue(segments[2].is_dialogue)

    def test_voice_assignment_is_stable_and_supports_profiles(self) -> None:
        segments = parse_segments("甲：你好\n乙：你好\n甲：再见")
        assigned = assign_voices(
            segments,
            {"甲": VoiceProfile("voice-a", rate="-10%"), "乙": "voice-b"},
            available_voices=("fallback",),
        )
        self.assertEqual([segment.voice for segment in assigned], ["voice-a", "voice-b", "voice-a"])
        self.assertEqual(assigned[0].rate, "-10%")

    def test_detect_roles_preserves_first_appearance_order(self) -> None:
        self.assertEqual(detect_roles("甲：一\n乙：二\n甲：三"), ["甲", "乙"])

    def test_missing_tts_dependencies_report_module_and_current_interpreter(self) -> None:
        original_import = builtins.__import__
        for missing_module in ("edge_tts", "aiohttp"):
            with self.subTest(missing_module=missing_module):
                import_error = ModuleNotFoundError(f"No module named '{missing_module}'", name=missing_module)

                def import_with_missing_dependency(name, *args, **kwargs):
                    if name == "edge_tts":
                        raise import_error
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=import_with_missing_dependency):
                    with self.assertRaisesRegex(RuntimeError, missing_module) as raised:
                        asyncio.run(TTSGenerator(".").generate_segment(Segment(id=1, text="测试"), "unused.mp3"))
                self.assertIn(sys.executable, str(raised.exception))
                self.assertIn("-m pip install edge-tts", str(raised.exception))
                self.assertIs(raised.exception.__cause__, import_error)


if __name__ == "__main__":
    unittest.main()
