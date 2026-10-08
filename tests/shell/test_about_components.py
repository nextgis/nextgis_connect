# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

import json
from pathlib import Path

import pytest

from nextgis_connect.shell.presentation.about.about_dialog import AboutDialog

COMPONENTS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "nextgis_connect"
    / "assets"
    / "components"
)


def test_packaged_component_index(qgis_app):
    index_path = COMPONENTS_PATH / "index.json"
    entries = json.loads(index_path.read_text(encoding="utf-8"))
    assert entries
    for entry in entries:
        component_path = COMPONENTS_PATH / entry
        component = json.loads(component_path.read_text(encoding="utf-8"))
        if "license_file" in component:
            assert (
                component_path.parent / component["license_file"]
            ).is_file()

    dialog = AboutDialog("nextgis_connect", components_path=index_path)
    try:
        assert dialog._components_list_widget.count() == len(entries)
        assert dialog._tab_widget.indexOf(dialog._components_tab) >= 0
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("inline", [False, True])
def test_component_metadata_formats(qgis_app, tmp_path, inline):
    component = {
        "title": "Example",
        "description": {"en": "Example component"},
        "license_url": "https://example.com/license",
        "project_url": "https://example.com",
    }
    (tmp_path / "component.json").write_text(
        json.dumps(component), encoding="utf-8"
    )
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps([component if inline else "component.json"]),
        encoding="utf-8",
    )

    dialog = AboutDialog("nextgis_connect", components_path=index_path)
    try:
        assert dialog._components_list_widget.count() == 1
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize(
    "entry", ["missing.json", "invalid.json", "../outside.json"]
)
def test_invalid_component_reference(qgis_app, tmp_path, entry):
    components_path = tmp_path / "components"
    components_path.mkdir()
    (components_path / "invalid.json").write_text("{", encoding="utf-8")
    (tmp_path / "outside.json").write_text(
        json.dumps(
            {
                "title": "Outside",
                "description": "Not part of the component directory",
                "license_url": "https://example.com/license",
                "project_url": "https://example.com",
            }
        ),
        encoding="utf-8",
    )
    index_path = components_path / "index.json"
    index_path.write_text(json.dumps([entry]), encoding="utf-8")

    dialog = AboutDialog("nextgis_connect", components_path=index_path)
    try:
        assert dialog._components_list_widget.count() == 0
        assert dialog._tab_widget.indexOf(dialog._components_tab) == -1
    finally:
        dialog.deleteLater()
