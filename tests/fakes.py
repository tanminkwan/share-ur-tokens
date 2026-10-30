"""Test doubles for unit tests (P2-E1): deterministic LLM and owner. Live tests use the real LLM instead."""
from arena.llm import LLMError
from arena.peer.owner import Answer


class ScriptedLLM:
    """returns queued answers in order; each answer is a dict, a callable(kwargs)->dict, or an Exception to raise"""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def push(self, *answers):
        self.answers += answers

    async def ask_json(self, **kw):
        self.calls.append(kw)
        if not self.answers:
            raise LLMError("no scripted answer left")
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a(kw) if callable(a) else a


class FakeOwner:
    def __init__(self, yes=True, why="ok", writes=()):
        self.yes, self.why, self.writes, self.asked, self.tasks = yes, why, list(writes), [], []

    async def ask(self, question, context=""):
        self.asked.append((question, context))
        return Answer(self.yes, self.why)

    async def write(self, task, context, schema):
        self.tasks.append((task, context))
        w = self.writes.pop(0)
        return w(task, context) if callable(w) else w
