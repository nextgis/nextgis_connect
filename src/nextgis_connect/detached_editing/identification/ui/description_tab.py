from typing import Any, Optional

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import pyqtSlot
from qgis.PyQt.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from nextgis_connect.compat import QgsFeatureId
from nextgis_connect.detached_editing.detached_layer import DetachedLayer
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.shared.ui.description_text_editor import (
    DescriptionTextEditor,
)


class DescriptionTab(QWidget):
    """Display and edit a feature description.

    Keep the editor content synchronized with the selected feature description
    and propagate user changes back to the detached layer.

    :ivar _text_editor: Editor widget used to display and edit description text.
    :ivar _detached_layer: Detached layer currently bound to the tab.
    :ivar _feature_id: Identifier of the feature currently shown in the tab.
    :ivar _description_changed_connection: Active connection to description update notifications.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the description tab widget.

        :param parent: Parent widget.
        """
        super().__init__(parent)

        self._text_editor = DescriptionTextEditor(self)
        self._text_editor.textChanged.connect(self._on_text_changed)

        self._detached_layer: Optional[DetachedLayer] = None
        self._feature_id: Optional[QgsFeatureId] = None
        self._description_changed_connection: Optional[Any] = None

        layout = QVBoxLayout(self)
        margins = layout.contentsMargins()
        margins.setTop(margins.top() // 2)
        layout.setContentsMargins(margins)
        layout.addWidget(self._text_editor)

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
        self._detached_layer = detached_editing_manager.layer(layer)
        self._feature_id = feature_id

        self._text_editor.blockSignals(True)
        self._text_editor.set_content(
            self._detached_layer.feature_description(feature_id) or ""
        )
        self._text_editor.blockSignals(False)

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
        self._text_editor.clearSource()

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

        self._text_editor.blockSignals(True)
        self._text_editor.set_content(description or "")
        self._text_editor.blockSignals(False)

    @pyqtSlot()
    def _on_text_changed(self) -> None:
        if self._detached_layer is None or self._feature_id is None:
            return

        self._disconnect_description_signal()

        self._detached_layer.set_feature_description(
            self._feature_id, self._text_editor.content()
        )

        self._description_changed_connection = (
            self._detached_layer.description_updated.connect(
                self._on_description_updated
            )
        )

    def _disconnect_description_signal(self) -> None:
        if self._description_changed_connection is None:
            return

        try:
            self.disconnect(self._description_changed_connection)
        except (RuntimeError, TypeError):
            pass

        self._description_changed_connection = None
