"""Application-wide settings persistence and legacy migration."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import config
from shortcut_utils import normalize_sequence


logger = logging.getLogger(__name__)


DEFAULT_SHORTCUTS = {
    "move_backward": "<Left>",
    "move_forward": "<Right>",
    "previous_node": "<Control-Left>",
    "next_node": "<Control-Right>",
    "zoom_track_in": "<Up>",
    "zoom_track_out": "<Down>",
    "zoom_all_in": "<Control-Up>",
    "zoom_all_out": "<Control-Down>",
}


_DEFAULTS = {
    "general": {
        "opacity": config.DEFAULT_ALPHA,
    },
    "alerts": {
        "sound_enabled": True,
        "visual_enabled": True,
        "alert_lead_frames": 60,
        "pause_lead_frames": config.PAUSE_LEAD_FRAMES,
    },
    "timeline": {
        "node_find_tolerance": config.NODE_FIND_TOLERANCE,
        "node_click_tolerance": config.NODE_CLICK_TOLERANCE,
        "keyboard_scroll_step": config.KEYBOARD_SCROLL_STEP,
        "mouse_wheel_scroll_step": config.MOUSE_WHEEL_SCROLL_STEP,
    },
    "shortcuts": DEFAULT_SHORTCUTS,
    "ruler": {
        "websocket_uri": config.WEBSOCKET_URI,
        "reconnect_delay": config.WEBSOCKET_RECONNECT_DELAY,
    },
    "auto_pause": {
        "pc_key_hold_ms": config.PC_PAUSE_KEY_HOLD_MS,
        "focus_game_before_send": config.FOCUS_GAME_BEFORE_SEND,
        "require_admin_for_pc": config.PAUSE_REQUIRE_ADMIN_FOR_PC,
    },
    "emulator": {
        "enabled": config.ADB_PAUSE_ENABLED,
        "auto_detect": True,
        "install_dir": "",
        "adb_path": "",
        "serial": config.ADB_SERIAL,
        "prefer_for_emulator": config.ADB_PREFER_FOR_EMULATOR,
    },
}


class SettingsValidationError(ValueError):
    """Raised when a user setting has an invalid type, value, or shortcut."""


def default_settings() -> dict[str, Any]:
    return copy.deepcopy(_DEFAULTS)


def _number(value: Any, path: str, minimum: float, maximum: float, *, integer: bool) -> int | float:
    if isinstance(value, bool):
        raise SettingsValidationError(f"{path} 必须是数字")
    try:
        converted = int(value) if integer else float(value)
    except (TypeError, ValueError) as exc:
        raise SettingsValidationError(f"{path} 必须是数字") from exc
    if not minimum <= converted <= maximum:
        raise SettingsValidationError(f"{path} 必须在 {minimum} 到 {maximum} 之间")
    return converted


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SettingsValidationError(f"{path} 必须是布尔值")
    return value


def _string(value: Any, path: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SettingsValidationError(f"{path} 必须是字符串")
    return value.strip()


def validate_settings(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge partial settings with defaults and strictly validate known fields."""
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise SettingsValidationError("设置根节点必须是对象")

    result = default_settings()

    ranges = {
        "general.opacity": (0.30, 1.00, False),
        "alerts.alert_lead_frames": (0, 300, True),
        "alerts.pause_lead_frames": (0, 30, True),
        "timeline.node_find_tolerance": (0, 30, True),
        "timeline.node_click_tolerance": (0, 30, True),
        "timeline.keyboard_scroll_step": (1, 30, True),
        "timeline.mouse_wheel_scroll_step": (1, 30, True),
        "ruler.reconnect_delay": (1, 60, True),
        "auto_pause.pc_key_hold_ms": (10, 500, True),
    }
    booleans = {
        "alerts.sound_enabled",
        "alerts.visual_enabled",
        "auto_pause.focus_game_before_send",
        "auto_pause.require_admin_for_pc",
        "emulator.enabled",
        "emulator.auto_detect",
        "emulator.prefer_for_emulator",
    }
    strings = {
        "emulator.install_dir",
        "emulator.adb_path",
        "emulator.serial",
    }

    for dotted, (minimum, maximum, integer) in ranges.items():
        value = get_setting(data, dotted, None)
        if value is not None:
            set_setting(result, dotted, _number(value, dotted, minimum, maximum, integer=integer))

    for dotted in booleans:
        value = get_setting(data, dotted, None)
        if value is not None:
            set_setting(result, dotted, _boolean(value, dotted))

    for dotted in strings:
        value = get_setting(data, dotted, None)
        if value is not None:
            set_setting(result, dotted, _string(value, dotted))

    ruler_uri = get_setting(data, "ruler.websocket_uri", None)
    if ruler_uri is not None:
        set_setting(result, "ruler.websocket_uri", _string(ruler_uri, "ruler.websocket_uri", allow_empty=False))

    shortcuts = data.get("shortcuts", {})
    if shortcuts is not None:
        if not isinstance(shortcuts, Mapping):
            raise SettingsValidationError("shortcuts 必须是对象")
        for action in DEFAULT_SHORTCUTS:
            if action in shortcuts:
                raw = _string(shortcuts[action], f"shortcuts.{action}", allow_empty=False)
                try:
                    result["shortcuts"][action] = normalize_sequence(raw)
                except ValueError as exc:
                    raise SettingsValidationError(f"shortcuts.{action}: {exc}") from exc

    seen: dict[str, str] = {}
    for action, sequence in result["shortcuts"].items():
        normalized = normalize_sequence(sequence).casefold()
        if normalized in seen:
            raise SettingsValidationError(f"快捷键冲突：{seen[normalized]} 与 {action}")
        seen[normalized] = action

    return result


