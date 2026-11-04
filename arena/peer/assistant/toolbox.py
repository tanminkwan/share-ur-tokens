"""Toolbox: the registered tools, which ones an event offers, the owner's view of them, and running one with every check
done by code first (role, closed event, arguments, JSON arguments, handles back to keys). One responsibility: tools."""
from __future__ import annotations

import json
import re

from .handles import Handles
from .tools import ARG_LABELS, LABELS, Tool

JSON_ARGS = ("data_json", "value_json", "subjects_json", "input_json")


class Toolbox:
    HIDDEN_FROM_OWNER = ("wait", "ask_owner")  # the owner does not wait for themselves, nor ask themselves

    def __init__(self, handles: Handles, tools: list[Tool] = ()):
        self.handles = handles
        self.tools: dict[str, Tool] = {}
        for t in tools:
            self.add(t)

    def add(self, tool: Tool) -> None:
        """extend the assistant without changing it"""
        if tool.name in self.tools:
            raise ValueError(f"tool {tool.name!r} registered twice")
        self.tools[tool.name] = tool

    def offered(self, st) -> list[str]:
        """the tools this event offers to whoever drives it (role, closed or not, the event's elements)"""
        return [n for n, t in self.tools.items() if (st.role == "host" or not t.host_only) and (st.role != "host" or not t.participant_only)
                and (not st.closed or t.after_close) and (t.element is None or t.element in st.elements)
                and (t.ledger is None or t.ledger == st.on_ledger)]

    def lines(self, st) -> str:
        return "\n".join(f"- {n} {self.tools[n].description}" for n in self.offered(st))

    def owner_view(self, st) -> list[dict]:
        """the tools the owner may run on this event, in plain names, with argument schemas carrying plain titles (the screen
        draws forms from them; the code names stay for the record)"""
        out = []
        for n in self.offered(st):
            if n in self.HIDDEN_FROM_OWNER:
                continue
            t = self.tools[n]
            args = json.loads(json.dumps(t.args or {"type": "object", "properties": {}}))
            for k, v in args.get("properties", {}).items():
                v.setdefault("title", ARG_LABELS.get(k, k))
            out.append({"name": n, "label": t.label or LABELS.get(n, n), "help": re.sub(r"^\{[^}]*\}:\s*", "", t.description),
                        "description": t.description, "args": args})
        return out

    async def run(self, host, ctx, st, name, args):
        """run a tool for `host` (the ToolHost the tool works through), after the checks code enforces"""
        tool = self.tools.get(name)
        if tool is None:
            return {"error": f"없는 도구: {name}"}
        if tool.host_only and st.role != "host":
            return {"error": "개최자만 쓸 수 있는 도구"}
        if st.closed and not tool.after_close:
            return {"error": "닫힌 이벤트"}
        if tool.ledger is True and not st.on_ledger:  # P6-N2: enforced by code, whoever asks
            return {"error": "이 broker 그룹에는 원장이 없어 쓸 수 없는 도구(원장에 기록하거나 원장을 읽는다)"}
        if tool.ledger is False and st.on_ledger:
            return {"error": "원장이 있는 이벤트에서는 쓰지 않는 도구"}
        missing = [k for k in (tool.args or {"required": []})["required"] if k not in args]
        if missing:
            return {"error": f"인자가 맞지 않음: {', '.join(missing)} 없음"}
        if tool.participant_only and st.role == "host":
            return {"error": "참가자만 쓰는 도구"}
        for k in JSON_ARGS:
            if k in args:
                try:
                    args[k[:-5]] = json.loads(args.pop(k) or "{}")
                except ValueError:
                    return {"error": f"인자가 맞지 않음: {k}가 JSON이 아님"}
        args = self.handles.expand(st, args)  # handles and short refs back to real keys and hashes
        args, unknown = await self.handles.check_handles(ctx, st, args)
        if unknown:  # identification enforced by code: a mistyped or garbled handle never reaches the ledger
            return {"error": f"아무도 가리키지 않는 필명: {', '.join(unknown)}. 진행 현황이나 지금 상태에 나온 필명을 그대로 쓴다"}
        try:
            return await tool.run(host, ctx, st, **args)
        except TypeError as e:
            return {"error": f"인자가 맞지 않음: {e}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
