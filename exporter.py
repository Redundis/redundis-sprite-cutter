"""Write one zip per sprite sheet, and an optional zip of those zips."""

from __future__ import annotations

import zipfile
from pathlib import Path

from PIL import Image

from cutter import Piece


def piece_filename(stem: str, number: int) -> str:
    """Default name: the original file name, a space, then -1, -2, and so on."""
    return f"{stem} -{number}.png"


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


def allocate_zip_path(
    folder: Path,
    stem: str,
    used: set[Path],
    keep_both: bool,
) -> Path:
    """Choose a zip path that does not collide inside this batch.

    When keep_both is on, a file that is already on disk gets (2), (3), ...
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
        if in_batch or (on_disk and keep_both):
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


def names_for_pieces(stem: str, pieces: list[Piece], custom_names: dict[int, str] | None) -> list[str]:
    """Build the file name for each piece. Custom names are optional."""
    custom_names = custom_names or {}
    used: set[str] = set()
    names: list[str] = []
    for piece in pieces:
        fallback = piece_filename(stem, piece.number)
        raw = custom_names.get(piece.number, fallback)
        name = safe_filename(raw, fallback)
        if name.lower() in used:
            base = name[:-4]
            name = safe_filename(f"{base} -{piece.number}", fallback)
        used.add(name.lower())
        names.append(name)
    return names


def _png_bytes(image: Image.Image) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
