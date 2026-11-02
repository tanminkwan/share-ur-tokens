"""The owner desk (P6-P3 ~ P6-P5): one place where a person sees what their peer brings them (questions, requests to
write, suggested actions, notices, scheduled times, ledger news, messages) and answers. The same desk serves an agent
peer (the LLM drives, the person decides the important things) and a human peer (no LLM, the person drives)."""
from .desk import OwnerDesk, OwnerDeskApp  # noqa: F401
from .model import ITEM_KINDS, DeskItem  # noqa: F401
from .owner import DeskOwner  # noqa: F401
