"""functions a service peer exposes through its spec file (test samples). A service function is async (input, ctx) -> dict."""


async def add(input, ctx):
    return {"sum": input["a"] + input["b"]}


async def bigger(input, ctx):
    """a 'judge' that computes a result in code: which of two numbers is bigger"""
    a, b = input["a"], input["b"]
    return {"winner": "a" if a > b else "b" if b > a else ""}
