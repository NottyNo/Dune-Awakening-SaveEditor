# Dune: Awakening Save Editor

A Python GUI for inspecting and editing a Dune: Awakening PC solo save. It
understands the game's eight-byte wrapper, decompresses the zlib payload in memory,
validates the SQLite database, and writes it back.

**Release status:** Alpha v1.0 (`1.0.0a1`). Save-format support is experimental, and no
prebuilt Windows executable is included yet.
## Run

Python 3.11 or newer with Tk support is required.

```powershell
python run_editor.py
```

After installing the package, the equivalent command is:

```powershell
python -m dune_save_editor
```

Close Dune: Awakening before opening or saving `game.db`. The navigation tabs provide:

- carried inventory item add, quantity change, and removal;
- category filtering/sorting and separate Grade 1–5 choices for gradeable items;
- character health, hydration, heat, spice, Eyes of Ibad, and intel-point values;
- XP and levels for all five specialization tracks; and
- Atreides, Harkonnen, and Smuggler reputation points.

The game derives overall player level from specialization progression and faction rank
from reputation; those derived values are not independent fields in `game.db`. The
editor works in memory until Save is pressed. Saving creates a timestamped backup
beside the target and refuses to overwrite a file that changed after it was opened.

> This is an experimental editor for an undocumented format. Test restored saves
> on a copy first.

## How to use

1. Open the program
2. Select your save file by clicking the top left button and choosing the game.db file in the correct save folder
Savepath: ```C:\Users\<User>\AppData\Local\DuneSandbox\Saved\Cloud\PlayerClientStorage\FLS_retail\```
3. Make your changes
4. Click Apply (if needed) and Save your changes
5. Enjoy! :D

## Item catalog

Users do **not** need FModel or any exported datatables to use the editor. A generated
catalog is bundled with every source release, so item search and adding items work
immediately after downloading the repository or a future executable.

The current catalog contains 6,287 unique template IDs gathered from the complete
`Systems/Items` export. Use the category selector or click a catalog column heading to
sort the list. Items covered by the game's quality rules appear as separate choices, such
as `Way of the Misr`, `Way of the Misr Grade 1`, through `Way of the Misr Grade 5`.
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

```powershell
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

```powershell
python -m pytest
python -m compileall src tests tools
python -m ruff check .
```

The application uses only the Python standard library at runtime.
