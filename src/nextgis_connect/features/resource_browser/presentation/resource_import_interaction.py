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

from typing import Callable, Optional, cast

from qgis.PyQt.QtCore import QCoreApplication, QModelIndex
from qgis.PyQt.QtWidgets import QCheckBox, QMessageBox

from nextgis_connect.features.resource_browser.application import (
    ResourceAddingErrorContext,
    ResourceImportCancelledError,
)
from nextgis_connect.legacy.dialog_choose_style import (
    NGWLayerStyleChooserDialog,
)
from nextgis_connect.legacy.tree_widget.item import QNGWResourceItem
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.errors import NgConnectError


class QgisResourceImportInteraction:
    """Own all modal user decisions required by resource import."""

    def __init__(
        self,
        translate: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._translate = translate or self._default_translate
        self._skip_future_adding_errors = False
        self._skip_wfs_with_z: Optional[bool] = None

    @property
    def applies_to_future_errors(self) -> bool:
        return self._skip_future_adding_errors

    def select_default_style(
        self,
        title: str,
        index: object,
        resource_model: object,
    ) -> int:
        """Ask the user to choose one of multiple layer styles."""
        dialog = NGWLayerStyleChooserDialog(
            title,
            cast(QModelIndex, index),
            resource_model,
        )
        if dialog.exec() != NGWLayerStyleChooserDialog.DialogCode.Accepted:
            raise ResourceImportCancelledError

        selected_index = dialog.selectedStyleIndex()
        if selected_index is None or not selected_index.isValid():
            raise ResourceImportCancelledError

        resource = selected_index.data(QNGWResourceItem.NGWResourceRole)
        return resource.resource_id

    def confirm_root_import(self) -> bool:
        return self._confirm_import(
            self._translate(
                "All resources of the Web GIS will be added to QGIS. "
                "Do you want to continue?"
            )
        )

    def confirm_large_import(self, layer_count: int) -> bool:
        return self._confirm_import(
            self._translate(
                "{} layers will be added to QGIS. Do you want to continue?"
            ).format(layer_count)
        )

    def _confirm_import(self, message: str) -> bool:
        message_box = QMessageBox()
        message_box.setWindowTitle(self._translate("Warning"))
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setText(message)
        message_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.No)
        return message_box.exec() == QMessageBox.StandardButton.Yes

    @staticmethod
    def _default_translate(text: str) -> str:
        return QCoreApplication.translate("QgisResourceBatchImporter", text)

    def should_skip_wfs_with_z(self) -> bool:
        """Return the cached decision for importing WFS Z layers."""
        if self._skip_wfs_with_z is not None:
            return self._skip_wfs_with_z

        message_box = QMessageBox()
        message_box.setWindowTitle(self._translate("Warning"))
        message_box.setText(
            self._translate(
                "You are trying to add a WFS service containing a layer"
                " with Z dimension. WFS in QGIS doesn't fully support"
                " editing such geometries. You won't be able to edit and"
                " create new features. You will only be able to delete"
                " features.\nTo fix this, change geometry type of your"
                " layer(s) and recreate WFS service."
            )
        )
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setStandardButtons(
            QMessageBox.StandardButtons()
            | QMessageBox.StandardButton.Ignore
            | QMessageBox.StandardButton.Cancel
        )
        message_box.button(QMessageBox.StandardButton.Ignore).setText(
            self._translate("Add anyway")
        )
        message_box.button(QMessageBox.StandardButton.Cancel).setText(
            self._translate("Skip")
        )
        result = message_box.exec()
        self._skip_wfs_with_z = result == QMessageBox.StandardButton.Cancel
        return self._skip_wfs_with_z

    def should_skip_after_error(
        self,
        error: Exception,
        context: ResourceAddingErrorContext,
        can_skip: bool,
    ) -> bool:
        """Ask whether one failed resource should be skipped."""
        if not can_skip:
            return False

        if self._skip_future_adding_errors:
            self._log_skipped_error(error, context)
            return True

        message_box = QMessageBox()
        message_box.setWindowTitle(self._translate("Adding error"))
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setText(
            self._translate('Resource "{}" can\'t be added to the map').format(
                context.display_name
            )
        )
        message_box.setInformativeText(self._informative_text(error))
        detail = self._error_detail(error, context)
        if len(detail) > 0:
            message_box.setDetailedText(detail)
        message_box.setStandardButtons(
            QMessageBox.StandardButtons()
            | QMessageBox.StandardButton.Ignore
            | QMessageBox.StandardButton.Cancel
        )
        message_box.button(QMessageBox.StandardButton.Ignore).setText(
            self._translate("Skip")
        )
        message_box.button(QMessageBox.StandardButton.Cancel).setText(
            self._translate("Cancel")
        )
        message_box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        apply_to_all_checkbox = QCheckBox(self._translate("Apply to all"))
        message_box.setCheckBox(apply_to_all_checkbox)

        if message_box.exec() != QMessageBox.StandardButton.Ignore:
            raise ResourceImportCancelledError

        self._skip_future_adding_errors = apply_to_all_checkbox.isChecked()
        self._log_skipped_error(error, context)
        return True

    def _informative_text(self, error: Exception) -> str:
        error_message = self._error_user_message(error)
        question = self._translate(
            "Do you want to skip this resource and continue?"
        )
        if len(error_message) == 0:
            return question

        return error_message.rstrip(".") + ".\n\n" + question

    def _error_detail(
        self,
        error: Exception,
        context: ResourceAddingErrorContext,
    ) -> str:
        lines = []
        if len(context.resource_ids) > 0:
            resource_ids = ", ".join(
                str(resource_id) for resource_id in context.resource_ids
            )
            lines.append(
                self._translate("Resource ID(s): {resource_ids}").format(
                    resource_ids=resource_ids
                )
            )

        if context.resource_url is not None:
            lines.append(
                self._translate("Resource URL: {resource_url}").format(
                    resource_url=context.resource_url
                )
            )

        if isinstance(error, NgConnectError):
            if error.detail is not None:
                lines.append(error.detail)
            lines.append(error.log_message)
        elif len(str(error)) > 0:
            lines.append(str(error))

        return "\n".join(lines)

    @staticmethod
    def _error_user_message(error: Exception) -> str:
        if isinstance(error, NgConnectError):
            return error.user_message
        return str(error)

    @staticmethod
    def _log_skipped_error(
        error: Exception,
        context: ResourceAddingErrorContext,
    ) -> None:
        logger.warning(
            f'Resource "{context.display_name}" was skipped during adding'
        )
        logger.warning(str(error))
