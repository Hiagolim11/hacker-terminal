"""Local socket that lets ``ht-open`` ask this window to preview a file.

Each Hacker Terminal process listens on a private UNIX socket and exports
its path to child shells as ``HACKER_TERMINAL_SOCKET``. The only request is
"show this file in the viewer"; nothing is ever executed.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import threading
from pathlib import Path
from typing import Callable

from .constants import APP_NAME
from .runtime import GLib

LOGGER = logging.getLogger(__name__)
SOCKET_ENV = "HACKER_TERMINAL_SOCKET"
PANE_ENV = "HACKER_TERMINAL_PANE"
MAX_REQUEST_BYTES = 16 * 1024
MAX_SOCKET_PATH = 100  # sun_path holds 108 bytes on Linux


def runtime_directories() -> list[Path]:
    """Private socket directories, preferred first."""
    candidates = []
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and Path(base).is_dir():
        candidates.append(Path(base) / APP_NAME)
    candidates.append(Path(tempfile.gettempdir()) / f"{APP_NAME}-{os.getuid()}")
    return candidates


def _remove_stale_sockets(directory: Path) -> None:
    """Delete sockets left by Hacker Terminal processes that no longer exist."""
    for item in directory.glob("*.sock"):
        try:
            pid = int(item.stem)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            item.unlink(missing_ok=True)
        except PermissionError:
            pass  # alive, but not ours to judge


class OpenServer:
    """Accepts ``{"action": "open", "path": ..., "pane": ...}`` requests."""

    def __init__(self, on_open: Callable[[Path, str | None], None]) -> None:
        self.on_open = on_open
        self.path: Path | None = None
        self.sock: socket.socket | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> Path | None:
        for directory in runtime_directories():
            path = directory / f"{os.getpid()}.sock"
            if len(os.fsencode(path)) > MAX_SOCKET_PATH:
                continue
            sock = self._listen(directory, path)
            if sock is not None:
                self.sock, self.path = sock, path
                self.thread = threading.Thread(target=self._serve, name="ht-open-server", daemon=True)
                self.thread.start()
                return path
        LOGGER.warning("visualizador por comando desativado: nenhum diretório seguro para o socket")
        return None

    @staticmethod
    def _listen(directory: Path, path: Path) -> socket.socket | None:
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
            # Refuse a directory another user could have planted.
            info = directory.lstat()
            if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
                LOGGER.warning("diretório de socket inseguro ignorado: %s", directory)
                return None
            _remove_stale_sockets(directory)
            path.unlink(missing_ok=True)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.bind(str(path))
                path.chmod(0o600)
                sock.listen(8)
            except OSError:
                sock.close()
                raise
            return sock
        except OSError as error:
            LOGGER.warning("não foi possível criar o socket em %s: %s", directory, error)
            return None

    def _serve(self) -> None:
        while self.sock is not None:
            try:
                connection, _address = self.sock.accept()
            except OSError:
                return
            with connection:
                connection.settimeout(2)
                reply = self._handle(connection)
                try:
                    connection.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode())
                except OSError:
                    pass

    def _handle(self, connection: socket.socket) -> dict:
        data = b""
        try:
            while b"\n" not in data and len(data) < MAX_REQUEST_BYTES:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                data += chunk
            request = json.loads(data.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return {"ok": False, "error": "pedido inválido"}
        if not isinstance(request, dict) or request.get("action") != "open":
            return {"ok": False, "error": "ação desconhecida"}
        raw_path = request.get("path")
        pane = request.get("pane")
        if not isinstance(raw_path, str) or not raw_path:
            return {"ok": False, "error": "caminho ausente"}
        path = Path(raw_path)
        if not path.is_absolute():
            return {"ok": False, "error": "caminho precisa ser absoluto"}
        if not path.is_file():
            return {"ok": False, "error": f"arquivo não encontrado: {path}"}
        if not os.access(path, os.R_OK):
            return {"ok": False, "error": f"sem permissão de leitura: {path}"}
        GLib.idle_add(self._dispatch, path, pane if isinstance(pane, str) else None)
        return {"ok": True}

    def _dispatch(self, path: Path, pane: str | None) -> bool:
        try:
            self.on_open(path, pane)
        except Exception:  # noqa: BLE001 - never let a viewer error kill the server
            LOGGER.exception("falha ao abrir %s no visualizador", path)
        return False

    def stop(self) -> None:
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        if self.path is not None:
            self.path.unlink(missing_ok=True)
            self.path = None
