"""The basic assistant: the primordial way to hold or join an event (natural-language rules + generic tools)."""
from .core import EventAssistant  # noqa: F401
from .state import EventState, commit_hash  # noqa: F401
from .tools import Tool, default_tools  # noqa: F401
