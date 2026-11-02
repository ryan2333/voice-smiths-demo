import array
import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from backend.audio import get_ffmpeg_executable, merge_audio_segments
from backend.core import Chapter, Segment, TTSGenerator, assign_voices, chapter_audio_filename


class AudioExportTests(unittest.TestCase):
    def test_empty_chapter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "没有可配音"):
            TTSGenerator(".").generate_chapter_sync(Chapter(number=1, title="空章", text=""))

    def test_empty_merge_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "没有可合并"):
            merge_audio_segments([], Path("unused.mp3"))

    def test_chapter_filename_preserves_title_and_rejects_path_characters(self) -> None:
        self.assertEqual(chapter_audio_filename("第一章 初见"), "第一章 初见.mp3")
        self.assertEqual(chapter_audio_filename("../初见:重逢?"), "_初见_重逢_.mp3")
        self.assertEqual(chapter_audio_filename(" ... "), "未命名章节.mp3")
        self.assertEqual(chapter_audio_filename("CON"), "_CON.mp3")
        self.assertLess(len(chapter_audio_filename("中文" * 100).encode("utf-8")), 256)

class AudioMergeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.executable = get_ffmpeg_executable()
        except RuntimeError as error:
            raise unittest.SkipTest(str(error)) from error

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="小说's audio-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.sources = []
        for index, frequency in enumerate((440, 880)):
            source = self.root / f"角色 {index}.mp3"
            subprocess.run(
                [
                    self.executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=24000:duration=0.3",
                    "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", str(source),
                ],
                check=True,
                capture_output=True,
            )
            self.sources.append(source)

    def test_chapter_merges_all_roles_in_order_into_one_playable_mp3(self) -> None:
        async def save_segment(segment, output_path):
            shutil.copyfile(self.sources[segment.id - 1], output_path)
            return output_path

        chapter = Chapter(
            number=1, title="初见", text="", segments=assign_voices([
                Segment(id=1, text="你好", speaker="林默"),
                Segment(id=2, text="再见", speaker="苏晚"),
            ], {"林默": "zh-CN-YunxiNeural", "苏晚": "zh-CN-XiaoxiaoNeural"}),
        )
        with patch.object(TTSGenerator, "generate_segment", new=AsyncMock(side_effect=save_segment)) as synthesize:
            paths = TTSGenerator(self.root).generate_chapter_sync(chapter)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].name, "初见.mp3")
        self.assertEqual([call.args[0].voice for call in synthesize.await_args_list], [
            "zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural",
        ])
        manifest = json.loads((paths[0].parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["audio"], paths[0].name)
        self.assertEqual(len(manifest["segments"]), 2)

        decoded = subprocess.run(
            [self.executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(paths[0]),
             "-f", "s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
            capture_output=True, check=True,
        )
        samples = array.array("h", decoded.stdout)
        self.assertGreater(len(samples) / 24000, 0.55)
        self.assertLess(len(samples) / 24000, 0.8)

        def tone_energy(start, frequency):
            window = samples[int(start * 24000):int((start + 0.08) * 24000)]
            real = sum(value * math.cos(2 * math.pi * frequency * index / 24000) for index, value in enumerate(window))
            imaginary = sum(value * math.sin(2 * math.pi * frequency * index / 24000) for index, value in enumerate(window))
            return real * real + imaginary * imaginary

        self.assertGreater(tone_energy(0.08, 440), 10 * tone_energy(0.08, 880))
        self.assertGreater(tone_energy(0.42, 880), 10 * tone_energy(0.42, 440))

    def test_single_segment_becomes_one_chapter_mp3(self) -> None:
        output = self.root / "整章.mp3"
        self.assertEqual(merge_audio_segments(self.sources[:1], output), output)
        self.assertGreater(output.stat().st_size, 0)

    def test_merge_failure_does_not_leave_a_partial_chapter_file(self) -> None:
        invalid = self.root / "invalid.mp3"
        invalid.write_bytes(b"invalid audio")
        output = self.root / "chapter.mp3"
        with self.assertRaisesRegex(RuntimeError, "合并失败"):
            merge_audio_segments([invalid], output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob("merge-*")), [])


if __name__ == "__main__":
    unittest.main()
