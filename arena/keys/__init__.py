"""A peer's own keys (6-K, user 2026-11-02/03): "키 발급은 peer의 보안 영역에서 스스로 만드는 거지".

    store.py     where the private key lives: the OS key store, or a 0600 file (KeyStore)
    backup.py    the encrypted backup: sealed on the device with the owner's passphrase; whoever keeps it sees only ciphertext
    lineage.py   key succession on the ledger: the next key is promised in advance (its hash), so a thief holding only
                 the current key cannot take over; an owner may name key peers that can recover a key lost with its backup
    cli.py       python -m arena.keys register | rotate | recover | backup | restore | status

The keys are always made by the peer itself. A key peer (arena.peers.key_peer, optional and anyone may run one) keeps
encrypted backups and, only where the owner named it in advance, signs a recovery. It never sees a private key."""
from .backup import BackupError, open_backup, put_request, seal_backup  # noqa: F401
from .store import FileKeyStore, KeyStore, OsKeyStore, open_key_store  # noqa: F401
