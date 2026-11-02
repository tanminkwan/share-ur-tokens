from arena.events import EventLog


def test_pb13_event_log_keeps_tail_and_notifies():
    seen = []
    log = EventLog(keep=3, echo=False)
    log.subscribe(seen.append)
    for i in range(5):
        log.emit("k", "a", f"t{i}")
    assert [e["text"] for e in log.tail(10)] == ["t2", "t3", "t4"]
    assert len(seen) == 5 and set(seen[0]) == {"ts", "kind", "actor", "text"}
