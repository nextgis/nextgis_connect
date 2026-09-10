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

from contextlib import suppress
from typing import Any, Optional

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import QEvent, QObject, Qt, pyqtSlot
from qgis.PyQt.QtWidgets import (
    QLabel,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.detached_editing.detached_layer import (
    DetachedLayer,
)
from nextgis_connect.platform.qgis.compat import QgsFeatureId
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.ui_kit.icons import draw_icon, plugin_icon
from nextgis_connect.ui_kit.widgets.description_text_editor import (
    DescriptionTextEditor,
)


class DescriptionTab(QWidget):
    """Display and edit a feature description.

    Keep the editor content synchronized with the selected feature description
    and propagate user changes back to the detached layer.

    :ivar _text_editor: Editor widget used to display and edit description text.
    :ivar _detached_layer: Detached layer currently bound to the tab.
    :ivar _feature_id: Identifier of the feature currently shown in the tab.
    :ivar _description: Description currently rendered by the editor.
    :ivar _description_changed_connection: Active connection to description update notifications.
    """

    EMPTY_OVERLAY_ICON_SIZE = 32

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the description tab widget.

        :param parent: Parent widget.
        """
        super().__init__(parent)

        self._text_editor = DescriptionTextEditor(self)
        self._text_editor.textChanged.connect(self._on_text_changed)
        self._text_edit_viewport = self._text_editor.text_edit.viewport()
        self._text_edit_viewport.installEventFilter(self)
        self._create_empty_description_overlay()

        self._detached_layer: Optional[DetachedLayer] = None
        self._feature_id: Optional[QgsFeatureId] = None
        self._description = ""
        self._description_changed_connection: Optional[Any] = None

        layout = QVBoxLayout(self)
        margins = layout.contentsMargins()
        margins.setTop(margins.top() // 2)
        layout.setContentsMargins(margins)
        layout.addWidget(self._text_editor)

    def _create_empty_description_overlay(self) -> None:
        palette = self.palette()
        disabled_text_color = palette.color(
            palette.ColorGroup.Disabled,
            palette.ColorRole.Text,
        ).name()

        self._empty_description_overlay = QWidget(self._text_edit_viewport)
        self._empty_description_overlay.setObjectName(
            "emptyDescriptionOverlay"
        )
        self._empty_description_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._empty_description_overlay.setStyleSheet(
            f"""
            QWidget#emptyDescriptionOverlay {{
                background-color: transparent;
            }}
            QLabel#emptyDescriptionText {{
                color: {disabled_text_color};
                font-size: 14px;
                padding: 0 8px 4px 8px;
            }}
            """
        )

        layout = QVBoxLayout(self._empty_description_overlay)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_description_icon_label = QLabel(
            self._empty_description_overlay
        )
        self._empty_description_icon_label.setFixedSize(
            self.EMPTY_OVERLAY_ICON_SIZE,
            self.EMPTY_OVERLAY_ICON_SIZE,
        )
        draw_icon(
            self._empty_description_icon_label,
            plugin_icon(
                "material/edit_document_48dp_FFFFFF_FILL0_wght400_GRAD0_opsz48.svg",
                color=disabled_text_color,
                size=self.EMPTY_OVERLAY_ICON_SIZE,
            ),
            size=self.EMPTY_OVERLAY_ICON_SIZE,
        )

        self._empty_description_text_label = QLabel(
            self._empty_description_overlay
        )
        self._empty_description_text_label.setObjectName(
            "emptyDescriptionText"
        )
        self._empty_description_text_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self._empty_description_text_label.setWordWrap(True)
        self._empty_description_text_label.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding,
            self._empty_description_text_label.sizePolicy().verticalPolicy(),
        )
        self._empty_description_text_label.setText(
            self.tr("No description yet")
        )

        layout.addWidget(
            self._empty_description_icon_label,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        layout.addWidget(
            self._empty_description_text_label,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._empty_description_overlay.hide()

    @property
    def text_edit(self) -> QTextEdit:
        """Return the underlying text edit widget.

        :return: Text edit used by the description editor.
        """
        return self._text_editor.text_edit

    def set_feature(
        self, layer: QgsVectorLayer, feature_id: QgsFeatureId
    ) -> None:
        """Bind the tab to a feature description.

        :param layer: Source vector layer for the feature.
        :param feature_id: Identifier of the feature to display.
        """
        self._disconnect_description_signal()

        detached_editing_manager = (
            NgConnectInterface.instance().detached_editing
        )
        detached_layer = detached_editing_manager.layer(layer)
        description = detached_layer.feature_description(feature_id) or ""
        if (
            detached_layer is not self._detached_layer
            or feature_id != self._feature_id
            or description != self._description
        ):
            self._text_editor.blockSignals(True)
            self._text_editor.set_content(description)
            self._text_editor.blockSignals(False)

        self._detached_layer = detached_layer
        self._feature_id = feature_id
        self._description = description
        self._refresh_empty_description_overlay()

        self._description_changed_connection = (
            self._detached_layer.description_updated.connect(
                self._on_description_updated
            )
        )

    def clear_feature(self) -> None:
        """Clear the current feature binding and editor content."""
        self._disconnect_description_signal()
        self._detached_layer = None
        self._feature_id = None
        self._description = ""
        self._text_editor.clearSource()
        self._refresh_empty_description_overlay()

    def set_read_only(self, read_only: bool) -> None:
        """Set the editor read-only state.

        :param read_only: Whether editing should be disabled.
        """
        self._text_editor.set_read_only(read_only)

    @pyqtSlot(QgsFeatureId, str)
    def _on_description_updated(
        self, feature_id: QgsFeatureId, description: str
    ) -> None:
        if self._feature_id is None or self._feature_id != feature_id:
            return
        if description == self._description:
            return

        self._text_editor.blockSignals(True)
        self._text_editor.set_content(description or "")
        self._text_editor.blockSignals(False)
        self._description = description
        self._refresh_empty_description_overlay()

    @pyqtSlot()
    def _on_text_changed(self) -> None:
        if self._detached_layer is None or self._feature_id is None:
            return

        self._disconnect_description_signal()

        description = self._text_editor.content()
        self._description = description
        self._refresh_empty_description_overlay()
        self._detached_layer.set_feature_description(
            self._feature_id, description
        )

        self._description_changed_connection = (
            self._detached_layer.description_updated.connect(
                self._on_description_updated
            )
        )

    def eventFilter(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, watched: QObject, event: QEvent
    ) -> bool:
        """Enable layer editing when a read-only description is double-clicked."""
        if (
            watched is self._text_edit_viewport
            and event.type() == QEvent.Type.MouseButtonDblClick
        ):
            self._enable_edit_mode()
        elif (
            watched is self._text_edit_viewport
            and event.type() == QEvent.Type.Resize
        ):
            self._sync_empty_description_overlay_geometry()
        return super().eventFilter(watched, event)

    def _refresh_empty_description_overlay(self) -> None:
        has_description = bool(
            self._text_editor.text_edit.toPlainText().strip()
        )
        if self._feature_id is None or has_description:
            self._empty_description_overlay.hide()
            return

        self._sync_empty_description_overlay_geometry()
        self._empty_description_overlay.show()
        self._empty_description_overlay.raise_()

    def _sync_empty_description_overlay_geometry(self) -> None:
        self._empty_description_overlay.setGeometry(
            self._text_edit_viewport.rect()
        )

    def _enable_edit_mode(self) -> None:
        if not self._text_editor.text_edit.isReadOnly():
            return

        detached_layer = self._detached_layer
        if detached_layer is None:
            return

        layer = detached_layer.qgs_layer
        if layer.readOnly():
            return

        if not layer.isEditable() and not layer.startEditing():
            return

        self.set_read_only(False)

    def _disconnect_description_signal(self) -> None:
        if self._description_changed_connection is None:
            return

        with suppress(RuntimeError, TypeError):
            self.disconnect(self._description_changed_connection)

        self._description_changed_connection = None
