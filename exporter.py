"""Write one zip per sprite sheet, and an optional zip of those zips."""

from __future__ import annotations

import zipfile
from pathlib import Path

from PIL import Image

from cutter import Piece


def piece_filename(stem: str, number: int) -> str:
    """Default name: the original file name, a space, then -1, -2, and so on."""
    return f"{stem} -{number}.png"


def name_base(raw: str, stem: str) -> str:
    """Keep the words the user typed, without .png or a trailing list number."""
    text = (raw or "").strip()
    if text.lower().endswith(".png"):
        text = text[:-4]
    if " -" in text:
        head, tail = text.rsplit(" -", 1)
        if tail.isdigit():
            text = head.strip()
    text = text.strip()
    if not text or text == stem:
        return ""
    return text


def cut_filename(stem: str, number: int, custom_base: str = "") -> str:
    """Sheet name or a shared custom name, plus a list number."""
    return piece_filename(custom_base or stem, number)


def custom_base_of(custom_names: dict | None, cut_id: str, stem: str) -> str:
    return name_base(str((custom_names or {}).get(cut_id, "") or ""), stem)


def included_cut_ids(order: list[str], cuts: dict) -> list[str]:
    ids = []
    for cut_id in order:
        record = cuts.get(cut_id)
        if record is None or record.get("out") or record.get("keep_with"):
            continue
        ids.append(cut_id)
    return ids


def cut_display_name(stem: str, order: list[str], cuts: dict, custom_names: dict | None, cut_id: str) -> str:
    """Unique custom names stay plain. Shared names get -1, -2. Defaults use the sheet name."""
    included = included_cut_ids(order, cuts)
    base = custom_base_of(custom_names, cut_id, stem)
    if cut_id not in included:
        return f"{base or stem}.png"
    if not base:
        return piece_filename(stem, included.index(cut_id) + 1)
    group = [item for item in included if custom_base_of(custom_names, item, stem).lower() == base.lower()]
    if len(group) < 2:
        return f"{base}.png"
    return piece_filename(base, group.index(cut_id) + 1)


def safe_filename(name: str, fallback: str) -> str:
    """Keep a custom name usable on Windows and force a .png ending."""
    cleaned = name.strip()
    for mark in '\\/:*?"<>|':
        cleaned = cleaned.replace(mark, "")
    cleaned = cleaned.strip(" .")
    if not cleaned:
        cleaned = fallback
    if not cleaned.lower().endswith(".png"):
        cleaned += ".png"
    return cleaned


def safe_zip_stem(name: str) -> str:
    """Keep a project or sheet name usable as a zip file name."""
    cleaned = str(name or "").strip()
    if cleaned.lower().endswith(".zip"):
        cleaned = cleaned[:-4]
    for mark in '\\/:*?"<>|':
        cleaned = cleaned.replace(mark, "")
    cleaned = " ".join(cleaned.split())
    return cleaned.strip(" .")


def zip_stem(project: str, sheet_stem: str) -> str:
    """Project name prefixes the sheet zip. A blank project uses the sheet name."""
    prefix = safe_zip_stem(project)
    base = safe_zip_stem(sheet_stem) or "sheet"
    return f"{prefix} - {base}" if prefix else base


def project_zip_name(project: str) -> str:
    """Name for the optional zip that holds every sheet zip."""
    prefix = safe_zip_stem(project)
    return f"{prefix}.zip" if prefix else "sprite sheets.zip"


def allocate_zip_path(
    folder: Path,
    stem: str,
    used: set[Path],
    unique: bool = True,
) -> Path:
    """Choose a zip path that does not collide inside this batch.

    When unique is on, a file that is already on disk gets (2), (3), ...
    When it is off, that existing file is reused so the export can overwrite it.
    Two sheets in the same batch that share a name always get separate zips.
    """
    number = 1
    while True:
        if number == 1:
            path = folder / f"{stem}.zip"
        else:
            path = folder / f"{stem} ({number}).zip"
        in_batch = path in used
        on_disk = path.exists()
        if in_batch or (on_disk and unique):
            number += 1
            continue
        used.add(path)
        return path


def write_original_zip(path: Path, source: Path) -> None:
    """Put the untouched source file in a zip when a sheet is excluded from cutting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(source, arcname=source.name)


def scale_piece(image: Image.Image, factor: int) -> Image.Image:
    """Enlarge a cut by a whole number so each pixel stays a square."""
    factor = max(1, min(4, int(factor)))
    if factor == 1:
        return image
    return image.resize((image.width * factor, image.height * factor), Image.Resampling.NEAREST)


def write_sheet_zip(path: Path, pieces: list[tuple[str, Image.Image]]) -> None:
    """Save the cut pictures inside one zip. Names are the first item of each pair."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, image in pieces:
            archive.writestr(name, _png_bytes(image))


def write_project_zip(path: Path, sheet_zips: list[Path]) -> None:
    """Bundle the individual sheet zips into one project zip."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for sheet_zip in sheet_zips:
            archive.write(sheet_zip, arcname=sheet_zip.name)


def names_for_pieces(stem: str, pieces: list[Piece], custom_names: dict | None) -> list[str]:
    """Unique custom names stay plain. Shared names get -1, -2. Defaults use the sheet name."""
    custom_names = custom_names or {}
    used: set[str] = set()
    names: list[str] = []
    bases = []
    for piece in pieces:
        raw = custom_names.get(piece.cut_id, "") if piece.cut_id else ""
        if not raw:
            raw = custom_names.get(piece.number, "")
        bases.append(name_base(str(raw or ""), stem))
    for piece, base in zip(pieces, bases):
        if not base:
            raw = piece_filename(stem, piece.number)
        else:
            group = [item.number for item, other in zip(pieces, bases) if other.lower() == base.lower()]
            raw = piece_filename(base, group.index(piece.number) + 1) if len(group) > 1 else f"{base}.png"
        fallback = piece_filename(stem, piece.number)
        name = safe_filename(raw, fallback)
        if name.lower() in used:
            name = safe_filename(piece_filename(base or stem, piece.number), fallback)
        used.add(name.lower())
        names.append(name)
    return names


def _png_bytes(image: Image.Image) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
