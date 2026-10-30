"""Sample third-party apps for the loader test (as an app developer would ship them)."""


class Greeter:
    name, version = "greeter", "1.0"

    def __init__(self, settings):
        self.settings = settings

    def ops(self):
        async def greet(ctx, msg, head):
            return {"ok": True, "hello": msg.get("who"), "from": ctx.pen, "group": head.group_id}
        return {"greet": greet}


def make_greeter(settings):
    return Greeter(settings)


def make_nothing(settings):
    class Empty:
        name, version = "empty", "1.0"
    return Empty()
