"""P5-C16: events a peer takes part in are kept locally; secrets in an owner-only file."""
import os
import stat

from arena.peer.event_store import FolderEventStore


def test_p5c16_save_load_and_secret_file(tmp_path):
    st = FolderEventStore(str(tmp_path / "events"))
    st.save("ev-1", {"event_id": "ev-1", "role": "participant", "transcript": ["[입력] a"]}, {"x-1": {"value": "v", "salt": "s"}})
    st.save("ev-2", {"event_id": "ev-2", "role": "host", "transcript": []}, {})
    loaded = dict((s["event_id"], (s, sec)) for s, sec in st.load_all())
    assert loaded["ev-1"][0]["transcript"] == ["[입력] a"] and loaded["ev-1"][1] == {"x-1": {"value": "v", "salt": "s"}}
    sec_file = tmp_path / "events" / "ev-1" / "_secrets.json"
    assert stat.S_IMODE(os.stat(sec_file).st_mode) == 0o600
    assert "salt" not in (tmp_path / "events" / "ev-1" / "state.json").read_text(encoding="utf-8")
    st.save("ev-1", {"event_id": "ev-1", "role": "participant", "transcript": ["[입력] a", "[입력] b"]}, {})
    assert dict((s["event_id"], s) for s, _ in st.load_all())["ev-1"]["transcript"][-1] == "[입력] b"
    assert FolderEventStore(str(tmp_path / "none")).load_all() == []
