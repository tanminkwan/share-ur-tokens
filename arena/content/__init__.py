"""Works and the ledger (CP-9, CP-10, user 2026-11-02): "원장에 책 정보를 찍는 것이 아니라 책에 원장 정보를 찍는 거야".

    reference.py   the ledger reference printed in a book (JSON, a one-line address for a QR code, the colophon text)
    works.py       register a work (publish, purpose authorship, its content form, optionally where it is kept: CP-4)
    check.py       a reader checks a copy: the body's hash, the ledger entry, the ledger itself from the root values
    links.py       permanent links at a link peer: the ledger names the link, only the author changes where it points
    cli.py         python -m arena.content hash | register | check | find | relink | resolve

The ledger keeps only the body's hash and the author's signature; the book carries the reference to the ledger."""
from .check import check_work  # noqa: F401
from .reference import colophon, from_uri, make_reference, to_uri  # noqa: F401
from .links import link_id, make_link, verify_link  # noqa: F401
from .works import register_work, relink, resolve_link, set_link  # noqa: F401
