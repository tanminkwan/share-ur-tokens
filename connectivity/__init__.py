"""connectivity: a general-purpose service that lets an HTTP server with no inbound access be reached. The server opens
only outgoing connections (long poll) to the connectivity server; requests sent to <server>/r/<its key>/<path> are
passed to it and its answers passed back. It knows nothing of who uses it (no agents, no ledgers): it moves HTTP requests
for whoever holds a key. Nothing here imports any other package of this repository (tests/test_layering.py)."""
