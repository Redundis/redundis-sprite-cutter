"""Cut a sprite sheet into separate pictures along a gap color."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

# Classic flat colors used as the empty space between sprites.
CHROMA_KEYS = (
    (255, 0, 255),
    (0, 255, 0),
    (0, 0, 255),
    (255, 0, 0),
    (0, 255, 255),
    (255, 255, 0),
)

# A guess that explodes into this many pieces is treated as noise, not a real cut.
MAX_SANE_PIECES = 4000


@dataclass
class Piece:
    """One cropped sprite, numbered in reading order starting at 1."""

    number: int
    x: int
    y: int
    width: int
    height: int
    image: Image.Image | None = None
    # The box from the original cut. Grouping changes x/y/width/height, not this.
    source_box: tuple[int, int, int, int] | None = None
    # Stable id. The number can change when the user reorders cuts.
    cut_id: str = ""
    origin_box: tuple[int, int, int, int] | None = None
    created: bool = False
    split_from: str = ""
    keep_with: str = ""
    out: bool = False
    passed: bool = False
    locked: bool = False
    clear_gap: bool = True


@dataclass
class SplitResult:
    """The cut pieces, plus a color suggestion when the sheet did not split."""

    pieces: list[Piece] = field(default_factory=list)
    suggestion: tuple[int, int, int] | None = None
    suggestion_text: str = ""

    @property
    def flagged(self) -> bool:
        return len(self.pieces) <= 1


def rgb_to_hex(color: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Not a hex color: {value}")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def load_image(path: str) -> Image.Image:
    """Open a still image. Animations use the first frame only."""
    with Image.open(path) as image:
        image.seek(0)
        return image.convert("RGBA")


def split_sheet(
    image: Image.Image,
    separator: tuple[int, int, int],
    tolerance: int = 0,
    min_pixels: int = 64,
    build_images: bool = True,
    smart_gaps: bool = True,
) -> SplitResult:
    """Split one sheet. Suggest a different gap color only for 0 or 1 piece."""
    rgba = np.array(image.convert("RGBA"))
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]
    pieces = _extract_pieces(
        rgba, rgb, alpha, separator, tolerance, min_pixels, build_images, smart_gaps
    )
    result = SplitResult(pieces=pieces)
    if len(pieces) <= 1:
        result.suggestion, result.suggestion_text = suggest_gap_color(
            rgb,
            alpha,
            separator,
            tolerance,
            min_pixels,
            len(pieces),
            smart_gaps,
        )
    return result


def suggest_gap_color(
    rgb: np.ndarray,
    alpha: np.ndarray,
    current: tuple[int, int, int],
    tolerance: int,
    min_pixels: int,
    piece_count: int,
    smart_gaps: bool = True,
) -> tuple[tuple[int, int, int] | None, str]:
    """Guess a gap color. The caller decides whether to use it."""
    if piece_count == 0:
        lead = "This sheet produced 0 pieces, so the cuts may be unsatisfactory."
    else:
        lead = "This sheet only produced 1 piece, so the cuts may be unsatisfactory."

    suggestion = _best_gap_candidate(rgb, alpha, current, tolerance, min_pixels, smart_gaps)
    if suggestion is None:
        text = (
            f"{lead} No clear gap color was found. "
            "Pick the color between the pictures, then double-check the preview."
        )
        return None, text

    text = (
        f"{lead} This sheet may be using {rgb_to_hex(suggestion)} instead. "
        "Double-check this color before exporting."
    )
    return suggestion, text


def _best_gap_candidate(
    rgb: np.ndarray,
    alpha: np.ndarray,
    current: tuple[int, int, int],
    tolerance: int,
    min_pixels: int,
    smart_gaps: bool = True,
) -> tuple[int, int, int] | None:
    """Pick a color that actually splits the sheet, without grabbing the grass."""
    edge = _mode_color(_border_pixels(rgb))
    common = _mode_color(rgb[::4, ::4].reshape(-1, 3))
    candidates: list[tuple[int, int, int]] = []

    def add(color: tuple[int, int, int]) -> None:
        if _same_color(color, current, tolerance):
            return
        if any(_same_color(color, existing, 0) for existing in candidates):
            return
        candidates.append(color)

    add(edge)
    for key in CHROMA_KEYS:
        found = _actual_color_near(rgb, key, max(tolerance, 8))
        if found is not None:
            add(found)

    sample = rgb[::4, ::4].reshape(-1, 3)
    colors, counts = np.unique(sample, axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]
    for index in order[:40]:
        color = tuple(int(channel) for channel in colors[index])
        if counts[index] < 8 or not _is_extreme(color):
            continue
        add(color)

    best_color = None
    best_rank = None
    for color in candidates[:16]:
        # The main picture color (often grass) is not a gap unless it is a
        # flat chroma key. Those keys are already extreme and stay eligible.
        if color == common and not _is_extreme(color):
            continue
        count = count_pieces(rgb, color, tolerance, min_pixels, alpha, smart_gaps)
        if count < 2 or count > MAX_SANE_PIECES:
            continue
        on_edge = _same_color(color, edge, max(tolerance, 0))
        # More separator pixels means a real gutter, not a stray speck.
        coverage = int(np.count_nonzero(_match_mask(rgb, color, tolerance)))
        rank = (_is_extreme(color), on_edge, coverage, count)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_color = color
    return best_color


def count_pieces(
    rgb: np.ndarray,
    separator: tuple[int, int, int],
    tolerance: int,
    min_pixels: int,
    alpha: np.ndarray | None = None,
    smart_gaps: bool = True,
) -> int:
    gap = _gap_mask(rgb, alpha, separator, tolerance, smart_gaps)
    return len(_boxes_from_content(~gap, min_pixels, smart_gaps))


def _extract_pieces(
    rgba: np.ndarray,
    rgb: np.ndarray,
    alpha: np.ndarray,
    separator: tuple[int, int, int],
    tolerance: int,
    min_pixels: int,
    build_images: bool,
    smart_gaps: bool,
) -> list[Piece]:
    gap = _gap_mask(rgb, alpha, separator, tolerance, smart_gaps)
    boxes = _boxes_from_content(~gap, min_pixels, smart_gaps)
    ordered = _reading_order(boxes)
    pieces: list[Piece] = []
    for number, (x, y, width, height) in enumerate(ordered, start=1):
        cropped = None
        if build_images:
            view = rgba[y : y + height, x : x + width].copy()
            view[gap[y : y + height, x : x + width], 3] = 0
            cropped = Image.fromarray(view, "RGBA")
        box = (x, y, width, height)
        pieces.append(Piece(number, x, y, width, height, cropped, box, origin_box=box))
    return pieces


def _gap_mask(
    rgb: np.ndarray,
    alpha: np.ndarray | None,
    separator: tuple[int, int, int],
    tolerance: int,
    smart_gaps: bool,
) -> np.ndarray:
    """Pixels that separate sprites and should not glue them together."""
    gap = _match_mask(rgb, separator, tolerance)
    if not smart_gaps:
        return gap
    if alpha is not None:
        # Empty pixels between sprites are a gap even when no color was painted there.
        gap = gap | (alpha <= 16)
    if _is_magenta_key(separator):
        # Some sheets draw the grid with a darker magenta than #ff00ff.
        family = (rgb[:, :, 0] >= 240) & (rgb[:, :, 1] <= 40) & (rgb[:, :, 2] >= 200)
        gap = gap | family
    gap = gap | _edge_flat_background(rgb, alpha)
    return gap


def _is_magenta_key(color: tuple[int, int, int]) -> bool:
    red, green, blue = color
    return red >= 200 and blue >= 200 and green <= 80


def _edge_flat_background(rgb: np.ndarray, alpha: np.ndarray | None) -> np.ndarray:
    """Black or white that touches the outside of the sheet, such as Cornelia's backdrop."""
    height, width = rgb.shape[:2]
    empty = np.zeros((height, width), dtype=bool)
    if height < 2 or width < 2:
        return empty
    edge = _mode_color(_border_pixels(rgb))
    high = max(edge)
    low = min(edge)
    if not (high <= 16 or low >= 240):
        return empty
    near = _match_mask(rgb, edge, 8)
    if alpha is not None:
        near = near & (alpha > 16)
    return _flood_from_edges(near)


