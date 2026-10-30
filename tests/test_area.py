"""P2-B4: the public area is a folder of markdown; files starting with the owner prefix are owner-only."""
from arena.peer.area import LocalFolderArea


def test_pb4_reads_docs_and_separates_owner_only(tmp_path, settings):
    (tmp_path / "notes.md").write_text("- 인프라 12년차\n- 장애 대응 경험\n\n", encoding="utf-8")
    (tmp_path / "tools.md").write_text("# 도구\n자동화 스크립트 모음\n", encoding="utf-8")
    (tmp_path / "_owner_rules.md").write_text("- 먼저 나에게 물어볼 것\n", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("not markdown", encoding="utf-8")
    area = LocalFolderArea(str(tmp_path), settings)
    assert [d.name for d in area.documents()] == ["notes.md", "tools.md"]
    assert [d.name for d in area.documents(include_owner_only=True)] == ["_owner_rules.md", "notes.md", "tools.md"]
    assert area.lines() == ["인프라 12년차", "장애 대응 경험", "도구", "자동화 스크립트 모음"]
    assert "먼저 나에게 물어볼 것" in area.lines(include_owner_only=True)
    assert [d.owner_only for d in area.documents(include_owner_only=True)] == [True, False, False]


def test_pb4_add_note_appends_to_the_notes_file(tmp_path, settings):
    area = LocalFolderArea(str(tmp_path / "new"), settings)
    area.add_note("심사를 해 보니 기준표가 중요했다")
    area.add_note("두 번째")
    assert area.lines()[-2:] == ["심사를 해 보니 기준표가 중요했다", "두 번째"]
    assert (tmp_path / "new" / settings.area_notes_file).exists()


def test_pb15_owner_only_memo_stays_out_of_public_lines(tmp_path, settings):
    area = LocalFolderArea(str(tmp_path), settings)
    area.add_note("공개 경험")
    area.add_note("비서의 판단 메모", doc="_journal.md")
    assert area.lines() == ["공개 경험"]
    assert "비서의 판단 메모" in area.lines(include_owner_only=True)
    import pytest
    with pytest.raises(ValueError):
        area.add_note("x", doc="../escape.md")
