"""User-configurable keyboard shortcuts.

Accelerators use GTK syntax (``<Primary><Shift>t``). Several accelerators may be
bound to one action by separating them with ``;``; an empty value disables the
action's shortcut.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .runtime import Gdk


@dataclass(frozen=True)
class ShortcutAction:
    identifier: str
    label: str
    default: str


SHORTCUT_ACTIONS = (
    ShortcutAction("new_tab", "Nova aba", "<Primary><Shift>t"),
    ShortcutAction("close_pane", "Fechar painel ou aba", "<Primary><Shift>w"),
    ShortcutAction("split_horizontal", "Dividir horizontalmente", "<Primary><Shift>d"),
    ShortcutAction("split_vertical", "Dividir verticalmente", "<Primary><Shift>e"),
    ShortcutAction("focus_other_pane", "Alternar painel dividido", "<Primary><Shift>o"),
    ShortcutAction("broadcast", "Digitar em todos os painéis da aba", "<Primary><Shift>i"),
    ShortcutAction("next_tab", "Próxima aba", "<Primary>Page_Down"),
    ShortcutAction("previous_tab", "Aba anterior", "<Primary>Page_Up"),
    ShortcutAction("previous_prompt", "Ir ao prompt anterior", "<Primary><Shift>Up"),
    ShortcutAction("next_prompt", "Ir ao próximo prompt", "<Primary><Shift>Down"),
    ShortcutAction("copy_last_output", "Copiar saída do último comando", "<Primary><Shift>l"),
    ShortcutAction("copy", "Copiar", "<Primary><Shift>c"),
    ShortcutAction("paste", "Colar", "<Primary><Shift>v"),
    ShortcutAction("search", "Pesquisar no histórico", "<Primary><Shift>f"),
    ShortcutAction("command_palette", "Paleta de comandos", "<Primary><Shift>p"),
    ShortcutAction("ssh_manager", "Conexões SSH", "<Primary><Shift>s"),
    ShortcutAction("rename_pane", "Renomear painel", "<Primary><Shift>r"),
    ShortcutAction("command_history", "Histórico de comandos", "<Primary><Shift>h"),
    ShortcutAction("toggle_panel", "Mostrar ou ocultar ações", "<Primary><Shift>b"),
    ShortcutAction("preferences", "Preferências", "<Primary>comma"),
    ShortcutAction("zoom_in", "Aumentar fonte", "<Primary>plus;<Primary>equal;<Primary>KP_Add"),
    ShortcutAction("zoom_out", "Diminuir fonte", "<Primary>minus;<Primary>KP_Subtract"),
    ShortcutAction("zoom_reset", "Tamanho padrão da fonte", "<Primary>0;<Primary>KP_0"),
    ShortcutAction("fullscreen", "Tela cheia", "F11"),
)
SHORTCUT_IDS = tuple(action.identifier for action in SHORTCUT_ACTIONS)
DEFAULT_SHORTCUTS = {action.identifier: action.default for action in SHORTCUT_ACTIONS}


def split_accelerators(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


# Parsed without Gtk.accelerator_parse, which needs a display; this keeps
# --list-shortcuts, --diagnose and the unit tests working over SSH or in CI.
MODIFIER_NAMES = {
    "primary": Gdk.ModifierType.CONTROL_MASK,
    "control": Gdk.ModifierType.CONTROL_MASK,
    "ctrl": Gdk.ModifierType.CONTROL_MASK,
    "ctl": Gdk.ModifierType.CONTROL_MASK,
    "shift": Gdk.ModifierType.SHIFT_MASK,
    "shft": Gdk.ModifierType.SHIFT_MASK,
    "alt": Gdk.ModifierType.MOD1_MASK,
    "mod1": Gdk.ModifierType.MOD1_MASK,
    "super": Gdk.ModifierType.SUPER_MASK,
    "hyper": Gdk.ModifierType.HYPER_MASK,
    "meta": Gdk.ModifierType.META_MASK,
}
MODIFIER_MASK = (
    Gdk.ModifierType.CONTROL_MASK
    | Gdk.ModifierType.SHIFT_MASK
    | Gdk.ModifierType.MOD1_MASK
    | Gdk.ModifierType.SUPER_MASK
    | Gdk.ModifierType.HYPER_MASK
    | Gdk.ModifierType.META_MASK
)
MODIFIER_LABELS = (
    (Gdk.ModifierType.CONTROL_MASK, "Ctrl", "<Primary>"),
    (Gdk.ModifierType.MOD1_MASK, "Alt", "<Alt>"),
    (Gdk.ModifierType.SHIFT_MASK, "Shift", "<Shift>"),
    (Gdk.ModifierType.SUPER_MASK, "Super", "<Super>"),
    (Gdk.ModifierType.HYPER_MASK, "Hyper", "<Hyper>"),
    (Gdk.ModifierType.META_MASK, "Meta", "<Meta>"),
)
ACCELERATOR = re.compile(r"^((?:<[A-Za-z0-9]+>)*)([^<>\s]+)$")
VOID_SYMBOL = 0xFFFFFF


def parse_accelerator(accelerator: str) -> tuple[int, Gdk.ModifierType] | None:
    match = ACCELERATOR.fullmatch(accelerator.strip())
    if match is None:
        return None
    mods = Gdk.ModifierType(0)
    for name in re.findall(r"<([A-Za-z0-9]+)>", match.group(1)):
        modifier = MODIFIER_NAMES.get(name.casefold())
        if modifier is None:
            return None
        mods |= modifier
    keyval = Gdk.keyval_from_name(match.group(2))
    if keyval in (0, VOID_SYMBOL):
        return None
    return Gdk.keyval_to_lower(keyval), mods


def accelerator_name(keyval: int, state: Gdk.ModifierType) -> str:
    mods = state & MODIFIER_MASK
    prefix = "".join(token for mask, _label, token in MODIFIER_LABELS if mods & mask)
    return prefix + (Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or "")


def key_label(keyval: int) -> str:
    name = Gdk.keyval_name(keyval) or "?"
    if name.startswith("KP_"):
        rest = name[3:]
        symbols = {"Add": "+", "Subtract": "-", "Multiply": "*", "Divide": "/"}
        return "Num " + symbols.get(rest, rest)
    character = Gdk.keyval_to_unicode(keyval)
    if character > 32 and not (0x7F <= character <= 0x9F):
        return chr(character).upper()
    return name.replace("_", " ")


def is_valid_accelerator(value: str) -> bool:
    return all(parse_accelerator(item) is not None for item in split_accelerators(value))


def accelerator_label(value: str) -> str:
    labels = []
    for item in split_accelerators(value):
        parsed = parse_accelerator(item)
        if parsed is not None:
            keyval, mods = parsed
            parts = [label for mask, label, _token in MODIFIER_LABELS if mods & mask]
            labels.append("+".join([*parts, key_label(keyval)]))
    return " / ".join(labels) or "Desativado"


def is_letter(keyval: int) -> bool:
    return Gdk.keyval_to_upper(keyval) != Gdk.keyval_to_lower(keyval)


class ShortcutMap:
    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self.bindings: dict[str, str] = dict(DEFAULT_SHORTCUTS)
        self.errors: list[str] = []
        for identifier, value in (overrides or {}).items():
            if identifier not in DEFAULT_SHORTCUTS:
                self.errors.append(f"ação de atalho desconhecida: {identifier}")
            elif not is_valid_accelerator(value):
                self.errors.append(f"atalho inválido para {identifier}: {value}")
            else:
                self.bindings[identifier] = value
        self._compiled: list[tuple[int, Gdk.ModifierType, str]] = []
        for identifier in SHORTCUT_IDS:
            for item in split_accelerators(self.bindings[identifier]):
                parsed = parse_accelerator(item)
                if parsed is not None:
                    self._compiled.append((parsed[0], parsed[1], identifier))

    def overrides(self) -> dict[str, str]:
        return {
            identifier: value
            for identifier, value in self.bindings.items()
            if value != DEFAULT_SHORTCUTS[identifier]
        }

    def conflicts(self) -> dict[tuple[int, int], list[str]]:
        seen: dict[tuple[int, int], list[str]] = {}
        for key, mods, identifier in self._compiled:
            seen.setdefault((key, int(mods)), []).append(identifier)
        return {combo: ids for combo, ids in seen.items() if len(set(ids)) > 1}

    def match(self, keyval: int, state: Gdk.ModifierType) -> str | None:
        key = Gdk.keyval_to_lower(keyval)
        mods = state & MODIFIER_MASK
        without_shift = mods & ~Gdk.ModifierType.SHIFT_MASK
        for bound_key, bound_mods, identifier in self._compiled:
            if bound_key != key:
                continue
            if mods == bound_mods:
                return identifier
            # Symbols such as "+" need Shift on many layouts; accept the
            # shifted keystroke when the binding itself does not use Shift.
            if (
                not is_letter(key)
                and not bound_mods & Gdk.ModifierType.SHIFT_MASK
                and without_shift == bound_mods
            ):
                return identifier
        return None
