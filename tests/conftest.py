"""Shared fixtures."""

import pytest

from study_bible_mcp.corpora import editorial_notes


# Fixture corpora are imported without the committed notes file, whose
# citations target the real texts (test_ancient_labelling checks the file).
@pytest.fixture(autouse=True)
def _empty_editorial_notes(monkeypatch, tmp_path_factory):
    path = tmp_path_factory.mktemp("notes") / "editorial_notes.json"
    path.write_text('{"notes": [], "links": []}', encoding="utf-8")
    monkeypatch.setattr(editorial_notes, "NOTES_PATH", path)
