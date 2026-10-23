# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `src/dune_save_editor/`. Keep the Tkinter interface in
`app.py`, save wrapper and SQLite operations in `save_file.py`, and FModel catalog
logic in `catalog.py`. The generated catalog is
`src/dune_save_editor/data/item_catalog.json`; rebuild it with the tool under
`tools/` rather than editing it manually. Tests belong in `tests/` and should
mirror the module they cover. `run_editor.py` is the source-checkout launcher.

## Build, Test, and Development Commands

Use Python 3.11 or newer from the repository root:

```powershell
python run_editor.py
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m compileall -q src tests tools
```

The app has no third-party runtime dependencies. Install the `dev` extra for
pytest and Ruff. Rebuild game data with
`python tools/build_item_catalog.py C:\path\to\CDT_BaseItems.json`.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation, UTF-8, and type hints on public APIs.
Use `snake_case` for modules/functions/variables, `PascalCase` for classes, and
`UPPER_SNAKE_CASE` for constants. Ruff enforces formatting and lint rules with a
100-character line limit. Keep binary decoding, database mutation, catalog
parsing, and GUI concerns separate.

## Testing Guidelines

Use pytest. Name files `test_*.py` and functions `test_<behavior>()`. Cover malformed
wrappers, schema drift, inventory constraints, external file changes, and complete
compress/decompress round trips. Tests must use synthetic or disposable copies;
never write to a real player save. Run the full test and lint commands before a PR.

## Commit & Pull Request Guidelines

Use focused, imperative subjects such as `Add inventory slot validation`. PRs should
describe user-visible behavior, list validation commands, link issues, and include
screenshots for GUI changes. Call out save-format assumptions and compatibility risks.

## Save-File Safety

Treat saves as irreplaceable. Edit in memory, create a timestamped backup, validate
SQLite integrity, and atomically replace only after validation. Refuse to overwrite a
save changed since opening. Never commit `*.db`, backups, account IDs, or credentials.

## Shared Knowledge Vault

- Vault: `C:\Users\timz2\Desktop\CodingVault\Coding Vault`
- Project page: `projects/Dune Awakening Save Editor.md`
- At the start of relevant work, read the Vault `AGENTS.md`, `index.md`,
  `project-registry.md`, this project page, and the smallest set of linked notes needed
  for the task.
- During work, distinguish verified facts, observations, inferences, and open questions.
- At closeout, update the project page and affected notes with durable findings,
  decisions, verified commands, status, regression coverage, and risks; add reciprocal
  links and a concise Vault `log.md` entry for material work.
- Never copy raw saves, credentials, personal identifiers, build output, dependency
  trees, or chat transcripts into the Vault. The repository remains authoritative for
  implementation details; the Vault stores curated context.
