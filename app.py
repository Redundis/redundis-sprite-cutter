"""Redundis Sprite Cutter — split sprite sheets and save one zip per sheet."""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import Label, Listbox, Menu, Toplevel, colorchooser, filedialog, messagebox

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from cutter import (
    crop_cut,
    empty_cut,
    export_from_cuts,
    hex_to_rgb,
    load_image,
    pieces_from_cuts,
    rgb_to_hex,
    split_sheet,
)
from exporter import (
    allocate_zip_path,
    cut_display_name,
    name_base,
    names_for_pieces,
    project_zip_name,
    safe_zip_stem,
    scale_piece,
    write_original_zip,
    write_project_zip,
    write_sheet_zip,
    zip_stem,
)
from settings import load_settings, save_settings, settings_file

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # Drag and drop is optional if the package is missing.
    DND_FILES = None
    TkinterDnD = None

# Still images only. WebM is video and is not accepted.
IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".avif",
    ".heic",
    ".heif",
}

BG = "#0c0c0c"
PANEL = "#161616"
RAISED = "#222222"
RED = "#d0122d"
RED_HOVER = "#a80e24"
TEXT = "#f4f4f4"
MUTED = "#9a9a9a"

HELP_TEXT = """Sprite Cutter splits a sprite sheet into separate pictures and saves them in a zip. Nothing is uploaded.

Where sheets come from
Use pictures you drew or exported yourself. A large public collection of game sprites is The Spriters Resource: https://www.spriters-resource.com/

Add pictures
Use Add sheets, Add folder, or drop files onto the window. The first sheet opens on its own. Click another sheet once to open that file and its cuts.

Gap color
The empty color between pictures. Default puts the shared color back to magenta, #ff00ff. This sheet only keeps a different color on the open sheet. Use default makes that sheet follow the color at the top again. Pick from sheet takes the color you click.

Pass as is
The selected pictures go in the zip as their own files, using the cuts you see. They turn purple.

Leave out of zip
Leaves the selected pictures out of the download. They stay on screen with a dashed outline and the words Left out of zip.

Look and pick
The main screen is for looking and picking. Scroll or pinch to zoom. Drag to look around. Reset size shows the whole sheet.

Select
Click a cut or a thumb. Ctrl+click adds one. Shift+click takes a range. Gold means selected.

Order and names
Drag a thumb to a new place to change its number. The cutter always shows those numbers so you can pick and edit. Saved files use the sheet name plus that number, like castle -1.png, unless Custom file names is on. Turn that on to type a name. A unique name stays as you typed it, like hero.png. If more than one picture uses the same name, the list adds -1, -2, -3, like sword -1.png. Pictures left out of the zip are not numbered. A project name only names the zip. It does not change these numbers. Reset order puts the numbers back the way they were after the first scan. It asks first. Undo takes one move back. Change history can undo several.

Quick merge
Joins two or more highlighted pictures into one box. The earliest number stays. Undo takes that merge back. Leave out gap color is on by default, so the gap between those boxes is taken out of the merged picture.

Leave out gap color
On for each picture unless you turn it off. It takes this sheet's gap color out of the selected pictures, including after a merge, a new box, or a resize. The empty bar is left see-through, or filled with the color around it if that bar is trapped inside the picture. Turn it off to keep the gap color in those pictures. You can change one picture, several, or all.

Change history
Lists every box change on this sheet. Undo to here puts the sheet back to before that change. The same list is used on the main screen and in Edit cuts.

Edit cuts
Opens a larger window to change boxes. That window has its own Help for zoom, pan, move, split, and the other tools. Confirm writes the edits. Cancel puts the sheet back.

Export
Each sheet becomes its own zip in the output folder. A project name only names that zip. It does not change the numbers on the cuts. The pictures inside still use the sheet name plus the number, like castle -1.png, unless Custom file names is on. If you type a project name, zips are named like FF1 - castle.zip. Leave it blank for the sheet name, like castle.zip. If that name is already in the folder, Save without replacing keeps the old file and writes castle (2).zip. You can also type a different project name there. Overwrite old files is the last choice. Also save one zip that contains every sheet zip asks where to put that extra file.
"""

EDIT_HELP_TEXT = """Edit cuts
Change the boxes on this sheet. Confirm keeps the edits. Cancel puts the sheet back.

Look around
The whole sheet stays on screen. Selecting a box only changes its outline. Scroll the mouse wheel to zoom. A trackpad pinch does the same. Drag to move the view, even if you start on a box. A drag does not change what is selected. Reset size shows the whole sheet again.

Select
A click or tap on a box highlights only that box. Dragging is never a select. Gold means that cut can be edited. A box must be highlighted before you can move or resize it.
The small pictures under the sheet work the same as the main page. Click one to select it. Ctrl+click adds or removes one. Shift+click marks a range. Select all and Select none are shortcuts.

Order and names
Drag a picture to a new place to change its number. The cutter always shows those numbers so you can pick and edit. Saved files use the sheet name plus that number, like castle -1.png, unless you typed a custom name. A unique custom name stays as you typed it, like hero.png. If more than one picture uses the same name, the list adds -1, -2, -3, like sword -1.png. Pictures left out of the zip are not numbered. Reset order puts the numbers back the way they were after the first scan. It asks first. Undo takes one move back. Redo and Change history can put several moves back.

Move and resize
After one box is highlighted, drag the middle to move the whole box. Drag an edge or a corner to resize. Move only works with one box selected. The selected box keeps the grab, even when other boxes sit close. Zoom in if two boxes are tight.

Lock
Lock pins the selected boxes so they cannot be moved or resized. Their outline turns sky blue and dashed. Unlock lets you edit them again. Use this for leftover boxes that keep getting grabbed by accident.

Buttons
New cut makes a new box, about the average size of the current cuts, then asks what number it should be. The new box is selected. If another box was highlighted, the new one appears near it.
Split across cuts one selected box in half, left and right. Split down cuts it top and bottom.
Merge turns two or more selected boxes into one box that covers them all. The earliest number stays. Undo and Redo can take that merge back. Leave out gap color is on by default, so the gap between those boxes is taken out of the merged picture and left empty or see-through. Turn that checkbox off on the selected pictures if you want to keep the gap color in them.
Keep with needs two cuts: a leftover and the sprite it belongs with. The leftover is not its own file.
Leave out keeps the selected cuts on screen with a dashed red outline, and they are not in the zip. Pass as is puts them in the zip as their own files, using the boxes you see now.
Leave out gap color takes the sheet's gap color out of the selected pictures. It is on by default. Turn it off to keep that color in those pictures. You can change one picture, several, or all.
Undo and Redo step through your edits. Change history lists every change on this sheet and lets you undo back to any one of them. Revert puts the selected cuts back to the first scan.

Colors
Gold = selected. Red = cut. Cyan = new. Orange = split. Dashed red = left out of the zip. Sky dashed = locked. Green = kept with another. Purple = pass as is.
"""
LINE = "#2e2e2e"
WARN = "#e0a030"
GOLD = "#f0c040"
EDIT = "#3ec6ff"
SPLIT = "#ff8c32"
LOCK = "#7dffb3"
PASS = "#b388ff"
PIN = "#7ec8ff"
SELECT = "#3a1218"
FONT_FAMILY = "Silkscreen"
_BOLD_FONT_PATH: Path | None = None


