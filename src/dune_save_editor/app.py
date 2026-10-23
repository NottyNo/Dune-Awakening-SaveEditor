from __future__ import annotations

import os
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from dune_save_editor.catalog import CatalogItem, default_item_stats, load_catalog
from dune_save_editor.save_file import DuneSave, Inventory, InventoryItem, SaveError
from dune_save_editor.stats import CHARACTER_STATS, SPECIALIZATION_TRACKS

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

ALL_CATEGORIES = "All categories"


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
        self.root.title("Dune: Awakening Save Editor")
        self.root.geometry("1220x760")
        self.root.minsize(980, 620)
        self._configure_theme()

        self.save: DuneSave | None = None
        self.player_row_id: int | None = None
        self.inventory: Inventory | None = None
        self.inventory_rows: dict[str, InventoryItem] = {}
        self.catalog = load_catalog()
        self.catalog_by_id = {item.template_id: item for item in self.catalog}
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
        self.catalog_search = tk.StringVar()
        self.catalog_category = tk.StringVar(value=ALL_CATEGORIES)
        self.catalog_count_text = tk.StringVar()
        self.catalog_sort_column = "category"
        self.catalog_sort_reverse = False
        self.quantity = tk.IntVar(value=1)
        self.stat_variables: dict[str, tk.StringVar | tk.BooleanVar] = {}
        self.stat_widgets: dict[str, ttk.Widget] = {}
        self.available_stat_keys: set[str] = set()
        self.specialization_variables: dict[int, tuple[tk.StringVar, tk.StringVar]] = {}
        self.faction_variables: dict[int, tk.StringVar] = {}

        self._build_ui()
        self._populate_catalog()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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
        style.configure(
            "Vertical.TScrollbar",
            background=colors["surface_raised"],
            troughcolor=colors["field"],
            bordercolor=colors["background"],
            arrowcolor=colors["muted"],
        )
        style.map("Vertical.TScrollbar", background=[("active", colors["border"])])
        style.configure("TPanedwindow", background=colors["background"], sashrelief=tk.FLAT)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(10, 10, 10, 6))
        toolbar.pack(fill=tk.X)
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
        self.navigation.add(inventory_page, text="Inventory")
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
        panes = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)
        left = ttk.Labelframe(panes, text="Carried Inventory", padding=8)
        right = ttk.Labelframe(panes, text="Item Catalog", padding=8)
        panes.add(left, weight=1)
        panes.add(right, weight=1)

        inventory_filter = ttk.Frame(left)
        inventory_filter.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(inventory_filter, text="Filter:").pack(side=tk.LEFT)
        entry = ttk.Entry(inventory_filter, textvariable=self.inventory_search)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.inventory_search.trace_add("write", lambda *_: self._populate_inventory())

        inv_actions = ttk.Frame(left)
        inv_actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        ttk.Button(inv_actions, text="Change Quantity", command=self.edit_quantity).pack(fill=tk.X)
        ttk.Button(
            inv_actions, text="Remove", command=self.remove_item, style="Danger.TButton"
        ).pack(fill=tk.X, pady=(6, 0))

        inv_columns = ("slot", "name", "template", "quantity", "quality", "durability")
        self.inventory_tree = ttk.Treeview(left, columns=inv_columns, show="headings")
        headings = {
            "slot": ("Slot", 48),
            "name": ("Name", 170),
            "template": ("Template ID", 150),
            "quantity": ("Qty", 55),
            "quality": ("Grade", 58),
            "durability": ("Durability", 75),
        }
        for column, (label, width) in headings.items():
            self.inventory_tree.heading(column, text=label)
            self.inventory_tree.column(
                column, width=width, minwidth=42, stretch=column in {"name", "template"}
            )
        inv_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.inventory_tree.yview)
        self.inventory_tree.configure(yscrollcommand=inv_scroll.set)
        self.inventory_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inv_scroll.pack(side=tk.LEFT, fill=tk.Y)
        self.inventory_tree.bind("<Double-1>", lambda _event: self.edit_quantity())

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

        cat_columns = ("name", "template", "category", "grade", "stack")
        self.catalog_tree = ttk.Treeview(right, columns=cat_columns, show="headings")
        self.catalog_heading_labels: dict[str, str] = {}
        for column, label, width in (
            ("name", "Name", 190),
            ("template", "Template ID", 170),
            ("category", "Category", 120),
            ("grade", "Grade", 52),
            ("stack", "Max", 50),
        ):
            self.catalog_heading_labels[column] = label
            self.catalog_tree.heading(
                column,
                text=label,
                command=lambda selected=column: self._sort_catalog(selected),
            )
            self.catalog_tree.column(
                column, width=width, minwidth=42, stretch=column in {"name", "template"}
            )
        cat_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=cat_scroll.set)
        self.catalog_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cat_scroll.pack(side=tk.LEFT, fill=tk.Y)
        self.catalog_tree.bind("<Double-1>", lambda _event: self.add_item())

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
            inventories = opened.carried_inventories(players[0].row_id)
            if not inventories:
                raise SaveError("No carried inventory (type 0) was found for the player")
        except (OSError, SaveError, ValueError) as exc:
            messagebox.showerror("Could not open save", str(exc))
            return

        if self.save:
            self.save.close()
        self.save = opened
        self.player_row_id = players[0].row_id
        self.inventory = inventories[0]
        self.path_text.set(str(opened.path))
        self.save_button.configure(state=tk.NORMAL)
        self._populate_inventory()
        self._populate_stats()
        self._populate_specializations()
        self._populate_factions()
        self.status_text.set(
            f"Opened {opened.path.name} — player {players[0].character_name} — "
            f"inventory {self.inventory.inventory_id}"
        )

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
            return
        needle = self.inventory_search.get().strip().casefold()
        for record in self.save.inventory_items(self.inventory.inventory_id):
            catalog_item = self.catalog_by_id.get(record.template_id)
            name = catalog_item.display_name if catalog_item else record.template_id
            if needle and needle not in f"{name} {record.template_id}".casefold():
                continue
            durability = "" if record.durability is None else f"{record.durability:g}"
            row_id = self.inventory_tree.insert(
                "",
                tk.END,
                values=(
                    record.position_index,
                    name,
                    record.template_id,
                    record.stack_size,
                    record.quality_level,
                    durability,
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
            catalog_item = self.catalog_by_id.get(record.template_id)
            if catalog_item:
                total += catalog_item.item_size * record.stack_size
        added = self.catalog_by_id.get(template_id)
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
        catalog_item = self.catalog_by_id.get(record.template_id)
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
