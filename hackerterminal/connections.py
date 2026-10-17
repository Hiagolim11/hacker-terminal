"""Saved SSH connections and hosts read from ~/.ssh/config.

Only connection details are stored — never passwords. Commands are built
with shlex.join, so names and options cannot inject shell syntax.
"""

from __future__ import annotations

import configparser
import io
import logging
import re
import shlex
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from .config import atomic_write_text, default_config_path

LOGGER = logging.getLogger(__name__)
CONNECTION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
# No leading "-": ssh would read "-oProxyCommand=…" as an option and run it.
DESTINATION = re.compile(r"^(?:[A-Za-z0-9._][A-Za-z0-9._-]*@)?[A-Za-z0-9._:\[\]%][A-Za-z0-9._:\[\]%-]*$")
MAX_SSH_CONFIG_BYTES = 1024 * 1024


class ConnectionError(ValueError):
    """Raised for invalid connection details."""


@dataclass(frozen=True)
class Connection:
    identifier: str
    name: str
    destination: str            # host, user@host or a ~/.ssh/config alias
    port: int | None = None
    identity_file: str = ""
    options: str = ""           # extra ssh arguments, e.g. "-J bastion -A"
    theme: str = ""             # theme for this tab; empty keeps the current one
    confirm: bool = False       # ask before connecting (production hosts)
    from_ssh_config: bool = False

    def command(self) -> list[str]:
        argv = ["ssh"]
        if self.port:
            argv += ["-p", str(self.port)]
        if self.identity_file:
            argv += ["-i", str(Path(self.identity_file).expanduser())]
        argv += shlex.split(self.options)
        argv.append(self.destination)
        return argv

    def command_line(self, askpass: Path | None = None) -> str:
        """The ssh command; with ``askpass`` a saved password answers the prompt.

        Only the connection's identifier goes on the command line; the
        helper fetches the password from the keyring itself.
        """
        line = shlex.join(self.command())
        if askpass is None:
            return line
        variables = {
            "SSH_ASKPASS": str(askpass),
            "SSH_ASKPASS_REQUIRE": "force",
            "HACKER_TERMINAL_SSH_ID": self.identifier,
        }
        # env works in any shell (fish has no "VAR=value command").
        return shlex.join(["env", *(f"{key}={value}" for key, value in variables.items())]) + " " + line

    def key_file(self) -> str:
        """Private key used for this host: its own, or the default ed25519 key."""
        return self.identity_file or "~/.ssh/id_ed25519"

    def key_setup_command(self, helper: Path) -> str:
        """Run ht-copy-key: create the key if needed and install it with ssh-copy-id.

        ssh-copy-id only understands -p, -i and -o; other extra options
        (like -J) are passed as their -o equivalents when possible.
        """
        key = str(Path(self.key_file()).expanduser())
        arguments = [str(helper), self.name, key]
        if self.port:
            arguments += ["-p", str(self.port)]
        arguments += copy_id_options(self.options)
        arguments.append(self.destination)
        return shlex.join(arguments)


def copy_id_options(options: str) -> list[str]:
    """Translate the ssh options ssh-copy-id cannot take into -o form."""
    result: list[str] = []
    try:
        words = shlex.split(options)
    except ValueError:
        return result
    index = 0
    while index < len(words):
        word, following = words[index], words[index + 1] if index + 1 < len(words) else None
        if word == "-o" and following is not None:
            result += ["-o", following]
            index += 2
        elif word.startswith("-o") and len(word) > 2:
            result += ["-o", word[2:]]
            index += 1
        elif word == "-J" and following is not None:
            result += ["-o", f"ProxyJump={following}"]
            index += 2
        elif word == "-i" and following is not None:
            index += 2  # the key being installed is passed separately
        else:
            index += 1  # flags such as -A or -X do not matter for copying a key
    return result


