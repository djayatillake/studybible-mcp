"""lookup_verse: several ';'-separated references in one call."""

import study_bible_mcp.server as server
from study_bible_mcp.server import split_references


def test_split_references():
    assert split_references("John 3:16") == ["John 3:16"]
    assert split_references("John 3:16; Romans 8:28-30, 31") == [
        "John 3:16", "Romans 8:28-30", "Romans 8:31"]
    assert split_references("John 3:16-4:2, 5") == ["John 3:16-4:2", "John 4:5"]
    assert split_references("1 John 1:9, 2:1") == ["1 John 1:9", "1 John 2:1"]
    assert split_references("Psalm 23, 24") == ["Psalm 23", "Psalm 24"]
    assert split_references("Song of Songs 2:1, 3; Jude 3") == [
        "Song of Songs 2:1", "Song of Songs 2:3", "Jude 3"]
    assert split_references(" ; ") == []


async def test_lookup_verses_joins_each_reference(monkeypatch):
    seen = []

    async def fake_lookup(args):
        seen.append(args["reference"])
        return server.text(f"<{args['reference']}>")

    monkeypatch.setattr(server, "handle_lookup_verse", fake_lookup)
    out = (await server.handle_lookup_references({"reference": "John 3:16; Jude 3, 5"}))[0].text
    assert seen == ["John 3:16", "Jude 1:3", "Jude 1:5"]
    assert out == "<John 3:16>\n\n---\n\n<Jude 1:3>\n\n---\n\n<Jude 1:5>"

    seen.clear()
    many = "; ".join(f"Psalm {n}" for n in range(1, 13))
    out = (await server.handle_lookup_references({"reference": many}))[0].text
    assert len(seen) == server.LOOKUP_VERSE_MAX_REFERENCES
    assert out.endswith("Continue with reference='Psalm 11; Psalm 12'.*")
