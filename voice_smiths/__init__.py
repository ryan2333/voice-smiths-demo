"""Application-facing helpers for the Voice Smiths demo.

The helpers return ordinary dictionaries so they can be passed directly to
``json.dumps`` or a small HTTP API without teaching the API about dataclasses.
"""

from .project import (
    assign_novel_voices,
    create_project,
    parse_novel,
    render_project,
)

__all__ = ["assign_novel_voices", "create_project", "parse_novel", "render_project"]
