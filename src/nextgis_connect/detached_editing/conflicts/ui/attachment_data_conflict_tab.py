from dataclasses import replace
from enum import Enum
from typing import Dict, Optional

from qgis.PyQt.QtCore import Qt, pyqtSlot
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    AttachmentDataConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentDataConflict,
)
from nextgis_connect.detached_editing.conflicts.ui.base_feature_conflict_tab import (
    ConflictTabBase,
)
from nextgis_connect.detached_editing.utils import AttachmentMetadata
from nextgis_connect.types import Unset, UnsetType
from nextgis_connect.ui.icon import draw_icon, material_icon, plugin_icon


class _AttachmentField(str, Enum):
    NAME = "name"
    DESCRIPTION = "description"
    FILE = "file"


class _ResoulutionSide(str, Enum):
    LOCAL = "local"
    RESULT = "result"
    REMOTE = "remote"


class AttachmentDataConflictTab(
    ConflictTabBase[AttachmentDataConflictResolvingItem]
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
        self._file_icon = plugin_icon("files/no_extension_file.svg")

        self._is_filling = False
        self._markers: Dict[_AttachmentField, QLabel] = {}
        self._result_edits: Dict[_AttachmentField, QLineEdit] = {}
        self._local_edits: Dict[_AttachmentField, QLineEdit] = {}
        self._remote_edits: Dict[_AttachmentField, QLineEdit] = {}
        self._file_icon_labels: Dict[_ResoulutionSide, QLabel] = {}
        self._apply_local_buttons: Dict[_AttachmentField, QToolButton] = {}
        self._apply_remote_buttons: Dict[_AttachmentField, QToolButton] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        scroll_content, scroll_content_layout = (
            self._create_scroll_content_layout(self.tr("Attachment change"))
        )

        grid_widget = QWidget(scroll_content)
        grid_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setColumnStretch(2, 1)
        grid_layout.setColumnStretch(4, 1)
        grid_layout.setColumnStretch(6, 1)

        local_label = QLabel(self.tr("<b>Local version</b>"), grid_widget)
        local_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(local_label, 0, 2)

        result_label = QLabel(self.tr("<b>Result</b>"), grid_widget)
        result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(result_label, 0, 4)

        remote_label = QLabel(self.tr("<b>Remote version</b>"), grid_widget)
        remote_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(remote_label, 0, 6)

        self._add_row(
            grid_widget,
            grid_layout,
            row=1,
            field_key=_AttachmentField.NAME,
            field_label=self.tr("Name"),
            editable_result=True,
        )
        self._add_row(
            grid_widget,
            grid_layout,
            row=2,
            field_key=_AttachmentField.DESCRIPTION,
            field_label=self.tr("Description"),
            editable_result=True,
        )

        spacer_row_widget = QWidget(grid_widget)
        spacer_row_widget.setFixedHeight(12)
        grid_layout.addWidget(spacer_row_widget, 3, 0, 1, 7)

        self._add_file_row(
            grid_widget,
            grid_layout,
            row=4,
            field_key=_AttachmentField.FILE,
            field_label=self.tr("File"),
        )

        scroll_content_layout.addWidget(grid_widget)
        scroll_content_layout.addStretch(1)
        self._set_enabled(False)

    def _add_row(
        self,
        parent: QWidget,
        layout: QGridLayout,
        *,
        row: int,
        field_key: _AttachmentField,
        field_label: str,
        editable_result: bool,
    ) -> None:
        marker = QLabel(parent)
        marker.setToolTip(self.tr("Unresolved conflict"))
        draw_icon(marker, self._unresolved_marker_icon)
        layout.addWidget(marker, row, 0)
        self._markers[field_key] = marker

        label = QLabel(field_label, parent)
        layout.addWidget(label, row, 1)

        local_edit = QLineEdit(parent)
        local_edit.setReadOnly(True)
        layout.addWidget(local_edit, row, 2)
        self._local_edits[field_key] = local_edit

        local_button = QToolButton(parent)
        local_button.setIcon(material_icon("keyboard_arrow_right"))
        local_button.clicked.connect(
            lambda _, key=field_key: self._apply_local(key)
        )
        layout.addWidget(local_button, row, 3)
        self._apply_local_buttons[field_key] = local_button

        result_edit = QLineEdit(parent)
        result_edit.setReadOnly(not editable_result)
        if field_key == _AttachmentField.NAME:
            result_edit.textChanged.connect(self._on_name_changed)
        elif field_key == _AttachmentField.DESCRIPTION:
            result_edit.textChanged.connect(self._on_description_changed)
        layout.addWidget(result_edit, row, 4)
        self._result_edits[field_key] = result_edit

        remote_button = QToolButton(parent)
        remote_button.setIcon(material_icon("keyboard_arrow_left"))
        remote_button.clicked.connect(
            lambda _, key=field_key: self._apply_remote(key)
        )
        layout.addWidget(remote_button, row, 5)
        self._apply_remote_buttons[field_key] = remote_button

        remote_edit = QLineEdit(parent)
        remote_edit.setReadOnly(True)
        layout.addWidget(remote_edit, row, 6)
        self._remote_edits[field_key] = remote_edit

    def _add_file_row(
        self,
        parent: QWidget,
        layout: QGridLayout,
        *,
        row: int,
        field_key: _AttachmentField,
        field_label: str,
    ) -> None:
        marker = QLabel(parent)
        marker.setToolTip(self.tr("Unresolved conflict"))
        draw_icon(marker, self._unresolved_marker_icon)
        layout.addWidget(marker, row, 0)
        self._markers[field_key] = marker

        label = QLabel(field_label, parent)
        layout.addWidget(label, row, 1)

        local_file_widget = self._create_file_widget(
            parent,
            _ResoulutionSide.LOCAL,
        )
        layout.addWidget(local_file_widget, row, 2)

        local_button = QToolButton(parent)
        local_button.setIcon(material_icon("keyboard_arrow_right"))
        local_button.clicked.connect(
            lambda _, key=field_key: self._apply_local(key)
        )
        layout.addWidget(local_button, row, 3)
        self._apply_local_buttons[field_key] = local_button

        result_file_widget = self._create_file_widget(
            parent,
            _ResoulutionSide.RESULT,
        )
        layout.addWidget(result_file_widget, row, 4)

        remote_button = QToolButton(parent)
        remote_button.setIcon(material_icon("keyboard_arrow_left"))
        remote_button.clicked.connect(
            lambda _, key=field_key: self._apply_remote(key)
        )
        layout.addWidget(remote_button, row, 5)
        self._apply_remote_buttons[field_key] = remote_button

        remote_file_widget = self._create_file_widget(
            parent,
            _ResoulutionSide.REMOTE,
        )
        layout.addWidget(remote_file_widget, row, 6)

    def _create_file_widget(
        self,
        parent: QWidget,
        side: _ResoulutionSide,
    ) -> QWidget:
        widget = QWidget(parent)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        icon_label = QLabel(widget)
        icon_label.setFixedSize(64, 64)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        self._file_icon_labels[side] = icon_label
        return widget

    def _set_file_icon(
        self,
        side: _ResoulutionSide,
        attachment: Optional[AttachmentMetadata],
    ) -> None:
        icon_label = self._file_icon_labels[side]
        has_file_value = self._attachment_file_label(attachment) != ""
        if not has_file_value:
            icon_label.clear()
            return

        icon_label.setPixmap(self._file_icon.pixmap(64, 64))

    def _attachment_name(
        self, attachment: Optional[AttachmentMetadata]
    ) -> str:
        if attachment is None:
            return ""
        return attachment.name or ""

    def _attachment_description(
        self,
        attachment: Optional[AttachmentMetadata],
    ) -> str:
        if attachment is None:
            return ""
        return attachment.description or ""

    def _attachment_file_label(
        self,
        attachment: Optional[AttachmentMetadata],
    ) -> str:
        if attachment is None:
            return ""

        if attachment.file_path is not None:
            return attachment.file_path.name

        if attachment.fileobj is None or isinstance(
            attachment.fileobj, UnsetType
        ):
            return ""

        return str(attachment.fileobj)

    def _set_enabled(self, enabled: bool) -> None:
        if not enabled:
            for button in self._apply_local_buttons.values():
                button.setEnabled(False)
            for button in self._apply_remote_buttons.values():
                button.setEnabled(False)

        self._result_edits[_AttachmentField.NAME].setReadOnly(True)
        self._result_edits[_AttachmentField.DESCRIPTION].setReadOnly(True)

    def _fill(self) -> None:
        if self._item is None:
            self._is_filling = True
            self._local_edits[_AttachmentField.NAME].setText("")
            self._remote_edits[_AttachmentField.NAME].setText("")
            self._result_edits[_AttachmentField.NAME].setText("")
            self._local_edits[_AttachmentField.DESCRIPTION].setText("")
            self._remote_edits[_AttachmentField.DESCRIPTION].setText("")
            self._result_edits[_AttachmentField.DESCRIPTION].setText("")
            self._file_icon_labels[_ResoulutionSide.LOCAL].clear()
            self._file_icon_labels[_ResoulutionSide.RESULT].clear()
            self._file_icon_labels[_ResoulutionSide.REMOTE].clear()
            self._is_filling = False

            self._set_enabled(False)
            self._update_state()
            return

        result_attachment = self._item.result_attachment
        assert not isinstance(result_attachment, UnsetType)
        assert result_attachment is not None

        self._is_filling = True
        self._local_edits[_AttachmentField.NAME].setText(
            self._attachment_name(self._item.local_attachment)
        )
        self._remote_edits[_AttachmentField.NAME].setText(
            self._attachment_name(self._item.remote_attachment)
        )
        self._result_edits[_AttachmentField.NAME].setText(
            self._attachment_name(result_attachment)
        )

        self._local_edits[_AttachmentField.DESCRIPTION].setText(
            self._attachment_description(self._item.local_attachment)
        )
        self._remote_edits[_AttachmentField.DESCRIPTION].setText(
            self._attachment_description(self._item.remote_attachment)
        )
        self._result_edits[_AttachmentField.DESCRIPTION].setText(
            self._attachment_description(result_attachment)
        )

        self._set_file_icon(
            _ResoulutionSide.LOCAL,
            self._item.local_attachment,
        )
        self._set_file_icon(
            _ResoulutionSide.REMOTE,
            self._item.remote_attachment,
        )
        self._set_file_icon(_ResoulutionSide.RESULT, result_attachment)
        self._is_filling = False

        self._set_enabled(True)
        self._update_state()

    def _is_field_resolved(self, field_key: _AttachmentField) -> bool:
        if self._item is None:
            return False

        if not self._is_field_conflicting(field_key):
            return True

        if field_key == _AttachmentField.NAME:
            return self._item.is_name_changed

        if field_key == _AttachmentField.DESCRIPTION:
            return self._item.is_description_changed

        if field_key == _AttachmentField.FILE:
            return self._item.is_file_changed

        return False

    def _is_field_conflicting(self, field_key: _AttachmentField) -> bool:
        if self._item is None:
            return False

        assert isinstance(self._item.conflict, AttachmentDataConflict)
        if field_key == _AttachmentField.NAME:
            return self._item.conflict.has_name_conflict

        if field_key == _AttachmentField.DESCRIPTION:
            return self._item.conflict.has_description_conflict

        if field_key == _AttachmentField.FILE:
            return self._item.conflict.has_file_conflict

        return False

    def _update_state(self) -> None:
        for field_key, marker in self._markers.items():
            is_conflicting = self._is_field_conflicting(field_key)
            marker.setVisible(is_conflicting)

            self._apply_local_buttons[field_key].setEnabled(is_conflicting)
            self._apply_remote_buttons[field_key].setEnabled(is_conflicting)

            if field_key in self._result_edits:
                self._result_edits[field_key].setReadOnly(not is_conflicting)

            if not is_conflicting:
                marker.setToolTip("")
                continue

            is_resolved = self._is_field_resolved(field_key)

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

    def _on_item_modified(self) -> None:
        if self._item is None:
            return

        self._update_state()
        super()._on_item_modified()

    def _apply_value_from(
        self,
        field_key: _AttachmentField,
        source_attachment: Optional[AttachmentMetadata],
    ) -> None:
        if self._item is None:
            return

        result_attachment = self._item.result_attachment
        assert not isinstance(result_attachment, UnsetType)
        assert result_attachment is not None

        if field_key == _AttachmentField.NAME:
            new_value = ""
            if (
                source_attachment is not None
                and source_attachment.name is not None
            ):
                new_value = source_attachment.name
            self._item.result_attachment = replace(
                result_attachment,
                name=new_value,
            )
            self._is_filling = True
            self._result_edits[_AttachmentField.NAME].setText(new_value)
            self._is_filling = False

        elif field_key == _AttachmentField.DESCRIPTION:
            new_value = ""
            if (
                source_attachment is not None
                and source_attachment.description is not None
            ):
                new_value = source_attachment.description
            self._item.result_attachment = replace(
                result_attachment,
                description=new_value,
            )
            self._is_filling = True
            self._result_edits[_AttachmentField.DESCRIPTION].setText(new_value)
            self._is_filling = False

        elif field_key == _AttachmentField.FILE:
            file_object = Unset
            mime_type = None
            size = None
            sha256 = None
            file_path = None
            if source_attachment is not None:
                file_object = source_attachment.fileobj
                mime_type = source_attachment.mime_type
                size = source_attachment.size
                sha256 = source_attachment.sha256
                file_path = source_attachment.file_path

            self._item.result_attachment = replace(
                result_attachment,
                fileobj=file_object,
                mime_type=mime_type,
                size=size,
                sha256=sha256,
                file_path=file_path,
            )

            self._is_filling = True
            self._set_file_icon(
                _ResoulutionSide.RESULT,
                self._item.result_attachment,
            )
            self._is_filling = False

        self._on_item_modified()

    @pyqtSlot(str)
    def _on_name_changed(self, text: str) -> None:
        if self._is_filling or self._item is None:
            return

        result_attachment = self._item.result_attachment
        assert not isinstance(result_attachment, UnsetType)
        assert result_attachment is not None

        self._item.result_attachment = replace(result_attachment, name=text)
        self._on_item_modified()

    @pyqtSlot(str)
    def _on_description_changed(self, text: str) -> None:
        if self._is_filling or self._item is None:
            return

        result_attachment = self._item.result_attachment
        assert not isinstance(result_attachment, UnsetType)
        assert result_attachment is not None

        self._item.result_attachment = replace(
            result_attachment,
            description=text,
        )
        self._on_item_modified()

    @pyqtSlot(_AttachmentField)
    def _apply_local(self, field_key: _AttachmentField) -> None:
        if self._item is None:
            return

        self._apply_value_from(field_key, self._item.local_attachment)

    @pyqtSlot(_AttachmentField)
    def _apply_remote(self, field_key: _AttachmentField) -> None:
        if self._item is None:
            return

        self._apply_value_from(field_key, self._item.remote_attachment)
