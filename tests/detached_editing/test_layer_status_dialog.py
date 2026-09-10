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

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qgis import utils as qgis_utils
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QMessageBox

from nextgis_connect.legacy.detached_editing.container.ui.layer_status_dialog import (
    DetachedLayerStatusDialog,
)
from nextgis_connect.legacy.detached_editing.reset import (
    confirm_reset_container,
)
from nextgis_connect.legacy.detached_editing.utils import DetachedLayerState
from nextgis_connect.shared.constants import PACKAGE_NAME
from tests.ng_connect_testcase import NgConnectTestCase


class _Metadata:
    has_changes = False


class _ChangesInfo:
    added_features_count = 0
    removed_features_count = 0
    updated_features_count = 0


class _Container(QObject):
    editing_started = pyqtSignal()
    editing_finished = pyqtSignal()
    state_changed = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.state = DetachedLayerState.Synchronized
        self.metadata = _Metadata()
        self.is_edit_mode_enabled = False
        self.sync_date = None
        self.error = None
        self.changes_info = _ChangesInfo()
        self.reset_calls_count = 0

    def synchronize(self, is_manual: bool = False) -> None:
        del is_manual

    def reset_container(self) -> None:
        self.reset_calls_count += 1


class TestDetachedLayerStatusDialog(NgConnectTestCase):
    def test_reset_requires_confirmation_when_layer_has_changes(self) -> None:
        container = _Container()
        container.metadata.has_changes = True

        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.No,
        ):
            was_reset = confirm_reset_container(container, None)

        self.assertFalse(was_reset)
        self.assertEqual(container.reset_calls_count, 0)

    def test_reset_is_blocked_in_edit_mode(self) -> None:
        container = _Container()
        container.is_edit_mode_enabled = True

        with patch.object(QMessageBox, "warning") as warning:
            was_reset = confirm_reset_container(container, None)

        self.assertFalse(was_reset)
        self.assertEqual(container.reset_calls_count, 0)
        warning.assert_called_once()

    def test_sync_and_close_buttons_stay_in_same_row(self) -> None:
        old_plugin = qgis_utils.plugins.get(PACKAGE_NAME)
        qgis_utils.plugins[PACKAGE_NAME] = SimpleNamespace(
            path=Path(__file__).resolve().parents[2] / "src/nextgis_connect"
        )
        try:
            dialog = DetachedLayerStatusDialog(_Container())
            dialog.show()
            QgsApplication.instance().processEvents()

            self.assertEqual(
                dialog.syncButton.geometry().y(),
                dialog.closeButton.geometry().y(),
            )
            self.assertFalse(dialog.syncButton.defaultAction().icon().isNull())
            self.assertFalse(
                dialog.syncButton.menu().actions()[0].icon().isNull()
            )
        finally:
            if old_plugin is None:
                qgis_utils.plugins.pop(PACKAGE_NAME, None)
            else:
                qgis_utils.plugins[PACKAGE_NAME] = old_plugin

            if "dialog" in locals():
                dialog.close()
                dialog.deleteLater()
