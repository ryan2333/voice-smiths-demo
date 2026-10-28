import json
import tempfile
import unittest
from pathlib import Path

from voice_smiths import create_project, parse_novel


class ProjectFacadeTests(unittest.TestCase):
    def test_parse_novel_returns_json_ready_project(self) -> None:
        project = parse_novel("第一章\n张三：你好")
        self.assertEqual(project["stats"]["chapter_count"], 1)
        self.assertEqual(project["roles"], ["张三"])
        json.dumps(project, ensure_ascii=False)

    def test_create_project_writes_source_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = create_project("Chapter 1\nHello", directory, title="Demo")
            self.assertEqual(project["title"], "Demo")
            self.assertTrue(Path(directory, "source.txt").exists())
            self.assertTrue(Path(directory, "project.json").exists())


if __name__ == "__main__":
    unittest.main()
