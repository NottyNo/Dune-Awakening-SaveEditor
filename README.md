# Dune: Awakening Save Editor

![Dune: Awakening Save Editor logo](src/dune_save_editor/assets/app_logo.png)

A Python GUI for inspecting and editing a Dune: Awakening PC solo save. It
understands the game's eight-byte wrapper, decompresses the zlib payload in memory,
validates the SQLite database, and writes it back.

**Release status:** Alpha 2 (`1.0.0a2`). Save-format support is experimental, and no
prebuilt Windows executable is included yet.
## Run

Python 3.11 or newer with Tk support is required.

```
python run_editor.py
```

After installing the package, the equivalent command is:

```
python -m dune_save_editor
```

Close Dune: Awakening before opening or saving `game.db`. The navigation tabs provide:

- carried and owned-vehicle inventory item add, quantity change, and removal;
- category filtering/sorting and separate Grade 1–5 choices for gradeable items;
- character health, hydration, heat, spice, Eyes of Ibad, and intel-point values;
- XP and levels for all five specialization tracks; and
- Atreides, Harkonnen, and Smuggler reputation points.

The game derives overall player level from specialization progression and faction rank
from reputation; those derived values are not independent fields in `game.db`. The
editor works in memory until Save is pressed. Saving creates a timestamped backup
inside a `Save Editor Backups` folder in the save directory and refuses to overwrite a
file that changed after it was opened.

Use the inventory selector to switch between the character and owned vehicles. Only
vehicles with an installed, positive-capacity storage inventory are shown; vehicles
without usable cargo storage, including the Carrier Ornithopter, are omitted. The
selected inventory shows its persisted maximum weight and the current estimated load
calculated from bundled catalog item sizes.

The selected-inventory Columns menu independently controls Slot, Name, Template ID,
Category, Quantity, Grade, Durability, Unit Weight, and Stack Weight. Durability is shown
as `CurrentDurability/MaxDurability`; use Change Durability to edit the current value up
to the item's verified stored or catalog maximum. Both item tables keep their configured
column widths and provide horizontal scrollbars instead of compressing every field.

The current application version is shown in the title bar and toolbar. On launch, the
editor checks this repository's published GitHub Releases, including alpha and beta
prereleases. It does not react to ordinary commits, draft releases, or tags without a
release. If a newer version exists, a Windows Yes/No dialog offers to open the Releases
page; choosing No continues normally. Offline checks and GitHub errors are ignored.

The editor includes a matching toolbar logo, window/taskbar icon, and multi-resolution
Windows icon at `src/dune_save_editor/assets/app_icon.ico` for future executable builds.

Global harvesting, XP, and other single-player multipliers are not edited yet. They
were not found as global settings in the inspected `game.db`; similarly named fields
inside that database belong to individual crafting jobs or loot records and are unsafe
to treat as world settings.

> This is an experimental editor for an undocumented format. Test restored saves
> on a copy first.

## How to use

1. Open the program
2. Select your save file by clicking the top left button and choosing the game.db file in the correct save folder. \
**Savepath:** `C:\Users\<User>\AppData\Local\DuneSandbox\Saved\Cloud\PlayerClientStorage\FLS_retail\`
3. Make your changes
4. Click Apply (if needed) and Save your changes
5. Enjoy! :D

## Item catalog

Users do **not** need FModel or any exported datatables to use the editor. A generated
catalog is bundled with every source release, so item search and adding items work
immediately after downloading the repository or a future executable.

Use the catalog's Columns menu to show or hide Name, Template ID, Category, Grade,
Max Stack, and Weight independently. Weight comes from the generated catalog's item-size
field, and category filtering remains available when the Category column is hidden.

The current catalog contains 6,216 inventory-eligible template IDs gathered from the
complete `Systems/Items` export. Ability and gadget definitions—including vehicle
abilities—are excluded because they are unlocked through game systems and cannot be used
as inventory items. Use the category selector or click a catalog column heading to sort
the list. Items covered by the game's quality rules appear as separate choices, such as
`Way of the Misr`, `Way of the Misr Grade 1`, through `Way of the Misr Grade 5`.
Selecting one of those rows writes its grade to the save's `quality_level` field.

Grade variants are generated only for the item tags listed by the game's
`DA_StatChangesPerQuality` asset: ranged weapons, melee weapons, assault armor, heavy
armor, scout armor, stillsuits, and utility clothing. Other templates are not assigned
grades without source evidence.

When a game patch changes item IDs or item metadata, the bundled catalog must be refreshed
before those changes can appear in the editor. The project maintainer will update and
publish the catalog for each relevant patch. Users should update to that release rather
than extracting the datatables themselves.

For contributors or maintainers who have a new FModel export, rebuild the catalog with:

```
python tools/build_item_catalog.py "C:\path\to\DuneSandbox\Content\Dune\Systems\Items"
```

The generator merges base item definitions, specialized item-table rows, explicit
`TemplateId` references, and the game's removal list. IDs are deduplicated
case-insensitively and are never renamed. When the sibling `Dune/Localization` export is
present, exact StringTable table/key values take precedence over embedded text. Display
labels remove development markers such as `PH_` while preserving the original text and
status for auditing. Entries without usable localization receive only a readable label
derived from their unchanged ID. Removed and deprecated legacy vehicle rows are not
presented as released Mk7/Mk8/Mk9 parts or with obsolete rank-based inventory names.
The command replaces `src/dune_save_editor/data/item_catalog.json`; run the tests and
include the regenerated catalog in the next release.

## Development

```
python -m pytest
python -m compileall src tests tools
python -m ruff check .
```

The application uses only the Python standard library at runtime.
