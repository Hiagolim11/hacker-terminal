"""Persistent, user-editable quick actions."""

from __future__ import annotations

import configparser
import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import default_config_path

ACTION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# {alvo} or {porta=80}; a default (even empty) makes the field optional.
PLACEHOLDER = re.compile(r"\{([^\W\d][\w-]{0,31})(?:=([^{}'\"\n]*))?\}")


@dataclass(frozen=True)
class Field:
    name: str
    default: str | None = None   # None: the field must be filled

    @property
    def required(self) -> bool:
        return self.default is None


def scan(command: str) -> list[tuple[int, int, str, str | None, str]]:
    """Placeholders as (start, end, name, default, context).

    Context is "plain" or "double" (inside double quotes). Text inside
    single quotes and ${VAR} are left alone, so awk '{print}' still works.
    """
    found = []
    state = "plain"
    index = 0
    while index < len(command):
        char = command[index]
        if state == "single":
            if char == "'":
                state = "plain"
        elif char == "\\":
            index += 1
        elif char == "'" and state == "plain":
            state = "single"
        elif char == '"':
            state = "plain" if state == "double" else "double"
        elif char == "{" and (index == 0 or command[index - 1] != "$"):
            match = PLACEHOLDER.match(command, index)
            if match:
                found.append((match.start(), match.end(), match.group(1), match.group(2), state))
                index = match.end()
                continue
        index += 1
    return found


def fields(command: str) -> list[Field]:
    result: dict[str, Field] = {}
    for _start, _end, name, default, _context in scan(command):
        result.setdefault(name, Field(name, default))
    return list(result.values())


def quote_for(value: str, context: str) -> str:
    if context == "double":
        for char in ("\\", '"', "$", "`"):
            value = value.replace(char, "\\" + char)
        return value
    return shlex.quote(value) if value else ""


def fill(command: str, values: dict[str, str]) -> str:
    """Replace placeholders with shell-quoted values (a value never runs as code)."""
    pieces = []
    last = 0
    for start, end, name, default, context in scan(command):
        value = values.get(name)
        if not value:
            value = default or ""
        pieces.append(command[last:start])
        pieces.append(quote_for(value, context))
        last = end
    pieces.append(command[last:])
    return "".join(pieces)


@dataclass(frozen=True)
class QuickAction:
    identifier: str
    label: str
    command: str
    confirm: bool = False


DEFAULT_ACTIONS = (
    QuickAction("identity", "Identidade", "printf '\\nUSER: '; whoami; printf 'HOST: '; hostname; printf 'KERNEL: '; uname -r"),
    QuickAction("network", "Interfaces de rede", "command -v ip >/dev/null && ip -brief address || echo 'Comando ip nao encontrado'"),
    QuickAction("ports", "Portas locais", "command -v ss >/dev/null && ss -tulpen || echo 'Comando ss nao encontrado'"),
    QuickAction("routes", "Rotas", "command -v ip >/dev/null && ip route || echo 'Comando ip nao encontrado'"),
    QuickAction("processes", "Processos ativos", "ps aux --sort=-%cpu | head -15"),
    QuickAction("ping", "Pingar host", "ping -c {vezes=4} {host}"),
    QuickAction("services", "Serviços de um alvo", "nmap -sV {alvo}"),
    QuickAction("ssh", "Conexões SSH", "printf 'SSH config:\\n'; ls -la ~/.ssh 2>/dev/null || echo 'Nenhuma configuracao SSH'"),
    QuickAction("health", "Saúde do sistema", "printf 'DISCO\\n'; df -h /; printf '\\nMEMORIA\\n'; free -h; printf '\\nUPTIME\\n'; uptime"),
    QuickAction("clear", "Limpar terminal", "clear"),
)


class ActionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path().with_name("actions.ini")

    def load(self) -> list[QuickAction]:
        if not self.path.is_file():
            return list(DEFAULT_ACTIONS)
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(self.path, encoding="utf-8")
            ordered: list[tuple[int, QuickAction]] = []
            for section_name in parser.sections():
                if not section_name.startswith("action:"):
                    continue
                identifier = section_name.removeprefix("action:")
                section = parser[section_name]
                label = section.get("label", "").strip()
                command = section.get("command", "").strip()
                if not ACTION_ID.fullmatch(identifier) or not label or not command:
                    raise ValueError(f"ação inválida: {section_name}")
                order = section.getint("order", fallback=len(ordered))
                confirm = section.getboolean("confirm", fallback=False)
                ordered.append((order, QuickAction(identifier, label, command, confirm)))
            return [action for _order, action in sorted(ordered, key=lambda item: item[0])]
        except (OSError, configparser.Error, ValueError):
            return list(DEFAULT_ACTIONS)

    def save(self, actions: list[QuickAction]) -> bool:
        parser = configparser.ConfigParser(interpolation=None)
        seen: set[str] = set()
        for order, action in enumerate(actions):
            if (
                not ACTION_ID.fullmatch(action.identifier)
                or action.identifier in seen
                or not action.label.strip()
                or not action.command.strip()
            ):
                return False
            seen.add(action.identifier)
            parser[f"action:{action.identifier}"] = {
                "order": str(order),
                "label": action.label.strip(),
                "command": action.command.strip(),
                "confirm": str(action.confirm).lower(),
            }
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(prefix=".actions.", dir=self.path.parent, text=True)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                parser.write(handle)
            temporary.chmod(0o600)
            temporary.replace(self.path)
            return True
        except OSError:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            return False
