"""Redundis Sprite Cutter — split sprite sheets and save one zip per sheet."""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import Menu, colorchooser, filedialog, messagebox

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from cutter import (
    apply_grouped_cuts,
    group_cut_into_parent,
    hex_to_rgb,
    load_image,
    omit_pieces,
    rgb_to_hex,
    split_sheet,
)
from exporter import (
    allocate_zip_path,
    names_for_pieces,
    scale_piece,
    write_original_zip,
    write_project_zip,
    write_sheet_zip,
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
LINE = "#2e2e2e"
WARN = "#e0a030"
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


class Sheet:
    """One source file waiting to be cut."""

    def __init__(self, path: Path):
        self.path = path
        self.override: tuple[int, int, int] | None = None
        self.piece_count: int | None = None
        self.piece_total: int | None = None
        self.suggestion: tuple[int, int, int] | None = None
        self.suggestion_text = ""
        self.custom_names: dict[int, str] = {}
        self.excluded = False
        # Original boxes the user grouped back into the picture around them.
        self.grouped_boxes: list[tuple[int, int, int, int]] = []
        # Cuts left out of the zip. The original file is not changed.
        self.removed_boxes: list[tuple[int, int, int, int]] = []
        # How many boxes each right-click added, so undo puts the whole batch back.
        self.group_steps: list[int] = []
        # Last Remove Cut or Exclude from zip, so Undo can put a mistake back.
        self.undo: list[tuple] = []
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
        self._fit_view = True
        self._view_origin = (0, 0, 1.0)
        self._raw_pieces = []
        self._thumb_token = 0
        self._thumb_pending: list = []
        self._thumb_columns: dict[tuple, object] = {}
        self._cut_boxes: list[tuple[int, int, int, int]] = []
        self._cut_anchor: tuple[int, int, int, int] | None = None
        self.list_sort = saved["list_sort"]
        self._ui_queue: queue.Queue = queue.Queue()

        self.include_subfolders = ctk.BooleanVar(value=saved["include_subfolders"])
        self.custom_names = ctk.BooleanVar(value=saved["custom_names"])
        self.preview_on = ctk.BooleanVar(value=saved["preview_before_export"])
        self.keep_both = ctk.BooleanVar(value=saved["keep_both"])
        self.bundle_project = ctk.BooleanVar(value=saved["bundle_project"])
        self.smart_gaps = ctk.BooleanVar(value=saved["smart_gaps"])

        self._build()
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
        settings.grid_columnconfigure(4, weight=1)

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
        self._button(settings, "Choose color", self._choose_color).grid(row=0, column=3, padx=4)
        self.eye_button = self._button(settings, "Pick from sheet", self._toggle_eyedropper)
        self.eye_button.grid(row=0, column=4, sticky="w", padx=4)

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
        self._check(checks, "Keep both if the zip name is taken", self.keep_both, self._persist).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=(0, 18), pady=3
        )
        self._check(checks, "Bundle sheet zips into one project zip", self.bundle_project, self._persist).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=3
        )
        self._check(
            checks,
            "Also split transparent and touching sprites",
            self.smart_gaps,
            self._cuts_changed,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=3)

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

        sheet_color = ctk.CTkFrame(right, fg_color=PANEL)
        sheet_color.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 4))
        self.sheet_color_label = ctk.CTkLabel(
            sheet_color,
            text="Select a sheet to give it its own gap color.",
            text_color=MUTED,
            anchor="w",
        )
        self.sheet_color_label.pack(side="top", anchor="w", fill="x")
        sheet_buttons = ctk.CTkFrame(sheet_color, fg_color=PANEL)
        sheet_buttons.pack(side="top", anchor="e", fill="x", pady=(4, 0))
        self.clear_override_button = self._button(sheet_buttons, "Use default color", self._clear_override, width=200)
        self.override_button = self._button(
            sheet_buttons, "Different color for this sheet", self._override_color, width=280
        )
        self.override_button.pack(side="right", padx=(6, 0))
        self.clear_override_button.pack(side="right")

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
        preview_wrap.grid_rowconfigure(1, weight=1)

        zoom_row = ctk.CTkFrame(preview_wrap, fg_color=BG)
        zoom_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        self.zoom_row = zoom_row
        ctk.CTkLabel(zoom_row, text="Zoom", text_color=MUTED).pack(side="left")
        self.zoom_slider = ctk.CTkSlider(
            zoom_row,
            from_=1,
            to=10,
            number_of_steps=9,
            command=self._on_zoom,
            width=150,
            button_color=RED,
            button_hover_color=RED_HOVER,
            progress_color=RED,
        )
        self.zoom_slider.set(self.zoom)
        self.zoom_slider.pack(side="left", padx=6)
        self.zoom_label = ctk.CTkLabel(zoom_row, text="Fit", text_color=TEXT, width=40)
        self.zoom_label.pack(side="left")
        self._button(zoom_row, "Reset size", self._fit_preview, width=108).pack(side="left", padx=(6, 0))
        self._button(zoom_row, "Remove Cut", self._remove_cut_selected, width=118).pack(side="left", padx=(6, 0))
        self._button(zoom_row, "Exclude from zip", self._exclude_cuts_selected, primary=True, width=156).pack(
            side="left", padx=(6, 0)
        )
        self._button(zoom_row, "Undo group", self._undo_group, width=118).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(zoom_row, text="Scroll to zoom. Drag to look around.", text_color=MUTED).pack(side="left", padx=8)

        self.canvas = ctk.CTkCanvas(preview_wrap, bg="#101010", highlightthickness=0, cursor="fleur")
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self.canvas.bind("<ButtonPress-1>", self._pan_press)
        self.canvas.bind("<B1-Motion>", self._pan_drag)
        self.canvas.bind("<ButtonRelease-1>", self._pan_release)
        self.canvas.bind("<Button-3>", self._on_preview_menu)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", lambda _event: self._draw_preview())

        self.preview_note = ctk.CTkLabel(
            preview_wrap,
            text="Preview is off. Export will cut the sheets and write the zip files directly.",
            text_color=MUTED,
        )

        self.thumbs = ctk.CTkScrollableFrame(
            preview_wrap,
            orientation="horizontal",
            height=168,
            fg_color=PANEL,
            corner_radius=8,
        )
        self.thumbs.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))

        status_bar = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 10))
        status_bar.grid_columnconfigure(1, weight=1)
        self.progress = ctk.CTkProgressBar(status_bar, width=180, progress_color=RED, fg_color=RAISED)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, padx=(0, 10))
        self.progress.grid_remove()
        self.status = ctk.CTkLabel(status_bar, text="Ready.", text_color=MUTED, anchor="w")
        self.status.grid(row=0, column=1, sticky="ew")
        support = ctk.CTkFrame(status_bar, fg_color="transparent")
        support.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._support_line(support, "If you like this, please consider donating - ", self._open_donate)
        self._support_line(support, "or consider subscribing on Twitch - ", self._open_twitch_sub)

        self._apply_preview_visibility()

    def _button(self, parent, text, command, primary=False, width=120):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=40,
            corner_radius=6,
            fg_color=RED if primary else RAISED,
            hover_color=RED_HOVER if primary else "#333333",
            text_color=TEXT,
        )

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

    def _support_line(self, parent, lead: str, command) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(anchor="w")
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
                "keep_both": self.keep_both.get(),
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
                callback()
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
        snapped = max(1, min(10, int(round(float(value)))))
        was_fit = self._fit_view
        if snapped == self.zoom and not was_fit:
            self.zoom_label.configure(text=f"{snapped}x")
            return
        # Keep the middle of the view put when the zoom locks to a new step.
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        scale = self._view_scale()
        center_x = self._pan_x + (width / scale) / 2
        center_y = self._pan_y + (height / scale) / 2
        self._fit_view = False
        self.zoom = snapped
        self._pan_x = center_x - (width / snapped) / 2
        self._pan_y = center_y - (height / snapped) / 2
        self.zoom_label.configure(text=f"{snapped}x")
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
        if event.delta > 0:
            if self._fit_view:
                self.zoom = 1 if scale < 1 else min(10, int(scale) + 1)
            else:
                self.zoom = min(10, int(self.zoom) + 1)
            self._fit_view = False
        elif int(self.zoom) <= 1 or self._fit_view:
            self._fit_preview()
            return
        else:
            self.zoom = max(1, int(self.zoom) - 1)
            self._fit_view = False
        self.zoom_slider.set(self.zoom)
        self.zoom_label.configure(text=f"{self.zoom}x")
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
        return float(max(1, int(self.zoom)))

    def _cuts_changed(self) -> None:
        if self.busy:
            return
        self.min_pixels = self._read_min_pixels()
        self._persist()
        for sheet in self.sheets:
            self._clear_result(sheet)
            self._style_row(sheet)
        if self.selected and self.preview_on.get():
            self._load_preview(self.selected)

    def _clear_result(self, sheet: Sheet) -> None:
        sheet.piece_count = None
        sheet.suggestion = None
        sheet.suggestion_text = ""
        sheet.error = ""
        sheet.grouped_boxes = []
        sheet.group_steps = []

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
            self.canvas.configure(cursor="fleur")

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
            self._load_preview(sheet)

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
            self._load_preview(preview)

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
            self._load_preview(self.selected)
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
            self._load_preview(sheet)

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
            self._load_preview(self.selected)
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
            self._load_preview(self.selected)

    def _apply_preview_visibility(self) -> None:
        if self.preview_on.get():
            self.preview_note.grid_forget()
            self.zoom_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
            self.canvas.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
            self.thumbs.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        else:
            self.zoom_row.grid_forget()
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
            grouped = apply_grouped_cuts(result.pieces, sheet.grouped_boxes)
            kept = omit_pieces(grouped, sheet.removed_boxes)
            sheet.piece_total = len(grouped)
            sheet.piece_count = len(kept)
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

    def _load_preview(self, sheet: Sheet) -> None:
        self._preview_token += 1
        token = self._preview_token
        sheet.generation += 1
        generation = sheet.generation
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
                lambda: self._show_preview(token, sheet, generation, image, result, error, excluded)
            )

        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, token, sheet, generation, image, result, error, excluded=False) -> None:
        if token != self._preview_token or sheet not in self.sheets:
            return
        if sheet.generation != generation:
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
        self._raw_pieces = result.pieces
        shown = self._visible_from(result.pieces, sheet)
        sheet.suggestion = result.suggestion
        sheet.suggestion_text = result.suggestion_text
        self._style_row(sheet)
        self._preview_image = image
        self._preview_pieces = shown
        self._cut_boxes = []
        self._cut_anchor = None
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

    def _clear_thumbs(self) -> None:
        self._thumb_token += 1
        self._thumb_pending = []
        self._thumb_columns = {}
        for child in self.thumbs.winfo_children():
            child.destroy()
        self._thumb_refs.clear()

    def _fill_thumbs(self) -> None:
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
            box = _piece_box(piece)
            column = ctk.CTkFrame(self.thumbs, fg_color=BG, corner_radius=6, border_width=2, border_color=BG)
            column.pack(side="left", padx=4, pady=4)
            self._thumb_columns[box] = column
            thumb = _fit_thumb(piece.image, 120, 78)
            photo = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=thumb.size)
            self._thumb_refs.append(photo)
            picture = ctk.CTkLabel(column, image=photo, text="")
            picture.pack(padx=4, pady=(4, 0))
            number = ctk.CTkLabel(column, text=str(piece.number), text_color=RED)
            number.pack()
            for widget in (column, picture, number):
                widget.bind("<Button-1>", lambda event, item=piece: self._select_cut(item, event))
                widget.bind("<Button-3>", lambda event, item=piece: self._cut_menu(event, item))
            self._style_thumb(box)
            if show_names and self.selected is not None:
                default = f"{stem} -{piece.number}.png"
                entry = ctk.CTkEntry(column, width=190, fg_color=PANEL, border_color=LINE, text_color=TEXT)
                entry.insert(0, self.selected.custom_names.get(piece.number, default))
                entry.pack(padx=4, pady=(0, 4))
                entry.bind("<KeyRelease>", lambda _event, number=piece.number, box=entry: self._store_name(number, box))
                entry.bind("<Button-3>", lambda event, item=piece: self._cut_menu(event, item))
        if self._thumb_pending and token == self._thumb_token:
            self.after(1, lambda: self._append_thumbs(token))

    def _store_name(self, number: int, entry) -> None:
        if self.selected is not None:
            self.selected.custom_names[number] = entry.get()

    def _draw_preview(self) -> None:
        self.canvas.delete("all")
        image = self._preview_image
        if image is None or not self.preview_on.get():
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
        crop = image.crop((x0, y0, x1, y1))
        framed = Image.alpha_composite(_checker(crop.size, x0, y0), crop)
        scaled_w = max(1, int(round((x1 - x0) * scale)))
        scaled_h = max(1, int(round((y1 - y0) * scale)))
        scaled = framed.resize((scaled_w, scaled_h), Image.Resampling.NEAREST)
        draw = ImageDraw.Draw(scaled)
        font = _badge_font()
        for piece in self._preview_pieces:
            left = (piece.x - x0) * scale
            top = (piece.y - y0) * scale
            right = left + piece.width * scale - 1
            bottom = top + piece.height * scale - 1
            if right < 0 or bottom < 0 or left > scaled.width or top > scaled.height:
                continue
            chosen = _piece_box(piece) in self._cut_boxes
            draw.rectangle((left, top, right, bottom), outline=WARN if chosen else RED, width=3 if chosen else 2)
            label = str(piece.number)
            text_box = draw.textbbox((0, 0), label, font=font)
            text_w = text_box[2] - text_box[0]
            text_h = text_box[3] - text_box[1]
            badge = (left + 2, top + 2, left + text_w + 10, top + text_h + 8)
            draw.rectangle(badge, fill=RED)
            draw.text((left + 6, top + 4), label, fill="white", font=font)
        offset_x = int((view_w - image_w * scale) / 2) if image_w * scale < view_w - 1 else 0
        offset_y = int((view_h - image_h * scale) / 2) if image_h * scale < view_h - 1 else 0
        self._view_origin = (offset_x, offset_y, scale)
        self._photo = ImageTk.PhotoImage(scaled)
        self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self._photo)

    def _pan_press(self, event) -> None:
        self._press = (event.x, event.y, self._pan_x, self._pan_y, self._view_scale(), event.state)

    def _pan_drag(self, event) -> None:
        if self.eyedropper or self._press is None or self._preview_image is None:
            return
        start_x, start_y, origin_x, origin_y, scale, state = self._press
        if state & 0x0001 or state & 0x0004:
            return
        self._pan_x = origin_x - (event.x - start_x) / scale
        self._pan_y = origin_y - (event.y - start_y) / scale
        self._draw_preview()

    def _pan_release(self, event) -> None:
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
        box = _piece_box(piece)
        order = [_piece_box(item) for item in self._preview_pieces]
        shift = bool(flags & 0x0001)
        ctrl = bool(flags & 0x0004)
        if shift and self._cut_anchor in order and box in order:
            start = order.index(self._cut_anchor)
            end = order.index(box)
            low, high = sorted((start, end))
            self._cut_boxes = order[low : high + 1]
        elif ctrl:
            if box in self._cut_boxes:
                self._cut_boxes = [item for item in self._cut_boxes if item != box]
            else:
                self._cut_boxes.append(box)
            self._cut_anchor = box
        else:
            self._cut_boxes = [box]
            self._cut_anchor = box
        self._style_cut_selection()

    def _style_cut_selection(self) -> None:
        for box in list(self._thumb_columns):
            self._style_thumb(box)
        self._draw_preview()
        count = len(self._cut_boxes)
        if count > 1:
            self._set_status(f"{count} cuts selected. Use Remove Cut or Exclude from zip.")
        elif count == 1:
            self._set_status("1 cut selected. Use Remove Cut or Exclude from zip.")

    def _style_thumb(self, box: tuple) -> None:
        column = self._thumb_columns.get(box)
        if column is None:
            return
        column.configure(border_color=WARN if box in self._cut_boxes else BG)

    def _cut_menu(self, event, piece) -> None:
        if self.busy or self.selected is None:
            return
        if piece is not None:
            box = _piece_box(piece)
            if box not in self._cut_boxes:
                self._cut_boxes = [box]
                self._cut_anchor = box
                self._style_cut_selection()
        targets = [box for box in self._cut_boxes if any(_piece_box(item) == box for item in self._preview_pieces)]
        menu = Menu(
            self,
            tearoff=0,
            bg=PANEL,
            fg=TEXT,
            activebackground=RED,
            activeforeground=TEXT,
            font=("Silkscreen", 10),
        )
        if len(targets) > 1:
            menu.add_command(
                label=f"Remove Cut on {len(targets)}",
                command=lambda boxes=list(targets): self._group_cuts(boxes),
            )
            menu.add_command(
                label=f"Exclude {len(targets)} from zip",
                command=lambda boxes=list(targets): self._exclude_cuts(boxes),
            )
        elif len(targets) == 1:
            number = next(item.number for item in self._preview_pieces if _piece_box(item) == targets[0])
            menu.add_command(
                label=f"Remove Cut {number}",
                command=lambda boxes=list(targets): self._group_cuts(boxes),
            )
            menu.add_command(
                label=f"Exclude cut {number} from zip",
                command=lambda boxes=list(targets): self._exclude_cuts(boxes),
            )
        if self.selected.grouped_boxes:
            menu.add_command(label="Undo last grouping", command=self._undo_group)
        if menu.index("end") is None:
            return
        menu.tk_popup(event.x_root, event.y_root)

    def _group_cuts(self, boxes: list[tuple[int, int, int, int]]) -> None:
        sheet = self.selected
        if sheet is None or not self._raw_pieces or not boxes:
            self._set_status("Select a cut first.")
            return
        # Smallest first, and don't let one selected cut swallow another.
        ordered = sorted(boxes, key=lambda box: box[2] * box[3])
        pending = list(sheet.grouped_boxes)
        current = apply_grouped_cuts(self._raw_pieces, pending)
        added = 0
        skipped = 0
        for box in ordered:
            if box in pending:
                continue
            updated = group_cut_into_parent(current, box, skip_boxes=ordered)
            if updated is None:
                skipped += 1
                continue
            pending.append(box)
            current = updated
            added += 1
        if added == 0:
            self._set_status("Those cuts are already the largest pictures, so there is nowhere to group them.")
            return
        sheet.grouped_boxes = pending
        sheet.group_steps.append(added)
        sheet.undo.append(("group", added))
        note = f"Remove Cut put {added} piece(s) back into the larger picture."
        if skipped:
            note += f" Left {skipped} with no larger picture."
        self._cut_boxes = []
        self._cut_anchor = None
        self._refresh_grouped_preview(note)

    def _undo_group(self) -> None:
        sheet = self.selected
        if sheet is None or not sheet.undo:
            self._set_status("Nothing to undo.")
            return
        kind, payload = sheet.undo.pop()
        if kind == "exclude":
            gone = set(payload)
            sheet.removed_boxes = [box for box in sheet.removed_boxes if box not in gone]
            note = "Put those cuts back in the zip."
        else:
            count = payload
            if sheet.group_steps:
                sheet.group_steps.pop()
            for _ in range(min(count, len(sheet.grouped_boxes))):
                sheet.grouped_boxes.pop()
            noun = "cuts" if count != 1 else "cut"
            note = f"Put the last {noun} back on their own."
        self._cut_boxes = []
        self._cut_anchor = None
        self._refresh_grouped_preview(note)

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
        self._set_status(f"{note} {_piece_label(sheet)}.")

    def _remove_cut_selected(self) -> None:
        self._group_cuts(list(self._cut_boxes))

    def _exclude_cuts_selected(self) -> None:
        self._exclude_cuts(list(self._cut_boxes))

    def _exclude_cuts(self, boxes: list[tuple[int, int, int, int]]) -> None:
        sheet = self.selected
        if sheet is None or not boxes:
            self._set_status("Select a cut first.")
            return
        sheet.removed_boxes = [*sheet.removed_boxes, *boxes]
        sheet.undo.append(("exclude", list(boxes)))
        self._cut_boxes = []
        self._cut_anchor = None
        noun = "cut" if len(boxes) == 1 else "cuts"
        self._refresh_grouped_preview(f"Excluded {len(boxes)} {noun} from the zip.")

    def _visible_from(self, pieces, sheet: Sheet):
        grouped = apply_grouped_cuts(pieces, sheet.grouped_boxes)
        shown = omit_pieces(grouped, sheet.removed_boxes)
        sheet.piece_total = len(grouped)
        sheet.piece_count = len(shown)
        return shown

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
        project_path = None
        if self.bundle_project.get():
            project_path = filedialog.asksaveasfilename(
                title="Save the project zip",
                parent=self,
                defaultextension=".zip",
                filetypes=[("Zip folder", "*.zip")],
                initialfile="sprite sheets.zip",
            )
            if not project_path:
                return

        self.min_pixels = self._read_min_pixels()
        used: set[Path] = set()
        jobs = []
        for sheet in self.sheets:
            dest = allocate_zip_path(folder, sheet.path.stem, used, self.keep_both.get())
            jobs.append(
                {
                    "source": sheet.path,
                    "dest": dest,
                    "stem": sheet.path.stem,
                    "color": self._gap_for(sheet),
                    "custom": dict(sheet.custom_names) if self.custom_names.get() else None,
                    "excluded": sheet.excluded,
                    "grouped": list(sheet.grouped_boxes),
                    "removed": list(sheet.removed_boxes),
                }
            )
        if not self.keep_both.get():
            existing = [job["dest"] for job in jobs if job["dest"].exists()]
            if existing:
                ok = messagebox.askyesno(
                    "Overwrite existing zips?",
                    f"{len(existing)} zip file(s) already exist in that folder.\n\nOverwrite them?",
                    parent=self,
                )
                if not ok:
                    return

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
            for index, job in enumerate(jobs, start=1):
                self._post(
                    lambda n=index, t=total, name=job["source"].name: self._set_status(
                        f"Exporting {n} of {t}: {name}"
                    )
                )
                self._post(lambda n=index, t=total: self.progress.set(n / t))
                try:
                    if job["excluded"]:
                        write_original_zip(job["dest"], job["source"])
                        written.append(job["dest"])
                        continue
                    image = load_image(job["source"])
                    result = split_sheet(
                        image, job["color"], tolerance, minimum, build_images=True, smart_gaps=smart
                    )
                    result.pieces = omit_pieces(apply_grouped_cuts(result.pieces, job["grouped"]), job["removed"])
                    if not result.pieces:
                        skipped.append(job["source"].name)
                        continue
                    names = names_for_pieces(job["stem"], result.pieces, job["custom"])
                    pairs = [
                        (name, scale_piece(piece.image, output_scale))
                        for name, piece in zip(names, result.pieces)
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


def _piece_box(piece) -> tuple[int, int, int, int]:
    return piece.source_box or (piece.x, piece.y, piece.width, piece.height)


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
