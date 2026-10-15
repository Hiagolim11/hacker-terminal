"""Persistent, user-editable quick actions."""

from __future__ import annotations

import configparser
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import default_config_path

ACTION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


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
