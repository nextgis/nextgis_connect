# AGENTS.md

## Runtime
- This repo is a QGIS Python plugin; imports/tests usually need a Python environment that provides `qgis`, `qgis.PyQt`, and `osgeo`.
- Keep code Python 3.8 compatible: `pyproject.toml` sets `pythonVersion = "3.8"` and Ruff `target-version = "py38"`.
- Plugin metadata supports QGIS `3.22` to `4.99` and `supportsQt6=True`; check `nextgis_connect.platform.qgis.compat` before changing Qt/QGIS-version-sensitive code.

## Terminology And Localization
- Use `Web GIS` (two words, both capitalized, separated by U+00A0) in English user-facing text and in translations that retain the English term; use `Web GIS` in documentation and log messages.
- In Russian user-facing text and `nextgis_connect_ru.ts`, translate it as `Веб ГИС`; write compounds as separate words (for example, `сервис Веб ГИС`).
- Keep the approved translation in each other locale; the Spanish catalogue intentionally retains `Web GIS`, while the About dialog contains locale-specific wording.
- Keep the responsive overlay fallback that turns `Web GIS` into `Web\u00a0GIS`: it protects externally supplied text from an undesirable line break.

## Entrypoints
- QGIS starts at `src/nextgis_connect/__init__.py:classFactory`, then `plugin/plugin_factory.py:create_plugin`.
- Normal lifecycle is `plugin/plugin.py:NgConnectPlugin` plus `plugin/plugin_container.py:PluginContainer`.
- Startup/import failures intentionally fall back to `plugin/startup_stub.py:NgConnectPluginStub` so QGIS can show the error.
- Much active behavior still lives under `src/nextgis_connect/legacy/`, especially NGW resources, detached editing, settings, and dock UI.

## Commands
- Install dev tools in the QGIS-capable Python env: `python -m pip install -e '.[dev]'`.
- Lint/format like pre-commit: `ruff check --fix .` then `ruff format .`.
- Run tests: `python -m pytest`.
- Run one test file or test: `python -m pytest tests/search/test_query_builder.py` or `python -m pytest tests/search/test_query_builder.py::test_name`.
- If available, run type checks with `pyright`.

## Build And Install
- Build plugin zip: `python setup.py build`; output is `build/nextgis_connect-<version>.zip`.
- Install to QGIS: `python setup.py install --qgis Vanilla --profile <profile> --force`.
- Editable install uses symlinks: `python setup.py install --editable --qgis <Vanilla|NextGIS|VanillaFlatpak|NextGISFlatpak> --profile <profile> --force`.
- Keep `pyproject.toml` version and `src/nextgis_connect/metadata.txt` version equal; `setup.py build/install` prompts if they differ.

## Generated Files
- `.ui` files are packaged directly because `[tool.qgsmith.forms] compile = false`; do not add generated UI Python files unless this changes.
- `python setup.py bootstrap` compiles configured assets/translations; `python setup.py bootstrap --ts` compiles only translations with `lrelease`.
- `python setup.py update_ts` updates `.ts` translation files with `pylupdate5`; `python setup.py clean` removes generated outputs known to `setup.py`.

## Tests
- `tests/conftest.py` starts an offscreen `QgsApplication`, sets temporary `QGIS_CUSTOM_CONFIG_PATH` and `QGIS_AUTH_DB_DIR_PATH`, and mocks `qgis.utils.iface`.
- Do not point tests at a user's real QGIS profile/settings/auth DB.
- For plugin lifecycle changes, run `python -m pytest tests/plugin/test_plugin_import.py`.
