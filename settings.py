"""Remember the last folder, gap color, and checkboxes between launches."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "output_folder": "",
    "gap_color": "#ff00ff",
    "tolerance": 0,
    "min_pixels": 64,
    "custom_names": False,
    "preview_before_export": True,
    "keep_both": False,
    "bundle_project": False,
    "include_subfolders": False,
    "smart_gaps": True,
    "zoom": 1,
    "output_scale": 1,
    "list_sort": "name",
}


def settings_file() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    folder = Path(base) / "Redundis Sprite Cutter"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def load_settings() -> dict:
    path = settings_file()
    saved: dict = {}
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}
    values = dict(DEFAULTS)
    if isinstance(saved, dict):
        for key in DEFAULTS:
            if key in saved:
                values[key] = saved[key]
    values["tolerance"] = _clamp_int(values["tolerance"], 0, 64, 0)
    values["min_pixels"] = _clamp_int(values["min_pixels"], 1, 100000, 64)
    values["zoom"] = _clamp_int(values["zoom"], 1, 10, 1)
    values["output_scale"] = _clamp_int(values["output_scale"], 1, 4, 1)
    values["gap_color"] = _clean_hex(str(values["gap_color"]))
    for key in (
        "custom_names",
        "preview_before_export",
        "keep_both",
        "bundle_project",
        "include_subfolders",
        "smart_gaps",
    ):
        values[key] = bool(values[key])
    values["output_folder"] = str(values["output_folder"] or "")
    sort = str(values["list_sort"] or "name")
    allowed = {
        "name",
        "name_desc",
        "modified_new",
        "modified_old",
        "created_new",
        "created_old",
        "size_desc",
        "size_asc",
        "pieces_desc",
        "pieces_asc",
        "folder",
    }
    values["list_sort"] = sort if sort in allowed else "name"
    return values


def save_settings(values: dict) -> None:
    payload = dict(DEFAULTS)
    payload.update({key: values[key] for key in DEFAULTS if key in values})
    path = settings_file()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _clean_hex(value: str) -> str:
    text = value.strip().lower()
    if not text.startswith("#"):
        text = "#" + text
    if len(text) != 7:
        return "#ff00ff"
    try:
        int(text[1:], 16)
    except ValueError:
        return "#ff00ff"
    return text
