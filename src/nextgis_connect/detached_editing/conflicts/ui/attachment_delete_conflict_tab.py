from enum import Enum
from typing import Dict, Optional

from qgis.PyQt.QtCore import QSignalBlocker, Qt, pyqtSlot
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    AttachmentDeleteConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    LocalAttachmentDeletionConflict,
    RemoteAttachmentDeletionConflict,
)
from nextgis_connect.detached_editing.conflicts.ui.base_feature_conflict_tab import (
    ConflictTabBase,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentDataMixin,
    ExistingAttachmentChange,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentChangeMixin,
)
from nextgis_connect.detached_editing.utils import AttachmentMetadata
from nextgis_connect.logging import logger
from nextgis_connect.types import UnsetType
from nextgis_connect.ui.icon import draw_icon, plugin_icon


class _AttachmentField(str, Enum):
    NAME = "name"
    DESCRIPTION = "description"
    FILE = "file"


class _Side(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class AttachmentDeleteConflictTab(
    ConflictTabBase[AttachmentDeleteConflictResolvingItem]
):
    def __init__(
        self,
        unresolved_marker_icon: QIcon,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._unresolved_marker_icon = unresolved_marker_icon
        self._file_icon = plugin_icon("files/no_extension_file.svg")

        self._markers: Dict[_AttachmentField, QLabel] = {}
        self._local_edits: Dict[_AttachmentField, QWidget] = {}
        self._remote_edits: Dict[_AttachmentField, QWidget] = {}
        self._deleted_groupboxes: Dict[_Side, QGroupBox] = {}

        self._local_radio: Optional[QRadioButton] = None
        self._remote_radio: Optional[QRadioButton] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        scroll_content, scroll_content_layout = (
            self._create_scroll_content_layout(self.tr("Attachment change"))
        )

        self._grid_widget = QWidget(scroll_content)
        self._grid_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        grid_layout = QGridLayout(self._grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setColumnStretch(2, 1)
        grid_layout.setColumnStretch(3, 1)

        grid_layout.addWidget(QWidget(self._grid_widget), 0, 0)
        grid_layout.addWidget(QWidget(self._grid_widget), 0, 1)

        self._local_radio = QRadioButton(
            self.tr("Local version"),
            self._grid_widget,
        )
        self._local_radio.setStyleSheet("QRadioButton { font-weight: bold; }")
        grid_layout.addWidget(self._local_radio, 0, 2)

        self._remote_radio = QRadioButton(
            self.tr("Remote version"),
            self._grid_widget,
        )
        self._remote_radio.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._remote_radio.setStyleSheet("QRadioButton { font-weight: bold; }")
        grid_layout.addWidget(self._remote_radio, 0, 3)

        self._local_radio.toggled.connect(self._on_local_toggled)
        self._remote_radio.toggled.connect(self._on_remote_toggled)

        self._add_value_row(
            layout=grid_layout,
            row=1,
            field_key=_AttachmentField.NAME,
            field_label=self.tr("Name"),
        )
        self._add_value_row(
            layout=grid_layout,
            row=2,
            field_key=_AttachmentField.DESCRIPTION,
            field_label=self.tr("Description"),
        )

        spacer_row_widget = QWidget(self._grid_widget)
        spacer_row_widget.setFixedHeight(12)
        grid_layout.addWidget(spacer_row_widget, 3, 0, 1, 4)

        self._add_file_row(layout=grid_layout, row=4)

        self._deleted_groupboxes[_Side.LOCAL] = self._create_deleted_groupbox(
            self._grid_widget
        )
        grid_layout.addWidget(
            self._deleted_groupboxes[_Side.LOCAL], 1, 2, 4, 1
        )

        self._deleted_groupboxes[_Side.REMOTE] = self._create_deleted_groupbox(
            self._grid_widget
        )
        grid_layout.addWidget(
            self._deleted_groupboxes[_Side.REMOTE], 1, 3, 4, 1
        )

        scroll_content_layout.addWidget(self._grid_widget)
        scroll_content_layout.addStretch(1)

        self._set_enabled(False)
        self._set_deleted_side(None)

    def _add_value_row(
        self,
        *,
        layout: QGridLayout,
        row: int,
        field_key: _AttachmentField,
        field_label: str,
    ) -> None:
        marker = QLabel(self._grid_widget)
        marker.setToolTip(self.tr("Field changed"))
        draw_icon(marker, self._unresolved_marker_icon)
        layout.addWidget(marker, row, 0)
        self._markers[field_key] = marker

        label = QLabel(field_label, self._grid_widget)
        layout.addWidget(label, row, 1)

        local_edit = QLineEdit(self._grid_widget)
        local_edit.setReadOnly(True)
        layout.addWidget(local_edit, row, 2)
        self._local_edits[field_key] = local_edit

        remote_edit = QLineEdit(self._grid_widget)
        remote_edit.setReadOnly(True)
        layout.addWidget(remote_edit, row, 3)
        self._remote_edits[field_key] = remote_edit

    def _add_file_row(self, *, layout: QGridLayout, row: int) -> None:
        marker = QLabel(self._grid_widget)
        marker.setToolTip(self.tr("Field changed"))
        draw_icon(marker, self._unresolved_marker_icon)
        layout.addWidget(marker, row, 0)
        self._markers[_AttachmentField.FILE] = marker

        label = QLabel(self.tr("File"), self._grid_widget)
        layout.addWidget(label, row, 1)

        local_file_widget = self._create_file_widget(self._grid_widget)
        layout.addWidget(local_file_widget, row, 2)
        self._local_edits[_AttachmentField.FILE] = local_file_widget

        remote_file_widget = self._create_file_widget(self._grid_widget)
        layout.addWidget(remote_file_widget, row, 3)
        self._remote_edits[_AttachmentField.FILE] = remote_file_widget

    def _create_deleted_groupbox(self, parent: QWidget) -> QGroupBox:
        deleted_groupbox = QGroupBox(parent)
        deleted_groupbox.setTitle("")
        deleted_groupbox_size_policy = deleted_groupbox.sizePolicy()
        deleted_groupbox_size_policy.setVerticalPolicy(
            QSizePolicy.Policy.Expanding
        )
        deleted_groupbox_size_policy.setHorizontalPolicy(
            QSizePolicy.Policy.Expanding
        )
        deleted_groupbox.setSizePolicy(deleted_groupbox_size_policy)
        deleted_groupbox.setLayout(QVBoxLayout())

        deleted_label = QLabel(
            self.tr("Attachment was deleted"), deleted_groupbox
        )
        deleted_label.setAlignment(
            Qt.Alignment()
            | Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignVCenter
        )
        deleted_groupbox.layout().addWidget(deleted_label)
        return deleted_groupbox

    def _create_file_widget(self, parent: QWidget) -> QWidget:
        widget = QWidget(parent)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        icon_label = QLabel(widget)
        icon_label.setFixedSize(64, 64)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setObjectName("FileIconLabel")
        layout.addWidget(icon_label)

        return widget

    def _set_enabled(self, enabled: bool) -> None:
        self._local_radio.setEnabled(enabled)
        self._remote_radio.setEnabled(enabled)

    def _fill(self) -> None:
        if self._item is None:
            self._set_enabled(False)
            self._set_deleted_side(None)
            self._clear_values()

            for marker in self._markers.values():
                marker.setVisible(False)

            with QSignalBlocker(self._local_radio):
                self._local_radio.setAutoExclusive(False)
                self._local_radio.setChecked(False)
                self._local_radio.setAutoExclusive(True)
            with QSignalBlocker(self._remote_radio):
                self._remote_radio.setAutoExclusive(False)
                self._remote_radio.setChecked(False)
                self._remote_radio.setAutoExclusive(True)
            return

        if isinstance(self._item.conflict, LocalAttachmentDeletionConflict):
            deleted_side = _Side.LOCAL
        elif isinstance(self._item.conflict, RemoteAttachmentDeletionConflict):
            deleted_side = _Side.REMOTE
        else:
            self._set_enabled(False)
            self._set_deleted_side(None)
            self._clear_values()
            logger.warning(
                "Unexpected conflict type: %s",
                type(self._item.conflict),
            )
            return

        self._set_enabled(True)
        self._set_deleted_side(deleted_side)

        with QSignalBlocker(self._local_radio):
            self._local_radio.setAutoExclusive(False)
            self._local_radio.setChecked(
                self._item.resolution_type == ResolutionType.Local
            )
            self._local_radio.setAutoExclusive(True)

        with QSignalBlocker(self._remote_radio):
            self._remote_radio.setAutoExclusive(False)
            self._remote_radio.setChecked(
                self._item.resolution_type == ResolutionType.Remote
            )
            self._remote_radio.setAutoExclusive(True)

        self._set_attachment_values(_Side.LOCAL, self._item.local_attachment)
        self._set_attachment_values(_Side.REMOTE, self._item.remote_attachment)

        self._markers[_AttachmentField.NAME].setVisible(
            self._has_name_changed(self._item)
        )
        self._markers[_AttachmentField.DESCRIPTION].setVisible(
            self._has_description_changed(self._item)
        )
        self._markers[_AttachmentField.FILE].setVisible(
            self._has_file_changed(self._item)
        )

    def _clear_values(self) -> None:
        for field_key in (_AttachmentField.NAME, _AttachmentField.DESCRIPTION):
            casted_local = self._local_edits[field_key]
            casted_remote = self._remote_edits[field_key]
            assert isinstance(casted_local, QLineEdit)
            assert isinstance(casted_remote, QLineEdit)
            casted_local.setText("")
            casted_remote.setText("")

        self._clear_file_icon(self._local_edits[_AttachmentField.FILE])
        self._clear_file_icon(self._remote_edits[_AttachmentField.FILE])

    def _set_deleted_side(self, side: Optional[_Side]) -> None:
        for side_key, groupbox in self._deleted_groupboxes.items():
            is_deleted = side_key == side
            groupbox.setVisible(is_deleted)
            for field_key in _AttachmentField:
                edits = (
                    self._local_edits
                    if side_key == _Side.LOCAL
                    else self._remote_edits
                )
                edits[field_key].setVisible(not is_deleted)

    def _set_attachment_values(
        self,
        side: _Side,
        attachment: Optional[AttachmentMetadata],
    ) -> None:
        edits = (
            self._local_edits if side == _Side.LOCAL else self._remote_edits
        )

        name_edit = edits[_AttachmentField.NAME]
        description_edit = edits[_AttachmentField.DESCRIPTION]

        assert isinstance(name_edit, QLineEdit)
        assert isinstance(description_edit, QLineEdit)

        if attachment is None:
            name_edit.setText("")
            description_edit.setText("")
            self._clear_file_icon(edits[_AttachmentField.FILE])
            return

        name_edit.setText(attachment.name or "")
        description_edit.setText(attachment.description or "")
        self._set_file_icon(edits[_AttachmentField.FILE], attachment)

    def _set_file_icon(
        self,
        file_widget: QWidget,
        attachment: AttachmentMetadata,
    ) -> None:
        icon_label = file_widget.findChild(QLabel, "FileIconLabel")
        if icon_label is None:
            return

        icon_label.setPixmap(self._file_icon.pixmap(64, 64))

    def _clear_file_icon(self, file_widget: QWidget) -> None:
        icon_label = file_widget.findChild(QLabel, "FileIconLabel")
        if icon_label is not None:
            icon_label.clear()

    def _has_name_changed(
        self,
        item: AttachmentDeleteConflictResolvingItem,
    ) -> bool:
        conflict = item.conflict
        if isinstance(conflict, LocalAttachmentDeletionConflict):
            if not isinstance(conflict.remote_action, AttachmentChangeMixin):
                return False
            return not isinstance(conflict.remote_action.name, UnsetType)

        if isinstance(conflict, RemoteAttachmentDeletionConflict):
            if not isinstance(conflict.local_change, AttachmentDataMixin):
                return False
            return not isinstance(conflict.local_change.name, UnsetType)

        return False

    def _has_description_changed(
        self,
        item: AttachmentDeleteConflictResolvingItem,
    ) -> bool:
        conflict = item.conflict
        if isinstance(conflict, LocalAttachmentDeletionConflict):
            if not isinstance(conflict.remote_action, AttachmentChangeMixin):
                return False
            return not isinstance(
                conflict.remote_action.description, UnsetType
            )

        if isinstance(conflict, RemoteAttachmentDeletionConflict):
            if not isinstance(conflict.local_change, AttachmentDataMixin):
                return False
            return not isinstance(conflict.local_change.description, UnsetType)

        return False

    def _has_file_changed(
        self,
        item: AttachmentDeleteConflictResolvingItem,
    ) -> bool:
        conflict = item.conflict
        if isinstance(conflict, LocalAttachmentDeletionConflict):
            if not isinstance(conflict.remote_action, AttachmentChangeMixin):
                return False
            return not isinstance(conflict.remote_action.fileobj, UnsetType)

        if isinstance(conflict, RemoteAttachmentDeletionConflict):
            if not isinstance(conflict.local_change, ExistingAttachmentChange):
                return False
            return conflict.local_change.is_file_new

        return False

    @pyqtSlot(bool)
    def _on_local_toggled(self, state: bool) -> None:
        if not state or self._item is None:
            return

        self._item.resolve_as_local()
        self._on_item_modified()

    @pyqtSlot(bool)
    def _on_remote_toggled(self, state: bool) -> None:
        if not state or self._item is None:
            return

        self._item.resolve_as_remote()
        self._on_item_modified()
