"""Private atomic writes and stable advisory locks shared by persistent stores."""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path
from typing import IO


def write_text(path: Path, text: str, prefix: str = ".write.") -> None:
    """Replace a file atomically; propagate failures and remove our temporary."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=prefix, dir=path.parent, text=True)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def exclusive_lock(path: Path, *, blocking: bool = True) -> IO[bytes]:
    """Hold a lock until the returned handle closes. Never unlink this file.

    The lock has its own inode because the protected data is replaced by
    rename. Independent opens also coordinate different threads/stores.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    handle = os.fdopen(descriptor, "r+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BaseException:
        handle.close()
        raise
    return handle
