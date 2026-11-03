"""Functions the example service peer exposes (example-service.json). A service function is async (input, ctx) -> dict.
Replace this file and the spec with your own service, or point the spec's ops at an existing HTTP API."""


async def add(input, ctx):
    return {"sum": input["a"] + input["b"]}


async def echo(input, ctx):
    return {"echo": input}