def load_settings(path: str | os.PathLike[str]) -> dict[str, Any]:
    settings_path = Path(path)
    if not settings_path.exists():
        return default_settings()
    try:
        with settings_path.open("r", encoding="utf-8") as handle:
            return validate_settings(json.load(handle))
    except (OSError, json.JSONDecodeError, SettingsValidationError, TypeError) as exc:
        logger.warning("设置文件损坏或无效，已使用默认值: %s", exc)
        return default_settings()


def save_settings(path: str | os.PathLike[str], data: Mapping[str, Any]) -> dict[str, Any]:
    settings = validate_settings(data)
    settings_path = Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=settings_path.parent, prefix=f".{settings_path.name}.", suffix=".tmp", delete=False
        ) as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, settings_path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
    return settings


def migrate_legacy_settings(
    settings_path: str | os.PathLike[str],
    pause_settings_path: str | os.PathLike[str] | None = None,
    timeline_path: str | os.PathLike[str] | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Create settings.json once from legacy pause and first-track reminder values."""
    target = Path(settings_path)
    if target.exists():
        return load_settings(target)

    migrated = default_settings()
    if pause_settings_path:
        try:
            with Path(pause_settings_path).open("r", encoding="utf-8") as handle:
                legacy_pause = json.load(handle)
            if "pause_lead_frames" in legacy_pause:
                migrated["alerts"]["pause_lead_frames"] = legacy_pause["pause_lead_frames"]
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    if timeline_path:
        try:
            with Path(timeline_path).open("r", encoding="utf-8") as handle:
                legacy_timeline = json.load(handle)
            tracks = legacy_timeline.get("tracks", []) if isinstance(legacy_timeline, dict) else []
            first = tracks[0] if tracks and isinstance(tracks[0], dict) else {}
            mappings = {
                "sound_alert_enabled": "sound_enabled",
                "visual_alert_enabled": "visual_enabled",
                "alert_lead_frames": "alert_lead_frames",
            }
            for old_key, new_key in mappings.items():
                if old_key in first:
                    migrated["alerts"][new_key] = first[old_key]
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    migrated = validate_settings(migrated)
    return save_settings(target, migrated) if persist else migrated


def get_setting(data: Mapping[str, Any], dotted_path: str, default: Any = None) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def set_setting(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current = data
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value