def app_folder() -> Path:
    """Folder that holds fonts. A packaged app unpacks these beside the program."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def load_brand_fonts() -> None:
    """Load Silkscreen for this app only, even if it is not installed on the PC."""
    global _BOLD_FONT_PATH
    folder = app_folder() / "fonts"
    regular = folder / "Silkscreen-Regular.ttf"
    bold = folder / "Silkscreen-Bold.ttf"
    _BOLD_FONT_PATH = bold if bold.exists() else None
    if os.name != "nt":
        return
    # Private fonts stay inside this program and do not change Windows.
    added = ctypes.windll.gdi32.AddFontResourceExW
    added.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
    added.restype = ctypes.c_int
    private = 0x10
    for path in (regular, bold):
        if path.exists():
            added(str(path), private, None)


def register_extra_formats() -> None:
    """Teach Pillow how to open Apple HEIC and AVIF files."""
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:
        pass
    try:
        from pillow_heif import register_avif_opener

        register_avif_opener()
    except Exception:
        pass


class WrapBar(ctk.CTkFrame):
    """A row of controls that drops to the next line when the window is too narrow."""

    def __init__(self, master, gap: int = 4, **kwargs):
        super().__init__(master, **kwargs)
        self._gap = gap
        self._items: list = []
        self._busy = False
        self._last_h = 34
        self.configure(height=34)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.bind("<Configure>", lambda _event: self.reflow())

    def add(self, widget):
        self._items.append(widget)
        self.after_idle(self.reflow)
        return widget

    def reflow(self, _event=None) -> None:
        if self._busy or not self.winfo_exists():
            return
        self._busy = True
        try:
            width = max(self.winfo_width(), 1)
            x = 0
            y = 0
            row_h = 0
            for child in self._items:
                if child is None or not child.winfo_exists():
                    continue
                child.update_idletasks()
                child_w = max(child.winfo_reqwidth(), 1)
                child_h = max(child.winfo_reqheight(), 1)
                if x and x + child_w > width:
                    x = 0
                    y += row_h + self._gap
                    row_h = 0
                child.place(x=x, y=y)
                x += child_w + self._gap
                row_h = max(row_h, child_h)
            needed = y + row_h if row_h else 34
            if abs(self._last_h - needed) > 1:
                self._last_h = needed
                self.configure(height=needed)
        finally:
            self._busy = False


class Sheet:
    """One source file waiting to be cut."""

    def __init__(self, path: Path):
        self.path = path
        self.override: tuple[int, int, int] | None = None
        self.piece_count: int | None = None
        self.piece_total: int | None = None
        self.suggestion: tuple[int, int, int] | None = None
        self.suggestion_text = ""
        self.custom_names: dict[str, str] = {}
        self.excluded = False
        self.next_cut = 1
        self.cut_order: list[str] = []
        self.scan_order: list[str] = []
        self.cuts: dict[str, dict] = {}
        self.box_undo: list[tuple[dict, str]] = []
        self.box_redo: list[tuple[dict, str]] = []
        self.error = ""
        self.generation = 0
        self.row = None
        self.meta_label = None
        self.chip = None
        self.mark = None

    @property
    def flagged(self) -> bool:
        count = self.piece_total if self.piece_total is not None else self.piece_count
        return count is not None and count <= 1

    def new_cut_id(self) -> str:
        cut_id = f"c{self.next_cut}"
        self.next_cut += 1
        return cut_id

    def install_scan(self, pieces) -> None:
        self.cuts = {}
        self.cut_order = []
        self.next_cut = 1
        self.box_undo = []
        self.box_redo = []
        self.custom_names = {}
        for piece in pieces:
            cut_id = self.new_cut_id()
            box = (piece.x, piece.y, piece.width, piece.height)
            self.cuts[cut_id] = empty_cut(box)
            self.cut_order.append(cut_id)
        self.scan_order = list(self.cut_order)

    def snapshot_cuts(self) -> dict:
        return {
            "order": list(self.cut_order),
            "cuts": {key: dict(value) for key, value in self.cuts.items()},
            "next_cut": self.next_cut,
        }

    def restore_cuts(self, state: dict) -> None:
        self.cut_order = list(state.get("order") or [])
        self.cuts = {key: dict(value) for key, value in (state.get("cuts") or {}).items()}
        self.next_cut = int(state.get("next_cut") or (len(self.cut_order) + 1))

    def exportable_count(self) -> int:
        return sum(
            1
            for cut_id in self.cut_order
            if cut_id in self.cuts and not self.cuts[cut_id].get("out") and not self.cuts[cut_id].get("keep_with")
        )


class App(ctk.CTk, *(TkinterDnD.DnDWrapper,) if TkinterDnD else ()):
    def __init__(self):
        load_brand_fonts()
        ctk.ThemeManager.theme["CTkFont"]["family"] = FONT_FAMILY
        ctk.ThemeManager.theme["CTkFont"]["size"] = 16
        super().__init__()
        self._dnd = False
        if TkinterDnD is not None:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self._dnd = True
            except Exception:
                self._dnd = False

        self.title("Redundis Sprite Cutter")
        self._apply_window_icon()
        self.geometry("1440x980")
        self.minsize(1040, 720)
        self.configure(fg_color=BG)

        saved = load_settings()
        self.output_folder = saved["output_folder"]
        self.gap_color = hex_to_rgb(saved["gap_color"])
        self.tolerance = saved["tolerance"]
        self.min_pixels = saved["min_pixels"]
        self.zoom = saved["zoom"]
        self.output_scale = saved["output_scale"]
        self.sheets: list[Sheet] = []
        self.selection: list[Sheet] = []
        self._anchor: Sheet | None = None
        self._known: set[str] = set()
        self.selected: Sheet | None = None
        self.busy = False
        self.eyedropper = False
        self._preview_image: Image.Image | None = None
        self._preview_pieces = []
        self._preview_token = 0
        self._photo = None
        self._thumb_refs: list = []
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._press = None
        self._resize = None
        self._fit_view = True
        self._view_origin = (0, 0, 1.0)
        self._raw_pieces = []
        self._thumb_token = 0
        self._thumb_focus = None
        self._thumb_pending: list = []
        self._thumb_columns: dict[tuple, object] = {}
        self._cut_ids: list[str] = []
        self._cut_anchor: str | None = None
        self._cut_boxes: list = []
        self._thumb_drag = None
        self.list_sort = saved["list_sort"]
        self._ui_queue: queue.Queue = queue.Queue()

        self.include_subfolders = ctk.BooleanVar(value=saved["include_subfolders"])
        self.custom_names = ctk.BooleanVar(value=saved["custom_names"])
        self.preview_on = ctk.BooleanVar(value=saved["preview_before_export"])
        self.project_name = ctk.StringVar(value=saved["project_name"])
        self.bundle_project = ctk.BooleanVar(value=saved["bundle_project"])
        self.smart_gaps = ctk.BooleanVar(value=saved["smart_gaps"])
        self.clear_gap_var = ctk.BooleanVar(value=True)
        self._clear_gap_sync = False

        self._build()
        self.after(200, self._apply_window_icon)
        self.after(50, self._drain_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if self._dnd:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 4))
        title = ctk.CTkFrame(header, fg_color=BG)
        title.pack(side="left")
        ctk.CTkLabel(
            title,
            text="REDUNDIS",
            text_color=RED,
            font=ctk.CTkFont(family=FONT_FAMILY, size=24, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            title,
            text="  Sprite Cutter",
            text_color=TEXT,
            font=ctk.CTkFont(family=FONT_FAMILY, size=24),
        ).pack(side="left")
        link = ctk.CTkLabel(
            header,
            text="redundis.com",
            text_color=RED,
            cursor="hand2",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, underline=True),
        )
        link.pack(side="right", padx=(0, 4))
        link.bind("<Button-1>", lambda _event: webbrowser.open("https://redundis.com"))
        self._button(header, "Help", self._show_help, width=80).pack(side="right", padx=(0, 12))

        left = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=8)
        left.grid_rowconfigure(3, weight=1)
        left.grid_columnconfigure(0, weight=1)

        buttons = ctk.CTkFrame(left, fg_color=PANEL)
        buttons.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        self._button(buttons, "Add sheets", self._add_files).pack(side="left", padx=(0, 6))
        self._button(buttons, "Add folder", self._add_folder).pack(side="left")

        ctk.CTkCheckBox(
            left,
            text="Include subfolders",
            variable=self.include_subfolders,
            command=self._persist,
            fg_color=RED,
            hover_color=RED_HOVER,
            text_color=TEXT,
        ).grid(row=1, column=0, sticky="w", padx=14, pady=4)

        sort_row = ctk.CTkFrame(left, fg_color=PANEL)
        sort_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
        ctk.CTkLabel(sort_row, text="Sort", text_color=MUTED).pack(side="left", padx=(0, 8))
        self.sort_menu = ctk.CTkOptionMenu(
            sort_row,
            values=[label for label, _key in SORT_CHOICES],
            command=self._on_sort,
            fg_color=RAISED,
            button_color=RED,
            button_hover_color=RED_HOVER,
            dropdown_fg_color=PANEL,
            dropdown_hover_color=SELECT,
            text_color=TEXT,
            width=230,
            height=32,
        )
        self.sort_menu.set(_sort_label(self.list_sort))
        self.sort_menu.pack(side="left", fill="x", expand=True)

        self.list_frame = ctk.CTkScrollableFrame(left, fg_color=BG, corner_radius=8)
        self.list_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=6)
        self.empty_label = ctk.CTkLabel(
            self.list_frame,
            text="Drop sprite sheets here,\nor use Add sheets / Add folder.",
            text_color=MUTED,
            justify="center",
        )
        self.empty_label.pack(pady=24)

        row_buttons = ctk.CTkFrame(left, fg_color=PANEL)
        row_buttons.grid(row=4, column=0, sticky="ew", padx=10, pady=(4, 10))
        self._button(row_buttons, "Remove", self._remove_selected, width=90).pack(side="left", padx=(0, 6))
        self.exclude_button = self._button(row_buttons, "Exclude", self._toggle_exclude, width=110)
        self.exclude_button.pack(side="left", padx=(0, 6))
        self._button(row_buttons, "Clear", self._clear_sheets, width=80).pack(side="left", padx=(0, 6))
        self.scan_button = self._button(row_buttons, "Scan all", self._scan, primary=True, width=140)
        self.scan_button.pack(side="right")

        right = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=8)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(4, weight=1)

        settings = ctk.CTkFrame(right, fg_color=PANEL)
        settings.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        settings.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(settings, text="Gap color", text_color=MUTED).grid(row=0, column=0, padx=(0, 8), pady=4)
        self.swatch = ctk.CTkButton(
            settings,
            text="",
            width=36,
            height=28,
            fg_color=rgb_to_hex(self.gap_color),
            hover_color=rgb_to_hex(self.gap_color),
            command=self._choose_color,
        )
        self.swatch.grid(row=0, column=1, pady=4)
        self.hex_entry = ctk.CTkEntry(settings, width=120, fg_color=BG, border_color=LINE, text_color=TEXT)
        self.hex_entry.insert(0, rgb_to_hex(self.gap_color))
        self.hex_entry.grid(row=0, column=2, padx=8)
        self.hex_entry.bind("<Return>", self._apply_hex_entry)
        self.hex_entry.bind("<FocusOut>", self._apply_hex_entry)
        self._button(settings, "Choose color", self._choose_color, width=120).grid(row=0, column=3, padx=4)
        self._button(settings, "Default", self._reset_gap_color, width=90).grid(row=0, column=4, padx=4)
        self.eye_button = self._button(settings, "Pick from sheet", self._toggle_eyedropper, width=130)
        self.eye_button.grid(row=0, column=5, sticky="w", padx=4)

        ctk.CTkLabel(settings, text="Tolerance", text_color=MUTED).grid(row=1, column=0, sticky="w", pady=4)
        self.tol_slider = ctk.CTkSlider(
            settings,
            from_=0,
            to=64,
            number_of_steps=64,
            command=self._on_tolerance,
            button_color=RED,
            button_hover_color=RED_HOVER,
            progress_color=RED,
        )
        self.tol_slider.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8)
        self.tol_slider.set(self.tolerance)
        self.tol_slider.bind("<ButtonRelease-1>", lambda _event: self._cuts_changed())
        self.tol_value = ctk.CTkLabel(settings, text=str(self.tolerance), text_color=TEXT, width=30)
        self.tol_value.grid(row=1, column=4, sticky="w")

        ctk.CTkLabel(settings, text="Minimum size", text_color=MUTED).grid(row=2, column=0, sticky="w", pady=4)
        self.min_entry = ctk.CTkEntry(settings, width=80, fg_color=BG, border_color=LINE, text_color=TEXT)
        self.min_entry.insert(0, str(self.min_pixels))
        self.min_entry.grid(row=2, column=1, sticky="w", pady=4)
        self.min_entry.bind("<FocusOut>", lambda _event: self._cuts_changed())
        self.min_entry.bind("<Return>", lambda _event: self._cuts_changed())
        ctk.CTkLabel(settings, text="pixels. Smaller specks are ignored.", text_color=MUTED).grid(
            row=2, column=2, columnspan=3, sticky="w", padx=8
        )

        ctk.CTkLabel(settings, text="Output size", text_color=MUTED).grid(row=3, column=0, sticky="w", pady=4)
        self.scale_menu = ctk.CTkOptionMenu(
            settings,
            values=["1x", "2x", "3x", "4x"],
            command=self._on_output_scale,
            fg_color=RAISED,
            button_color=RED,
            button_hover_color=RED_HOVER,
            dropdown_fg_color=PANEL,
            dropdown_hover_color=SELECT,
            text_color=TEXT,
            width=90,
            height=32,
        )
        self.scale_menu.set(f"{self.output_scale}x")
        self.scale_menu.grid(row=3, column=1, sticky="w", pady=4)
        ctk.CTkLabel(settings, text="Whole steps. Saved sprites stay blocky.", text_color=MUTED).grid(
            row=3, column=2, columnspan=3, sticky="w", padx=8
        )

        checks = ctk.CTkFrame(right, fg_color=PANEL)
        checks.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        self._check(checks, "Custom file names", self.custom_names, self._toggle_names).grid(
            row=0, column=0, sticky="w", padx=(0, 18), pady=3
        )
        self._check(checks, "Preview before export", self.preview_on, self._toggle_preview).grid(
            row=0, column=1, sticky="w", pady=3
        )
        self._check(checks, "Also save one zip that contains every sheet zip", self.bundle_project, self._persist).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=3
        )
        self._check(
            checks,
            "Also split transparent and touching sprites",
            self.smart_gaps,
            self._cuts_changed,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=3)

        output = ctk.CTkFrame(right, fg_color=PANEL)
        output.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        output.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(output, text="Output folder", text_color=MUTED).grid(row=0, column=0, padx=(0, 8))
        self.output_label = ctk.CTkLabel(
            output,
            text=self.output_folder or "No folder chosen",
            text_color=TEXT if self.output_folder else MUTED,
            anchor="w",
        )
        self.output_label.grid(row=0, column=1, sticky="ew")
        self._button(output, "Browse", self._choose_output).grid(row=0, column=2, padx=(8, 0))
        self.export_button = self._button(output, "Export all", self._export, primary=True, width=140)
        self.export_button.grid(row=0, column=3, padx=(8, 0))
        ctk.CTkLabel(output, text="Project name", text_color=MUTED).grid(row=1, column=0, padx=(0, 8), pady=(8, 0))
        self.project_entry = ctk.CTkEntry(
            output,
            textvariable=self.project_name,
            fg_color=BG,
            border_color=LINE,
            text_color=TEXT,
            placeholder_text="optional",
        )
        self.project_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(8, 0))
        self.project_entry.bind("<FocusOut>", lambda _event: self._persist())
        ctk.CTkLabel(
            output,
            text="Names the zip only, like FF1 - castle.zip. The pictures inside still use numbers. Leave blank for the sheet name.",
            text_color=MUTED,
            wraplength=360,
            justify="left",
            anchor="w",
        ).grid(row=2, column=1, columnspan=3, sticky="ew", pady=(2, 0))

        sheet_color = ctk.CTkFrame(right, fg_color=PANEL)
        sheet_color.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 4))
        sheet_color.grid_columnconfigure(0, weight=1)
        self.sheet_color_label = ctk.CTkLabel(
            sheet_color,
            text="Select a sheet to give it its own gap color.",
            text_color=MUTED,
            anchor="w",
        )
        self.sheet_color_label.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)
        self.clear_override_button = self._button(sheet_color, "Use default", self._clear_override, width=120)
        self.override_button = self._button(sheet_color, "This sheet only", self._override_color, width=140)
        self.override_button.grid(row=0, column=2, padx=(6, 0), pady=4)
        self.clear_override_button.grid(row=0, column=1, pady=4)

        self.suggest_box = ctk.CTkFrame(right, fg_color="#2a2114", corner_radius=8)
        self.suggest_box.grid_columnconfigure(1, weight=1)
        self.suggest_swatch = ctk.CTkFrame(self.suggest_box, width=22, height=22, fg_color=RED, corner_radius=4)
        self.suggest_swatch.grid(row=0, column=0, padx=(10, 8), pady=(8, 4), sticky="nw")
        self.suggest_swatch.grid_propagate(False)
        self.suggest_label = ctk.CTkLabel(
            self.suggest_box,
            text="",
            text_color=WARN,
            wraplength=760,
            justify="left",
            anchor="w",
        )
        self.suggest_label.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(8, 4))
        self.suggest_buttons = ctk.CTkFrame(self.suggest_box, fg_color="#2a2114")
        self.suggest_buttons.grid(row=1, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 8))
        self.use_all_button = self._button(
            self.suggest_buttons, "Use for every flagged sheet", self._use_suggestion_all, width=220
        )
        self.use_one_button = self._button(
            self.suggest_buttons, "Use for this sheet", self._use_suggestion_one, width=150
        )
        self.use_all_button.pack(side="left", padx=(0, 6))
        self.use_one_button.pack(side="left")

        preview_wrap = ctk.CTkFrame(right, fg_color=BG, corner_radius=8)
        preview_wrap.grid(row=4, column=0, sticky="nsew", padx=12, pady=(4, 8))
        preview_wrap.grid_columnconfigure(0, weight=1)
        preview_wrap.grid_rowconfigure(2, weight=1)

        zoom_row = ctk.CTkFrame(preview_wrap, fg_color=BG)
        zoom_row.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 2))
        self.zoom_bar = zoom_row
        ctk.CTkLabel(zoom_row, text="Zoom", text_color=MUTED).pack(side="left")
        self.zoom_slider = ctk.CTkSlider(
            zoom_row,
            from_=0.25,
            to=8,
            command=self._on_zoom,
            width=160,
            button_color=RED,
            button_hover_color=RED_HOVER,
            progress_color=RED,
        )
        self.zoom_slider.set(self.zoom)
        self.zoom_slider.pack(side="left", padx=6)
        self.zoom_label = ctk.CTkLabel(zoom_row, text="Fit", text_color=TEXT, width=36)
        self.zoom_label.pack(side="left")
        self._button(zoom_row, "Reset size", self._fit_preview, width=100).pack(side="left", padx=(6, 0))
        self._compare_refs = []

        self.canvas = ctk.CTkCanvas(preview_wrap, bg="#101010", highlightthickness=0, cursor="hand2")
        self.canvas.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        self.canvas.bind("<ButtonPress-1>", self._pan_press)
        self.canvas.bind("<B1-Motion>", self._pan_drag)
        self.canvas.bind("<ButtonRelease-1>", self._pan_release)
        self.canvas.bind("<Button-3>", self._on_preview_menu)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", lambda _event: self._draw_preview())
        self.canvas.bind("<Motion>", self._preview_cursor)

        action_row = WrapBar(preview_wrap, gap=4, fg_color=BG)
        action_row.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 2))
        self.zoom_row = action_row
        self._button(
            action_row,
            "Pass as is",
            self._pass_as_is,
            width=84,
            tip="The selected pictures go in the zip as their own files, using the cuts you see now.",
        )
        self._button(
            action_row,
            "Leave out",
            self._exclude_cuts_selected,
            primary=True,
            width=84,
            tip="Leave the selected pictures out of the zip. They stay on screen with a dashed red outline.",
        )
        self._button(
            action_row,
            "Quick merge",
            self._quick_merge,
            width=92,
            tip="Join two or more highlighted pictures into one box. The earliest number stays.",
        )
        self._button(
            action_row,
            "Undo",
            self._undo_last,
            width=56,
            tip="Take back the last change on this sheet, including a Quick merge.",
        )
        self._button(
            action_row,
            "History",
            self._show_change_history,
            width=72,
            tip="See every box change on this sheet and undo back to any one of them.",
        )
        self._button(
            action_row,
            "Edit cuts",
            self._show_sprite_changes,
            width=80,
            tip="Open a larger window to zoom, move boxes, split, join, or make a new cut. That window has its own Help.",
        )
        self._button(
            action_row,
            "Reset order",
            self._ask_reset_order,
            width=100,
            tip="Put the numbers back in the original scan order. This asks first.",
        )
        self.clear_gap_box = self._gap_check(action_row)

        self.preview_note = ctk.CTkLabel(
            preview_wrap,
            text="Preview is off. Export will cut the sheets and write the zip files directly.",
            text_color=MUTED,
        )

        self.thumbs = ctk.CTkScrollableFrame(
            preview_wrap,
            orientation="horizontal",
            height=160,
            fg_color=PANEL,
            corner_radius=8,
        )
        self.thumbs.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 8))

        status_bar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 10))
        status_bar.grid_columnconfigure(1, weight=1)
        self.progress = ctk.CTkProgressBar(status_bar, width=180, progress_color=RED, fg_color=RAISED)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, padx=(0, 10))
        self.progress.grid_remove()
        self.status = ctk.CTkLabel(status_bar, text="Ready.", text_color=MUTED, anchor="w")
        self.status.grid(row=0, column=1, sticky="ew")
        self.bind("<Map>", self._on_window_map)
        self.bind("<Unmap>", self._on_window_unmap)
        support = ctk.CTkFrame(status_bar, fg_color="transparent")
        support.grid(row=0, column=2, sticky="e")
        self._support_line(support, "If you like this, please consider donating ", self._open_donate)
        self._support_line(support, " or subscribing on Twitch ", self._open_twitch_sub)

        self._apply_preview_visibility()

    def _button(self, parent, text, command, primary=False, width=120, tip: str = ""):
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=34,
            corner_radius=6,
            fg_color=RED if primary else RAISED,
            hover_color=RED_HOVER if primary else "#333333",
            text_color=TEXT,
        )
        if tip:
            self._tip(button, tip)
        if isinstance(parent, WrapBar):
            parent.add(button)
        return button

    def _tip(self, widget, text: str) -> None:
        """Show a short note when the mouse rests on this control."""
        state = {"window": None, "after": None}

        def hide(_event=None) -> None:
            handle = state.get("after")
            if handle is not None:
                try:
                    widget.after_cancel(handle)
                except Exception:
                    pass
                state["after"] = None
            window = state.get("window")
            if window is not None and window.winfo_exists():
                window.destroy()
            state["window"] = None

        def popup() -> None:
            if not widget.winfo_exists():
                return
            hide()
            window = Toplevel(widget)
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.configure(bg="#2a1619")
            Label(
                window,
                text=text,
                bg="#2a1619",
                fg=TEXT,
                wraplength=260,
                justify="left",
                font=("Segoe UI", 11),
                padx=8,
                pady=6,
            ).pack()
            window.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 8}")
            state["window"] = window

        def schedule(_event=None) -> None:
            hide()
            if widget.winfo_exists():
                state["after"] = widget.after(350, popup)

        targets = [widget, *list(widget.winfo_children())]
        for target in targets:
            target.bind("<Enter>", schedule, add="+")
            target.bind("<Leave>", hide, add="+")

    def _check(self, parent, text, variable, command):
        return ctk.CTkCheckBox(
            parent,
            text=text,
            variable=variable,
            command=command,
            fg_color=RED,
            hover_color=RED_HOVER,
            text_color=TEXT,
        )

    def _gap_check(self, parent):
        box = ctk.CTkCheckBox(
            parent,
            text="Leave out gap color",
            variable=self.clear_gap_var,
            command=self._on_clear_gap,
            fg_color=RED,
            hover_color=RED_HOVER,
            text_color=MUTED,
            height=28,
            checkbox_width=16,
            checkbox_height=16,
        )
        self._tip(
            box,
            "On for the selected pictures. The gap color is taken out of those pictures and left empty, like the cutter already does on the sheet. Turn it off to keep that color in the picture. Uses this sheet's gap color, or the default if you did not pick one.",
        )
        if isinstance(parent, WrapBar):
            parent.add(box)
        return box

    def _support_line(self, parent, lead: str, command) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(side="left")
        ctk.CTkLabel(
            row,
            text=lead,
            text_color=MUTED,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        ).pack(side="left")
        link = ctk.CTkLabel(
            row,
            text="here",
            text_color="#4c8dff",
            cursor="hand2",
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, underline=True),
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda _event: command())

    def _open_donate(self) -> None:
        webbrowser.open("https://www.redundis.com/donate.html")

    def _open_twitch_sub(self) -> None:
        webbrowser.open("http://twitch.tv/subs/redundis")

    def _on_output_scale(self, label: str) -> None:
        try:
            scale = int(str(label).rstrip("xX"))
        except ValueError:
            scale = 1
        self.output_scale = max(1, min(4, scale))
        self._persist()

    def _persist(self) -> None:
        save_settings(
            {
                "output_folder": self.output_folder,
                "gap_color": rgb_to_hex(self.gap_color),
                "tolerance": self.tolerance,
                "min_pixels": self.min_pixels,
                "custom_names": self.custom_names.get(),
                "preview_before_export": self.preview_on.get(),
                "project_name": self.project_name.get(),
                "bundle_project": self.bundle_project.get(),
                "include_subfolders": self.include_subfolders.get(),
                "smart_gaps": self.smart_gaps.get(),
                "zoom": self.zoom,
                "output_scale": self.output_scale,
                "list_sort": self.list_sort,
            }
        )

    def _on_close(self) -> None:
        if self.sheets:
            leave = messagebox.askyesno(
                "Redundis Sprite Cutter",
                "Sheets are still in this list. Close the app anyway?",
            )
            if not leave:
                return
        self._persist()
        self.destroy()

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _post(self, callback) -> None:
        """Run a UI update on the main thread. Workers must use this."""
        self._ui_queue.put(callback)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                try:
                    callback()
                except Exception:
                    pass
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(50, self._drain_ui_queue)

    def _read_min_pixels(self) -> int:
        try:
            value = int(self.min_entry.get().strip())
        except ValueError:
            value = 64
        value = max(1, min(100000, value))
        if self.min_entry.get().strip() != str(value):
            self.min_entry.delete(0, "end")
            self.min_entry.insert(0, str(value))
        return value

    def _gap_for(self, sheet: Sheet) -> tuple[int, int, int]:
        return sheet.override or self.gap_color

    def _on_tolerance(self, value) -> None:
        self.tolerance = int(round(float(value)))
        self.tol_value.configure(text=str(self.tolerance))

    def _on_zoom(self, value) -> None:
        zoom = max(0.25, min(8, float(value)))
        if abs(zoom - float(self.zoom)) < 0.001 and not self._fit_view:
            return
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        scale = self._view_scale() or 1
        center_x = self._pan_x + (width / scale) / 2
        center_y = self._pan_y + (height / scale) / 2
        self._fit_view = False
        self.zoom = zoom
        self._pan_x = center_x - (width / zoom) / 2
        self._pan_y = center_y - (height / zoom) / 2
        self.zoom_label.configure(text=f"{zoom:.1f}x")
        self._persist()
        self._draw_preview()

    def _fit_preview(self) -> None:
        """Show the whole sheet in the preview without stretching it."""
        self._fit_view = True
        self._pan_x = 0
        self._pan_y = 0
        self.zoom_label.configure(text="Fit")
        self._draw_preview()

    def _on_wheel(self, event) -> None:
        if self._preview_image is None:
            return
        scale = self._view_scale()
        image_x = self._pan_x + (event.x - self._view_origin[0]) / scale
        image_y = self._pan_y + (event.y - self._view_origin[1]) / scale
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self.zoom = max(0.25, min(8, (scale if self._fit_view else float(self.zoom)) * factor))
        self._fit_view = False
        self.zoom_slider.set(self.zoom)
        self.zoom_label.configure(text=f"{self.zoom:.1f}x")
        self._pan_x = image_x - event.x / self.zoom
        self._pan_y = image_y - event.y / self.zoom
        self._persist()
        self._draw_preview()

    def _view_scale(self) -> float:
        image = self._preview_image
        if image is not None and self._fit_view:
            view_w = max(self.canvas.winfo_width(), 2)
            view_h = max(self.canvas.winfo_height(), 2)
            image_w, image_h = image.size
            return min(view_w / max(image_w, 1), view_h / max(image_h, 1))
        return max(0.25, min(8, float(self.zoom)))

    def _cuts_changed(self) -> None:
        if self.busy:
            return
        self.min_pixels = self._read_min_pixels()
        self._persist()
        for sheet in self.sheets:
            self._clear_result(sheet)
            self._style_row(sheet)
        if self.selected and self.preview_on.get():
            self._queue_preview(self.selected)

    def _clear_result(self, sheet: Sheet) -> None:
        sheet.piece_count = None
        sheet.piece_total = None
        sheet.suggestion = None
        sheet.suggestion_text = ""
        sheet.error = ""
        sheet.cuts = {}
        sheet.cut_order = []
        sheet.next_cut = 1
        sheet.box_undo = []
        sheet.box_redo = []

    def _choose_color(self) -> None:
        chosen = self._ask_color(self.gap_color, "Gap color")
        if chosen:
            self._set_gap_color(chosen)

    def _apply_hex_entry(self, _event=None) -> None:
        try:
            color = hex_to_rgb(self.hex_entry.get())
        except ValueError:
            self._write_hex_entry(rgb_to_hex(self.gap_color))
            return
        if color != self.gap_color:
            self._set_gap_color(color)

    def _write_hex_entry(self, text: str) -> None:
        self.hex_entry.delete(0, "end")
        self.hex_entry.insert(0, text)

    def _set_gap_color(self, color: tuple[int, int, int]) -> None:
        self.gap_color = color
        hex_color = rgb_to_hex(color)
        self.swatch.configure(fg_color=hex_color, hover_color=hex_color)
        self._write_hex_entry(hex_color)
        self._update_sheet_color_label()
        self._cuts_changed()

    def _reset_gap_color(self) -> None:
        """Put the shared gap color back to the standard magenta."""
        self._set_gap_color((255, 0, 255))
        self._set_status("Gap color is magenta #ff00ff again. Sheets with their own color are unchanged.")

    def _show_help(self) -> None:
        """Plain-language help. Segoe UI stays readable at this size."""
        window = ctk.CTkToplevel(self)
        window.title("Sprite Cutter help")
        window.geometry("640x560")
        window.transient(self)
        box = ctk.CTkTextbox(window, wrap="word", font=("Segoe UI", 14), fg_color=BG, text_color=TEXT)
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("end", HELP_TEXT)
        box.configure(state="disabled")

    def _show_edit_help(self) -> None:
        """Help for the Edit cuts window only."""
        parent = getattr(self, "_change_window", None) or self
        window = ctk.CTkToplevel(parent)
        window.title("Edit cuts help")
        window.geometry("640x560")
        window.transient(parent)
        box = ctk.CTkTextbox(window, wrap="word", font=("Segoe UI", 14), fg_color=BG, text_color=TEXT)
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.insert("end", EDIT_HELP_TEXT)
        box.configure(state="disabled")

    def _ask_color(self, current: tuple[int, int, int], title: str) -> tuple[int, int, int] | None:
        """Color dialog with a hex box. The Windows wheel itself only offers RGB."""
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.configure(fg_color=BG)
        dialog.resizable(False, False)
        dialog.transient(self)
        chosen: dict[str, tuple[int, int, int] | None] = {"color": None}

        swatch = ctk.CTkFrame(dialog, width=56, height=56, fg_color=rgb_to_hex(current), corner_radius=6)
        swatch.grid(row=0, column=0, padx=16, pady=16)
        swatch.grid_propagate(False)
        form = ctk.CTkFrame(dialog, fg_color=BG)
        form.grid(row=0, column=1, padx=(0, 16), pady=16, sticky="w")
        ctk.CTkLabel(form, text="Hex", text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(0, 8))
        hex_box = ctk.CTkEntry(form, width=130, fg_color=PANEL, border_color=LINE, text_color=TEXT)
        hex_box.insert(0, rgb_to_hex(current))
        hex_box.grid(row=0, column=1, columnspan=5, sticky="w", pady=4)
        rgb_boxes = []
        for index, label in enumerate(("R", "G", "B")):
            ctk.CTkLabel(form, text=label, text_color=MUTED).grid(row=1, column=index * 2, sticky="w", padx=(0, 4))
            box = ctk.CTkEntry(form, width=58, fg_color=PANEL, border_color=LINE, text_color=TEXT)
            box.insert(0, str(current[index]))
            box.grid(row=1, column=index * 2 + 1, sticky="w", padx=(0, 8), pady=4)
            rgb_boxes.append(box)

        def paint(color: tuple[int, int, int]) -> None:
            swatch.configure(fg_color=rgb_to_hex(color))

        def fill(color: tuple[int, int, int]) -> None:
            hex_box.delete(0, "end")
            hex_box.insert(0, rgb_to_hex(color))
            for box, channel in zip(rgb_boxes, color):
                box.delete(0, "end")
                box.insert(0, str(channel))
            paint(color)

        def from_hex(_event=None) -> None:
            try:
                fill(hex_to_rgb(hex_box.get()))
            except ValueError:
                pass

        def from_rgb(_event=None) -> None:
            try:
                channels = tuple(int(box.get()) for box in rgb_boxes)
            except ValueError:
                return
            if all(0 <= channel <= 255 for channel in channels):
                fill(channels)  # type: ignore[arg-type]

        def open_wheel() -> None:
            try:
                seed = hex_to_rgb(hex_box.get())
            except ValueError:
                seed = current
            dialog.grab_release()
            picked = colorchooser.askcolor(color=rgb_to_hex(seed), title=title, parent=dialog)
            dialog.grab_set()
            if picked and picked[0]:
                red, green, blue = picked[0]
                fill((int(red), int(green), int(blue)))

        def accept() -> None:
            try:
                chosen["color"] = hex_to_rgb(hex_box.get())
            except ValueError:
                return
            dialog.destroy()

        hex_box.bind("<Return>", from_hex)
        hex_box.bind("<FocusOut>", from_hex)
        for box in rgb_boxes:
            box.bind("<Return>", from_rgb)
            box.bind("<FocusOut>", from_rgb)
        buttons = ctk.CTkFrame(dialog, fg_color=BG)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", padx=16, pady=(0, 16))
        self._button(buttons, "Color wheel", open_wheel, width=140).pack(side="left", padx=(0, 6))
        self._button(buttons, "Cancel", dialog.destroy, width=100).pack(side="left", padx=(0, 6))
        self._button(buttons, "Use color", accept, primary=True, width=120).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.grab_set()
        dialog.wait_window()
        return chosen["color"]

    def _toggle_eyedropper(self) -> None:
        self.eyedropper = not self.eyedropper
        if self.eyedropper:
            self.eye_button.configure(text="Click the gap color", fg_color=RED, hover_color=RED_HOVER)
            self.canvas.configure(cursor="crosshair")
            self._set_status("Click the color between the pictures.")
        else:
            self.eye_button.configure(text="Pick from sheet", fg_color=RAISED, hover_color="#333333")
            self.canvas.configure(cursor="hand2")

    def _choose_output(self) -> None:
        folder = filedialog.askdirectory(title="Choose where the zip files go", parent=self)
        if not folder:
            return
        self.output_folder = folder
        self.output_label.configure(text=folder, text_color=TEXT)
        self._persist()

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Add sprite sheets",
            parent=self,
            filetypes=[
                ("Still images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff *.avif *.heic *.heif"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self._ingest([Path(path) for path in paths])

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Add a folder of sprite sheets", parent=self)
        if folder:
            self._ingest([Path(folder)])

    def _on_drop(self, event) -> None:
        self._ingest([Path(path) for path in _parse_drop(event.data)])

    def _ingest(self, paths: list[Path]) -> None:
        added = 0
        skipped = 0
        recursive = self.include_subfolders.get()
        for path in paths:
            if path.is_dir():
                walker = path.rglob("*") if recursive else path.iterdir()
                files = sorted((item for item in walker if item.is_file()), key=lambda item: str(item).lower())
                for file in files:
                    if file.suffix.lower() in IMAGE_EXTS:
                        added += int(self._add_sheet(file))
                    else:
                        skipped += 1
            elif path.is_file() and path.suffix.lower() in IMAGE_EXTS:
                added += int(self._add_sheet(path))
            else:
                skipped += 1
        self._rebuild_list()
        message = f"Added {added} sheet(s)."
        if skipped:
            message += f" Skipped {skipped} that are not still images."
        self._set_status(message)
        if self.selected is None and self.sheets:
            self._select(self.sheets[0])

    def _add_sheet(self, path: Path) -> bool:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            return False
        if key in self._known:
            return False
        self._known.add(key)
        self.sheets.append(Sheet(path.resolve()))
        return True

    def _on_sort(self, label: str) -> None:
        self.list_sort = _sort_key(label)
        self._persist()
        self._rebuild_list()

    def _sort_sheets(self) -> None:
        """Reorder the list. Missing dates and piece counts stay at the bottom."""
        self.sheets.sort(key=lambda sheet: _sheet_sort_value(sheet, self.list_sort))

    def _rebuild_list(self) -> None:
        self._sort_sheets()
        for child in self.list_frame.winfo_children():
            child.destroy()
        if not self.sheets:
            self.empty_label = ctk.CTkLabel(
                self.list_frame,
                text="Drop sprite sheets here,\nor use Add sheets / Add folder.",
                text_color=MUTED,
                justify="center",
            )
            self.empty_label.pack(pady=24)
            return
        for sheet in self.sheets:
            row = ctk.CTkFrame(self.list_frame, fg_color=BG, corner_radius=6)
            row.pack(fill="x", pady=2, padx=2)
            chip = ctk.CTkFrame(row, width=14, height=14, fg_color=BG, corner_radius=3)
            chip.pack(side="left", padx=(8, 4), pady=8)
            chip.pack_propagate(False)
            mark = ctk.CTkLabel(row, text="✓", width=28, text_color=TEXT, cursor="hand2")
            mark.pack(side="left", padx=(0, 6))
            mark.bind("<Button-1>", lambda _event, item=sheet: self._flip_sheet_mark(item))
            # Name and status sit on separate lines so a long filename cannot cover the marker.
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=4)
            name = ctk.CTkLabel(text, text=_short_name(sheet.path.name), text_color=TEXT, anchor="w")
            name.pack(fill="x", anchor="w")
            meta = ctk.CTkLabel(text, text="", text_color=MUTED, anchor="w")
            meta.pack(fill="x", anchor="w")
            sheet.row = row
            sheet.meta_label = meta
            sheet.chip = chip
            sheet.mark = mark
            for widget in (row, chip, text, name, meta):
                widget.bind("<Button-1>", lambda event, item=sheet: self._on_row_click(event, item))
                widget.bind("<Button-3>", lambda event, item=sheet: self._on_row_menu(event, item))
                widget.bind("<Enter>", lambda _event, item=sheet: self._hover_sheet(item))
            self._style_row(sheet)

    def _hover_sheet(self, sheet: Sheet) -> None:
        if not self.busy:
            self._set_status(str(sheet.path))

    def _style_row(self, sheet: Sheet) -> None:
        if sheet.row is None:
            return
        selected = sheet in self.selection
        if sheet.excluded and not selected:
            row_color = "#2a2114"
        else:
            row_color = SELECT if selected else BG
        sheet.row.configure(fg_color=row_color)
        if sheet.excluded:
            text = "Excluded — kept in zip"
            color = WARN
        elif sheet.error:
            text = "Could not read"
            color = RED
        elif sheet.piece_count is None:
            text = "Not scanned"
            color = MUTED
        elif sheet.flagged:
            hint = f"try {rgb_to_hex(sheet.suggestion)}" if sheet.suggestion else "check color"
            text = f"{_piece_label(sheet)} — {hint}"
            color = WARN
        else:
            text = _piece_label(sheet)
            color = TEXT
        sheet.meta_label.configure(text=text, text_color=color)
        if sheet.excluded:
            chip_color = WARN
        elif sheet.suggestion:
            chip_color = rgb_to_hex(sheet.suggestion)
        elif sheet.override:
            chip_color = rgb_to_hex(sheet.override)
        else:
            chip_color = SELECT if selected else BG
        sheet.chip.configure(fg_color=chip_color)
        if sheet.mark is not None:
            sheet.mark.configure(text="×" if sheet.excluded else "✓", text_color=WARN if sheet.excluded else TEXT)

    def _flip_sheet_mark(self, sheet: Sheet) -> None:
        if self.busy:
            return
        sheet.excluded = not sheet.excluded
        self._style_row(sheet)
        if self.selected is sheet:
            self._queue_preview(sheet)

    def _on_row_click(self, event, sheet: Sheet) -> None:
        if self.busy:
            return
        shift = bool(event.state & 0x0001)
        ctrl = bool(event.state & 0x0004)
        if shift and self._anchor in self.sheets:
            start = self.sheets.index(self._anchor)
            end = self.sheets.index(sheet)
            low, high = sorted((start, end))
            self.selection = self.sheets[low : high + 1]
        elif ctrl:
            if sheet in self.selection:
                self.selection = [item for item in self.selection if item is not sheet]
            else:
                self.selection = [*self.selection, sheet]
            self._anchor = sheet
        else:
            self.selection = [sheet]
            self._anchor = sheet
        self._refresh_selection(sheet if sheet in self.selection else None)
        return "break"

    def _on_row_menu(self, event, sheet: Sheet) -> None:
        if self.busy:
            return
        if sheet not in self.selection:
            self.selection = [sheet]
            self._anchor = sheet
            self._refresh_selection(sheet)
        menu = Menu(
            self,
            tearoff=0,
            bg=PANEL,
            fg=TEXT,
            activebackground=RED,
            activeforeground=TEXT,
            font=("Silkscreen", 10),
        )
        if self.selection and all(item.excluded for item in self.selection):
            menu.add_command(label="Include in the cut", command=self._toggle_exclude)
        else:
            menu.add_command(label="Exclude — keep original in the zip", command=self._toggle_exclude)
        menu.add_command(label="Remove from list", command=self._remove_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _refresh_selection(self, preview: Sheet | None) -> None:
        for item in self.sheets:
            self._style_row(item)
        self._update_exclude_button()
        if preview is None and self.selection:
            preview = self.selection[-1]
        self.selected = preview
        self._update_sheet_color_label()
        if preview is None:
            self._preview_image = None
            self._preview_pieces = []
            self._hide_suggestion()
            self._clear_thumbs()
            self._draw_preview()
            return
        if self.preview_on.get():
            self._queue_preview(preview)

    def _update_exclude_button(self) -> None:
        if self.selection and all(item.excluded for item in self.selection):
            self.exclude_button.configure(text="Include")
        else:
            self.exclude_button.configure(text="Exclude")

    def _toggle_exclude(self) -> None:
        targets = list(self.selection)
        if not targets or self.busy:
            return
        exclude = not all(item.excluded for item in targets)
        for sheet in targets:
            sheet.excluded = exclude
            if exclude:
                sheet.piece_count = None
                sheet.suggestion = None
                sheet.suggestion_text = ""
                sheet.error = ""
            self._style_row(sheet)
        self._update_exclude_button()
        if self.selected in targets and self.preview_on.get():
            self._queue_preview(self.selected)
        note = "Excluded. The original file will still go in the zip." if exclude else "Included in the cut again."
        self._set_status(note)

    def _select(self, sheet: Sheet) -> None:
        self.selection = [sheet]
        self._anchor = sheet
        self.selected = sheet
        for item in self.sheets:
            self._style_row(item)
        self._update_exclude_button()
        self._update_sheet_color_label()
        if self.preview_on.get():
            self._queue_preview(sheet)

    def _update_sheet_color_label(self) -> None:
        sheet = self.selected
        if sheet is None:
            self.sheet_color_label.configure(text="Select a sheet to give it its own gap color.")
            return
        if sheet.override:
            self.sheet_color_label.configure(
                text=f"This sheet uses its own gap color {rgb_to_hex(sheet.override)}."
            )
        else:
            self.sheet_color_label.configure(
                text=f"This sheet uses the default gap color {rgb_to_hex(self.gap_color)}."
            )

    def _remove_selected(self) -> None:
        targets = list(self.selection)
        if not targets or self.busy:
            return
        index = min(self.sheets.index(sheet) for sheet in targets)
        for sheet in targets:
            self.sheets.remove(sheet)
            self._known.discard(str(sheet.path.resolve()).lower())
        self.selection = []
        self._anchor = None
        self.selected = None
        self._preview_image = None
        self._preview_pieces = []
        if self.sheets:
            self.selected = self.sheets[min(index, len(self.sheets) - 1)]
        self._rebuild_list()
        self._hide_suggestion()
        self._clear_thumbs()
        self._draw_preview()
        self._update_exclude_button()
        if self.selected:
            self._select(self.selected)
        else:
            self._update_sheet_color_label()

    def _clear_sheets(self) -> None:
        if not self.sheets or self.busy:
            return
        if len(self.sheets) > 1:
            ok = messagebox.askyesno(
                "Clear the list?",
                f"Remove all {len(self.sheets)} sheets from the list?\nThe files on disk stay where they are.",
                parent=self,
            )
            if not ok:
                return
        self.sheets.clear()
        self.selection = []
        self._anchor = None
        self._known.clear()
        self.selected = None
        self._preview_image = None
        self._preview_pieces = []
        self._rebuild_list()
        self._hide_suggestion()
        self._clear_thumbs()
        self._draw_preview()
        self._update_exclude_button()
        self._update_sheet_color_label()
        self._set_status("List cleared.")

    def _override_color(self) -> None:
        if self.selected is None:
            return
        chosen = self._ask_color(self._gap_for(self.selected), "Gap color for this sheet")
        if not chosen:
            return
        self.selected.override = chosen
        self._after_sheet_recolor([self.selected])

    def _clear_override(self) -> None:
        if self.selected is None or self.selected.override is None:
            return
        self.selected.override = None
        self._after_sheet_recolor([self.selected])

    def _use_suggestion_one(self) -> None:
        self._apply_suggestion(False)

    def _use_suggestion_all(self) -> None:
        self._apply_suggestion(True)

    def _apply_suggestion(self, every_match: bool) -> None:
        sheet = self.selected
        if sheet is None or sheet.suggestion is None or self.busy:
            return
        color = sheet.suggestion
        if every_match:
            targets = [
                item
                for item in self.sheets
                if item.flagged and item.suggestion == color
            ]
        else:
            targets = [sheet]
        for item in targets:
            item.override = color
        self._after_sheet_recolor(targets)

    def _after_sheet_recolor(self, sheets: list[Sheet]) -> None:
        for sheet in sheets:
            self._clear_result(sheet)
            self._style_row(sheet)
        self._update_sheet_color_label()
        if self.preview_on.get() and self.selected in sheets:
            self._queue_preview(self.selected)
        elif len(sheets) > 1:
            self._scan_sheets(sheets)

    def _toggle_names(self) -> None:
        self._persist()
        if self.selected and self.preview_on.get() and self._preview_pieces:
            self._fill_thumbs()

    def _toggle_preview(self) -> None:
        self._persist()
        self._apply_preview_visibility()
        if self.preview_on.get() and self.selected:
            self._queue_preview(self.selected)

    def _apply_preview_visibility(self) -> None:
        if getattr(self, "_hold_main", False):
            self.canvas.grid_remove()
            self.thumbs.grid_remove()
            return
        if self.preview_on.get():
            self.preview_note.grid_forget()
            self.canvas.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
            self.zoom_bar.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 2))
            self.zoom_row.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 2))
            self.thumbs.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 8))
        else:
            self.zoom_row.grid_forget()
            self.zoom_bar.grid_forget()
            self.canvas.grid_forget()
            self.thumbs.grid_forget()
            self._hide_suggestion()
            self.preview_note.grid(row=1, column=0, pady=40)

    def _scan(self) -> None:
        if self.busy:
            return
        if not self.sheets:
            self._set_status("Add a sprite sheet first.")
            return
        self._scan_sheets(list(self.sheets))

    def _scan_sheets(self, sheets: list[Sheet]) -> None:
        if self.busy or not sheets:
            return
        self.busy = True
        self.scan_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.progress.grid()
        self.min_pixels = self._read_min_pixels()
        tolerance = self.tolerance
        smart = self.smart_gaps.get()
        jobs = []
        for sheet in sheets:
            if sheet.excluded:
                continue
            sheet.generation += 1
            jobs.append((sheet, sheet.generation, self._gap_for(sheet)))

        def work() -> None:
            total = max(1, len(jobs))
            for index, (sheet, generation, color) in enumerate(jobs, start=1):
                self._post(lambda n=index, t=total, name=sheet.path.name: self._set_status(f"Scanning {n} of {t}: {name}"))
                self._post(lambda n=index, t=total: self.progress.set(n / t))
                try:
                    image = load_image(sheet.path)
                    result = split_sheet(
                        image, color, tolerance, self.min_pixels, build_images=False, smart_gaps=smart
                    )
                    error = ""
                except Exception as exc:
                    result = None
                    error = str(exc)
                self._post(lambda s=sheet, g=generation, r=result, e=error: self._apply_scan(s, g, r, e))
            self._post(self._scan_finished)

        threading.Thread(target=work, daemon=True).start()

    def _apply_scan(self, sheet: Sheet, generation: int, result, error: str) -> None:
        if sheet.generation != generation or sheet not in self.sheets:
            return
        if error:
            sheet.error = error
            sheet.piece_count = None
            sheet.piece_total = None
            sheet.suggestion = None
            sheet.suggestion_text = ""
        else:
            sheet.error = ""
            if not sheet.cuts:
                sheet.install_scan(result.pieces)
            sheet.piece_total = len(sheet.cut_order)
            sheet.piece_count = sheet.exportable_count()
            sheet.suggestion = result.suggestion
            sheet.suggestion_text = result.suggestion_text
        self._style_row(sheet)
        if sheet is self.selected and result and result.flagged:
            self._show_suggestion(result.suggestion, result.suggestion_text)

    def _scan_finished(self) -> None:
        self.busy = False
        self.scan_button.configure(state="normal")
        self.export_button.configure(state="normal")
        self.progress.set(0)
        self.progress.grid_remove()
        flagged = sum(1 for sheet in self.sheets if sheet.flagged)
        if flagged:
            self._set_status(f"Scan finished. {flagged} sheet(s) produced 0 or 1 piece. Double-check those colors.")
        else:
            self._set_status("Scan finished.")
        if self.list_sort.startswith("pieces"):
            self._rebuild_list()

    def _queue_preview(self, sheet: Sheet | None) -> None:
        """Wait until the click settles, then read that one sheet."""
        self._preview_wait = sheet
        job = getattr(self, "_preview_job", None)
        if job is not None:
            self.after_cancel(job)
        self._preview_job = self.after(80, self._flush_preview)

    def _flush_preview(self) -> None:
        self._preview_job = None
        sheet = getattr(self, "_preview_wait", None)
        if sheet is None or sheet is not self.selected or not self.preview_on.get():
            return
        self._load_preview(sheet)

    def _load_preview(self, sheet: Sheet) -> None:
        self._preview_token += 1
        token = self._preview_token
        color = self._gap_for(sheet)
        tolerance = self.tolerance
        self.min_pixels = self._read_min_pixels()
        minimum = self.min_pixels
        smart = self.smart_gaps.get()
        excluded = sheet.excluded
        self._set_status(f"Reading {sheet.path.name}...")

        def work() -> None:
            try:
                image = load_image(sheet.path)
                if excluded:
                    result = None
                else:
                    result = split_sheet(
                        image, color, tolerance, minimum, build_images=True, smart_gaps=smart
                    )
                error = ""
            except Exception as exc:
                image = None
                result = None
                error = str(exc)
            self._post(
                lambda: self._show_preview(token, sheet, image, result, error, excluded)
            )

        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, token, sheet, image, result, error, excluded=False) -> None:
        if token != self._preview_token or sheet not in self.sheets or sheet is not self.selected:
            return
        if excluded or sheet.excluded:
            self._preview_image = image
            self._preview_pieces = []
            self._pan_x = 0
            self._pan_y = 0
            self._show_suggestion(
                None,
                "Excluded. The original file will be copied into its zip unchanged.",
            )
            self._clear_thumbs()
            self._draw_preview()
            self._style_row(sheet)
            self._set_status(f"{sheet.path.name} is excluded and will be kept whole.")
            return
        if error:
            sheet.error = error
            sheet.piece_count = None
            sheet.piece_total = None
            self._preview_image = None
            self._preview_pieces = []
            self._style_row(sheet)
            self._hide_suggestion()
            self._clear_thumbs()
            self._draw_preview()
            self._set_status(f"Could not read {sheet.path.name}: {error}")
            return
        sheet.error = ""
        self._preview_image = image
        self._raw_pieces = result.pieces
        if not sheet.cuts:
            sheet.install_scan(result.pieces)
        shown = self._visible_from(result.pieces, sheet)
        sheet.suggestion = result.suggestion
        sheet.suggestion_text = result.suggestion_text
        self._style_row(sheet)
        self._preview_pieces = shown
        self._cut_ids = []
        self._cut_anchor = None
        self._cut_boxes = []
        self._thumb_focus = None
        self._fit_view = True
        self._pan_x = 0
        self._pan_y = 0
        self.zoom_label.configure(text="Fit")
        if len(shown) <= 1:
            self._show_suggestion(result.suggestion, result.suggestion_text)
        else:
            self._hide_suggestion()
        self._fill_thumbs()
        self._draw_preview()
        self._set_status(f"{sheet.path.name}: {len(shown)} piece(s).")

    def _show_suggestion(self, color, text: str) -> None:
        if not self.preview_on.get():
            return
        self.suggest_label.configure(text=text)
        if color:
            self.suggest_swatch.configure(fg_color=rgb_to_hex(color))
            self.suggest_buttons.grid()
        else:
            self.suggest_swatch.configure(fg_color="#2a2114")
            self.suggest_buttons.grid_remove()
        self.suggest_box.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 6))

    def _hide_suggestion(self) -> None:
        self.suggest_box.grid_forget()

    def _thumb_host(self):
        if getattr(self, "_hold_main", False):
            host = getattr(self, "_change_thumbs", None)
            if host is not None and host.winfo_exists():
                return host
            return None
        return self.thumbs

    def _clear_thumbs(self) -> None:
        self._thumb_token += 1
        self._thumb_pending = []
        self._thumb_columns = {}
        host = self._thumb_host()
        if host is not None:
            for child in host.winfo_children():
                child.destroy()
        self._thumb_refs.clear()

    def _fill_thumbs(self) -> None:
        if self._thumb_host() is None:
            return
        self._clear_thumbs()
        self._thumb_pending = [piece for piece in self._preview_pieces if piece.image is not None]
        self._append_thumbs(self._thumb_token)

    def _append_thumbs(self, token: int) -> None:
        """Add every cut to the strip, a few at a time so a big sheet stays responsive."""
        if token != self._thumb_token:
            return
        show_names = self.custom_names.get()
        stem = self.selected.path.stem if self.selected else "piece"
        batch = self._thumb_pending[:24]
        self._thumb_pending = self._thumb_pending[24:]
        for piece in batch:
            host = self._thumb_host()
            if host is None:
                return
            column = ctk.CTkFrame(host, fg_color=BG, corner_radius=6, border_width=2, border_color=BG)
            column.pack(side="left", padx=4, pady=4)
            self._thumb_columns[piece.cut_id] = column
            thumb = _fit_thumb(piece.image, 120, 78)
            photo = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=thumb.size)
            self._thumb_refs.append(photo)
            picture = ctk.CTkLabel(column, image=photo, text="")
            picture.pack(padx=4, pady=(4, 0))
            number = ctk.CTkLabel(column, text=_cut_badge(piece, self.selected, show_names) or str(piece.number or ""), text_color=RED)
            number.pack()
            note = _cut_note(piece, self.selected, show_names)
            extra = None
            if note:
                extra = ctk.CTkLabel(column, text=note, text_color=MUTED, font=ctk.CTkFont(family=FONT_FAMILY, size=11))
                extra.pack()
            for widget in (column, picture, number, extra):
                if widget is None:
                    continue
                widget.bind("<Button-1>", lambda event, item=piece: self._thumb_press(event, item))
                widget.bind("<B1-Motion>", lambda event, item=piece: self._thumb_move(event, item))
                widget.bind("<ButtonRelease-1>", lambda event, item=piece: self._thumb_release(event, item))
                widget.bind("<Button-3>", lambda event, item=piece: self._cut_menu(event, item))
            self._style_thumb(piece.cut_id)
            if show_names and self.selected is not None and not piece.keep_with:
                zip_number = _export_number(self.selected, piece.cut_id)
                shown = cut_display_name(stem, self.selected.cut_order, self.selected.cuts, self.selected.custom_names, piece.cut_id)
                entry = ctk.CTkEntry(column, width=190, fg_color=PANEL, border_color=LINE, text_color=TEXT)
                entry.insert(0, shown)
                if not zip_number:
                    entry.configure(state="disabled")
                entry.pack(padx=4, pady=(0, 4))
                entry.bind("<KeyRelease>", lambda _event, cut_id=piece.cut_id, box=entry: self._store_name(cut_id, box))
                entry.bind("<FocusOut>", lambda _event, cut_id=piece.cut_id, box=entry: self._store_name(cut_id, box, rewrite=True))
                entry.bind("<Button-3>", lambda event, item=piece: self._cut_menu(event, item))
        if self._thumb_pending and token == self._thumb_token:
            self.after(1, lambda: self._append_thumbs(token))
        else:
            self._place_thumb_scroll()

    def _place_thumb_scroll(self) -> None:
        host = self._thumb_host()
        canvas = getattr(host, "_parent_canvas", None) if host is not None else None
        if canvas is None:
            return
        canvas.update_idletasks()
        number = self._thumb_focus
        column = None
        if number:
            for piece in self._preview_pieces:
                if piece.number == number:
                    column = self._thumb_columns.get(piece.cut_id)
                    break
        if column is None:
            canvas.xview_moveto(0)
            return
        span = canvas.bbox("all")
        total = span[2] if span else 1
        canvas.xview_moveto(max(0, column.winfo_x() - 8) / max(total, 1))

    def _thumb_press(self, event, piece) -> None:
        self._thumb_drag = (piece.cut_id, event.x_root, False)

    def _thumb_move(self, event, piece) -> None:
        start = getattr(self, "_thumb_drag", None)
        if start is None or start[0] != piece.cut_id:
            return
        if abs(event.x_root - start[1]) > 8:
            self._thumb_drag = (piece.cut_id, start[1], True)

    def _thumb_release(self, event, piece) -> None:
        start = getattr(self, "_thumb_drag", None)
        self._thumb_drag = None
        if start is None:
            return
        if not start[2]:
            self._select_cut(piece, event)
            return
        sheet = self.selected
        if sheet is None:
            return
        target = None
        for other in self._preview_pieces:
            column = self._thumb_columns.get(other.cut_id)
            if column is None:
                continue
            left = column.winfo_rootx()
            right = left + column.winfo_width()
            if left <= event.x_root <= right:
                target = other.cut_id
                break
        if target is None or target == piece.cut_id:
            return
        column = self._thumb_columns.get(target)
        place = "before"
        if column is not None:
            left = column.winfo_rootx()
            mid = left + column.winfo_width() / 2
            if event.x_root > mid:
                place = "after"
        self._reorder_cut(piece.cut_id, target, place)

    def _reorder_cut(self, cut_id: str, target_id: str, place: str = "before") -> None:
        sheet = self.selected
        if sheet is None or cut_id not in sheet.cut_order or target_id not in sheet.cut_order:
            return
        from_num = sheet.cut_order.index(cut_id) + 1
        order = [item for item in sheet.cut_order if item != cut_id]
        index = order.index(target_id)
        if place == "after":
            index += 1
        order.insert(index, cut_id)
        to_num = order.index(cut_id) + 1
        if to_num == from_num:
            return
        self._push_box_history(sheet, f"Moved #{from_num} to #{to_num}")
        sheet.cut_order = order
        self._thumb_focus = to_num
        self._refresh_grouped_preview(f"Moved #{from_num} to #{to_num}")

    def _store_name(self, cut_id: str, entry, rewrite: bool = False) -> None:
        sheet = self.selected
        if sheet is None:
            return
        stem = sheet.path.stem
        base = name_base(entry.get(), stem)
        if base:
            sheet.custom_names[cut_id] = base
        else:
            sheet.custom_names.pop(cut_id, None)
        if rewrite:
            self._fill_thumbs()

    def _ask_reset_order(self) -> None:
        sheet = self.selected
        if sheet is None or not sheet.cut_order:
            self._set_status("Scan a sheet first, then you can reset the numbers.")
            return
        if not messagebox.askyesno(
            "Reset order?",
            "Put the numbers back in the original scan order? New cuts stay at the end. Undo can take this back.",
            parent=getattr(self, "_change_window", None) or self,
        ):
            return
        self._reset_cut_order()

    def _reset_cut_order(self) -> None:
        sheet = self.selected
        if sheet is None:
            return
        if not sheet.scan_order:
            sheet.scan_order = list(sheet.cut_order)
        original = [cut_id for cut_id in sheet.scan_order if cut_id in sheet.cut_order]
        extras = [cut_id for cut_id in sheet.cut_order if cut_id not in original]
        next_order = original + extras if original else list(sheet.cut_order)
        if next_order == sheet.cut_order:
            self._set_status("The numbers are already in the original order.")
            return
        self._push_box_history(sheet, "Reset cut order")
        sheet.cut_order = next_order
        self._refresh_grouped_preview("Put the numbers back in the original scan order")

    def _apply_window_icon(self) -> None:
        """Use the split-sprite picture on the window, taskbar, and exe."""
        folder = app_folder()
        icon = folder / "icon.ico"
        png = folder / "icon.png"
        if icon.exists():
            try:
                self.iconbitmap(default=str(icon))
            except Exception:
                try:
                    self.iconbitmap(str(icon))
                except Exception:
                    pass
        if png.exists():
            try:
                image = Image.open(png).resize((64, 64), Image.Resampling.NEAREST)
                self._icon_photo = ImageTk.PhotoImage(image)
                self.iconphoto(True, self._icon_photo)
            except Exception:
                pass

    def _on_window_unmap(self, event) -> None:
        if event.widget is not self:
            return
        job = getattr(self, "_draw_job", None)
        if job is not None:
            self.after_cancel(job)
            self._draw_job = None

    def _on_window_map(self, event) -> None:
        if event.widget is not self:
            return
        job = getattr(self, "_draw_job", None)
        if job is not None:
            self.after_cancel(job)
        self._draw_job = self.after(180, self._draw_preview_now)

    def _draw_preview(self) -> None:
        if getattr(self, "_hold_main", False) or str(self.state()) == "iconic":
            return
        job = getattr(self, "_draw_job", None)
        if job is not None:
            self.after_cancel(job)
        delay = 160 if getattr(self, "_draw_burst", 0) > 2 else 40
        self._draw_burst = getattr(self, "_draw_burst", 0) + 1
        self._draw_job = self.after(delay, self._finish_draw)

    def _finish_draw(self) -> None:
        self._draw_burst = 0
        self._draw_preview_now()

    def _draw_preview_now(self) -> None:
        self._draw_job = None
        if getattr(self, "_hold_main", False) or str(self.state()) == "iconic":
            return
        image = self._preview_image
        if image is None or not self.preview_on.get():
            self.canvas.delete("all")
            return
        scale = self._view_scale()
        if scale <= 0:
            return
        view_w = max(self.canvas.winfo_width(), 2)
        view_h = max(self.canvas.winfo_height(), 2)
        image_w, image_h = image.size
        src_w = view_w / scale
        src_h = view_h / scale
        self._pan_x = min(max(0.0, self._pan_x), max(0.0, image_w - src_w))
        self._pan_y = min(max(0.0, self._pan_y), max(0.0, image_h - src_h))
        x0 = int(self._pan_x)
        y0 = int(self._pan_y)
        x1 = min(image_w, max(x0 + 1, int(round(self._pan_x + src_w))))
        y1 = min(image_h, max(y0 + 1, int(round(self._pan_y + src_h))))
        try:
            crop = image.crop((x0, y0, x1, y1))
            scaled_w = max(1, int(round((x1 - x0) * scale)))
            scaled_h = max(1, int(round((y1 - y0) * scale)))
            scaled = crop.resize((scaled_w, scaled_h), Image.Resampling.NEAREST)
            if scaled.mode != "RGBA":
                scaled = scaled.convert("RGBA")
            framed = Image.alpha_composite(_checker((scaled_w, scaled_h), int(x0 * scale), int(y0 * scale)), scaled)
            draw = ImageDraw.Draw(framed)
            font = _badge_font()
            for piece in self._preview_pieces:
                left = (piece.x - x0) * scale
                top = (piece.y - y0) * scale
                right = left + piece.width * scale - 1
                bottom = top + piece.height * scale - 1
                if right < 0 or bottom < 0 or left > framed.width or top > framed.height:
                    continue
                outline, width, dashed = _cut_style(piece, piece.cut_id in self._cut_ids)
                draw.rectangle((left, top, right, bottom), outline=outline, width=width)
                if dashed:
                    draw.rectangle((left + 3, top + 3, right - 3, bottom - 3), outline=outline, width=1)
                if piece.locked:
                    draw.rectangle((left + 3, top + 3, right - 3, bottom - 3), outline=PIN, width=2)
                label = _cut_badge(piece, self.selected, self.custom_names.get())
                if not label:
                    continue
                text_box = draw.textbbox((0, 0), label, font=font)
                text_w = text_box[2] - text_box[0]
                text_h = text_box[3] - text_box[1]
                badge = (left + 2, top + 2, left + text_w + 10, top + text_h + 8)
                draw.rectangle(badge, fill=outline)
                draw.text((left + 6, top + 4), label, fill="white", font=font)
            offset_x = int((view_w - image_w * scale) / 2) if image_w * scale < view_w - 1 else 0
            offset_y = int((view_h - image_h * scale) / 2) if image_h * scale < view_h - 1 else 0
            photo = ImageTk.PhotoImage(framed)
        except Exception as exc:
            self._set_status(f"Could not draw the sheet preview. {exc}")
            return
        self._view_origin = (offset_x, offset_y, scale)
        self._photo = photo
        self.canvas.delete("all")
        self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self._photo)

    def _pan_press(self, event) -> None:
        handle = self._resize_hit(event.x, event.y)
        if handle is not None:
            piece, edge = handle
            self._resize = (piece, edge, piece.x, piece.y, piece.width, piece.height, event.x, event.y)
            self._press = None
            return
        self._resize = None
        self._press = (event.x, event.y, self._pan_x, self._pan_y, self._view_scale(), event.state)

    def _pan_drag(self, event) -> None:
        if self._resize is not None:
            self._drag_resize(event)
            return
        if self.eyedropper or self._press is None or self._preview_image is None:
            return
        start_x, start_y, origin_x, origin_y, scale, state = self._press
        if state & 0x0001 or state & 0x0004:
            return
        self._pan_x = origin_x - (event.x - start_x) / scale
        self._pan_y = origin_y - (event.y - start_y) / scale
        self._draw_preview()

    def _pan_release(self, event) -> None:
        if self._resize is not None:
            self._commit_resize()
            self._resize = None
            return
        if self._press and self._preview_image is not None:
            start_x, start_y, _ox, _oy, _scale, state = self._press
            stayed = abs(event.x - start_x) < 5 and abs(event.y - start_y) < 5
            if stayed and self.eyedropper:
                self._sample_gap(event.x, event.y)
            elif stayed and not self.eyedropper:
                piece = self._piece_at(event.x, event.y)
                if piece is not None:
                    self._select_cut(piece, state=state)
                elif not (state & 0x0001 or state & 0x0004):
                    self._cut_ids = []
                    self._cut_boxes = []
                    self._cut_anchor = None
                    self._style_cut_selection()
        self._press = None

    def _sample_gap(self, view_x: int, view_y: int) -> None:
        image = self._preview_image
        if image is None:
            return
        scale = self._view_origin[2] or self._view_scale()
        pixel_x = int(self._pan_x + (view_x - self._view_origin[0]) / scale)
        pixel_y = int(self._pan_y + (view_y - self._view_origin[1]) / scale)
        width, height = image.size
        if not (0 <= pixel_x < width and 0 <= pixel_y < height):
            return
        red, green, blue, _alpha = image.getpixel((pixel_x, pixel_y))
        picked = (red, green, blue)
        self.eyedropper = True
        self._toggle_eyedropper()
        if self.selected is not None and self.selected.override is not None:
            self.selected.override = picked
            self._after_sheet_recolor([self.selected])
        else:
            self._set_gap_color(picked)
        self._set_status(f"Gap color set to {rgb_to_hex(picked)}.")

    def _on_preview_menu(self, event) -> None:
        piece = self._piece_at(event.x, event.y)
        self._cut_menu(event, piece)

    def _piece_at(self, view_x: int, view_y: int):
        """The smallest cut under the cursor. A vine wins over the map around it."""
        if not self._preview_pieces:
            return None
        scale = self._view_origin[2] or self._view_scale()
        if scale <= 0:
            return None
        image_x = self._pan_x + (view_x - self._view_origin[0]) / scale
        image_y = self._pan_y + (view_y - self._view_origin[1]) / scale
        hits = [
            piece
            for piece in self._preview_pieces
            if piece.x <= image_x < piece.x + piece.width and piece.y <= image_y < piece.y + piece.height
        ]
        if not hits:
            return None
        return min(hits, key=lambda piece: piece.width * piece.height)

    def _select_cut(self, piece, event=None, state: int | None = None) -> None:
        """Ctrl adds one cut. Shift selects the range between two cuts."""
        if self.busy:
            return
        flags = event.state if state is None and event is not None else (state or 0)
        cut_id = piece.cut_id
        order = [item.cut_id for item in self._preview_pieces]
        shift = bool(flags & 0x0001)
        ctrl = bool(flags & 0x0004)
        if shift and self._cut_anchor in order and cut_id in order:
            start = order.index(self._cut_anchor)
            end = order.index(cut_id)
            low, high = sorted((start, end))
            self._cut_ids = order[low : high + 1]
        elif ctrl:
            if cut_id in self._cut_ids:
                self._cut_ids = [item for item in self._cut_ids if item != cut_id]
            else:
                self._cut_ids.append(cut_id)
            self._cut_anchor = cut_id
        else:
            self._cut_ids = [cut_id]
            self._cut_anchor = cut_id
        self._cut_boxes = list(self._cut_ids)
        if getattr(self, "_hold_main", False):
            self._change_picks = set(self._cut_ids)
            self._change_anchor = self._cut_anchor
        self._style_cut_selection()

    def _style_cut_selection(self) -> None:
        for cut_id in list(self._thumb_columns):
            self._style_thumb(cut_id)
        if getattr(self, "_hold_main", False):
            self._paint_change_view()
        else:
            self._draw_preview()
        count = len(self._cut_ids)
        if count > 1:
            self._set_status(f"{count} pictures selected. Quick merge joins them, or open Edit cuts to change boxes.")
        elif count == 1:
            self._set_status("1 picture selected. Open Edit cuts to move the box, or leave it out of the zip.")
        self._sync_clear_gap()

    def _style_thumb(self, cut_id: str) -> None:
        column = self._thumb_columns.get(cut_id)
        if column is None:
            return
        piece = next((item for item in self._preview_pieces if item.cut_id == cut_id), None)
        if piece is None:
            return
        outline, _width, _dashed = _cut_style(piece, cut_id in self._cut_ids)
        column.configure(border_color=GOLD if cut_id in self._cut_ids else outline if outline != RED else BG)

    def _cut_menu(self, event, piece) -> None:
        if self.busy or self.selected is None:
            return
        if piece is not None and piece.cut_id not in self._cut_ids:
            self._cut_ids = [piece.cut_id]
            self._cut_anchor = piece.cut_id
            self._cut_boxes = list(self._cut_ids)
            self._style_cut_selection()
        if not self._cut_ids:
            return
        menu = Menu(
            self,
            tearoff=0,
            bg=PANEL,
            fg=TEXT,
            activebackground=RED,
            activeforeground=TEXT,
            font=("Silkscreen", 10),
        )
        menu.add_command(label="Leave out of zip", command=self._exclude_cuts_selected)
        menu.add_command(label="Pass as is", command=self._pass_as_is)
        menu.add_command(label="Edit cuts", command=self._show_sprite_changes)
        menu.tk_popup(event.x_root, event.y_root)

    def _chosen_pieces(self):
        chosen = {cut_id for cut_id in self._cut_ids}
        return [piece for piece in self._preview_pieces if piece.cut_id in chosen]

    def _refresh_grouped_preview(self, note: str) -> None:
        sheet = self.selected
        if sheet is None:
            return
        shown = self._visible_from(self._raw_pieces, sheet)
        self._preview_pieces = shown
        self._style_row(sheet)
        if self.list_sort.startswith("pieces"):
            self._rebuild_list()
        self._fill_thumbs()
        self._draw_preview()
        if getattr(self, "_hold_main", False):
            self._sync_edit_window()
        self._set_status(f"{note} {_piece_label(sheet)}.")
        self._sync_clear_gap()

    def _exclude_cuts_selected(self) -> None:
        self._leave_out(self._cut_ids)

    def _leave_out(self, cut_ids) -> None:
        sheet = self.selected
        ids = [cut_id for cut_id in cut_ids if cut_id in (sheet.cuts if sheet else {})]
        if sheet is None or not ids:
            self._set_status("Select a cut first.")
            return
        self._push_box_history(sheet, "Left out of zip")
        for cut_id in ids:
            sheet.cuts[cut_id]["out"] = True
            sheet.cuts[cut_id]["passed"] = False
        noun = "cut" if len(ids) == 1 else "cuts"
        self._refresh_grouped_preview(f"Left {len(ids)} {noun} out of the zip.")
        self._sync_edit_window()

    def _visible_from(self, pieces, sheet: Sheet):
        if not sheet.cuts and pieces:
            sheet.install_scan(pieces)
        shown = pieces_from_cuts(
            self._preview_image, sheet.cut_order, sheet.cuts, self._gap_for(sheet), self.tolerance
        )
        sheet.piece_total = len(sheet.cut_order)
        sheet.piece_count = sheet.exportable_count()
        return shown

    def _clear_gap_controls(self):
        boxes = [getattr(self, "clear_gap_box", None), getattr(self, "_change_clear_gap", None)]
        return [box for box in boxes if box is not None and box.winfo_exists()]

    def _sync_clear_gap(self) -> None:
        sheet = self.selected
        ids = [cut_id for cut_id in self._cut_ids if sheet is not None and cut_id in sheet.cuts]
        on = all(sheet.cuts[cut_id].get("clear_gap", True) is not False for cut_id in ids) if ids else True
        mixed = bool(
            ids
            and any(sheet.cuts[cut_id].get("clear_gap") is False for cut_id in ids)
            and any(sheet.cuts[cut_id].get("clear_gap", True) is not False for cut_id in ids)
        )
        self._clear_gap_sync = True
        self.clear_gap_var.set(False if mixed else on)
        for box in self._clear_gap_controls():
            box.configure(
                state="normal" if ids else "disabled",
                text="Leave out gap color (mixed)" if mixed else "Leave out gap color",
            )
        self._clear_gap_sync = False
        self._reflow_wrap_bars()

    def _reflow_wrap_bars(self) -> None:
        for bar in (getattr(self, "zoom_row", None), getattr(self, "_change_actions", None), getattr(self, "_change_picks", None)):
            if bar is not None and hasattr(bar, "reflow"):
                bar.reflow()

    def _on_clear_gap(self) -> None:
        if self._clear_gap_sync:
            return
        sheet = self.selected
        ids = [cut_id for cut_id in self._cut_ids if sheet is not None and cut_id in sheet.cuts]
        if sheet is None or not ids:
            self._sync_clear_gap()
            self._set_status("Select a picture first, then turn Leave out gap color on or off.")
            return
        on = bool(self.clear_gap_var.get())
        self._push_box_history(sheet, "Leave out gap color" if on else "Keep gap color")
        for cut_id in ids:
            sheet.cuts[cut_id]["clear_gap"] = on
        self._preview_pieces = self._visible_from(self._raw_pieces, sheet)
        self._fill_thumbs()
        self._draw_preview()
        if getattr(self, "_hold_main", False):
            self._sync_edit_window()
        self._sync_clear_gap()
        self._set_status(
            "Gap color is left out of the selected pictures."
            if on
            else "Gap color stays in the selected pictures."
        )
        self._reflow_wrap_bars()

    def _set_main_preview_held(self, held: bool) -> None:
        """Hide the main sheet while Edit cuts is open so only one canvas is drawn."""
        self._hold_main = held
        if held:
            self.canvas.grid_remove()
            self.thumbs.grid_remove()
            self.canvas.delete("all")
            return
        self._apply_preview_visibility()

    def _show_sprite_changes(self) -> None:
        """Zoomed editor. The main sheet stays put until Confirm or Cancel."""
        image = self._preview_image
        sheet = self.selected
        if image is None or sheet is None or not self._preview_pieces:
            self._set_status("Open a sheet first, then Edit cuts.")
            return
        self._change_ids = [piece.cut_id for piece in self._preview_pieces]
        self._change_picks = set(self._cut_ids)
        self._change_anchor = self._cut_ids[0] if self._cut_ids else None
        self._change_id = self._cut_ids[0] if self._cut_ids else (self._change_ids[0] if self._change_ids else None)
        self._change_zoom = 1.0
        self._change_pan = [0.0, 0.0]
        self._change_drag_state = None
        self._change_dirty = False
        self._change_snapshot = self._box_state(sheet)
        self._change_undo_snap = list(sheet.box_undo)
        self._change_redo_snap = list(sheet.box_redo)
        self._set_main_preview_held(True)
        window = ctk.CTkToplevel(self)
        window.title("Edit cuts")
        window.geometry("1040x820")
        window.minsize(780, 560)
        window.transient(self)
        window.configure(fg_color=BG)
        window.protocol("WM_DELETE_WINDOW", self._change_close)
        self._change_window = window
        head = ctk.CTkFrame(window, fg_color=BG)
        head.pack(fill="x", padx=12, pady=(12, 2))
        ctk.CTkLabel(
            head,
            text="Change the boxes, or make a new one. Gold means selected. The small pictures below work like the main page.",
            text_color=MUTED,
            wraplength=860,
            justify="left",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self._button(head, "Help", self._show_edit_help, width=80, tip="How this window works: zoom, pan, move boxes, and each button.").pack(side="right")
        ctk.CTkLabel(
            window,
            text="Gold = selected. Red = cut. Cyan = new. Orange = split. Dashed red = left out of the zip. Sky dashed = locked. Green = kept with another. Purple = pass as is.",
            text_color=MUTED,
            wraplength=1000,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 4))
        actions = WrapBar(window, gap=6, fg_color=BG)
        actions.pack(fill="x", padx=12, pady=(0, 4))
        self._change_actions = actions
        self._button(actions, "New cut", self._new_cut, width=88, tip="Make a new box, about the average size of the current cuts, then pick its number.")
        self._button(actions, "Split across", lambda: self._change_split(True), width=110, tip="Cut the one selected box in half, left and right.")
        self._button(actions, "Split down", lambda: self._change_split(False), width=100, tip="Cut the one selected box in half, top and bottom.")
        self._button(actions, "Merge", self._change_merge, width=80, tip="Turn two or more selected boxes into one box that covers them all. Undo and Redo can take this back.")
        self._button(actions, "Keep with", self._keep_with, width=96, tip="Pick two cuts: a leftover and the sprite it belongs with. The leftover is not its own file.")
        self._button(actions, "Lock", lambda: self._set_cut_lock(True), width=72, tip="Lock the selected boxes. A locked box keeps its size and cannot be dragged.")
        self._button(actions, "Unlock", lambda: self._set_cut_lock(False), width=88, tip="Unlock the selected boxes so you can move or resize them again.")
        self._button(actions, "Leave out", self._exclude_cuts_selected, width=96, tip="Leave the selected cuts out of the zip. They stay on screen with a dashed red outline.")
        self._button(actions, "Pass as is", self._pass_as_is, width=96, tip="The selected cuts go in the zip as their own files, using the boxes you see now.")
        self._button(actions, "Undo", lambda: self._change_history(False), width=72, tip="Take back the last edit in this window.")
        self._button(actions, "Redo", lambda: self._change_history(True), width=72, tip="Put back an edit you just undid.")
        self._button(actions, "Revert", self._revert_boxes, width=80, tip="Put the selected cuts back to the first scan. Other cuts stay as they are.")
        self._button(actions, "Change history", self._show_change_history, width=130, tip="See every box change on this sheet and undo back to any one of them.")
        look = ctk.CTkFrame(window, fg_color=BG)
        look.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(look, text="Zoom", text_color=MUTED).pack(side="left")
        self._change_zoom_var = ctk.DoubleVar(value=1.0)
        ctk.CTkSlider(look, from_=0.25, to=8, variable=self._change_zoom_var, command=self._change_zoom_set, width=180).pack(side="left", padx=(8, 0))
        self._button(look, "Reset size", self._change_reset_view, width=100, tip="Show the whole sheet again.").pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            window,
            text="Drag to move the view, even over other boxes. A tap or click on a box selects it. Gold means selected. Use the small pictures below like the main page.",
            text_color=MUTED,
            wraplength=1000,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 2))
        self._change_canvas = ctk.CTkCanvas(window, bg="#101010", highlightthickness=0, cursor="hand2")
        self._change_canvas.pack(fill="both", expand=True, padx=12, pady=8)
        self._change_canvas.bind("<ButtonPress-1>", self._change_press)
        self._change_canvas.bind("<B1-Motion>", self._change_drag)
        self._change_canvas.bind("<ButtonRelease-1>", self._change_release)
        self._change_canvas.bind("<ButtonPress-2>", self._change_pan_press)
        self._change_canvas.bind("<B2-Motion>", self._change_pan_drag)
        self._change_canvas.bind("<ButtonRelease-2>", self._change_pan_release)
        self._change_canvas.bind("<Motion>", self._change_cursor)
        self._change_canvas.bind("<MouseWheel>", self._change_wheel)
        self._change_canvas.bind("<Button-4>", lambda event: self._change_wheel_step(event, 1.12))
        self._change_canvas.bind("<Button-5>", lambda event: self._change_wheel_step(event, 1 / 1.12))
        self._change_canvas.bind("<Configure>", self._change_resized)
        picks = WrapBar(window, gap=6, fg_color=BG)
        picks.pack(fill="x", padx=12, pady=(0, 2))
        self._change_picks = picks
        self._button(picks, "Select all", self._change_select_all, width=96, tip="Select every picture so you can edit them together.")
        self._button(picks, "Select none", self._change_select_none, width=108, tip="Clear the selection. Nothing is being edited.")
        self._button(picks, "Reset order", self._ask_reset_order, width=100, tip="Put the numbers back in the original scan order. This asks first.")
        self._change_clear_gap = self._gap_check(picks)
        self._sync_clear_gap()
        self._change_thumbs = ctk.CTkScrollableFrame(
            window,
            orientation="horizontal",
            height=160,
            fg_color=PANEL,
            corner_radius=8,
        )
        self._change_thumbs.pack(fill="x", padx=12, pady=(0, 8))
        self._change_note = None
        self._change_decide = ctk.CTkFrame(window, fg_color=BG)
        self._change_decide.pack(fill="x", padx=12, pady=(0, 12))
        self._button(self._change_decide, "Confirm", self._change_confirm, width=100, tip="Keep these edits and go back to the sheet.").pack(side="left")
        self._button(self._change_decide, "Cancel", self._change_cancel, width=100, tip="Throw away the edits in this window and go back.").pack(side="left", padx=(8, 0))
        self._fill_thumbs()
        self._paint_change_view()
        window.after(40, self._reflow_wrap_bars)

    def _mark_change_dirty(self) -> None:
        self._change_dirty = True
        frame = getattr(self, "_change_decide", None)
        if frame is not None and frame.winfo_exists() and not frame.winfo_ismapped():
            frame.pack(fill="x", padx=12, pady=(0, 12))

    def _change_close(self) -> None:
        if getattr(self, "_change_dirty", False):
            window = getattr(self, "_change_window", None)
            apply = messagebox.askyesno(
                "Edit cuts",
                "Apply these changes to the sheet?",
                parent=window,
            )
            if apply:
                self._change_confirm()
            else:
                self._change_cancel()
            return
        self._close_change_window(True)

    def _change_confirm(self) -> None:
        self._change_dirty = False
        sheet = self.selected
        if sheet is not None:
            self._preview_pieces = self._visible_from(self._raw_pieces, sheet)
        self._close_change_window(True)

    def _change_cancel(self) -> None:
        sheet = self.selected
        self._change_dirty = False
        if sheet is not None and getattr(self, "_change_snapshot", None) is not None:
            self._apply_box_state(sheet, self._change_snapshot)
            sheet.box_undo = list(self._change_undo_snap)
            sheet.box_redo = list(self._change_redo_snap)
            self._preview_pieces = self._visible_from(self._raw_pieces, sheet)
        self._close_change_window(True)

    def _close_change_window(self, refresh: bool) -> None:
        window = getattr(self, "_change_window", None)
        self._change_thumbs = None
        self._change_window = None
        self._change_actions = None
        self._change_picks = None
        self._change_clear_gap = None
        if window is not None and window.winfo_exists():
            window.destroy()
        self._set_main_preview_held(False)
        if refresh:
            self._fill_thumbs()
            self._draw_preview()

    def _change_resized(self, event) -> None:
        canvas = getattr(self, "_change_canvas", None)
        if canvas is None or event.widget is not canvas:
            return
        size = (event.width, event.height)
        if size == getattr(self, "_change_canvas_size", None) or event.width < 20 or event.height < 20:
            return
        self._change_canvas_size = size
        self._paint_change_view()

    def _change_zoom_set(self, value) -> None:
        if getattr(self, "_change_zoom_lock", False):
            return
        self._change_zoom = float(value)
        self._paint_change_view()

    def _change_reset_view(self) -> None:
        self._change_zoom = 1.0
        self._change_pan = [0.0, 0.0]
        self._change_frozen_bounds = None
        self._change_zoom_lock = True
        self._change_zoom_var.set(1.0)
        self._change_zoom_lock = False
        self._paint_change_view()

    def _change_wheel(self, event) -> None:
        self._change_wheel_step(event, 1.12 if getattr(event, "delta", 0) > 0 else 1 / 1.12)

    def _change_wheel_step(self, event, factor: float) -> None:
        layout = self._change_layout()
        if layout is None:
            return
        _cw, _ch, left, top, _rw, _rh, fit, scale, ox, oy = layout
        zoom = max(0.25, min(self._change_zoom * factor, 8))
        img_x = left + (event.x - ox) / scale
        img_y = top + (event.y - oy) / scale
        new_scale = max(0.25, fit * zoom)
        new_ox = event.x - (img_x - left) * new_scale
        new_oy = event.y - (img_y - top) * new_scale
        self._change_zoom = zoom
        self._change_pan = [new_ox - (_cw - _rw * new_scale) / 2, new_oy - (_ch - _rh * new_scale) / 2]
        self._change_zoom_lock = True
        self._change_zoom_var.set(zoom)
        self._change_zoom_lock = False
        self._paint_change_view()

    def _change_pan_press(self, event) -> None:
        pan = list(getattr(self, "_change_pan", [0.0, 0.0]))
        self._change_drag_state = ("pan", event.x, event.y, pan[0], pan[1])

    def _change_pan_drag(self, event) -> None:
        state = getattr(self, "_change_drag_state", None)
        if state is None or state[0] != "pan":
            return
        _kind, start_x, start_y, pan_x, pan_y = state
        self._change_pan = [pan_x + event.x - start_x, pan_y + event.y - start_y]
        self._paint_change_view()

    def _change_pan_release(self, _event) -> None:
        self._change_drag_state = None

    def _change_layout(self):
        """Canvas size, the sheet area on screen, and where it is drawn."""
        canvas = getattr(self, "_change_canvas", None)
        image = self._preview_image
        if canvas is None or image is None or not canvas.winfo_exists():
            return None
        cw = max(canvas.winfo_width(), 200)
        ch = max(canvas.winfo_height(), 160)
        left, top, right, bottom = 0, 0, image.width, image.height
        rect_w = max(1, right - left)
        rect_h = max(1, bottom - top)
        fit = min(cw / rect_w, ch / rect_h)
        scale = max(0.25, min(fit * getattr(self, "_change_zoom", 1.0), 32))
        pan = getattr(self, "_change_pan", [0.0, 0.0])
        ox = (cw - rect_w * scale) / 2 + pan[0]
        oy = (ch - rect_h * scale) / 2 + pan[1]
        return cw, ch, left, top, rect_w, rect_h, fit, scale, ox, oy

    def _rebuild_change_picker(self) -> None:
        live = list(self._preview_pieces)
        self._change_ids = [piece.cut_id for piece in live]
        self._cut_ids = [item for item in self._change_ids if item in self._change_picks]
        host = getattr(self, "_change_thumbs", None)
        if host is None or not host.winfo_exists():
            return
        if set(self._thumb_columns) == set(self._change_ids):
            for cut_id in self._change_ids:
                self._style_thumb(cut_id)
            return
        self._fill_thumbs()

    def _on_number_click(self, event, cut_id: str) -> None:
        ctrl = bool(event.state & 0x0004)
        shift = bool(event.state & 0x0001)
        self._apply_change_select(cut_id, ctrl=ctrl, shift=shift)

    def _drop_change_pick(self, cut_id: str) -> None:
        self._change_picks.discard(cut_id)
        self._cut_ids = [item for item in self._change_ids if item in self._change_picks]
        self._change_id = self._cut_ids[0] if self._cut_ids else None
        self._rebuild_change_picker()
        self._paint_change_view()

    def _apply_change_select(self, cut_id: str, ctrl: bool = False, shift: bool = False) -> None:
        ids = list(self._change_ids)
        anchor = getattr(self, "_change_anchor", None)
        if shift and anchor in ids and cut_id in ids:
            start = ids.index(anchor)
            end = ids.index(cut_id)
            low, high = (start, end) if start <= end else (end, start)
            range_ids = ids[low : high + 1]
            if range_ids and all(item in self._change_picks for item in range_ids):
                self._change_picks.difference_update(range_ids)
            elif ctrl:
                self._change_picks.update(range_ids)
            else:
                self._change_picks = set(range_ids)
        elif ctrl:
            if cut_id in self._change_picks:
                self._change_picks.discard(cut_id)
            else:
                self._change_picks.add(cut_id)
            self._change_anchor = cut_id
        else:
            self._change_picks = {cut_id}
            self._change_anchor = cut_id
        self._change_id = cut_id if cut_id in self._change_picks else (next(iter(self._change_picks), None))
        self._cut_ids = [item for item in ids if item in self._change_picks]
        self._rebuild_change_picker()
        self._paint_change_view()
        self._sync_clear_gap()

    def _toggle_change_piece(self, cut_id) -> None:
        self._apply_change_select(cut_id, ctrl=True)

    def _change_select_all(self) -> None:
        self._change_picks = {piece.cut_id for piece in self._preview_pieces}
        self._change_anchor = self._change_ids[0] if self._change_ids else None
        self._cut_ids = list(self._change_picks)
        self._rebuild_change_picker()
        self._paint_change_view()
        self._sync_clear_gap()

    def _change_select_none(self) -> None:
        self._change_picks = set()
        self._change_anchor = None
        self._cut_ids = []
        self._rebuild_change_picker()
        self._paint_change_view()
        self._sync_clear_gap()

    def _change_split(self, vertical: bool) -> None:
        self._cut_ids = [cut_id for cut_id in self._change_ids if cut_id in self._change_picks]
        before = {piece.cut_id for piece in self._preview_pieces}
        self._split_piece(vertical)
        after = {piece.cut_id for piece in self._preview_pieces}
        self._change_picks.update(after - before)
        self._change_ids = [piece.cut_id for piece in self._preview_pieces]
        self._mark_change_dirty()
        self._rebuild_change_picker()
        self._paint_change_view()

    def _change_merge(self) -> None:
        self._cut_ids = [cut_id for cut_id in self._change_ids if cut_id in self._change_picks]
        self._merge_selected(ask=False)
        live = {piece.cut_id for piece in self._preview_pieces}
        self._change_picks = {cut_id for cut_id in self._change_picks if cut_id in live}
        self._change_ids = [piece.cut_id for piece in self._preview_pieces]
        self._mark_change_dirty()
        self._rebuild_change_picker()
        self._paint_change_view()

    def _change_history(self, redo: bool) -> None:
        if redo:
            self._redo_box()
        else:
            self._undo_box()
        live = {piece.cut_id for piece in self._preview_pieces}
        self._change_ids = [piece.cut_id for piece in self._preview_pieces]
        self._change_picks = {cut_id for cut_id in self._change_picks if cut_id in live}
        self._cut_ids = list(self._change_picks)
        self._mark_change_dirty()
        self._rebuild_change_picker()
        self._paint_change_view()

    def _pick_change_piece(self, box) -> None:
        self._change_id = box
        self._cut_boxes = [box]
        self._paint_change_view()

    def _change_piece(self):
        return next((piece for piece in self._preview_pieces if piece.cut_id == self._change_id), None)

    def _paint_change_view(self) -> None:
        """Draw the loaded sprites large enough to fill this window."""
        canvas = getattr(self, "_change_canvas", None)
        image = self._preview_image
        window = getattr(self, "_change_window", None)
        layout = self._change_layout()
        if canvas is None or image is None or window is None or layout is None or not window.winfo_exists():
            return
        cw, ch, left, top, _rect_w, _rect_h, _fit, scale, ox, oy = layout
        img_x0 = left + (0 - ox) / scale
        img_y0 = top + (0 - oy) / scale
        img_x1 = img_x0 + cw / scale
        img_y1 = img_y0 + ch / scale
        crop_left = max(0, int(img_x0))
        crop_top = max(0, int(img_y0))
        crop_right = min(image.width, int(img_x1) + 1)
        crop_bottom = min(image.height, int(img_y1) + 1)
        if crop_right <= crop_left or crop_bottom <= crop_top:
            return
        crop = image.crop((crop_left, crop_top, crop_right, crop_bottom))
        shown = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(shown)
        self._change_photo = photo
        self._change_origin = (img_x0, img_y0, scale)
        canvas.delete("all")
        canvas.create_image((crop_left - img_x0) * scale, (crop_top - img_y0) * scale, anchor="nw", image=photo)
        loaded = list(self._preview_pieces)
        for item in loaded:
            box_left = (item.x - img_x0) * scale
            box_top = (item.y - img_y0) * scale
            box_right = box_left + item.width * scale
            box_bottom = box_top + item.height * scale
            outline, width, dashed = _cut_style(item, item.cut_id in self._change_picks)
            canvas.create_rectangle(box_left, box_top, box_right, box_bottom, outline=outline, width=width)
            if dashed:
                canvas.create_rectangle(box_left + 3, box_top + 3, box_right - 3, box_bottom - 3, outline=outline, width=1)
            if item.locked:
                canvas.create_rectangle(box_left + 3, box_top + 3, box_right - 3, box_bottom - 3, outline=PIN, width=2)
            label = _cut_badge(item, self.selected, self.custom_names.get())
            if label:
                canvas.create_rectangle(box_left, box_top, box_left + max(22, 7 * len(label)), box_top + 16, fill="#0c0c0c", outline="")
                canvas.create_text(box_left + 3, box_top + 1, anchor="nw", text=label, fill="#ffffff", font=("Segoe UI", 11, "bold"))
    def _change_nudge(self, edge: str, grow: bool) -> None:
        piece = self._change_piece()
        if piece is None:
            return
        self._cut_ids = [piece.cut_id]
        self._nudge(edge, grow)
        self._paint_change_view()

    def _edge_pad(self, scale: float) -> int:
        # Grow the grab zone when zoomed out so thin edges stay easy to catch.
        boost = int((1.25 - scale) * 18) if 0 < scale < 1.25 else 0
        return 20 + max(0, boost)

    def _box_view_rect(self, piece, origin):
        left0, top0, scale = origin
        left = (piece.x - left0) * scale
        top = (piece.y - top0) * scale
        return left, top, left + piece.width * scale, top + piece.height * scale

    def _edge_on_box(self, view_x: int, view_y: int, rect, outer_pad: int):
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        # Keep a real middle so a selected box can be dragged, not only resized.
        inner_x = min(outer_pad, max(3, (width - 12) / 2))
        inner_y = min(outer_pad, max(3, (height - 12) / 2))
        in_x = left - outer_pad <= view_x <= right + outer_pad
        in_y = top - outer_pad <= view_y <= bottom + outer_pad
        if not in_x or not in_y:
            return "", float("inf")
        if left + inner_x <= view_x <= right - inner_x and top + inner_y <= view_y <= bottom - inner_y:
            return "", float("inf")
        dist_n = abs(view_y - top)
        dist_s = abs(view_y - bottom)
        dist_w = abs(view_x - left)
        dist_e = abs(view_x - right)
        pad_n = outer_pad if view_y < top else inner_y
        pad_s = outer_pad if view_y > bottom else inner_y
        pad_w = outer_pad if view_x < left else inner_x
        pad_e = outer_pad if view_x > right else inner_x
        edge = ""
        if dist_n <= pad_n and in_x:
            edge += "n"
        if dist_s <= pad_s and in_x:
            edge += "s"
        if dist_w <= pad_w and in_y:
            edge += "w"
        if dist_e <= pad_e and in_y:
            edge += "e"
        if not edge:
            return "", float("inf")
        dist = min(
            dist_n if "n" in edge else float("inf"),
            dist_s if "s" in edge else float("inf"),
            dist_w if "w" in edge else float("inf"),
            dist_e if "e" in edge else float("inf"),
        )
        return edge, dist

    def _change_hit(self, view_x: int, view_y: int, selected_only: bool = False):
        origin = getattr(self, "_change_origin", None)
        if origin is None:
            return None, None
        pad = self._edge_pad(origin[2])
        selected = [piece for piece in self._preview_pieces if piece.cut_id in self._change_picks]
        can_move = len(selected) == 1 and not selected[0].locked
        best = None
        for piece in selected:
            if piece.locked:
                continue
            edge, dist = self._edge_on_box(view_x, view_y, self._box_view_rect(piece, origin), pad)
            if edge and (best is None or dist < best[2]):
                best = (piece, edge, dist)
        if best is not None:
            return best[0], best[1]
        if can_move:
            piece = selected[0]
            left, top, right, bottom = self._box_view_rect(piece, origin)
            if left <= view_x <= right and top <= view_y <= bottom:
                return piece, "move"
        if selected_only:
            return None, None
        hits = []
        for piece in self._preview_pieces:
            left, top, right, bottom = self._box_view_rect(piece, origin)
            if left - pad <= view_x <= right + pad and top - pad <= view_y <= bottom + pad:
                hits.append(piece)
        if not hits:
            return None, None
        piece = min(hits, key=lambda item: item.width * item.height)
        edge, _dist = self._edge_on_box(view_x, view_y, self._box_view_rect(piece, origin), pad)
        return piece, edge or ""

    def _change_cursor(self, event) -> None:
        canvas = self._change_canvas
        piece, edge = self._change_hit(event.x, event.y, selected_only=True)
        cursors = {"nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw", "n": "sb_v_double_arrow", "s": "sb_v_double_arrow", "e": "sb_h_double_arrow", "w": "sb_h_double_arrow", "move": "fleur"}
        if piece is not None and not piece.locked:
            canvas.configure(cursor=cursors.get(edge or "", "hand2"))
        else:
            canvas.configure(cursor="hand2")

    def _change_press(self, event) -> None:
        piece, edge = self._change_hit(event.x, event.y)
        pan = list(getattr(self, "_change_pan", [0.0, 0.0]))
        picked = (
            piece is not None
            and piece.cut_id in self._change_picks
            and not piece.locked
        )
        can_resize = picked and bool(edge) and edge != "move"
        can_move = picked and edge == "move" and len(self._change_picks) == 1
        self._change_drag_state = (
            "maybe-box" if can_resize or can_move else "maybe-pan",
            event.x,
            event.y,
            pan[0],
            pan[1],
            piece,
            edge,
            bool(event.state & 0x0004),
            bool(event.state & 0x0001),
            False,
        )

    def _change_drag(self, event) -> None:
        state = getattr(self, "_change_drag_state", None)
        if state is None:
            return
        if state[0] in {"maybe-pan", "maybe-box"}:
            kind, start_x, start_y, pan_x, pan_y, piece, edge, ctrl, shift, _moved = state
            if abs(event.x - start_x) <= 8 and abs(event.y - start_y) <= 8:
                return
            if kind == "maybe-box":
                self._change_id = piece.cut_id
                self._change_drag_state = ("edge", edge, piece.x, piece.y, piece.width, piece.height, start_x, start_y, piece.cut_id)
            else:
                self._change_drag_state = ("pan", start_x, start_y, pan_x, pan_y)
            state = self._change_drag_state
        if state[0] == "pan":
            _kind, start_x, start_y, pan_x, pan_y = state
            self._change_pan = [pan_x + event.x - start_x, pan_y + event.y - start_y]
            self._paint_change_view()
            return
        origin = getattr(self, "_change_origin", None)
        piece = self._change_piece()
        image = self._preview_image
        if origin is None or piece is None or image is None:
            return
        _kind, edge, x, y, width, height, start_x, start_y, *_rest = state
        scale = origin[2] or 1
        dx = int(round((event.x - start_x) / scale))
        dy = int(round((event.y - start_y) / scale))
        left, top, right, bottom = x, y, x + width, y + height
        if edge == "move":
            left = x + dx
            top = y + dy
            right = left + width
            bottom = top + height
        else:
            if "w" in edge:
                left = x + dx
            if "e" in edge:
                right = x + width + dx
            if "n" in edge:
                top = y + dy
            if "s" in edge:
                bottom = y + height + dy
        if left > right:
            left, right = right, left
        if top > bottom:
            top, bottom = bottom, top
        image_w, image_h = image.size
        left = max(0, min(left, image_w - 1))
        top = max(0, min(top, image_h - 1))
        right = max(left + 1, min(right, image_w))
        bottom = max(top + 1, min(bottom, image_h))
        piece.x, piece.y = left, top
        piece.width, piece.height = right - left, bottom - top
        self._paint_change_view()

    def _change_release(self, _event) -> None:
        state = getattr(self, "_change_drag_state", None)
        self._change_drag_state = None
        self._change_frozen_bounds = None
        if state is None:
            return
        if state[0] in {"maybe-pan", "maybe-box"}:
            _kind, _x, _y, _px, _py, piece, _edge, ctrl, shift, _moved = state
            if piece is not None:
                self._apply_change_select(piece.cut_id, ctrl=ctrl, shift=shift)
                if piece.locked:
                    self._set_status(f"Cut {piece.number} is locked. Unlock it before you resize.")
            return
        if state[0] != "edge":
            self._paint_change_view()
            return
        piece = self._change_piece()
        sheet = self.selected
        image = self._preview_image
        if piece is None or sheet is None or image is None:
            return
        self._cut_ids = [piece.cut_id]
        self._push_box_history(sheet, f"Picture {piece.number or piece.cut_id} set to {piece.width}×{piece.height}")
        sheet.cuts[piece.cut_id]["box"] = (piece.x, piece.y, piece.width, piece.height)
        piece.image = crop_cut(
            image,
            (piece.x, piece.y, piece.width, piece.height),
            sheet.cuts[piece.cut_id],
            self._gap_for(sheet),
            self.tolerance,
        )
        self._mark_change_dirty()
        self._paint_change_view()

    def _piece_from_box(self, piece, box, image, identity=None):
        from cutter import Piece

        x, y, width, height = box
        cropped = image.crop((x, y, x + width, y + height))
        return Piece(piece.number, x, y, width, height, cropped, identity or _piece_box(piece))

    def _apply_splits_and_merges(self, pieces, sheet: Sheet):
        image = self._preview_image
        if image is None:
            return pieces
        drops = {drop for _keep, drop in sheet.sprite_merges}
        keeps: dict[tuple, list] = {}
        for keep, drop in sheet.sprite_merges:
            keeps.setdefault(keep, []).append(drop)
        by_id = {_piece_box(piece): piece for piece in pieces}
        output = []
        for piece in pieces:
            identity = _piece_box(piece)
            if identity in drops:
                continue
            if identity in sheet.splits:
                output.extend(self._expand_piece(piece, image, sheet, set()))
                continue
            others = [by_id[drop] for drop in keeps.get(identity, []) if drop in by_id]
            if others:
                group = [piece, *others]
                left = min(item.x for item in group)
                top = min(item.y for item in group)
                right = max(item.x + item.width for item in group)
                bottom = max(item.y + item.height for item in group)
                output.append(self._piece_from_box(piece, (left, top, right - left, bottom - top), image))
                continue
            output.append(piece)
        return output

    def _expand_piece(self, piece, image, sheet: Sheet, seen: set):
        """Split a picture, then split either half again if the user did that too."""
        identity = _piece_box(piece)
        if identity not in sheet.splits or identity in seen:
            return [piece]
        seen.add(identity)
        output = []
        for box in sheet.splits[identity]:
            child = self._piece_from_box(piece, box, image, box)
            output.extend(self._expand_piece(child, image, sheet, seen))
        return output

    def _split_horizontal(self) -> None:
        self._split_piece(vertical=False)

    def _split_vertical(self) -> None:
        self._split_piece(vertical=True)

    def _split_piece(self, vertical: bool) -> None:
        sheet = self.selected
        picks = [piece for piece in self._preview_pieces if piece.cut_id in self._cut_ids and not piece.keep_with]
        piece = picks[0] if len(picks) == 1 else self._focused_piece()
        if sheet is None or piece is None:
            self._set_status("Light one number, then split.")
            return
        if piece.width < 2 and vertical:
            self._set_status("That picture is too narrow to split.")
            return
        if piece.height < 2 and not vertical:
            self._set_status("That picture is too short to split.")
            return
        if vertical:
            half = max(1, piece.width // 2)
            first = (piece.x, piece.y, half, piece.height)
            second = (piece.x + half, piece.y, piece.width - half, piece.height)
            label = "Split across"
        else:
            half = max(1, piece.height // 2)
            first = (piece.x, piece.y, piece.width, half)
            second = (piece.x, piece.y + half, piece.width, piece.height - half)
            label = "Split down"
        self._push_box_history(sheet, label)
        record = sheet.cuts[piece.cut_id]
        record["box"] = first
        new_id = sheet.new_cut_id()
        sheet.cuts[new_id] = empty_cut(second, split_from=piece.cut_id)
        sheet.cuts[new_id]["clear_gap"] = record.get("clear_gap", True) is not False
        index = sheet.cut_order.index(piece.cut_id)
        sheet.cut_order.insert(index + 1, new_id)
        self._cut_ids = [piece.cut_id, new_id]
        self._cut_anchor = piece.cut_id
        self._refresh_grouped_preview(
            f"{label}. The first half keeps number {piece.number}. The new half is the next number."
        )

    def _quick_merge(self) -> None:
        """Join highlighted pictures on the main page without a confirm prompt."""
        self._merge_selected(ask=False)

    def _undo_last(self) -> None:
        self._undo_box(1)

    def _merge_selected(self, ask: bool = True) -> None:
        """Join two or more selected pictures into the earliest number."""
        sheet = self.selected
        chosen = [piece for piece in self._preview_pieces if piece.cut_id in set(self._cut_ids) and not piece.keep_with]
        chosen.sort(key=lambda piece: piece.number or 10**9)
        if sheet is None or len(chosen) < 2:
            self._set_status("Highlight two or more pictures, then Quick merge.")
            return
        keep_piece = chosen[0]
        numbers = ", ".join(str(piece.number) for piece in chosen)
        if ask and not messagebox.askyesno(
            "Merge cuts?",
            f"Merge {numbers} into {keep_piece.number}?",
            parent=getattr(self, "_change_window", None) or self,
        ):
            return
        self._push_box_history(sheet, f"Merged {numbers} into {keep_piece.number}")
        left = min(item.x for item in chosen)
        top = min(item.y for item in chosen)
        right = max(item.x + item.width for item in chosen)
        bottom = max(item.y + item.height for item in chosen)
        sheet.cuts[keep_piece.cut_id]["box"] = (left, top, right - left, bottom - top)
        dropped = [item.cut_id for item in chosen[1:]]
        sheet.cut_order = [cut_id for cut_id in sheet.cut_order if cut_id not in dropped]
        for cut_id in dropped:
            sheet.cuts.pop(cut_id, None)
        self._cut_ids = [keep_piece.cut_id]
        self._refresh_grouped_preview(f"Merged {numbers} into {keep_piece.number}.")

    def _pass_as_is(self) -> None:
        """Keep the selected cuts as their own files in the zip."""
        sheet = self.selected
        if sheet is None or not self._cut_ids:
            self._set_status("Select the pictures that should go in the zip as their own files.")
            return
        self._push_box_history(sheet, "Pass selection as is")
        for cut_id in self._cut_ids:
            record = sheet.cuts.get(cut_id)
            if record is None:
                continue
            record["passed"] = True
            record["out"] = False
            record["keep_with"] = ""
        self._refresh_grouped_preview("Those pictures will go in the zip as they are now. Purple marks Pass as is.")
        self._sync_edit_window()

    def _new_cut(self) -> None:
        sheet = self.selected
        image = self._preview_image
        if sheet is None or image is None:
            return
        pieces = self._preview_pieces
        if pieces:
            width = max(8, int(sum(item.width for item in pieces) / len(pieces)))
            height = max(8, int(sum(item.height for item in pieces) / len(pieces)))
        else:
            width, height = 32, 32
        focus_id = self._change_id if self._change_id in self._change_picks else next(iter(self._change_picks), None)
        near = next((item for item in pieces if item.cut_id == focus_id), None)
        if near is not None:
            x = near.x + 12
            y = near.y + 12
            if x + width > image.width:
                x = max(0, near.x - 12)
            if y + height > image.height:
                y = max(0, near.y - 12)
            x = max(0, min(x, image.width - width))
            y = max(0, min(y, image.height - height))
        else:
            layout = self._change_layout()
            if layout is None:
                x = max(0, (image.width - width) // 2)
                y = max(0, (image.height - height) // 2)
            else:
                _cw, _ch, left, top, rect_w, rect_h, *_rest = layout
                x = max(0, min(image.width - width, int(left + rect_w / 2 - width / 2)))
                y = max(0, min(image.height - height, int(top + rect_h / 2 - height / 2)))
        count = len(sheet.cut_order) + 1
        ask = ctk.CTkInputDialog(text=f"What number should this new cut be? 1 to {count}.", title="New cut")
        raw = ask.get_input()
        if raw is None:
            return
        try:
            number = max(1, min(count, int(raw)))
        except ValueError:
            number = count
        self._push_box_history(sheet, "New cut")
        cut_id = sheet.new_cut_id()
        sheet.cuts[cut_id] = empty_cut((x, y, width, height), created=True)
        sheet.cut_order.insert(number - 1, cut_id)
        self._cut_ids = [cut_id]
        self._change_picks = {cut_id}
        self._change_id = cut_id
        self._refresh_grouped_preview(f"New cut is number {number}. Drag it where you want it.")
        self._sync_edit_window()

    def _keep_with(self) -> None:
        sheet = self.selected
        chosen = [piece for piece in self._preview_pieces if piece.cut_id in set(self._cut_ids)]
        if sheet is None or len(chosen) != 2:
            self._set_status("Light two numbers: the leftover and the sprite it belongs with.")
            return
        chosen.sort(key=lambda piece: piece.width * piece.height)
        child, parent = chosen
        child_name = _cut_label(child, sheet, self.custom_names.get())
        parent_name = _cut_label(parent, sheet, self.custom_names.get())
        if not messagebox.askyesno(
            "Keep with?",
            f"Keep {child_name} with {parent_name}? {child_name} will not be its own file.",
            parent=getattr(self, "_change_window", None) or self,
        ):
            return
        self._push_box_history(sheet, f"Keep {child_name} with {parent_name}")
        sheet.cuts[child.cut_id]["keep_with"] = parent.cut_id
        sheet.cuts[child.cut_id]["out"] = False
        sheet.cuts[child.cut_id]["passed"] = False
        self._refresh_grouped_preview(f"{child_name} is kept with {parent_name}.")
        self._sync_edit_window()

    def _sync_edit_window(self) -> None:
        window = getattr(self, "_change_window", None)
        if window is None or not window.winfo_exists():
            return
        self._change_ids = [piece.cut_id for piece in self._preview_pieces]
        self._mark_change_dirty()
        self._rebuild_change_picker()
        self._paint_change_view()

    def _focused_piece(self):
        if len(self._cut_ids) != 1:
            return None
        cut_id = self._cut_ids[0]
        return next((piece for piece in self._preview_pieces if piece.cut_id == cut_id), None)

    def _resize_hit(self, view_x: int, view_y: int):
        """Main preview is select-only. Box edits happen in Edit cuts."""
        return None
        piece = self._focused_piece()
        if piece is None:
            return None
        origin_x, origin_y, scale = self._view_origin
        if scale <= 0:
            return None
        left = origin_x + (piece.x - self._pan_x) * scale
        top = origin_y + (piece.y - self._pan_y) * scale
        right = left + piece.width * scale
        bottom = top + piece.height * scale
        pad = 8
        near_l = abs(view_x - left) <= pad
        near_r = abs(view_x - right) <= pad
        near_t = abs(view_y - top) <= pad
        near_b = abs(view_y - bottom) <= pad
        in_x = left - pad <= view_x <= right + pad
        in_y = top - pad <= view_y <= bottom + pad
        edge = ""
        if near_t and in_x:
            edge += "n"
        if near_b and in_y:
            edge += "s"
        if near_l and in_y:
            edge += "w"
        if near_r and in_x:
            edge += "e"
        if not edge:
            return None
        return piece, edge

    def _drag_resize(self, event) -> None:
        piece, edge, x, y, width, height, start_x, start_y = self._resize
        image = self._preview_image
        if image is None:
            return
        scale = self._view_origin[2] or 1
        dx = int(round((event.x - start_x) / scale))
        dy = int(round((event.y - start_y) / scale))
        left, top, right, bottom = x, y, x + width, y + height
        if "w" in edge:
            left = x + dx
        if "e" in edge:
            right = x + width + dx
        if "n" in edge:
            top = y + dy
        if "s" in edge:
            bottom = y + height + dy
        if left > right:
            left, right = right, left
        if top > bottom:
            top, bottom = bottom, top
        image_w, image_h = image.size
        left = max(0, min(left, image_w - 1))
        top = max(0, min(top, image_h - 1))
        right = max(left + 1, min(right, image_w))
        bottom = max(top + 1, min(bottom, image_h))
        piece.x, piece.y = left, top
        piece.width, piece.height = right - left, bottom - top
        self._draw_preview()

    def _nudge_key(self, edge: str, event) -> str | None:
        widget = self.focus_get()
        if widget is not None and widget.winfo_class() in {"Entry", "TEntry"}:
            return None
        grow = not bool(event.state & 0x0001)
        self._nudge(edge, grow)
        return "break"

    def _nudge(self, edge: str, grow: bool) -> None:
        """Move one edge by a single pixel. Grow pushes it outward. Shrink pulls it in."""
        sheet = self.selected
        piece = self._focused_piece()
        image = self._preview_image
        if sheet is None or piece is None or image is None:
            self._set_status("Select one picture on the bottom row first.")
            return
        left, top = piece.x, piece.y
        right, bottom = piece.x + piece.width, piece.y + piece.height
        step = 1 if grow else -1
        if edge == "w":
            left -= step
        elif edge == "e":
            right += step
        elif edge == "n":
            top -= step
        else:
            bottom += step
        image_w, image_h = image.size
        if right - left < 1 or bottom - top < 1:
            return
        left = max(0, min(left, image_w - 1))
        top = max(0, min(top, image_h - 1))
        right = max(left + 1, min(right, image_w))
        bottom = max(top + 1, min(bottom, image_h))
        piece.x, piece.y = left, top
        piece.width, piece.height = right - left, bottom - top
        side = {"w": "left", "e": "right", "n": "up", "s": "down"}[edge]
        self._push_box_history(sheet, f"Picture {piece.number or piece.cut_id} {side} {'out' if grow else 'in'} 1 px")
        sheet.cuts[piece.cut_id]["box"] = (piece.x, piece.y, piece.width, piece.height)
        piece.image = crop_cut(
            image,
            (piece.x, piece.y, piece.width, piece.height),
            sheet.cuts[piece.cut_id],
            self._gap_for(sheet),
            self.tolerance,
        )
        if getattr(self, "_change_window", None) is not None:
            self._preview_pieces = self._visible_from(self._raw_pieces, sheet)
            self._paint_change_view()
            self._rebuild_change_picker()
            return
        self._fill_thumbs()
        self._draw_preview()

    def _commit_resize(self) -> None:
        sheet = self.selected
        piece = self._focused_piece()
        image = self._preview_image
        if sheet is None or piece is None or image is None:
            return
        box = (piece.x, piece.y, piece.width, piece.height)
        self._push_box_history(sheet, f"Picture {piece.number or piece.cut_id} set to {box[2]}×{box[3]}")
        sheet.cuts[piece.cut_id]["box"] = box
        piece.image = crop_cut(image, box, sheet.cuts[piece.cut_id], self._gap_for(sheet), self.tolerance)
        self._fill_thumbs()
        self._draw_preview()
        self._set_status(f"Box adjusted. Undo has {len(sheet.box_undo)} step(s). Cyan means edited.")

    def _box_state(self, sheet: Sheet) -> dict:
        return sheet.snapshot_cuts()

    def _apply_box_state(self, sheet: Sheet, state: dict) -> None:
        sheet.restore_cuts(state)

    def _push_box_history(self, sheet: Sheet, label: str) -> None:
        sheet.box_undo.append((self._box_state(sheet), label))
        if len(sheet.box_undo) > 10:
            sheet.box_undo.pop(0)
        sheet.box_redo.clear()

    def _restore_boxes(self, sheet: Sheet, snapshot: dict) -> None:
        self._apply_box_state(sheet, snapshot)
        self._refresh_grouped_preview(f"Updated the boxes. {len(sheet.box_undo)} undo step(s) left.")

    def _undo_box(self, steps: int = 1) -> None:
        sheet = self.selected
        if sheet is None or not sheet.box_undo:
            if sheet is not None and sheet.cuts:
                self._set_status("Nothing to undo on this sheet.")
                return
            self._set_status("Nothing to undo on this sheet.")
            return
        steps = min(steps, len(sheet.box_undo))
        current = self._box_state(sheet)
        target = current
        for _ in range(steps):
            snapshot, label = sheet.box_undo.pop()
            sheet.box_redo.append((current, label))
            if len(sheet.box_redo) > 10:
                sheet.box_redo.pop(0)
            target = snapshot
            current = snapshot
        self._restore_boxes(sheet, target)

    def _redo_box(self, steps: int = 1) -> None:
        sheet = self.selected
        if sheet is None or not sheet.box_redo:
            self._set_status("Nothing to redo on this sheet.")
            return
        steps = min(steps, len(sheet.box_redo))
        target = self._box_state(sheet)
        current = target
        for _ in range(steps):
            snapshot, label = sheet.box_redo.pop()
            sheet.box_undo.append((current, label))
            if len(sheet.box_undo) > 10:
                sheet.box_undo.pop(0)
            current = snapshot
            target = snapshot
        self._restore_boxes(sheet, target)

    def _show_change_history(self) -> None:
        """List box changes and let the user undo back to any one of them."""
        parent = getattr(self, "_change_window", None)
        if parent is None or not parent.winfo_exists():
            parent = self
        existing = getattr(self, "_history_window", None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()
        window = ctk.CTkToplevel(parent)
        window.title("Change history")
        window.geometry("520x420")
        window.transient(parent)
        window.configure(fg_color=BG)
        self._history_window = window
        ctk.CTkLabel(
            window,
            text="Newest first. Undo to here puts the sheet back to before that change. The same list is used on the main page and in Edit cuts.",
            text_color=MUTED,
            wraplength=480,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=12, pady=(12, 8))
        self._history_list = ctk.CTkScrollableFrame(window, fg_color=BG)
        self._history_list.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._button(window, "Close", window.destroy, width=100).pack(pady=(0, 12))
        self._fill_history_list()

    def _fill_history_list(self) -> None:
        frame = getattr(self, "_history_list", None)
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        sheet = self.selected
        history = list(reversed(sheet.box_undo)) if sheet is not None else []
        if not history:
            ctk.CTkLabel(frame, text="No changes on this sheet yet.", text_color=MUTED, anchor="w").pack(fill="x")
            return
        self._button(frame, "Undo all", lambda: self._undo_history_to(len(history)), width=100).pack(anchor="w", pady=(0, 8))
        for index, (_snapshot, label) in enumerate(history):
            row = ctk.CTkFrame(frame, fg_color=PANEL, corner_radius=6)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=label or "Change", text_color=TEXT, anchor="w", wraplength=280).pack(
                side="left", fill="x", expand=True, padx=8, pady=6
            )
            self._button(row, "Undo to here", lambda n=index + 1: self._undo_history_to(n), width=120).pack(
                side="right", padx=8, pady=6
            )

    def _undo_history_to(self, steps: int) -> None:
        self._undo_box(steps)
        if getattr(self, "_hold_main", False):
            live = {piece.cut_id for piece in self._preview_pieces}
            self._change_ids = [piece.cut_id for piece in self._preview_pieces]
            self._change_picks = {cut_id for cut_id in self._change_picks if cut_id in live}
            self._cut_ids = list(self._change_picks)
            self._rebuild_change_picker()
            self._paint_change_view()
        self._fill_history_list()

    def _box_history_menu(self, event, redo: bool) -> None:
        sheet = self.selected
        history = sheet.box_redo if redo and sheet is not None else sheet.box_undo if sheet is not None else []
        if not history:
            self._set_status("Nothing in that list yet.")
            return
        menu = Menu(self, tearoff=0, bg=PANEL, fg=TEXT, activebackground=RED, activeforeground=TEXT, font=("Silkscreen", 10))
        verb = "Redo" if redo else "Undo"
        recent = list(reversed(history[-10:]))
        for index, (_snapshot, label) in enumerate(recent, start=1):
            menu.add_command(label=f"{verb} {index}: {label}", command=lambda n=index, back=redo: self._redo_box(n) if back else self._undo_box(n))
        menu.tk_popup(event.x_root, event.y_root)

    def _revert_boxes(self) -> None:
        """Put only the selected sprites back to the boxes from the scan."""
        sheet = self.selected
        chosen = list(self._cut_ids)
        if sheet is None:
            self._set_status("Open a sheet first.")
            return
        if not chosen:
            self._set_status("Select the sprites you want to put back to the original scan.")
            return
        ok = messagebox.askyesno(
            "Revert selected sprites to original?",
            "Put the selected sprites back to the way they were when this sheet was scanned?\n\nOther sprites stay as they are. Undo can bring these edits back.",
            parent=self,
        )
        if not ok:
            return
        chosen_set = set(chosen)
        self._push_box_history(sheet, "Revert selected sprites to original")
        for cut_id in chosen_set:
            record = sheet.cuts.get(cut_id)
            if record is None:
                continue
            record["box"] = tuple(record.get("origin") or record["box"])
            record["out"] = False
            record["passed"] = False
            record["keep_with"] = ""
        self._refresh_grouped_preview("Those sprites are back to the original scan. Undo can restore the edits.")

    def _set_cut_lock(self, locked: bool) -> None:
        sheet = self.selected
        ids = list(getattr(self, "_change_picks", None) or self._cut_ids)
        if sheet is None or not ids:
            self._set_status("Highlight a cut first, then Lock or Unlock.")
            return
        self._push_box_history(sheet, "Lock" if locked else "Unlock")
        for cut_id in ids:
            record = sheet.cuts.get(cut_id)
            if record is not None:
                record["locked"] = locked
        self._preview_pieces = self._visible_from(self._raw_pieces, sheet)
        self._mark_change_dirty()
        self._rebuild_change_picker()
        self._paint_change_view()
        self._fill_thumbs()
        self._draw_preview()
        self._set_status(
            "Locked. Sky dashed outline. That box cannot be moved or resized."
            if locked
            else "Unlocked. Highlight it, then drag an edge to resize."
        )

    def _preview_cursor(self, event) -> None:
        if self.eyedropper:
            self.canvas.configure(cursor="crosshair")
            return
        hit = self._resize_hit(event.x, event.y)
        if hit is None:
            self.canvas.configure(cursor="hand2")
            return
        _piece, edge = hit
        cursors = {
            "nw": "size_nw_se",
            "se": "size_nw_se",
            "ne": "size_ne_sw",
            "sw": "size_ne_sw",
            "n": "sb_v_double_arrow",
            "s": "sb_v_double_arrow",
            "e": "sb_h_double_arrow",
            "w": "sb_h_double_arrow",
        }
        self.canvas.configure(cursor=cursors.get(edge, "hand2"))

    def _project_label(self) -> str:
        return safe_zip_stem(self.project_name.get())

    def _ask_zip_clash(self, existing: list[Path], project: str) -> tuple[str, bool] | None:
        """Ask what to do when zip names are already in the folder.

        Returns (project name, unique) or None if cancelled.
        unique True keeps the old files and writes a new name.
        """
        dialog = ctk.CTkToplevel(self)
        dialog.title("Those zip names are already used")
        dialog.configure(fg_color=BG)
        dialog.resizable(False, False)
        dialog.transient(self)
        chosen: dict[str, tuple[str, bool] | None] = {"value": None}
        names = [path.name for path in existing[:8]]
        extra = len(existing) - len(names)
        listed = "\n".join(names)
        if extra > 0:
            listed += f"\n…and {extra} more"
        ctk.CTkLabel(
            dialog,
            text="These zip names are already in that folder:\n\n"
            + listed
            + "\n\nSave without replacing keeps the old files and writes a unique name, like castle (2).zip. "
            "A project name prefixes every zip, like FF1 - castle.zip. Leave it blank for the generic unique name. "
            "Overwrite old files replaces the ones already there.",
            text_color=TEXT,
            wraplength=460,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 8))
        ctk.CTkLabel(dialog, text="Project name", text_color=MUTED).grid(
            row=1, column=0, sticky="w", padx=16, pady=(0, 4)
        )
        name_var = ctk.StringVar(value=project)
        name_box = ctk.CTkEntry(
            dialog,
            textvariable=name_var,
            fg_color=PANEL,
            border_color=LINE,
            text_color=TEXT,
            placeholder_text="optional",
            width=320,
        )
        name_box.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(0, 4))

        def finish(unique: bool) -> None:
            chosen["value"] = (safe_zip_stem(name_var.get()), unique)
            dialog.destroy()

        def cancel() -> None:
            chosen["value"] = None
            dialog.destroy()

        buttons = ctk.CTkFrame(dialog, fg_color=BG)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", padx=16, pady=(12, 16))
        self._button(buttons, "Cancel", cancel, width=100).pack(side="left", padx=(0, 6))
        self._button(buttons, "Overwrite old files", lambda: finish(False), width=170).pack(side="left", padx=(0, 6))
        self._button(buttons, "Save without replacing", lambda: finish(True), primary=True, width=190).pack(side="left")
        name_box.bind("<Return>", lambda _event: finish(True))
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.grab_set()
        name_box.focus_set()
        dialog.wait_window()
        return chosen["value"]

    def _export(self) -> None:
        if self.busy:
            return
        if not self.sheets:
            self._set_status("Add a sprite sheet first.")
            return
        folder = Path(self.output_folder) if self.output_folder else None
        if folder is None or not folder.is_dir():
            messagebox.showwarning(
                "Choose an output folder",
                "Pick the folder where each sheet's zip file should be saved.",
                parent=self,
            )
            return

        project = self._project_label()
        self._persist()
        used: set[Path] = set()
        preview_paths = [
            allocate_zip_path(folder, zip_stem(project, sheet.path.stem), used, unique=False)
            for sheet in self.sheets
        ]
        existing = [path for path in preview_paths if path.exists()]
        unique = True
        if existing:
            choice = self._ask_zip_clash(existing, project)
            if choice is None:
                return
            project, unique = choice
            self.project_name.set(project)
            self._persist()

        project_path = None
        if self.bundle_project.get():
            project_path = filedialog.asksaveasfilename(
                title="Save the project zip",
                parent=self,
                defaultextension=".zip",
                filetypes=[("Zip folder", "*.zip")],
                initialfile=project_zip_name(project),
            )
            if not project_path:
                return

        self.min_pixels = self._read_min_pixels()
        used = set()
        jobs = []
        for sheet in self.sheets:
            dest = allocate_zip_path(folder, zip_stem(project, sheet.path.stem), used, unique=unique)
            jobs.append(
                {
                    "source": sheet.path,
                    "dest": dest,
                    "stem": sheet.path.stem,
                    "color": self._gap_for(sheet),
                    "custom": dict(sheet.custom_names) if self.custom_names.get() else None,
                    "excluded": sheet.excluded,
                    "order": list(sheet.cut_order),
                    "cuts": {key: dict(value) for key, value in sheet.cuts.items()},
                }
            )

        self.busy = True
        self.scan_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.progress.grid()
        tolerance = self.tolerance
        minimum = self.min_pixels
        smart = self.smart_gaps.get()
        output_scale = self.output_scale

        def work() -> None:
            written: list[Path] = []
            skipped: list[str] = []
            failed: list[str] = []
            total = len(jobs)
            try:
                for index, job in enumerate(jobs, start=1):
                    self._post(
                        lambda n=index, t=total, name=job["source"].name: self._set_status(
                            f"Exporting {n} of {t}: {name}"
                        )
                    )
                    self._post(lambda n=index, t=total: self.progress.set((n - 1) / t))
                    try:
                        if job["excluded"]:
                            write_original_zip(job["dest"], job["source"])
                            written.append(job["dest"])
                            continue
                        image = load_image(job["source"])
                        if job["order"]:
                            result_pieces = export_from_cuts(
                                image, job["order"], job["cuts"], job["color"], tolerance
                            )
                        else:
                            result = split_sheet(
                                image, job["color"], tolerance, minimum, build_images=True, smart_gaps=smart
                            )
                            result_pieces = result.pieces
                        if not result_pieces:
                            skipped.append(job["source"].name)
                            continue
                        names = names_for_pieces(job["stem"], result_pieces, job["custom"])
                        pairs = [
                            (name, scale_piece(piece.image, output_scale))
                            for name, piece in zip(names, result_pieces)
                            if piece.image
                        ]
                        write_sheet_zip(job["dest"], pairs)
                        written.append(job["dest"])
                    except Exception as exc:
                        failed.append(f"{job['source'].name}: {exc}")
                if project_path and written:
                    try:
                        write_project_zip(Path(project_path), written)
                    except Exception as exc:
                        failed.append(f"Project zip: {exc}")
            finally:
                self._post(lambda: self._export_finished(written, skipped, failed, folder))

        threading.Thread(target=work, daemon=True).start()

    def _export_finished(self, written, skipped, failed, folder: Path) -> None:
        self.busy = False
        self.scan_button.configure(state="normal")
        self.export_button.configure(state="normal")
        self.progress.set(0)
        self.progress.grid_remove()
        lines = [f"Saved {len(written)} zip file(s)."]
        if skipped:
            lines.append(f"Skipped {len(skipped)} with no pieces: {', '.join(skipped[:6])}")
        if failed:
            lines.append("Could not finish:\n" + "\n".join(failed[:6]))
        self._set_status(lines[0])
        messagebox.showinfo("Export finished", "\n\n".join(lines), parent=self)
        if written and folder.is_dir():
            os.startfile(folder)


def _parse_drop(data: str) -> list[str]:
    """Turn a Windows drop payload into file paths. Braces protect spaces."""
    paths: list[str] = []
    token: list[str] = []
    in_braces = False
    for char in data:
        if char == "{" and not in_braces:
            in_braces = True
            token = []
            continue
        if char == "}" and in_braces:
            in_braces = False
            paths.append("".join(token))
            token = []
            continue
        if char == " " and not in_braces:
            if token:
                paths.append("".join(token))
                token = []
            continue
        token.append(char)
    if token:
        paths.append("".join(token))
    return paths


SORT_CHOICES = (
    ("Name", "name"),
    ("Name, Z to A", "name_desc"),
    ("Date modified, newest", "modified_new"),
    ("Date modified, oldest", "modified_old"),
    ("Date created, newest", "created_new"),
    ("Date created, oldest", "created_old"),
    ("File size, largest", "size_desc"),
    ("File size, smallest", "size_asc"),
    ("Piece count, most", "pieces_desc"),
    ("Piece count, least", "pieces_asc"),
    ("Folder", "folder"),
)


def _sort_label(key: str) -> str:
    for label, item in SORT_CHOICES:
        if item == key:
            return label
    return "Name"


def _sort_key(label: str) -> str:
    for item_label, key in SORT_CHOICES:
        if item_label == label:
            return key
    return "name"


def _expand_split_boxes(identity, splits, seen):
    """Keep splitting halves when the user split a piece more than once."""
    if identity not in splits or identity in seen:
        return [identity]
    seen.add(identity)
    boxes = []
    for box in splits[identity]:
        boxes.extend(_expand_split_boxes(box, splits, seen))
    return boxes


def _export_user_edits(pieces, image, splits, merges):
    """Turn split and merged cuts into the pictures that should be saved."""
    from cutter import Piece

    drops = {drop for _keep, drop in merges}
    keeps: dict[tuple, list] = {}
    for keep, drop in merges:
        keeps.setdefault(keep, []).append(drop)
    by_id = {_piece_box(piece): piece for piece in pieces}
    output = []
    for piece in pieces:
        identity = _piece_box(piece)
        if identity in drops:
            continue
        boxes = []
        if identity in splits:
            boxes = [(box, box) for box in _expand_split_boxes(identity, splits, set())]
        elif identity in keeps:
            others = [by_id[drop] for drop in keeps[identity] if drop in by_id]
            if others:
                group = [piece, *others]
                left = min(item.x for item in group)
                top = min(item.y for item in group)
                right = max(item.x + item.width for item in group)
                bottom = max(item.y + item.height for item in group)
                boxes = [((left, top, right - left, bottom - top), identity)]
        if not boxes:
            output.append(piece)
            continue
        for box, piece_id in boxes:
            x, y, width, height = box
            output.append(Piece(0, x, y, width, height, image.crop((x, y, x + width, y + height)), piece_id))
    for number, piece in enumerate(output, start=1):
        piece.number = number
    return output


def _piece_box(piece) -> tuple[int, int, int, int]:
    return piece.source_box or (piece.x, piece.y, piece.width, piece.height)


def _cut_style(piece, selected: bool) -> tuple[str, int, bool]:
    if selected:
        return GOLD, 3, bool(piece.out)
    if piece.out:
        return RED, 2, True
    if piece.locked:
        return PIN, 3, True
    if piece.keep_with:
        return LOCK, 2, False
    if piece.created:
        return EDIT, 2, False
    if piece.split_from:
        return SPLIT, 2, True
    if piece.passed:
        return PASS, 3, False
    return RED, 2, False


def _export_number(sheet, cut_id: str) -> int:
    number = 0
    for item in sheet.cut_order:
        record = sheet.cuts.get(item)
        if record is None or record.get("out") or record.get("keep_with"):
            continue
        number += 1
        if item == cut_id:
            return number
    return 0


def _cut_label(piece, sheet, custom: bool) -> str:
    # The cutter always reads by number. Custom names only go on saved files.
    if piece.number:
        return f"#{piece.number}"
    return "this cut"


def _cut_badge(piece, sheet, custom: bool) -> str:
    if piece.number:
        return f"{piece.number}L" if piece.locked else str(piece.number)
    return _cut_note(piece, sheet, custom)


def _cut_note(piece, sheet, custom: bool) -> str:
    if piece.out:
        return "Left out of zip"
    if piece.locked:
        return "Locked"
    if piece.keep_with and sheet is not None:
        index = sheet.cut_order.index(piece.keep_with) + 1 if piece.keep_with in sheet.cut_order else 0
        parent_name = f"#{index}" if index else "another sprite"
        return f"With {parent_name}"
    if getattr(piece, "clear_gap", True) is False:
        return "Keeps gap color"
    if piece.created:
        return "New cut"
    if piece.split_from:
        return "From a split"
    return ""


def _piece_label(sheet: Sheet) -> str:
    """90 pieces after Remove Cut. 80 out of 90 after Exclude from zip."""
    if sheet.piece_count is None:
        return "Not scanned"
    total = sheet.piece_total if sheet.piece_total is not None else sheet.piece_count
    if sheet.piece_count == total:
        noun = "piece" if sheet.piece_count == 1 else "pieces"
        return f"{sheet.piece_count} {noun}"
    return f"{sheet.piece_count} out of {total}"


def _sheet_sort_value(sheet: Sheet, mode: str):
    """A sort key. Dates and sizes use the file on disk. Unscanned sheets sort last by count."""
    name = sheet.path.name.lower()
    folder = str(sheet.path.parent).lower()
    try:
        info = sheet.path.stat()
        modified = info.st_mtime
        created = info.st_ctime
        size = info.st_size
    except OSError:
        modified = 0
        created = 0
        size = 0
    missing_count = sheet.piece_count is None
    count = 0 if sheet.piece_count is None else sheet.piece_count
    if mode == "name_desc":
        return tuple(-ord(char) for char in name)
    if mode == "modified_new":
        return (-modified, name)
    if mode == "modified_old":
        return (modified, name)
    if mode == "created_new":
        return (-created, name)
    if mode == "created_old":
        return (created, name)
    if mode == "size_desc":
        return (-size, name)
    if mode == "size_asc":
        return (size, name)
    if mode == "pieces_desc":
        return (missing_count, -count, name)
    if mode == "pieces_asc":
        return (missing_count, count, name)
    if mode == "folder":
        return (folder, name)
    return (name, folder)


def _short_name(name: str) -> str:
    if len(name) <= 42:
        return name
    return name[:18] + "..." + name[-20:]


def _badge_font():
    """Silkscreen for the numbers drawn on the sheet preview."""
    if _BOLD_FONT_PATH and _BOLD_FONT_PATH.exists():
        return ImageFont.truetype(str(_BOLD_FONT_PATH), 16)
    return ImageFont.load_default()


def _checker(size: tuple[int, int], origin_x: int, origin_y: int) -> Image.Image:
    """A dark checkerboard so transparent gap pixels are easy to see."""
    width, height = size
    tile = 8
    ys, xs = np.indices((height, width))
    board = ((xs + origin_x) // tile + (ys + origin_y) // tile) % 2
    pixels = np.empty((height, width, 4), dtype=np.uint8)
    pixels[:] = (26, 26, 26, 255)
    pixels[board == 0] = (46, 46, 46, 255)
    return Image.fromarray(pixels, "RGBA")


def _fit_thumb(image: Image.Image, max_w: int, max_h: int) -> Image.Image:
    width, height = image.size
    scale = min(max_w / max(width, 1), max_h / max(height, 1))
    resample = Image.Resampling.NEAREST if scale >= 1 else Image.Resampling.BOX
    fitted = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), resample)
    return Image.alpha_composite(_checker(fitted.size, 0, 0), fitted)


def main() -> None:
    try:
        _start()
    except Exception:
        _show_startup_error()


def _start() -> None:
    register_extra_formats()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App()
    app.mainloop()


def _show_startup_error() -> None:
    """Show a dialog if the app dies before its window is up. There is no console to read."""
    import traceback

    detail = traceback.format_exc()
    try:
        log = settings_file().with_name("error.log")
        log.write_text(detail, encoding="utf-8")
    except OSError:
        pass
    try:
        messagebox.showerror("Redundis Sprite Cutter", "The cutter could not start.\n\n" + detail[-1500:])
    except Exception:
        pass


if __name__ == "__main__":
    main()
