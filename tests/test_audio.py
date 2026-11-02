import array
import asyncio
import json
import math
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from backend.audio import cleanup_chapter_intermediates, get_ffmpeg_executable, merge_audio_segments
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

    def test_legacy_cleanup_preserves_final_unrelated_files_and_external_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "chapter"
            target.mkdir()
            audio = target / "0002_成品.mp3"
            audio.write_bytes(b"complete-audio")
            segment = target / "0001_旁白.mp3"
            segment.write_bytes(b"segment")
            unrelated = target / "notes.txt"
            unrelated.write_text("keep", encoding="utf-8")
            external = root / "0004_原稿.mp3"
            external.write_bytes(b"external")
            linked = target / "0003_链接.mp3"
            linked.symlink_to(external)
            manifest = target / "manifest.json"
            manifest.write_text(json.dumps({"audio": audio.name, "segments": [
                {"audio": name} for name in (segment.name, audio.name, "../0004_原稿.mp3", linked.name, unrelated.name)
            ]}), encoding="utf-8")
            self.assertEqual(cleanup_chapter_intermediates(audio), 2)
            self.assertEqual(audio.read_bytes(), b"complete-audio")
            self.assertFalse(segment.exists())
            self.assertFalse(manifest.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(external.read_bytes(), b"external")
            self.assertTrue(linked.is_symlink())

    def test_legacy_segments_are_not_removed_without_a_valid_final_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            audio = target / "成品.mp3"
            segment = target / "0001_旁白.mp3"
            segment.write_bytes(b"segment")
            manifest = target / "manifest.json"
            manifest.write_text(json.dumps({"audio": audio.name, "segments": [{"audio": segment.name}]}), encoding="utf-8")
            self.assertEqual(cleanup_chapter_intermediates(audio), 0)
            audio.touch()
            self.assertEqual(cleanup_chapter_intermediates(audio), 0)
            self.assertTrue(segment.exists())
            self.assertTrue(manifest.exists())

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
        self.assertEqual(list(paths[0].parent.iterdir()), paths)

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


class ChapterCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.target = self.root / "chapter_001"
        self.target.mkdir()
        self.audio = self.target / "初见.mp3"
        self.audio.write_bytes(b"previous-audio")
        self.chapter = Chapter(number=1, title="初见", text="", segments=[Segment(id=1, text="你好"), Segment(id=2, text="再见")])
        self.ffmpeg = patch("backend.core.get_ffmpeg_executable", return_value="unused-ffmpeg")
        self.ffmpeg.start()
        self.addCleanup(self.ffmpeg.stop)

    def assert_only_original_audio_remains(self) -> None:
        self.assertEqual(list(self.target.iterdir()), [self.audio])
        self.assertEqual(self.audio.read_bytes(), b"previous-audio")

    async def test_synthesis_failure_cleans_completed_and_partial_segments(self) -> None:
        async def generate(generator, segment, output_path):
            output_path.write_bytes(b"partial")
            if segment.id == 2:
                raise RuntimeError("配音失败")
            return output_path

        with patch.object(TTSGenerator, "generate_segment", new=generate):
            with self.assertRaisesRegex(RuntimeError, "配音失败"):
                await TTSGenerator(self.root).generate_chapter(self.chapter)
        self.assert_only_original_audio_remains()

    async def test_merge_failure_cleans_intermediates_and_preserves_existing_audio(self) -> None:
        async def generate(generator, segment, output_path):
            output_path.write_bytes(b"segment")
            return output_path

        def fail(paths, output_path, **options):
            output_path.write_bytes(b"partial-merge")
            raise RuntimeError("合并失败")

        with patch.object(TTSGenerator, "generate_segment", new=generate), patch("backend.core.merge_audio_segments", new=fail):
            with self.assertRaisesRegex(RuntimeError, "合并失败"):
                await TTSGenerator(self.root).generate_chapter(self.chapter)
        self.assert_only_original_audio_remains()

    async def test_cancellation_during_synthesis_cleans_partial_files(self) -> None:
        started = asyncio.Event()

        async def generate(generator, segment, output_path):
            output_path.write_bytes(b"partial")
            started.set()
            await asyncio.Event().wait()

        with patch.object(TTSGenerator, "generate_segment", new=generate):
            task = asyncio.create_task(TTSGenerator(self.root).generate_chapter(self.chapter))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assert_only_original_audio_remains()

    async def test_cancellation_waits_for_merge_before_cleaning_its_inputs(self) -> None:
        started = threading.Event()
        release = threading.Event()
        intact = []

        async def generate(generator, segment, output_path):
            output_path.write_bytes(b"segment")
            return output_path

        def merge(paths, output_path, **options):
            started.set()
            if not release.wait(3):
                raise RuntimeError("测试未释放合并线程")
            intact.append(all(path.is_file() for path in paths))
            output_path.write_bytes(b"merged")
            return output_path

        with patch.object(TTSGenerator, "generate_segment", new=generate), patch("backend.core.merge_audio_segments", new=merge):
            task = asyncio.create_task(TTSGenerator(self.root).generate_chapter(self.chapter))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 3))
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(intact, [True])
        self.assert_only_original_audio_remains()


if __name__ == "__main__":
    unittest.main()
