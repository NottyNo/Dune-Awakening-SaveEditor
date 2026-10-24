from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from dune_save_editor import __version__
from dune_save_editor.catalog import CatalogItem, default_item_stats, load_catalog
from dune_save_editor.save_file import DuneSave, Inventory, InventoryItem, SaveError
from dune_save_editor.stats import CHARACTER_STATS, SPECIALIZATION_TRACKS
from dune_save_editor.update_check import RELEASES_PAGE_URL, ReleaseInfo, check_for_update

DARK_COLORS = {
    "background": "#111419",
    "surface": "#1A1F26",
    "surface_raised": "#242B34",
    "field": "#0D1014",
    "border": "#343C47",
    "text": "#E7E9ED",
    "muted": "#9CA6B3",
    "accent": "#C9A34A",
    "accent_active": "#DDBB68",
    "accent_dark": "#5A4824",
    "danger": "#9B3D45",
    "danger_active": "#B94A54",
    "warning": "#E4B65E",
}

ASSET_DIRECTORY = Path(__file__).with_name("assets")
ALL_CATEGORIES = "All categories"
CATALOG_COLUMN_DEFINITIONS = (
    ("name", "Name", 190),
    ("template", "Template ID", 170),
    ("category", "Category", 120),
    ("grade", "Grade", 52),
    ("stack", "Max Stack", 70),
    ("weight", "Weight", 65),
)
INVENTORY_COLUMN_DEFINITIONS = (
    ("slot", "Slot", 48),
    ("name", "Name", 170),
    ("template", "Template ID", 150),
    ("category", "Category", 105),
    ("quantity", "Qty", 55),
    ("quality", "Grade", 58),
    ("durability", "Durability (Current/Max)", 145),
    ("weight", "Unit Weight", 78),
    ("total_weight", "Stack Weight", 85),
)


def _display_number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def catalog_item_for_template(
    catalog_by_id: Mapping[str, CatalogItem], template_id: str
) -> CatalogItem | None:
    """Find catalog metadata without assuming save-file identifier capitalization."""

    return catalog_by_id.get(template_id) or catalog_by_id.get(template_id.casefold())


def inventory_weight_summary(
    inventory: Inventory,
    records: Iterable[InventoryItem],
    catalog_by_id: Mapping[str, CatalogItem],
) -> str:
    known_weight = 0.0
    unknown_stacks = 0
    for record in records:
        item = catalog_item_for_template(catalog_by_id, record.template_id)
        if item is None:
            unknown_stacks += 1
        else:
            known_weight += item.item_size * record.stack_size

    if inventory.max_item_volume is None:
        maximum = "not stored"
    elif inventory.max_item_volume < 0:
        maximum = "unlimited"
    else:
        maximum = _display_number(inventory.max_item_volume)
    load_kind = "Known load" if unknown_stacks else "Estimated load"
    unknown = f" (+{unknown_stacks} unlisted stacks)" if unknown_stacks else ""
    return (
        f"Max inventory weight: {maximum}  •  {load_kind}: {_display_number(known_weight)}{unknown}"
    )


def visible_catalog_columns(selections: Mapping[str, bool]) -> tuple[str, ...]:
    return tuple(
        column for column, _label, _width in CATALOG_COLUMN_DEFINITIONS if selections.get(column)
    )


def visible_inventory_columns(selections: Mapping[str, bool]) -> tuple[str, ...]:
    return tuple(
        column for column, _label, _width in INVENTORY_COLUMN_DEFINITIONS if selections.get(column)
    )


def effective_max_durability(
    record: InventoryItem, catalog_item: CatalogItem | None
) -> float | None:
    stored = record.stored_max_durability
    if stored is not None and stored > 0:
        return stored
    if catalog_item is not None and catalog_item.max_durability > 0:
        return catalog_item.max_durability
    return None


def durability_summary(record: InventoryItem, catalog_item: CatalogItem | None) -> str:
    current = record.durability
    maximum = effective_max_durability(record, catalog_item)
    if current is None and maximum is None:
        return ""
    current_text = "—" if current is None else _display_number(current)
    maximum_text = "?" if maximum is None else _display_number(maximum)
    return f"{current_text}/{maximum_text}"


@dataclass(frozen=True, slots=True)
class CatalogChoice:
    item: CatalogItem
    quality_level: int = 0

    @property
    def display_name(self) -> str:
        if self.quality_level:
            return f"{self.item.display_name} Grade {self.quality_level}"
        return self.item.display_name

    @property
    def search_text(self) -> str:
        grade = f" grade {self.quality_level}" if self.quality_level else ""
        return f"{self.item.search_text}{grade}"


class SaveEditorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"Dune: Awakening Save Editor — v{__version__}")
        self.root.geometry("1220x760")
        self.root.minsize(980, 620)
        self._configure_theme()
        self.app_icon_image: tk.PhotoImage | None = None
        self.toolbar_logo_image: tk.PhotoImage | None = None
        self._load_brand_assets()

        self.save: DuneSave | None = None
        self.player_row_id: int | None = None
        self.inventory: Inventory | None = None
        self.inventories: list[Inventory] = []
        self.inventory_choices: dict[str, Inventory] = {}
        self.inventory_rows: dict[str, InventoryItem] = {}
        self.catalog = load_catalog()
        self.catalog_by_id = {item.template_id.casefold(): item for item in self.catalog}
        self.catalog_choices = tuple(
            CatalogChoice(item, quality_level)
            for item in self.catalog
            for quality_level in (0, *item.quality_levels)
        )
        self.catalog_rows: dict[str, CatalogChoice] = {}
        self.catalog_categories = (
            ALL_CATEGORIES,
            *sorted({item.category for item in self.catalog}, key=str.casefold),
        )

        self.status_text = tk.StringVar(
            value=(
                f"Ready — {len(self.catalog_choices):,} item choices from "
                f"{len(self.catalog):,} unique template IDs"
            )
        )
        self.path_text = tk.StringVar(value="No save open")
        self.inventory_search = tk.StringVar()
        self.inventory_choice = tk.StringVar()
        self.inventory_weight_text = tk.StringVar(value="Max inventory weight: —")
        self.inventory_column_variables = {
            column: tk.BooleanVar(value=True)
            for column, _label, _width in INVENTORY_COLUMN_DEFINITIONS
        }
        self.catalog_search = tk.StringVar()
        self.catalog_category = tk.StringVar(value=ALL_CATEGORIES)
        self.catalog_count_text = tk.StringVar()
        self.catalog_column_variables = {
            column: tk.BooleanVar(value=True)
            for column, _label, _width in CATALOG_COLUMN_DEFINITIONS
        }
        self.catalog_sort_column = "category"
        self.catalog_sort_reverse = False
        self.quantity = tk.IntVar(value=1)
        self.stat_variables: dict[str, tk.StringVar | tk.BooleanVar] = {}
        self.stat_widgets: dict[str, ttk.Widget] = {}
        self.available_stat_keys: set[str] = set()
        self.specialization_variables: dict[int, tuple[tk.StringVar, tk.StringVar]] = {}
        self.faction_variables: dict[int, tk.StringVar] = {}
        self._update_results: queue.SimpleQueue[ReleaseInfo | None] = queue.SimpleQueue()

        self._build_ui()
        self._populate_catalog()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(300, self._start_update_check)

    def _load_brand_assets(self) -> None:
        try:
            self.app_icon_image = tk.PhotoImage(
                master=self.root,
                file=str(ASSET_DIRECTORY / "app_icon.png"),
            )
            self.root.iconphoto(True, self.app_icon_image)
        except tk.TclError:
            self.app_icon_image = None

        if os.name == "nt":
            try:
                self.root.iconbitmap(str(ASSET_DIRECTORY / "app_icon.ico"))
            except tk.TclError:
                pass

        try:
            logo = tk.PhotoImage(
                master=self.root,
                file=str(ASSET_DIRECTORY / "app_logo.png"),
            )
            self.toolbar_logo_image = logo.subsample(8, 8)
        except tk.TclError:
            self.toolbar_logo_image = None

    def _configure_theme(self) -> None:
        colors = DARK_COLORS
        self.root.configure(background=colors["background"])
        self.root.option_add("*Font", "{Segoe UI} 10")
        self.root.option_add("*Background", colors["background"])
        self.root.option_add("*Foreground", colors["text"])
        self.root.option_add("*Entry.Background", colors["field"])
        self.root.option_add("*Entry.Foreground", colors["text"])
        self.root.option_add("*Entry.InsertBackground", colors["text"])
        self.root.option_add("*selectBackground", colors["accent_dark"])
        self.root.option_add("*selectForeground", colors["text"])

        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure(
            ".",
            background=colors["background"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            darkcolor=colors["background"],
            lightcolor=colors["surface_raised"],
            troughcolor=colors["field"],
            focuscolor=colors["accent"],
        )
        style.configure("TFrame", background=colors["background"])
        style.configure("TLabel", background=colors["background"], foreground=colors["text"])
        style.configure("Muted.TLabel", background=colors["background"], foreground=colors["muted"])
        style.configure(
            "Warning.TLabel", background=colors["background"], foreground=colors["warning"]
        )
        style.configure(
            "Status.TLabel",
            background=colors["surface"],
            foreground=colors["muted"],
            bordercolor=colors["border"],
            relief=tk.FLAT,
        )
        style.configure(
            "TLabelframe",
            background=colors["surface"],
            bordercolor=colors["border"],
            darkcolor=colors["surface"],
            lightcolor=colors["surface"],
            relief=tk.SOLID,
        )
        style.configure(
            "TLabelframe.Label",
            background=colors["surface"],
            foreground=colors["accent_active"],
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "TButton",
            background=colors["surface_raised"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            focusthickness=2,
            focuscolor=colors["accent"],
            padding=(10, 6),
        )
        style.map(
            "TButton",
            background=[("pressed", colors["accent_dark"]), ("active", colors["border"])],
            foreground=[("disabled", colors["muted"])],
            bordercolor=[("focus", colors["accent"])],
        )
        style.configure(
            "Accent.TButton",
            background=colors["accent"],
            foreground=colors["field"],
            bordercolor=colors["accent"],
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", colors["surface_raised"]),
                ("pressed", colors["accent_dark"]),
                ("active", colors["accent_active"]),
            ],
            foreground=[("disabled", colors["muted"]), ("pressed", colors["text"])],
        )
        style.configure(
            "Danger.TButton",
            background=colors["danger"],
            foreground=colors["text"],
            bordercolor=colors["danger"],
        )
        style.map(
            "Danger.TButton",
            background=[("pressed", colors["danger"]), ("active", colors["danger_active"])],
        )
        for widget_style in ("TEntry", "TSpinbox", "TCombobox"):
            style.configure(
                widget_style,
                fieldbackground=colors["field"],
                foreground=colors["text"],
                insertcolor=colors["text"],
                bordercolor=colors["border"],
                lightcolor=colors["border"],
                darkcolor=colors["border"],
                padding=5,
            )
            style.map(
                widget_style,
                fieldbackground=[
                    ("disabled", colors["surface"]),
                    ("readonly", colors["surface"]),
                ],
                foreground=[("disabled", colors["muted"])],
                bordercolor=[("focus", colors["accent"])],
            )
        style.configure(
            "Treeview",
            background=colors["field"],
            fieldbackground=colors["field"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            rowheight=28,
        )
        style.map(
            "Treeview",
            background=[("selected", colors["accent_dark"])],
            foreground=[("selected", colors["text"])],
        )
        style.configure(
            "Treeview.Heading",
            background=colors["surface_raised"],
            foreground=colors["accent_active"],
            bordercolor=colors["border"],
            relief=tk.FLAT,
            padding=(6, 7),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", colors["border"])],
            foreground=[("active", colors["text"])],
        )
        style.configure(
            "TNotebook",
            background=colors["background"],
            bordercolor=colors["border"],
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=colors["surface"],
            foreground=colors["muted"],
            bordercolor=colors["border"],
            padding=(14, 8),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", colors["accent_dark"]),
                ("active", colors["surface_raised"]),
            ],
            foreground=[
                ("selected", colors["accent_active"]),
                ("active", colors["text"]),
            ],
        )
        style.configure("TCheckbutton", background=colors["surface"], foreground=colors["text"])
        style.map(
            "TCheckbutton",
            background=[("active", colors["surface"])],
            foreground=[("disabled", colors["muted"])],
            indicatorcolor=[
                ("selected", colors["accent"]),
                ("!selected", colors["field"]),
            ],
        )
        for scrollbar_style in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(
                scrollbar_style,
                background=colors["surface_raised"],
                troughcolor=colors["field"],
                bordercolor=colors["background"],
                arrowcolor=colors["muted"],
            )
            style.map(scrollbar_style, background=[("active", colors["border"])])
        style.configure("TPanedwindow", background=colors["background"], sashrelief=tk.FLAT)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(10, 10, 10, 6))
        toolbar.pack(fill=tk.X)
        if self.toolbar_logo_image is not None:
            ttk.Label(toolbar, image=self.toolbar_logo_image).pack(
                side=tk.LEFT,
                padx=(0, 10),
            )
        ttk.Button(toolbar, text="Open game.db", command=self.open_save).pack(side=tk.LEFT)
        self.save_button = ttk.Button(
            toolbar,
            text="Save Changes",
            command=self.save_changes,
            state=tk.DISABLED,
            style="Accent.TButton",
        )
        self.save_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.path_text).pack(side=tk.LEFT, padx=14)
        ttk.Label(
            toolbar,
            text=f"Version {__version__}",
            style="Muted.TLabel",
        ).pack(side=tk.RIGHT, padx=(14, 0))

        notice = ttk.Label(
            self.root,
            text=(
                "Close the game before opening or saving. "
                "All edits stay in memory until Save Changes."
            ),
            style="Warning.TLabel",
            padding=(10, 0, 10, 8),
        )
        notice.pack(fill=tk.X)

        self.navigation = ttk.Notebook(self.root)
        self.navigation.pack(fill=tk.BOTH, expand=True, padx=10)

        inventory_page = ttk.Frame(self.navigation)
        stats_page = ttk.Frame(self.navigation, padding=12)
        specializations_page = ttk.Frame(self.navigation, padding=12)
        factions_page = ttk.Frame(self.navigation, padding=12)
        self.navigation.add(inventory_page, text="Inventories")
        self.navigation.add(stats_page, text="Character Statistics")
        self.navigation.add(specializations_page, text="Specializations & Level")
        self.navigation.add(factions_page, text="Faction Reputation")

        self._build_inventory_page(inventory_page)
        self._build_stats_page(stats_page)
        self._build_specializations_page(specializations_page)
        self._build_factions_page(factions_page)

        status = ttk.Label(
            self.root,
            textvariable=self.status_text,
            anchor=tk.W,
            padding=7,
            style="Status.TLabel",
        )
        status.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_inventory_page(self, parent: ttk.Frame) -> None:
        selector = ttk.Frame(parent, padding=(0, 8, 0, 8))
        selector.pack(fill=tk.X)
        ttk.Label(selector, text="Edit inventory:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(
            selector,
            textvariable=self.inventory_weight_text,
            style="Muted.TLabel",
        ).pack(side=tk.RIGHT, padx=(8, 8))
        self.inventory_selector = ttk.Combobox(
            selector,
            textvariable=self.inventory_choice,
            state=tk.DISABLED,
            width=48,
        )
        self.inventory_selector.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        self.inventory_selector.bind("<<ComboboxSelected>>", self._select_inventory)

        panes = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)
        left = ttk.Labelframe(panes, text="Selected Inventory", padding=8)
        right = ttk.Labelframe(panes, text="Item Catalog", padding=8)
        panes.add(left, weight=1)
        panes.add(right, weight=1)

        inventory_filter = ttk.Frame(left)
        inventory_filter.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(inventory_filter, text="Filter:").pack(side=tk.LEFT)
        self.inventory_columns_button = ttk.Menubutton(inventory_filter, text="Columns")
        self.inventory_columns_button.pack(side=tk.RIGHT, padx=(8, 0))
        self.inventory_columns_menu = tk.Menu(
            self.inventory_columns_button,
            tearoff=False,
            background=DARK_COLORS["surface_raised"],
            foreground=DARK_COLORS["text"],
            activebackground=DARK_COLORS["accent_dark"],
            activeforeground=DARK_COLORS["text"],
            selectcolor=DARK_COLORS["field"],
        )
        for column, label, _width in INVENTORY_COLUMN_DEFINITIONS:
            self.inventory_columns_menu.add_checkbutton(
                label=label,
                variable=self.inventory_column_variables[column],
                command=self._apply_inventory_columns,
            )
        self.inventory_columns_button.configure(menu=self.inventory_columns_menu)
        entry = ttk.Entry(inventory_filter, textvariable=self.inventory_search)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.inventory_search.trace_add("write", lambda *_: self._populate_inventory())

        inv_actions = ttk.Frame(left)
        inv_actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        ttk.Button(inv_actions, text="Change Quantity", command=self.edit_quantity).pack(fill=tk.X)
        ttk.Button(inv_actions, text="Change Durability", command=self.edit_durability).pack(
            fill=tk.X, pady=(6, 0)
        )
        ttk.Button(
            inv_actions, text="Remove", command=self.remove_item, style="Danger.TButton"
        ).pack(fill=tk.X, pady=(6, 0))

        inv_columns = tuple(column for column, _label, _width in INVENTORY_COLUMN_DEFINITIONS)
        inventory_table = ttk.Frame(left)
        inventory_table.pack(fill=tk.BOTH, expand=True)
        inventory_table.columnconfigure(0, weight=1)
        inventory_table.rowconfigure(0, weight=1)
        self.inventory_tree = ttk.Treeview(inventory_table, columns=inv_columns, show="headings")
        for column, label, width in INVENTORY_COLUMN_DEFINITIONS:
            self.inventory_tree.heading(column, text=label)
            self.inventory_tree.column(column, width=width, minwidth=width, stretch=False)
        inv_vertical_scroll = ttk.Scrollbar(
            inventory_table, orient=tk.VERTICAL, command=self.inventory_tree.yview
        )
        self.inventory_horizontal_scroll = ttk.Scrollbar(
            inventory_table, orient=tk.HORIZONTAL, command=self.inventory_tree.xview
        )
        self.inventory_tree.configure(
            yscrollcommand=inv_vertical_scroll.set,
            xscrollcommand=self.inventory_horizontal_scroll.set,
        )
        self.inventory_tree.grid(row=0, column=0, sticky="nsew")
        inv_vertical_scroll.grid(row=0, column=1, sticky="ns")
        self.inventory_horizontal_scroll.grid(row=1, column=0, sticky="ew")
        self.inventory_tree.bind("<Double-1>", lambda _event: self.edit_quantity())
        self._apply_inventory_columns()

        catalog_filter = ttk.Frame(right)
        catalog_filter.pack(fill=tk.X, pady=(0, 6))
        search_row = ttk.Frame(catalog_filter)
        search_row.pack(fill=tk.X)
        ttk.Label(search_row, text="Search:").pack(side=tk.LEFT)
        catalog_entry = ttk.Entry(search_row, textvariable=self.catalog_search)
        catalog_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.catalog_search.trace_add("write", lambda *_: self._populate_catalog())

        category_row = ttk.Frame(catalog_filter)
        category_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(category_row, text="Category:").pack(side=tk.LEFT)
        category_box = ttk.Combobox(
            category_row,
            textvariable=self.catalog_category,
            values=self.catalog_categories,
            state="readonly",
            width=25,
        )
        category_box.pack(side=tk.LEFT, padx=(6, 10))
        category_box.bind("<<ComboboxSelected>>", lambda _event: self._populate_catalog())
        self.catalog_columns_button = ttk.Menubutton(category_row, text="Columns")
        self.catalog_columns_button.pack(side=tk.LEFT)
        self.catalog_columns_menu = tk.Menu(
            self.catalog_columns_button,
            tearoff=False,
            background=DARK_COLORS["surface_raised"],
            foreground=DARK_COLORS["text"],
            activebackground=DARK_COLORS["accent_dark"],
            activeforeground=DARK_COLORS["text"],
            selectcolor=DARK_COLORS["field"],
        )
        for column, label, _width in CATALOG_COLUMN_DEFINITIONS:
            self.catalog_columns_menu.add_checkbutton(
                label=label,
                variable=self.catalog_column_variables[column],
                command=self._apply_catalog_columns,
            )
        self.catalog_columns_button.configure(menu=self.catalog_columns_menu)
        ttk.Label(category_row, textvariable=self.catalog_count_text, style="Muted.TLabel").pack(
            side=tk.RIGHT
        )

        add_actions = ttk.Frame(right)
        add_actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        ttk.Label(add_actions, text="Quantity:").pack(anchor=tk.W)
        ttk.Spinbox(add_actions, from_=1, to=1_000_000, textvariable=self.quantity, width=9).pack(
            fill=tk.X, pady=(4, 6)
        )
        ttk.Button(
            add_actions,
            text="Add Selected Item",
            command=self.add_item,
            style="Accent.TButton",
        ).pack(fill=tk.X)

        cat_columns = tuple(column for column, _label, _width in CATALOG_COLUMN_DEFINITIONS)
        catalog_table = ttk.Frame(right)
        catalog_table.pack(fill=tk.BOTH, expand=True)
        catalog_table.columnconfigure(0, weight=1)
        catalog_table.rowconfigure(0, weight=1)
        self.catalog_tree = ttk.Treeview(catalog_table, columns=cat_columns, show="headings")
        self.catalog_heading_labels: dict[str, str] = {}
        for column, label, width in CATALOG_COLUMN_DEFINITIONS:
            self.catalog_heading_labels[column] = label
            self.catalog_tree.heading(
                column,
                text=label,
                command=lambda selected=column: self._sort_catalog(selected),
            )
            self.catalog_tree.column(column, width=width, minwidth=width, stretch=False)
        cat_vertical_scroll = ttk.Scrollbar(
            catalog_table, orient=tk.VERTICAL, command=self.catalog_tree.yview
        )
        self.catalog_horizontal_scroll = ttk.Scrollbar(
            catalog_table, orient=tk.HORIZONTAL, command=self.catalog_tree.xview
        )
        self.catalog_tree.configure(
            yscrollcommand=cat_vertical_scroll.set,
            xscrollcommand=self.catalog_horizontal_scroll.set,
        )
        self.catalog_tree.grid(row=0, column=0, sticky="nsew")
        cat_vertical_scroll.grid(row=0, column=1, sticky="ns")
        self.catalog_horizontal_scroll.grid(row=1, column=0, sticky="ew")
        self.catalog_tree.bind("<Double-1>", lambda _event: self.add_item())
        self._apply_catalog_columns()

    def _apply_catalog_columns(self) -> None:
        selections = {
            column: variable.get() for column, variable in self.catalog_column_variables.items()
        }
        visible = visible_catalog_columns(selections)
        self.catalog_tree.configure(displaycolumns=visible)
        self.catalog_columns_button.configure(
            text=f"Columns ({len(visible)}/{len(CATALOG_COLUMN_DEFINITIONS)})"
        )

    def _apply_inventory_columns(self) -> None:
        selections = {
            column: variable.get() for column, variable in self.inventory_column_variables.items()
        }
        visible = visible_inventory_columns(selections)
        self.inventory_tree.configure(displaycolumns=visible)
        self.inventory_columns_button.configure(
            text=f"Columns ({len(visible)}/{len(INVENTORY_COLUMN_DEFINITIONS)})"
        )

    def _build_stats_page(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text=(
                "These values come from the player pawn/controller actor data. "
                "Unavailable fields are disabled for compatibility with other save versions."
            ),
            wraplength=950,
        ).pack(anchor=tk.W, pady=(0, 10))

        content = ttk.Frame(parent)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        groups: dict[str, ttk.Labelframe] = {}
        group_order: list[str] = []
        for definition in CHARACTER_STATS:
            if definition.group not in groups:
                group_order.append(definition.group)
                frame = ttk.Labelframe(content, text=definition.group, padding=10)
                index = len(group_order) - 1
                frame.grid(row=index // 2, column=index % 2, sticky="nsew", padx=5, pady=5)
                frame.columnconfigure(1, weight=1)
                groups[definition.group] = frame
            frame = groups[definition.group]
            row = len(frame.grid_slaves()) // 2
            ttk.Label(frame, text=definition.label).grid(row=row, column=0, sticky=tk.W, pady=3)
            if definition.kind == "boolean":
                variable: tk.StringVar | tk.BooleanVar = tk.BooleanVar(value=False)
                widget: ttk.Widget = ttk.Checkbutton(frame, variable=variable)
            else:
                variable = tk.StringVar()
                widget = ttk.Entry(frame, textvariable=variable, width=18)
            widget.grid(row=row, column=1, sticky=tk.EW, padx=(12, 0), pady=3)
            self.stat_variables[definition.key] = variable
            self.stat_widgets[definition.key] = widget

        ttk.Button(
            parent,
            text="Apply Character Statistics",
            command=self.apply_stats,
            style="Accent.TButton",
        ).pack(anchor=tk.E, pady=(10, 0))

    def _build_specializations_page(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text=(
                "The save persists XP and level separately for each specialization. "
                "The game derives the overall player level; there is no independent player-level "
                "field in game.db. Keep XP and level consistent with the progression you want."
            ),
            wraplength=950,
        ).pack(anchor=tk.W, pady=(0, 14))
        table = ttk.Labelframe(parent, text="Specialization tracks", padding=12)
        table.pack(fill=tk.X)
        ttk.Label(table, text="Track").grid(row=0, column=0, sticky=tk.W, padx=(0, 30))
        ttk.Label(table, text="XP amount").grid(row=0, column=1, sticky=tk.W)
        ttk.Label(table, text="Level").grid(row=0, column=2, sticky=tk.W, padx=(12, 0))
        for row, (track_type, name) in enumerate(SPECIALIZATION_TRACKS, start=1):
            xp = tk.StringVar(value="0")
            level = tk.StringVar(value="0")
            self.specialization_variables[track_type] = (xp, level)
            ttk.Label(table, text=name).grid(row=row, column=0, sticky=tk.W, pady=5)
            ttk.Entry(table, textvariable=xp, width=18).grid(row=row, column=1, pady=5)
            ttk.Entry(table, textvariable=level, width=18).grid(
                row=row, column=2, padx=(12, 0), pady=5
            )
        ttk.Button(
            parent,
            text="Apply Specializations",
            command=self.apply_specializations,
            style="Accent.TButton",
        ).pack(anchor=tk.E, pady=(12, 0))

    def _build_factions_page(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text=(
                "Edit persisted reputation points. Faction rank/level is calculated by the game "
                "from these points and is not stored as a separate field."
            ),
            wraplength=950,
        ).pack(anchor=tk.W, pady=(0, 14))
        self.faction_rows = ttk.Labelframe(parent, text="Faction reputation", padding=12)
        self.faction_rows.pack(fill=tk.X)
        ttk.Label(self.faction_rows, text="Open a save to load factions.").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Button(
            parent,
            text="Apply Faction Reputation",
            command=self.apply_factions,
            style="Accent.TButton",
        ).pack(anchor=tk.E, pady=(12, 0))

    def _suggested_save_dir(self) -> Path:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidate = local / "DuneSandbox" / "Saved" / "Cloud" / "PlayerClientStorage" / "FLS_retail"
        return candidate if candidate.exists() else Path.home()

    def _discard_allowed(self) -> bool:
        return (
            not self.save
            or not self.save.dirty
            or messagebox.askyesno(
                "Discard unsaved changes?", "Opening another save will discard the current edits."
            )
        )

    def open_save(self) -> None:
        if not self._discard_allowed():
            return
        filename = filedialog.askopenfilename(
            title="Select Dune: Awakening game.db",
            initialdir=self._suggested_save_dir(),
            filetypes=(("Dune save", "*.db"), ("All files", "*.*")),
        )
        if not filename:
            return
        try:
            opened = DuneSave.open(filename)
            players = opened.players()
            if not players:
                raise SaveError("No player record was found in this save")
            carried = opened.carried_inventories(players[0].row_id)
            vehicles = opened.vehicle_inventories(players[0].row_id)
            inventories = [*carried, *vehicles]
            if not inventories:
                raise SaveError("No editable item-storage inventory was found for the player")
        except (OSError, SaveError, ValueError) as exc:
            messagebox.showerror("Could not open save", str(exc))
            return

        if self.save:
            self.save.close()
        self.save = opened
        self.player_row_id = players[0].row_id
        self._set_inventory_options(inventories)
        self.path_text.set(str(opened.path))
        self.save_button.configure(state=tk.NORMAL)
        self._populate_stats()
        self._populate_specializations()
        self._populate_factions()
        self.status_text.set(
            f"Opened {opened.path.name} — player {players[0].character_name} — "
            f"{len(carried)} carried and {len(vehicles)} vehicle storage inventories"
        )

    @staticmethod
    def _inventory_label(inventory: Inventory) -> str:
        owner = inventory.owner_kind
        if owner not in {"Character", "Controller"} and inventory.owner_id is not None:
            owner = f"{owner} #{inventory.owner_id}"
        capacity = (
            "unlimited slots"
            if inventory.max_item_count is None or inventory.max_item_count < 0
            else f"{inventory.max_item_count} slots"
        )
        return f"{owner} — {capacity} (inventory {inventory.inventory_id})"

    def _set_inventory_options(self, inventories: list[Inventory]) -> None:
        self.inventories = inventories
        self.inventory_choices = {
            self._inventory_label(inventory): inventory for inventory in inventories
        }
        labels = tuple(self.inventory_choices)
        self.inventory_selector.configure(values=labels, state="readonly")
        self.inventory_choice.set(labels[0])
        self.inventory = self.inventory_choices[labels[0]]
        self._populate_inventory()

    def _select_inventory(self, _event: tk.Event | None = None) -> None:
        inventory = self.inventory_choices.get(self.inventory_choice.get())
        if inventory is None:
            return
        self.inventory = inventory
        self._populate_inventory()
        self.status_text.set(f"Editing {self._inventory_label(inventory)}")

    def _populate_stats(self) -> None:
        if not self.save or self.player_row_id is None:
            return
        values = self.save.character_stats(self.player_row_id)
        self.available_stat_keys.clear()
        for definition in CHARACTER_STATS:
            value = values.get(definition.key)
            variable = self.stat_variables[definition.key]
            widget = self.stat_widgets[definition.key]
            if value is None:
                if isinstance(variable, tk.BooleanVar):
                    variable.set(False)
                else:
                    variable.set("Not stored in this save")
                widget.configure(state=tk.DISABLED)
                continue
            self.available_stat_keys.add(definition.key)
            widget.configure(state=tk.NORMAL)
            if isinstance(variable, tk.BooleanVar):
                variable.set(bool(value))
            elif isinstance(value, float):
                variable.set(f"{value:g}")
            else:
                variable.set(str(value))

    def _populate_specializations(self) -> None:
        if not self.save or self.player_row_id is None:
            return
        for specialization in self.save.specializations(self.player_row_id):
            xp, level = self.specialization_variables[specialization.track_type]
            xp.set(str(specialization.xp_amount))
            level.set(f"{specialization.level:g}")

    def _populate_factions(self) -> None:
        for child in self.faction_rows.winfo_children():
            child.destroy()
        self.faction_variables.clear()
        if not self.save or self.player_row_id is None:
            ttk.Label(self.faction_rows, text="Open a save to load factions.").grid(row=0, column=0)
            return
        ttk.Label(self.faction_rows, text="Faction").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(self.faction_rows, text="Reputation points").grid(
            row=0, column=1, sticky=tk.W, padx=(30, 0)
        )
        for row, faction in enumerate(self.save.faction_reputations(self.player_row_id), start=1):
            variable = tk.StringVar(value=str(faction.reputation_amount))
            self.faction_variables[faction.faction_id] = variable
            ttk.Label(self.faction_rows, text=faction.name).grid(
                row=row, column=0, sticky=tk.W, pady=5
            )
            ttk.Entry(self.faction_rows, textvariable=variable, width=20).grid(
                row=row, column=1, padx=(30, 0), pady=5
            )

    def apply_stats(self) -> None:
        if not self.save or self.player_row_id is None:
            messagebox.showinfo("Open a save", "Open a game.db file first.")
            return
        definitions = {definition.key: definition for definition in CHARACTER_STATS}
        updates: dict[str, int | float | bool] = {}
        try:
            for key in self.available_stat_keys:
                definition = definitions[key]
                raw = self.stat_variables[key].get()
                if definition.kind == "boolean":
                    updates[key] = bool(raw)
                elif definition.kind == "integer":
                    updates[key] = int(str(raw))
                else:
                    updates[key] = float(str(raw))
            self.save.update_character_stats(self.player_row_id, updates)
        except (SaveError, TypeError, ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid character statistic", str(exc))
            return
        self._populate_stats()
        self.status_text.set("Applied character statistics in memory (not saved yet)")

    def apply_specializations(self) -> None:
        if not self.save or self.player_row_id is None:
            messagebox.showinfo("Open a save", "Open a game.db file first.")
            return
        try:
            updates = {
                track_type: (int(xp.get()), float(level.get()))
                for track_type, (xp, level) in self.specialization_variables.items()
            }
            self.save.update_specializations(self.player_row_id, updates)
        except (SaveError, TypeError, ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid specialization", str(exc))
            return
        self._populate_specializations()
        self.status_text.set("Applied specialization XP and levels in memory (not saved yet)")

    def apply_factions(self) -> None:
        if not self.save or self.player_row_id is None:
            messagebox.showinfo("Open a save", "Open a game.db file first.")
            return
        try:
            updates = {
                faction_id: int(variable.get())
                for faction_id, variable in self.faction_variables.items()
            }
            self.save.update_faction_reputations(self.player_row_id, updates)
        except (SaveError, TypeError, ValueError, tk.TclError) as exc:
            messagebox.showerror("Invalid faction reputation", str(exc))
            return
        self._populate_factions()
        self.status_text.set("Applied faction reputation in memory (not saved yet)")

    def _populate_inventory(self) -> None:
        for row_id in self.inventory_tree.get_children():
            self.inventory_tree.delete(row_id)
        self.inventory_rows.clear()
        if not self.save or not self.inventory:
            self.inventory_weight_text.set("Max inventory weight: —")
            return
        records = self.save.inventory_items(self.inventory.inventory_id)
        self.inventory_weight_text.set(
            inventory_weight_summary(self.inventory, records, self.catalog_by_id)
        )
        needle = self.inventory_search.get().strip().casefold()
        for record in records:
            catalog_item = catalog_item_for_template(self.catalog_by_id, record.template_id)
            name = catalog_item.display_name if catalog_item else record.template_id
            if needle and needle not in f"{name} {record.template_id}".casefold():
                continue
            category = catalog_item.category if catalog_item else ""
            weight = catalog_item.item_size if catalog_item else None
            row_id = self.inventory_tree.insert(
                "",
                tk.END,
                values=(
                    record.position_index,
                    name,
                    record.template_id,
                    category,
                    record.stack_size,
                    record.quality_level,
                    durability_summary(record, catalog_item),
                    "" if weight is None else _display_number(weight),
                    "" if weight is None else _display_number(weight * record.stack_size),
                ),
            )
            self.inventory_rows[row_id] = record

    def _populate_catalog(self) -> None:
        for row_id in self.catalog_tree.get_children():
            self.catalog_tree.delete(row_id)
        self.catalog_rows.clear()
        needle = self.catalog_search.get().strip().casefold()
        selected_category = self.catalog_category.get()
        matches = [
            choice
            for choice in self.catalog_choices
            if (not needle or needle in choice.search_text)
            and (selected_category == ALL_CATEGORIES or choice.item.category == selected_category)
        ]
        key_functions = {
            "name": lambda choice: (
                choice.display_name.casefold(),
                choice.item.template_id.casefold(),
            ),
            "template": lambda choice: (
                choice.item.template_id.casefold(),
                choice.quality_level,
            ),
            "category": lambda choice: (
                choice.item.category.casefold(),
                choice.display_name.casefold(),
            ),
            "grade": lambda choice: (
                choice.quality_level,
                choice.item.display_name.casefold(),
            ),
            "stack": lambda choice: (
                choice.item.max_stack_size,
                choice.display_name.casefold(),
            ),
            "weight": lambda choice: (
                choice.item.item_size,
                choice.display_name.casefold(),
            ),
        }
        matches.sort(
            key=key_functions[self.catalog_sort_column],
            reverse=self.catalog_sort_reverse,
        )
        for choice in matches:
            item = choice.item
            flags = []
            if item.status != "current":
                flags.append(item.status)
            if not item.enabled:
                flags.append("disabled")
            category = item.category + (f" ({', '.join(flags)})" if flags else "")
            row_id = self.catalog_tree.insert(
                "",
                tk.END,
                values=(
                    choice.display_name,
                    item.template_id,
                    category,
                    choice.quality_level or "",
                    item.max_stack_size,
                    _display_number(item.item_size),
                ),
            )
            self.catalog_rows[row_id] = choice
        self.catalog_count_text.set(f"Showing {len(matches):,}")
        direction = "▼" if self.catalog_sort_reverse else "▲"
        for column, label in self.catalog_heading_labels.items():
            suffix = f" {direction}" if column == self.catalog_sort_column else ""
            self.catalog_tree.heading(column, text=label + suffix)

    def _sort_catalog(self, column: str) -> None:
        if column == self.catalog_sort_column:
            self.catalog_sort_reverse = not self.catalog_sort_reverse
        else:
            self.catalog_sort_column = column
            self.catalog_sort_reverse = False
        self._populate_catalog()

    def _selected_inventory_item(self) -> InventoryItem | None:
        selected = self.inventory_tree.selection()
        return self.inventory_rows.get(selected[0]) if selected else None

    def _selected_catalog_choice(self) -> CatalogChoice | None:
        selected = self.catalog_tree.selection()
        return self.catalog_rows.get(selected[0]) if selected else None

    def _projected_volume(
        self,
        template_id: str,
        quantity: int,
        replacing: InventoryItem | None = None,
    ) -> float:
        if not self.save or not self.inventory:
            return 0.0
        total = 0.0
        for record in self.save.inventory_items(self.inventory.inventory_id):
            if replacing and record.item_id == replacing.item_id:
                continue
            catalog_item = catalog_item_for_template(self.catalog_by_id, record.template_id)
            if catalog_item:
                total += catalog_item.item_size * record.stack_size
        added = catalog_item_for_template(self.catalog_by_id, template_id)
        return total + ((added.item_size * quantity) if added else 0.0)

    def _volume_allowed(
        self,
        template_id: str,
        quantity: int,
        replacing: InventoryItem | None = None,
    ) -> bool:
        if not self.inventory or self.inventory.max_item_volume is None:
            return True
        maximum = self.inventory.max_item_volume
        if maximum < 0:
            return True
        projected = self._projected_volume(template_id, quantity, replacing)
        if projected <= maximum:
            return True
        messagebox.showerror(
            "Inventory volume exceeded",
            f"This edit would use approximately {projected:g} of {maximum:g} inventory volume.",
        )
        return False

    def add_item(self) -> None:
        if not self.save or not self.inventory:
            messagebox.showinfo("Open a save", "Open a game.db file first.")
            return
        choice = self._selected_catalog_choice()
        if not choice:
            messagebox.showinfo("Select an item", "Select an item from the catalog first.")
            return
        item = choice.item
        grade = choice.quality_level
        try:
            quantity = int(self.quantity.get())
        except (TypeError, ValueError, tk.TclError):
            messagebox.showerror("Invalid quantity", "Quantity must be a positive whole number.")
            return
        if quantity <= 0 or quantity > item.max_stack_size:
            messagebox.showerror(
                "Invalid quantity",
                f"{item.display_name} supports stacks from 1 to {item.max_stack_size}.",
            )
            return
        if not self._volume_allowed(item.template_id, quantity):
            return
        if (item.status != "current" or not item.enabled) and not messagebox.askyesno(
            "Potentially unsafe item",
            f"This catalog entry is {item.status}"
            f"{' and disabled' if not item.enabled else ''}. Add it anyway?",
        ):
            return
        stats = self.save.stats_for_template(item.template_id) or default_item_stats(item)
        try:
            self.save.add_item(
                self.inventory.inventory_id,
                item.template_id,
                quantity,
                stats,
                quality_level=grade,
            )
        except SaveError as exc:
            messagebox.showerror("Could not add item", str(exc))
            return
        self._populate_inventory()
        grade_text = f", Grade {grade}" if grade else ""
        self.status_text.set(f"Added {quantity} × {item.display_name}{grade_text} (not saved yet)")

    def edit_quantity(self) -> None:
        if not self.save:
            return
        record = self._selected_inventory_item()
        if not record:
            messagebox.showinfo("Select an item", "Select an inventory stack first.")
            return
        catalog_item = catalog_item_for_template(self.catalog_by_id, record.template_id)
        maximum = catalog_item.max_stack_size if catalog_item else 1_000_000
        value = simpledialog.askinteger(
            "Change quantity",
            f"New quantity for {record.template_id} (maximum {maximum}):",
            initialvalue=record.stack_size,
            minvalue=1,
            maxvalue=maximum,
            parent=self.root,
        )
        if value is None:
            return
        if not self._volume_allowed(record.template_id, value, replacing=record):
            return
        try:
            self.save.update_stack_size(record.item_id, value)
        except SaveError as exc:
            messagebox.showerror("Could not change quantity", str(exc))
            return
        self._populate_inventory()
        self.status_text.set(f"Changed {record.template_id} quantity to {value} (not saved yet)")

    def edit_durability(self) -> None:
        if not self.save:
            return
        record = self._selected_inventory_item()
        if not record:
            messagebox.showinfo("Select an item", "Select an inventory item first.")
            return
        catalog_item = catalog_item_for_template(self.catalog_by_id, record.template_id)
        maximum = effective_max_durability(record, catalog_item)
        if maximum is None:
            messagebox.showinfo(
                "Durability unavailable",
                "This item does not have a verified maximum durability.",
            )
            return
        value = simpledialog.askfloat(
            "Change durability",
            f"Current durability for {record.template_id} (maximum {maximum:g}):",
            initialvalue=record.durability if record.durability is not None else maximum,
            minvalue=0.0,
            maxvalue=maximum,
            parent=self.root,
        )
        if value is None:
            return
        try:
            self.save.update_item_durability(record.item_id, value, maximum)
        except SaveError as exc:
            messagebox.showerror("Could not change durability", str(exc))
            return
        self._populate_inventory()
        self.status_text.set(
            f"Changed {record.template_id} durability to {_display_number(value)}/"
            f"{_display_number(maximum)} (not saved yet)"
        )

    def remove_item(self) -> None:
        if not self.save:
            return
        record = self._selected_inventory_item()
        if not record:
            messagebox.showinfo("Select an item", "Select an inventory stack first.")
            return
        if not messagebox.askyesno(
            "Remove item?",
            f"Remove the entire stack of {record.template_id}?\n\n"
            "This remains reversible until Save.",
        ):
            return
        try:
            self.save.remove_item(record.item_id)
        except SaveError as exc:
            messagebox.showerror("Could not remove item", str(exc))
            return
        self._populate_inventory()
        self.status_text.set(f"Removed {record.template_id} (not saved yet)")

    def save_changes(self) -> None:
        if not self.save:
            return
        if not self.save.dirty:
            messagebox.showinfo("No changes", "There are no unsaved changes.")
            return
        if not messagebox.askyesno(
            "Save changes?",
            "Confirm Dune: Awakening is fully closed. A timestamped backup will be created first.",
        ):
            return
        try:
            backup = self.save.save()
        except (OSError, SaveError) as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        detail = f"\nBackup: {backup}" if backup else ""
        messagebox.showinfo(
            "Save complete", f"The edited save passed validation and was written.{detail}"
        )
        self.status_text.set("Saved and validated successfully")

    def _on_close(self) -> None:
        if (
            self.save
            and self.save.dirty
            and not messagebox.askyesno(
                "Discard unsaved changes?", "Close without saving the current edits?"
            )
        ):
            return
        if self.save:
            self.save.close()
        self.root.destroy()

    def _start_update_check(self) -> None:
        thread = threading.Thread(target=self._fetch_update, daemon=True)
        thread.start()
        self.root.after(100, self._poll_update_check)

    def _fetch_update(self) -> None:
        self._update_results.put(check_for_update(__version__))

    def _poll_update_check(self) -> None:
        try:
            release = self._update_results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_update_check)
            return
        if release is not None:
            self._prompt_for_update(release)

    def _prompt_for_update(self, release: ReleaseInfo) -> None:
        release_name = release.name or release.tag_name
        if messagebox.askyesno(
            "Update available",
            f"{release_name} is available.\n\n"
            f"Installed version: {__version__}\n"
            f"Available version: {release.tag_name}\n\n"
            "Open GitHub Releases to download and install it?",
            parent=self.root,
        ):
            webbrowser.open(RELEASES_PAGE_URL, new=2)


def main() -> None:
    root = tk.Tk()
    try:
        SaveEditorApp(root)
    except (OSError, ValueError) as exc:
        root.withdraw()
        messagebox.showerror("Startup failed", str(exc))
        root.destroy()
        raise SystemExit(1) from exc
    root.mainloop()


if __name__ == "__main__":
    main()