def validate(connection: Connection) -> None:
    if not CONNECTION_ID.fullmatch(connection.identifier):
        raise ConnectionError("identificador inválido")
    if not connection.name.strip():
        raise ConnectionError("informe um nome para a conexão")
    if not DESTINATION.fullmatch(connection.destination):
        raise ConnectionError("destino inválido: use host, usuário@host ou um alias do ~/.ssh/config")
    if connection.port is not None and not 1 <= connection.port <= 65535:
        raise ConnectionError("porta deve estar entre 1 e 65535")
    try:
        options = shlex.split(connection.options)
    except ValueError as error:
        raise ConnectionError(f"opções inválidas: {error}") from error
    # A destination hidden in the options would bypass the check above.
    if any(not option.startswith("-") and index == 0 for index, option in enumerate(options)):
        raise ConnectionError("as opções extras devem começar com '-' (ex.: -J bastion -A)")


def read_ssh_config(path: Path | None = None) -> list[Connection]:
    """Host aliases from ~/.ssh/config (wildcard patterns are skipped)."""
    path = path or Path.home() / ".ssh" / "config"
    try:
        if path.stat().st_size > MAX_SSH_CONFIG_BYTES:
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hosts: list[Connection] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"[\s=]+", line, maxsplit=1)
        if len(parts) != 2 or parts[0].lower() != "host":
            continue
        for alias in parts[1].split():
            if any(char in alias for char in "*?!") or alias in seen or not DESTINATION.fullmatch(alias):
                continue
            seen.add(alias)
            identifier = "ssh-" + re.sub(r"[^a-z0-9-]+", "-", alias.lower()).strip("-")[:40]
            hosts.append(Connection(identifier or "ssh-host", alias, alias, from_ssh_config=True))
    return hosts


def unique_identifier(name: str, taken: set[str]) -> str:
    """A free identifier made from the display name: "Produção" -> "producao"."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:40] or "conexao"
    candidate, counter = base, 2
    while candidate in taken:
        candidate, counter = f"{base}-{counter}", counter + 1
    return candidate


class ConnectionStore:
    def __init__(self, path: Path | None = None, ssh_config: Path | None = None) -> None:
        self.path = path or default_config_path().with_name("ssh.ini")
        self.ssh_config = ssh_config

    def load_saved(self) -> list[Connection]:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(self.path, encoding="utf-8")
        except (configparser.Error, UnicodeError) as error:
            LOGGER.warning("conexões SSH ilegíveis em %s: %s", self.path, error)
            return []
        connections = []
        for section in parser.sections():
            if not section.startswith("ssh:"):
                continue
            data = parser[section]
            try:
                port_text = data.get("port", "").strip()
                connection = Connection(
                    identifier=section[4:],
                    name=data.get("name", "").strip(),
                    destination=data.get("destination", "").strip(),
                    port=int(port_text) if port_text else None,
                    identity_file=data.get("identity_file", "").strip(),
                    options=data.get("options", "").strip(),
                    theme=data.get("theme", "").strip(),
                    confirm=data.get("confirm", "false").strip().lower() in ("true", "1", "yes", "on"),
                )
                validate(connection)
            except (ValueError, ConnectionError) as error:
                LOGGER.warning("conexão SSH ignorada (%s): %s", section, error)
                continue
            connections.append(connection)
        return connections

    def load(self) -> list[Connection]:
        """Saved connections first, then ~/.ssh/config hosts not saved yet."""
        saved = self.load_saved()
        names = {connection.destination for connection in saved}
        extra = [host for host in read_ssh_config(self.ssh_config) if host.destination not in names]
        return saved + extra

    def save(self, connections: list[Connection]) -> bool:
        parser = configparser.ConfigParser(interpolation=None)
        for connection in connections:
            if connection.from_ssh_config:
                continue
            validate(connection)
            parser[f"ssh:{connection.identifier}"] = {
                "name": " ".join(connection.name.split()),
                "destination": connection.destination,
                "port": str(connection.port or ""),
                "identity_file": connection.identity_file,
                "options": connection.options,
                "theme": connection.theme,
                "confirm": str(connection.confirm).lower(),
            }
        buffer = io.StringIO()
        parser.write(buffer)
        return atomic_write_text(self.path, buffer.getvalue(), ".ssh.")

    def unique_identifier(self, name: str, taken: set[str]) -> str:
        return unique_identifier(name, taken)

    def promote(self, connection: Connection, taken: set[str]) -> Connection:
        """Turn a ~/.ssh/config host into a saved, editable connection."""
        return replace(connection, identifier=self.unique_identifier(connection.name, taken), from_ssh_config=False)
