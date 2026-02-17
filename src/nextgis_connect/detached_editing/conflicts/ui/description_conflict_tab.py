from typing import Optional

from qgis.PyQt.QtCore import Qt, pyqtSlot
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QGridLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    DescriptionConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.ui.base_feature_conflict_tab import (
    ConflictTabBase,
)
from nextgis_connect.detached_editing.identification.ui.feature_description_text_editor import (
    FeatureDescriptionTextEditor,
)
from nextgis_connect.types import UnsetType
from nextgis_connect.ui.icon import draw_icon, material_icon


class DescriptionConflictTab(
    ConflictTabBase[DescriptionConflictResolvingItem]
):
    def __init__(
        self,
        unresolved_marker_icon: QIcon,
        resolved_marker_icon: QIcon,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._unresolved_marker_icon = unresolved_marker_icon
        self._resolved_marker_icon = resolved_marker_icon

        self._is_filling = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        scroll_content, scroll_content_layout = (
            self._create_scroll_content_layout(self.tr("Description change"))
        )

        self._grid_widget = QWidget(scroll_content)
        self._grid_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        grid_layout = QGridLayout(self._grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setRowStretch(1, 1)
        grid_layout.setColumnStretch(1, 1)
        grid_layout.setColumnStretch(3, 1)
        grid_layout.setColumnStretch(5, 1)

        local_label = QLabel(
            self.tr("<b>Local version</b>"), self._grid_widget
        )
        local_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(local_label, 0, 1)

        result_label = QLabel(self.tr("<b>Result</b>"), self._grid_widget)
        result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(result_label, 0, 3)

        remote_label = QLabel(
            self.tr("<b>Remote version</b>"), self._grid_widget
        )
        remote_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(remote_label, 0, 5)

        grid_layout.addWidget(QWidget(self._grid_widget), 0, 2)
        grid_layout.addWidget(QWidget(self._grid_widget), 0, 4)

        self._marker = QLabel(self._grid_widget)
        self._marker.setObjectName("DescriptionChangedMarker")
        self._marker.setToolTip(self.tr("Unresolved conflict"))
        draw_icon(self._marker, self._unresolved_marker_icon)
        grid_layout.addWidget(self._marker, 1, 0)

        self._local_editor = FeatureDescriptionTextEditor(self._grid_widget)
        self._local_editor.set_read_only(True)
        self._local_editor.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        grid_layout.addWidget(self._local_editor, 1, 1)

        self._apply_local_button = QToolButton(self._grid_widget)
        self._apply_local_button.setIcon(material_icon("keyboard_arrow_right"))
        self._apply_local_button.clicked.connect(self._apply_local)
        grid_layout.addWidget(self._apply_local_button, 1, 2)

        self._result_editor = FeatureDescriptionTextEditor(self._grid_widget)
        self._result_editor.set_read_only(False)
        self._result_editor.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._result_editor.textChanged.connect(self._on_result_changed)
        grid_layout.addWidget(self._result_editor, 1, 3)

        self._apply_remote_button = QToolButton(self._grid_widget)
        self._apply_remote_button.setIcon(material_icon("keyboard_arrow_left"))
        self._apply_remote_button.clicked.connect(self._apply_remote)
        grid_layout.addWidget(self._apply_remote_button, 1, 4)

        self._remote_editor = FeatureDescriptionTextEditor(self._grid_widget)
        self._remote_editor.set_read_only(True)
        self._remote_editor.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        grid_layout.addWidget(self._remote_editor, 1, 5)

        scroll_content_layout.addWidget(self._grid_widget)
        scroll_content_layout.setStretch(0, 1)

        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        self._apply_local_button.setEnabled(enabled)
        self._apply_remote_button.setEnabled(enabled)
        self._result_editor.set_read_only(not enabled)

    def _fill(self) -> None:
        marker = self._marker

        if self._item is None:
            self._is_filling = True
            self._local_editor.set_content("")
            self._remote_editor.set_content("")
            self._result_editor.set_content("")
            self._is_filling = False

            self._set_enabled(False)
            marker.setToolTip(self.tr("Unresolved conflict"))
            draw_icon(marker, self._unresolved_marker_icon)
            return

        local_description = self._item.local_description or ""
        remote_description = self._item.remote_description or ""
        result_description_text = self._item.result_description or ""
        assert not isinstance(result_description_text, UnsetType)

        self._is_filling = True
        self._local_editor.set_content(local_description)
        self._remote_editor.set_content(remote_description)
        self._result_editor.set_content(result_description_text)
        self._is_filling = False

        self._set_enabled(True)
        self._update_state()

    def _update_state(self) -> None:
        marker = self._marker

        if self._item is None:
            marker.setToolTip(self.tr("Unresolved conflict"))
            draw_icon(marker, self._unresolved_marker_icon)
            self._apply_local_button.setEnabled(False)
            self._apply_remote_button.setEnabled(False)
            return

        is_resolved = self._item.is_resolved

        marker.setToolTip(
            self.tr("Resolved conflict")
            if is_resolved
            else self.tr("Unresolved conflict")
        )
        draw_icon(
            marker,
            self._resolved_marker_icon
            if is_resolved
            else self._unresolved_marker_icon,
        )

        self._apply_local_button.setEnabled(
            self._item.result_description != self._item.local_description
        )
        self._apply_remote_button.setEnabled(
            self._item.result_description != self._item.remote_description
        )

    def _on_item_modified(self) -> None:
        if self._item is None:
            return

        self._update_state()
        super()._on_item_modified()

    @pyqtSlot()
    def _apply_local(self) -> None:
        if self._item is None:
            return

        self._item.result_description = self._item.local_description
        self._is_filling = True
        self._result_editor.set_content(self._item.local_description or "")
        self._is_filling = False
        self._on_item_modified()

    @pyqtSlot()
    def _apply_remote(self) -> None:
        if self._item is None:
            return

        self._item.result_description = self._item.remote_description
        self._is_filling = True
        self._result_editor.set_content(self._item.remote_description or "")
        self._is_filling = False
        self._on_item_modified()

    @pyqtSlot()
    def _on_result_changed(self) -> None:
        if self._is_filling:
            return
        if self._item is None:
            return

        self._item.result_description = self._result_editor.content()
        self._on_item_modified()
