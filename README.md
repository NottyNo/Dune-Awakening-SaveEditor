# Dune: Awakening Save Editor

A dark-themed Python GUI for inspecting and editing a Dune: Awakening PC solo save. It
understands the game's eight-byte wrapper, decompresses the zlib payload in memory,
validates the SQLite database, and writes it back only when you choose **Save**.

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
- character health, hydration, heat, spice, Eyes of Ibad, and tech-point values;
- XP and levels for all five specialization tracks; and
- Atreides, Harkonnen, and Smuggler reputation points.

The game derives overall player level from specialization progression and faction rank
from reputation; those derived values are not independent fields in `game.db`. The
editor works in memory until Save is pressed. Saving creates a timestamped backup
beside the target and refuses to overwrite a file that changed after it was opened.

> This is an experimental editor for an undocumented format. Test restored saves
> on a copy first. Never commit `game.db` or its backups.

## Item catalog

Users do **not** need FModel or any exported datatables to use the editor. A generated
catalog is bundled with every source release, so item search and adding items work
immediately after downloading the repository or a future executable.

When a game patch changes item IDs or item metadata, the bundled catalog must be refreshed
before those changes can appear in the editor. The project maintainer will update and
publish the catalog for each relevant patch. Users should update to that release rather
than extracting the datatables themselves.

For contributors or maintainers who have a new FModel export, rebuild the catalog with:

```powershell
python tools/build_item_catalog.py "C:\path\to\CDT_BaseItems.json"
```

The command replaces `src/dune_save_editor/data/item_catalog.json`; run the tests and
include the regenerated catalog in the next release.

## Development

```powershell
python -m pytest
python -m compileall src tests tools
python -m ruff check .
```

The application uses only the Python standard library at runtime.
