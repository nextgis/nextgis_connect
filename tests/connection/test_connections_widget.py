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

import uuid
from pathlib import Path

from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.ngw_connection.domain.connection import (
    NgwConnection,
)
from nextgis_connect.legacy.ngw_connection.presentation.connections_widget import (
    NgwConnectionsWidget,
)


def test_project_containers_html_uses_labels_only() -> None:
    html = NgwConnectionsWidget._NgwConnectionsWidget__project_containers_html(
        [
            (
                Path("/tmp/cache/42.gpkg"),
                "Roads <main> (id=42)",
            )
        ]
    )

    assert html == "<ul><li>Roads &lt;main&gt; (id=42)</li></ul>"
    assert "/tmp/cache/42.gpkg" not in html


def test_connection_warning_width_matches_its_icon(qgis_app) -> None:
    connection = NgwConnection(
        id="connection-id",
        name="Missing user",
        url="https://example.com",
        auth_config_id=str(uuid.uuid4()),
    )
    connections_manager = NgwConnectionsManager(
        [connection],
        current_connection_id=connection.id,
    )
    widget = NgwConnectionsWidget(
        None,
        connections_manager=connections_manager,
    )

    assert (
        widget.warningLabel.minimumWidth()
        == widget.warningLabel.maximumWidth()
        == widget.warningLabel.pixmap().width()
    )

    widget.deleteLater()
