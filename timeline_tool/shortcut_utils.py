"""Helpers for Tk shortcut normalization and key capture."""

from __future__ import annotations


_MODIFIER_ORDER = ("Control", "Alt", "Shift")
_MODIFIER_ALIASES = {
    "ctrl": "Control",
    "control": "Control",
    "alt": "Alt",
    "shift": "Shift",
}
_PURE_MODIFIERS = {
    "control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r",
    "meta_l", "meta_r", "super_l", "super_r",
}


def _canonical_key(key: str) -> str:
    aliases = {
        "left": "Left", "right": "Right", "up": "Up", "down": "Down",
        "return": "Return", "enter": "Return", "escape": "Escape", "esc": "Escape",
        "space": "space", "tab": "Tab", "backspace": "BackSpace", "delete": "Delete",
        "home": "Home", "end": "End", "prior": "Prior", "next": "Next",
    }
    lower = key.casefold()
    if lower in aliases:
        return aliases[lower]
    if len(key) == 1:
        return key.upper()
    if lower.startswith("f") and lower[1:].isdigit():
        return lower.upper()
    return key


def normalize_sequence(sequence: str) -> str:
    if not isinstance(sequence, str) or not sequence.strip():
        raise ValueError("快捷键不能为空")
    inner = sequence.strip()
    if inner.startswith("<") and inner.endswith(">"):
        inner = inner[1:-1]
    parts = [part.strip() for part in inner.replace("+", "-").split("-") if part.strip()]
    modifiers = set()
    keys = []
    for part in parts:
        modifier = _MODIFIER_ALIASES.get(part.casefold())
        if modifier:
            modifiers.add(modifier)
        else:
            keys.append(part)
    if len(keys) != 1:
        raise ValueError("快捷键必须包含一个普通按键")
    ordered = [name for name in _MODIFIER_ORDER if name in modifiers]
    return "<" + "-".join([*ordered, _canonical_key(keys[0])]) + ">"


def format_key_event(event) -> str | None:
    keysym = str(getattr(event, "keysym", "") or "")
    if not keysym or keysym.casefold() in _PURE_MODIFIERS:
        return None
    state = int(getattr(event, "state", 0) or 0)
    modifiers = []
    if state & 0x0004:
        modifiers.append("Control")
    if state & (0x0008 | 0x20000):
        modifiers.append("Alt")
    if state & 0x0001:
        modifiers.append("Shift")
    return "<" + "-".join([*modifiers, _canonical_key(keysym)]) + ">"


def display_sequence(sequence: str) -> str:
    """Convert a stored Tk event sequence to a user-facing key label."""
    normalized = normalize_sequence(sequence)
    parts = normalized[1:-1].split("-")
    labels = {
        "Control": "Ctrl",
        "Left": "←",
        "Right": "→",
        "Up": "↑",
        "Down": "↓",
        "space": "Space",
        "Return": "Enter",
        "Escape": "Esc",
        "Prior": "Page Up",
        "Next": "Page Down",
        "BackSpace": "Backspace",
    }
    return " + ".join(labels.get(part, part) for part in parts)