def _flood_from_edges(mask: np.ndarray) -> np.ndarray:
    """Keep only mask pixels that can reach the border, so interior black stays put."""
    reached = np.zeros_like(mask)
    reached[0, :] = mask[0, :]
    reached[-1, :] = mask[-1, :]
    reached[:, 0] = mask[:, 0]
    reached[:, -1] = mask[:, -1]
    limit = max(mask.shape)
    for _ in range(limit):
        before = int(reached.sum())
        spread = reached.copy()
        spread[1:, :] |= reached[:-1, :]
        spread[:-1, :] |= reached[1:, :]
        spread[:, 1:] |= reached[:, :-1]
        spread[:, :-1] |= reached[:, 1:]
        reached = mask & spread
        if int(reached.sum()) == before:
            break
    return reached


def _boxes_from_content(content: np.ndarray, min_pixels: int, smart_gaps: bool) -> list[tuple[int, int, int, int]]:
    labels, _total = _label_foreground(content)
    if labels.max(initial=0) == 0:
        return []
    sizes = np.bincount(labels.ravel())
    boxes: list[tuple[int, int, int, int]] = []
    for label_id, size in enumerate(sizes):
        if label_id == 0 or size < min_pixels:
            continue
        ys, xs = np.nonzero(labels == label_id)
        x0 = int(xs.min())
        y0 = int(ys.min())
        x1 = int(xs.max())
        y1 = int(ys.max())
        if smart_gaps and size >= max(900, min_pixels * 8):
            split_boxes = _split_touching(content[y0 : y1 + 1, x0 : x1 + 1], min_pixels)
            if split_boxes:
                boxes.extend((x0 + sx, y0 + sy, sw, sh) for sx, sy, sw, sh in split_boxes)
                continue
        boxes.append((x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    return boxes


def _split_touching(component: np.ndarray, min_pixels: int) -> list[tuple[int, int, int, int]] | None:
    """Pull apart sprites that share an edge. A solid map stays one piece."""
    height, width = component.shape
    # A whole map is one picture. Splitting it walks every pixel and freezes the app.
    if height * width > 1_500_000:
        return None
    # Two pixels of shrink separates a light touch. Three handles a thicker join.
    for rounds in (2, 3):
        boxes = _split_eroded(component, min_pixels, rounds)
        if boxes:
            return boxes
    return None


def _erode(mask: np.ndarray, rounds: int) -> np.ndarray:
    """Shrink foreground by one pixel per round. A pixel stays only if its cross stays set."""
    result = mask.astype(bool)
    for _ in range(rounds):
        nxt = np.zeros_like(result)
        nxt[1:-1, 1:-1] = (
            result[1:-1, 1:-1]
            & result[1:-1, :-2]
            & result[1:-1, 2:]
            & result[:-2, 1:-1]
            & result[2:, 1:-1]
        )
        result = nxt
    return result


def _split_eroded(
    component: np.ndarray,
    min_pixels: int,
    rounds: int,
) -> list[tuple[int, int, int, int]] | None:
    eroded = _erode(component, rounds)
    seeds, total = _label_foreground(eroded)
    if total < 2:
        return None
    grown = _regrow(component, seeds)
    boxes = []
    sizes = np.bincount(grown.ravel())
    for label_id, size in enumerate(sizes):
        if label_id == 0 or size < min_pixels:
            continue
        ys, xs = np.nonzero(grown == label_id)
        x0 = int(xs.min())
        y0 = int(ys.min())
        boxes.append((x0, y0, int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1))
    if len(boxes) < 2 or not _split_keeps_sprite(component, boxes):
        return None
    return boxes


def _split_keeps_sprite(component: np.ndarray, boxes: list[tuple[int, int, int, int]]) -> bool:
    """Reject a split that would throw away thin parts, such as spray on a splash."""
    total = int(component.sum())
    if total <= 0:
        return False
    covered = np.zeros_like(component, dtype=bool)
    for x, y, w, h in boxes:
        covered[y : y + h, x : x + w] = True
    kept = int((component & covered).sum())
    return kept >= total * 0.9
    result = mask
    for _ in range(rounds):
        up = np.zeros_like(result)
        down = np.zeros_like(result)
        left = np.zeros_like(result)
        right = np.zeros_like(result)
        up[1:, :] = result[:-1, :]
        down[:-1, :] = result[1:, :]
        left[:, 1:] = result[:, :-1]
        right[:, :-1] = result[:, 1:]
        result = result & up & down & left & right
    return result


def _regrow(content: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """Spread eroded labels back out to the original sprite pixels."""
    labels = seeds.copy()
    height, width = content.shape
    for _ in range(max(height, width)):
        unlabeled = content & (labels == 0)
        if not np.any(unlabeled):
            break
        neighbor = np.zeros_like(labels)
        neighbor[1:, :] = np.maximum(neighbor[1:, :], labels[:-1, :])
        neighbor[:-1, :] = np.maximum(neighbor[:-1, :], labels[1:, :])
        neighbor[:, 1:] = np.maximum(neighbor[:, 1:], labels[:, :-1])
        neighbor[:, :-1] = np.maximum(neighbor[:, :-1], labels[:, 1:])
        fill = unlabeled & (neighbor > 0)
        if not np.any(fill):
            break
        labels[fill] = neighbor[fill]
    return labels


def _reading_order(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Group boxes into rows by their top edge, then left to right.

    Tops are compared instead of the full box height so a tall map on the
    left does not pull the rooms underneath it into the same row.
    """
    remaining = sorted(boxes, key=lambda box: (box[1], box[0]))
    rows: list[list[tuple[int, int, int, int]]] = []
    for box in remaining:
        _x, y, _w, height = box
        placed = False
        for row in rows:
            row_top = min(item[1] for item in row)
            shorter = min(height, min(item[3] for item in row))
            if abs(y - row_top) <= max(4, int(shorter * 0.55)):
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])

    rows.sort(key=lambda row: min(item[1] for item in row))
    ordered: list[tuple[int, int, int, int]] = []
    for row in rows:
        row.sort(key=lambda item: item[0])
        ordered.extend(row)
    return ordered


def apply_grouped_cuts(
    pieces: list[Piece],
    grouped_boxes: list[tuple[int, int, int, int]],
) -> list[Piece]:
    """Fold the listed cuts into the larger picture around each one."""
    current = pieces
    for box in grouped_boxes:
        updated = group_cut_into_parent(current, box)
        if updated is not None:
            current = updated
    return current


def group_cut_into_parent(
    pieces: list[Piece],
    child_box: tuple[int, int, int, int],
    skip_boxes: list[tuple[int, int, int, int]] | None = None,
) -> list[Piece] | None:
    """Paint one cut into the picture that contains it.

    The tighter containing picture wins. If the cut sits just outside every
    picture, it joins the nearest larger one. skip_boxes keeps other selected
    cuts from swallowing each other, so they all join the real picture around them.
    Returns None when this cut is already the largest picture on the sheet.
    """
    working = [_copy_piece(piece) for piece in pieces]
    child = next((piece for piece in working if _identity_box(piece) == child_box), None)
    if child is None:
        return None
    others = [piece for piece in working if piece is not child]
    skip = set(skip_boxes or [])
    preferred = [piece for piece in others if _identity_box(piece) not in skip]
    parent = _parent_picture(child, preferred) if preferred else None
    if parent is None:
        parent = _parent_picture(child, others)
    if parent is None:
        return None
    _paint_into(parent, child)
    working.remove(child)
    return _renumber(working)


def omit_pieces(pieces: list[Piece], removed_boxes: list[tuple[int, int, int, int]]) -> list[Piece]:
    """Drop cuts that should not be in the zip, then renumber what remains."""
    gone = set(removed_boxes)
    kept = [_copy_piece(piece) for piece in pieces if _identity_box(piece) not in gone]
    return _renumber(kept)


def apply_manual_boxes(
    pieces: list[Piece],
    image: Image.Image,
    manual: dict[tuple[int, int, int, int], tuple[int, int, int, int]],
) -> list[Piece]:
    """Replace a cut's box with the rectangle the user drew, and crop that from the sheet.

    The crop keeps every pixel inside the new box, including ones the automatic
    cut missed. Two cuts may cover the same pixels. The original source box stays
    so later edits still know which cut this is.
    """
    if not manual:
        return pieces
    width, height = image.size
    updated = []
    for piece in pieces:
        copy = _copy_piece(piece)
        box = manual.get(_identity_box(copy))
        if box is not None:
            x, y, box_w, box_h = box
            x = max(0, min(width - 1, int(x)))
            y = max(0, min(height - 1, int(y)))
            box_w = max(1, min(width - x, int(box_w)))
            box_h = max(1, min(height - y, int(box_h)))
            copy.x, copy.y, copy.width, copy.height = x, y, box_w, box_h
            copy.image = image.crop((x, y, x + box_w, y + box_h))
        updated.append(copy)
    return updated


def _copy_piece(piece: Piece) -> Piece:
    copy = Piece(piece.number, piece.x, piece.y, piece.width, piece.height, piece.image, piece.source_box)
    copy.cut_id = piece.cut_id
    copy.origin_box = piece.origin_box
    copy.created = piece.created
    copy.split_from = piece.split_from
    copy.keep_with = piece.keep_with
    copy.out = piece.out
    copy.passed = piece.passed
    copy.locked = piece.locked
    copy.clear_gap = piece.clear_gap
    return copy


def _identity_box(piece: Piece) -> tuple[int, int, int, int]:
    return piece.source_box or (piece.x, piece.y, piece.width, piece.height)


def _parent_picture(child: Piece, others: list[Piece]) -> Piece | None:
    """The larger picture this cut belongs with."""
    child_area = child.width * child.height
    center_x = child.x + child.width / 2
    center_y = child.y + child.height / 2
    containers: list[Piece] = []
    for other in others:
        if other.width * other.height <= child_area:
            continue
        inside_x = other.x <= center_x <= other.x + other.width
        inside_y = other.y <= center_y <= other.y + other.height
        if inside_x and inside_y:
            containers.append(other)
    if containers:
        # The smallest container is the map this detail is sitting on,
        # not some bigger box that happens to cover the whole sheet.
        return min(containers, key=lambda piece: piece.width * piece.height)

    larger = [other for other in others if other.width * other.height > child_area]
    if not larger:
        return None

    def edge_gap(other: Piece) -> tuple[int, int]:
        gap_x = max(0, other.x - (child.x + child.width), child.x - (other.x + other.width))
        gap_y = max(0, other.y - (child.y + child.height), child.y - (other.y + other.height))
        return (gap_x * gap_x + gap_y * gap_y, other.width * other.height)

    return min(larger, key=edge_gap)


def _paint_into(parent: Piece, child: Piece) -> None:
    """Expand the parent so the child sprite is part of the same picture."""
    left = min(parent.x, child.x)
    top = min(parent.y, child.y)
    right = max(parent.x + parent.width, child.x + child.width)
    bottom = max(parent.y + parent.height, child.y + child.height)
    canvas = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    if parent.image is not None:
        canvas.paste(parent.image, (parent.x - left, parent.y - top), parent.image)
    if child.image is not None:
        canvas.paste(child.image, (child.x - left, child.y - top), child.image)
    parent.x = left
    parent.y = top
    parent.width = right - left
    parent.height = bottom - top
    parent.image = canvas


def _renumber(pieces: list[Piece]) -> list[Piece]:
    boxes = [(piece.x, piece.y, piece.width, piece.height) for piece in pieces]
    order = {box: index for index, box in enumerate(_reading_order(boxes))}
    pieces.sort(key=lambda piece: (order.get((piece.x, piece.y, piece.width, piece.height), 0), piece.y, piece.x))
    for number, piece in enumerate(pieces, start=1):
        piece.number = number
    return pieces


def _label_foreground(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Label 4-connected True pixels. 0 is the background."""
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    parent = [0]

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    next_id = 1
    for y in range(height):
        row = mask[y]
        x = 0
        while x < width:
            if not row[x]:
                x += 1
                continue
            start = x
            x += 1
            while x < width and row[x]:
                x += 1
            above_ids: list[int] = []
            if y > 0:
                above = labels[y - 1, start:x]
                found = np.unique(above)
                above_ids = [int(item) for item in found if item != 0]
            if above_ids:
                chosen = above_ids[0]
                for other in above_ids[1:]:
                    union(chosen, other)
            else:
                chosen = next_id
                parent.append(next_id)
                next_id += 1
            labels[y, start:x] = chosen

    roots = [find(index) for index in range(len(parent))]
    compact = np.zeros(len(parent), dtype=np.int32)
    remap: dict[int, int] = {}
    total = 0
    for index, root in enumerate(roots):
        if root == 0:
            continue
        if root not in remap:
            total += 1
            remap[root] = total
        compact[index] = remap[root]
    return compact[labels], total


def _match_mask(rgb: np.ndarray, color: tuple[int, int, int], tolerance: int) -> np.ndarray:
    """True where a pixel is close to the gap color. Distance is per channel."""
    diff = np.abs(rgb.astype(np.int16) - np.array(color, dtype=np.int16))
    return np.max(diff, axis=2) <= int(tolerance)


def _border_pixels(rgb: np.ndarray) -> np.ndarray:
    top = rgb[0, :, :]
    bottom = rgb[-1, :, :]
    left = rgb[:, 0, :]
    right = rgb[:, -1, :]
    return np.concatenate([top, bottom, left, right], axis=0)


def _mode_color(pixels: np.ndarray) -> tuple[int, int, int]:
    colors, counts = np.unique(pixels.reshape(-1, 3), axis=0, return_counts=True)
    chosen = colors[int(np.argmax(counts))]
    return tuple(int(channel) for channel in chosen)


def _is_extreme(color: tuple[int, int, int]) -> bool:
    """A flat key color such as pure magenta, not a natural green or brown."""
    high = max(color)
    low = min(color)
    return high >= 245 and low <= 15 and (high - low) >= 200


def _same_color(left: tuple[int, int, int], right: tuple[int, int, int], tolerance: int) -> bool:
    return max(abs(a - b) for a, b in zip(left, right)) <= tolerance


def _actual_color_near(
    rgb: np.ndarray,
    key: tuple[int, int, int],
    tolerance: int,
) -> tuple[int, int, int] | None:
    """The real pixel color near a chroma key, so an exact cut can still match."""
    step = rgb[::3, ::3]
    mask = _match_mask(step, key, tolerance)
    if not np.any(mask):
        return None
    return _mode_color(step[mask])


def punch_gap(image: Image.Image, separator: tuple[int, int, int], tolerance: int = 0) -> Image.Image:
    """Take gap-color pixels out of a crop. Edge-connected bars go see-through."""
    rgba = np.array(image.convert("RGBA"))
    height, width = rgba.shape[:2]
    if width == 0 or height == 0:
        return image
    rgb = rgba[:, :, :3].astype(np.int16)
    key = np.array(separator, dtype=np.int16)
    gap = np.max(np.abs(rgb - key), axis=2) <= int(tolerance)
    outside = np.zeros((height, width), dtype=bool)
    stack: list[tuple[int, int]] = []
    for x in range(width):
        if gap[0, x]:
            stack.append((0, x))
        if gap[height - 1, x]:
            stack.append((height - 1, x))
    for y in range(height):
        if gap[y, 0]:
            stack.append((y, 0))
        if gap[y, width - 1]:
            stack.append((y, width - 1))
    while stack:
        y, x = stack.pop()
        if outside[y, x] or not gap[y, x]:
            continue
        outside[y, x] = True
        if x > 0:
            stack.append((y, x - 1))
        if x + 1 < width:
            stack.append((y, x + 1))
        if y > 0:
            stack.append((y - 1, x))
        if y + 1 < height:
            stack.append((y + 1, x))
    rgba[outside] = (0, 0, 0, 0)
    interior = np.argwhere(gap & ~outside)
    neighbors = ((-1, 0), (1, 0), (0, -1), (0, 1))
    for y, x in interior:
        fill = None
        see_through = False
        for dy, dx in neighbors:
            ny, nx = int(y) + dy, int(x) + dx
            if ny < 0 or ny >= height or nx < 0 or nx >= width:
                continue
            if gap[ny, nx]:
                continue
            if rgba[ny, nx, 3] < 16:
                see_through = True
                break
            if fill is None:
                fill = rgba[ny, nx].copy()
        if see_through or fill is None:
            rgba[int(y), int(x)] = (0, 0, 0, 0)
        else:
            rgba[int(y), int(x)] = fill
    return Image.fromarray(rgba, "RGBA")


def crop_cut(
    image: Image.Image,
    box: tuple[int, int, int, int],
    record: dict | None = None,
    separator: tuple[int, int, int] | None = None,
    tolerance: int = 0,
) -> Image.Image:
    """Crop one cut. Leave out the gap color unless this cut keeps it."""
    x, y, width, height = box
    cropped = image.crop((int(x), int(y), int(x + width), int(y + height)))
    keep = record is not None and record.get("clear_gap") is False
    if keep or separator is None:
        return cropped
    return punch_gap(cropped, separator, tolerance)


def empty_cut(box: tuple[int, int, int, int], created: bool = False, split_from: str = "") -> dict:
    """One cut record. The id lives on the sheet, not in this dict."""
    return {
        "box": tuple(box),
        "origin": tuple(box),
        "created": created,
        "split_from": split_from,
        "keep_with": "",
        "out": False,
        "passed": False,
        "locked": False,
        "clear_gap": True,
    }


def pieces_from_cuts(
    image: Image.Image | None,
    order: list[str],
    cuts: dict[str, dict],
    separator: tuple[int, int, int] | None = None,
    tolerance: int = 0,
) -> list[Piece]:
    """Build the on-screen pieces from stable cut records."""
    shown: list[Piece] = []
    number = 1
    for cut_id in order:
        record = cuts.get(cut_id)
        if record is None:
            continue
        x, y, width, height = record["box"]
        cropped = crop_cut(image, record["box"], record, separator, tolerance) if image is not None else None
        origin = tuple(record.get("origin") or record["box"])
        piece = Piece(
            number,
            x,
            y,
            width,
            height,
            cropped,
            origin,
            cut_id=cut_id,
            origin_box=origin,
            created=bool(record.get("created")),
            split_from=str(record.get("split_from") or ""),
            keep_with=str(record.get("keep_with") or ""),
            out=bool(record.get("out")),
            passed=bool(record.get("passed")),
            locked=bool(record.get("locked")),
            clear_gap=record.get("clear_gap", True) is not False,
        )
        piece.number = number
        number += 1
        shown.append(piece)
    return shown


def export_from_cuts(
    image: Image.Image,
    order: list[str],
    cuts: dict[str, dict],
    separator: tuple[int, int, int] | None = None,
    tolerance: int = 0,
) -> list[Piece]:
    """Crop the cuts that belong in the zip. Kept-with children join their parent box."""
    boxes: dict[str, list[int]] = {}
    for cut_id in order:
        record = cuts.get(cut_id)
        if record is None or record.get("out"):
            continue
        parent = record.get("keep_with") or ""
        if parent:
            child = list(record["box"])
            if parent not in boxes:
                parent_record = cuts.get(parent)
                if parent_record is None or parent_record.get("out"):
                    boxes[cut_id] = child
                    continue
                boxes[parent] = list(parent_record["box"])
            left, top, width, height = boxes[parent]
            cx, cy, cw, ch = child
            new_left = min(left, cx)
            new_top = min(top, cy)
            new_right = max(left + width, cx + cw)
            new_bottom = max(top + height, cy + ch)
            boxes[parent] = [new_left, new_top, new_right - new_left, new_bottom - new_top]
            continue
        boxes.setdefault(cut_id, list(record["box"]))
    pieces: list[Piece] = []
    number = 1
    for cut_id in order:
        box = boxes.get(cut_id)
        if box is None:
            continue
        x, y, width, height = box
        record = cuts.get(cut_id) or {}
        pieces.append(
            Piece(
                number,
                x,
                y,
                width,
                height,
                crop_cut(image, (x, y, width, height), record, separator, tolerance),
                tuple(box),
                cut_id=cut_id,
                clear_gap=record.get("clear_gap", True) is not False,
            )
        )
        number += 1
    return pieces
