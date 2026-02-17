import re
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union, cast

from qgis.core import QgsFeature
from qgis.gui import (
    QgsDateEdit,
    QgsDateTimeEdit,
    QgsDoubleSpinBox,
    QgsFilterLineEdit,
    QgsSpinBox,
    QgsTimeEdit,
)
from qgis.PyQt.QtCore import (
    QSignalBlocker,
    Qt,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.compat import GeometryType
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    FeatureDeleteConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    LocalFeatureDeletionConflict,
    RemoteFeatureDeletionConflict,
)
from nextgis_connect.detached_editing.conflicts.ui.base_feature_conflict_tab import (
    FeatureConflictBaseTab,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDeletion,
    DescriptionPut,
    ExistingAttachmentChange,
    FeatureChange,
    FeatureDataMixin,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentCreateAction,
    AttachmentDeleteAction,
    AttachmentUpdateAction,
    DescriptionPutAction,
    FeatureDataChangeMixin,
    VersioningAction,
)
from nextgis_connect.detached_editing.utils import AttachmentMetadata
from nextgis_connect.logging import logger
from nextgis_connect.types import AttachmentId, NgwAttachmentId, UnsetType
from nextgis_connect.ui.icon import draw_icon, plugin_icon


class _Side(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class FeatureDeleteConflictTab(
    FeatureConflictBaseTab[FeatureDeleteConflictResolvingItem]
):
    def __init__(
        self,
        unresolved_marker_icon: QIcon,
        geometry_type: GeometryType,
        fields: Any,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(geometry_type, parent)

        self._unresolved_marker_icon = unresolved_marker_icon
        self._fields = list(fields)

        self._markers: Dict[str, QLabel] = {}
        self._local_edits: Dict[str, QWidget] = {}
        self._remote_edits: Dict[str, QWidget] = {}
        self._local_deleted_groupbox: Optional[QGroupBox] = None
        self._remote_deleted_groupbox: Optional[QGroupBox] = None
        self._grid_layout: Optional[QGridLayout] = None

        self._description_marker: Optional[QLabel] = None
        self._description_label: Optional[QLabel] = None
        self._attachment_markers: List[QLabel] = []
        self._attachment_labels: List[QLabel] = []
        self._attachment_local_widgets: List[QWidget] = []
        self._attachment_remote_widgets: List[QWidget] = []

        self._local_radio: Optional[QRadioButton] = None
        self._remote_radio: Optional[QRadioButton] = None

        self._is_description_row_visible = False

        self._attachments_start_row = 0
        self._base_last_row = 0

        self._setup_ui()

    def _setup_ui(self) -> None:
        scroll_content, scroll_content_layout = (
            self._create_scroll_content_layout(self.tr("Changes"))
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
        self._grid_layout = grid_layout

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
        self._remote_radio.setStyleSheet("QRadioButton { font-weight: bold; }")
        self._remote_radio.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        grid_layout.addWidget(self._remote_radio, 0, 3)

        self._local_radio.toggled.connect(self._on_local_toggled)
        self._remote_radio.toggled.connect(self._on_remote_toggled)

        row = 1
        for field in self._fields:
            marker = QLabel(self._grid_widget)
            marker.setToolTip(self.tr("Field value changed"))
            draw_icon(marker, self._unresolved_marker_icon)
            grid_layout.addWidget(marker, row, 0)
            self._markers[field.keyname] = marker

            label = QLabel(field.display_name, self._grid_widget)
            label.setToolTip(field.keyname)
            grid_layout.addWidget(label, row, 1)

            local_edit = self._create_field_widget(self._grid_widget, field)
            self._set_read_only(local_edit, True)
            grid_layout.addWidget(local_edit, row, 2)
            self._local_edits[field.keyname] = local_edit

            remote_edit = self._create_field_widget(self._grid_widget, field)
            self._set_read_only(remote_edit, True)
            grid_layout.addWidget(remote_edit, row, 3)
            self._remote_edits[field.keyname] = remote_edit
            row += 1

        geometry_marker = QLabel(self._grid_widget)
        geometry_marker.setToolTip(self.tr("Geometry changed"))
        draw_icon(geometry_marker, self._unresolved_marker_icon)
        grid_layout.addWidget(geometry_marker, row, 0)
        self._markers["__geometry__"] = geometry_marker

        geometry_label = QLabel(self.tr("Geometry"), self._grid_widget)
        grid_layout.addWidget(geometry_label, row, 1)

        local_canvas = self._create_geometry_widget(self._grid_widget)
        grid_layout.addWidget(local_canvas, row, 2)
        self._local_edits["__geometry__"] = local_canvas

        remote_canvas = self._create_geometry_widget(self._grid_widget)
        grid_layout.addWidget(remote_canvas, row, 3)
        self._remote_edits["__geometry__"] = remote_canvas

        row += 1

        description_marker = QLabel(self._grid_widget)
        description_marker.setToolTip(self.tr("Description changed"))
        draw_icon(description_marker, self._unresolved_marker_icon)
        grid_layout.addWidget(description_marker, row, 0)
        self._markers["__description_changed__"] = description_marker
        self._description_marker = description_marker

        description_label = QLabel(self.tr("Description"), self._grid_widget)
        grid_layout.addWidget(description_label, row, 1)
        self._description_label = description_label

        local_description = QLabel(self._grid_widget)
        local_description.setWordWrap(True)
        local_description.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        local_description.setAlignment(
            Qt.Alignment()
            | Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
        )
        local_description.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        grid_layout.addWidget(local_description, row, 2)
        self._local_edits["__description__"] = local_description

        remote_description = QLabel(self._grid_widget)
        remote_description.setWordWrap(True)
        remote_description.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        remote_description.setAlignment(
            Qt.Alignment()
            | Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
        )
        remote_description.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        grid_layout.addWidget(remote_description, row, 3)
        self._remote_edits["__description__"] = remote_description

        row += 1
        self._attachments_start_row = row
        self._base_last_row = row - 1

        row_span = max(1, self._base_last_row)

        self._local_deleted_groupbox = self._create_deleted_groupbox(
            self._grid_widget
        )
        grid_layout.addWidget(self._local_deleted_groupbox, 1, 2, row_span, 1)

        self._remote_deleted_groupbox = self._create_deleted_groupbox(
            self._grid_widget
        )
        grid_layout.addWidget(self._remote_deleted_groupbox, 1, 3, row_span, 1)

        scroll_content_layout.addWidget(self._grid_widget)
        scroll_content_layout.addStretch(1)

        self._reset_view()

    def _create_deleted_groupbox(self, parent: QWidget) -> QGroupBox:
        deleted_groupbox = QGroupBox(parent)
        deleted_groupbox.setTitle("")
        size_policy = deleted_groupbox.sizePolicy()
        size_policy.setVerticalPolicy(QSizePolicy.Policy.Expanding)
        size_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        deleted_groupbox.setSizePolicy(size_policy)
        deleted_groupbox.setLayout(QVBoxLayout())
        deleted_layout = deleted_groupbox.layout()
        assert isinstance(deleted_layout, QVBoxLayout)
        deleted_layout.addStretch(1)

        deleted_label = QLabel(
            self.tr("Feature was deleted"), deleted_groupbox
        )
        deleted_label.setAlignment(
            Qt.Alignment()
            | Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignVCenter
        )
        deleted_layout.addWidget(deleted_label)

        deleted_layout.addStretch(1)

        return deleted_groupbox

    def _set_read_only(self, edit_widget: QWidget, is_read_only: bool) -> None:
        if isinstance(edit_widget, (QgsSpinBox, QgsDoubleSpinBox)):
            edit_widget.setReadOnly(is_read_only)
            edit_widget.setShowClearButton(not is_read_only)
            edit_widget.lineEdit().setFrame(not is_read_only)
            edit_widget.lineEdit().setStyleSheet(
                "QLineEdit { border: none; background: transparent; }"
                if is_read_only
                else ""
            )
        elif isinstance(
            edit_widget, (QgsDateEdit, QgsDateTimeEdit, QgsTimeEdit)
        ):
            edit_widget.setReadOnly(is_read_only)
            edit_widget.setShowClearButton(not is_read_only)
        elif isinstance(edit_widget, QgsFilterLineEdit):
            edit_widget.setReadOnly(is_read_only)
            edit_widget.setShowClearButton(not is_read_only)

    def _set_enabled(self, enabled: bool) -> None:
        if self._local_radio is not None:
            self._local_radio.setEnabled(enabled)
        if self._remote_radio is not None:
            self._remote_radio.setEnabled(enabled)

    def _clear_values(self) -> None:
        for field in self._fields:
            local_widget = self._local_edits[field.keyname]
            remote_widget = self._remote_edits[field.keyname]
            self._set_field_value(local_widget, field, None)
            self._set_field_value(remote_widget, field, None)

        self._clear_canvas(self._local_edits["__geometry__"])
        self._clear_canvas(self._remote_edits["__geometry__"])

        self._set_text_widget_value(self._local_edits["__description__"], None)
        self._set_text_widget_value(
            self._remote_edits["__description__"], None
        )
        self._clear_attachments_rows()
        self._set_description_row_visible(False)

    def _set_deleted_side(self, side: Optional[_Side]) -> None:
        if self._local_deleted_groupbox is not None:
            is_local_deleted = side == _Side.LOCAL
            self._local_deleted_groupbox.setVisible(is_local_deleted)
            for widget in self._local_edits.values():
                widget.setVisible(not is_local_deleted)
            for widget in self._attachment_local_widgets:
                widget.setVisible(not is_local_deleted)

            local_description_widget = self._local_edits.get("__description__")
            if local_description_widget is not None:
                local_description_widget.setVisible(
                    (not is_local_deleted) and self._is_description_row_visible
                )

        if self._remote_deleted_groupbox is not None:
            is_remote_deleted = side == _Side.REMOTE
            self._remote_deleted_groupbox.setVisible(is_remote_deleted)
            for widget in self._remote_edits.values():
                widget.setVisible(not is_remote_deleted)
            for widget in self._attachment_remote_widgets:
                widget.setVisible(not is_remote_deleted)

            remote_description_widget = self._remote_edits.get(
                "__description__"
            )
            if remote_description_widget is not None:
                remote_description_widget.setVisible(
                    (not is_remote_deleted)
                    and self._is_description_row_visible
                )

    def _fill(self) -> None:
        if self._item is None:
            self._reset_view()
            return

        deleted_side: Optional[_Side] = None
        feature: Optional[QgsFeature] = None
        data_change: Optional[Any] = None
        conflict = self._item.conflict
        has_description_change = False

        if isinstance(conflict, RemoteFeatureDeletionConflict):
            if len(conflict.local_changes) == 0:
                logger.error(
                    "RemoteFeatureDeletionConflict has no local changes"
                )
                self._reset_view()
                return

            data_change = self._extract_local_feature_data_change(
                conflict.local_changes
            )
            has_description_change = self._is_description_changed(
                conflict.local_changes
            )

            deleted_side = _Side.REMOTE
            feature = self._item.local_feature

        elif isinstance(conflict, LocalFeatureDeletionConflict):
            if len(conflict.remote_actions) == 0:
                logger.error(
                    "LocalFeatureDeletionConflict has no remote actions"
                )
                self._reset_view()
                return

            data_change = self._extract_remote_feature_data_change(
                conflict.remote_actions
            )
            has_description_change = self._is_description_changed(
                conflict.remote_actions
            )

            feature = self._item.remote_feature

            deleted_side = _Side.LOCAL

        else:
            logger.error(f"Unknown conflict type: {type(conflict)}")
            self._reset_view()

            return

        if deleted_side is None or feature is None:
            logger.error("Conflict side or feature is None")
            self._reset_view()
            return

        self._set_enabled(True)
        self._set_deleted_side(deleted_side)
        self._clear_values()

        if self._local_radio is not None:
            with QSignalBlocker(self._local_radio):
                self._local_radio.setAutoExclusive(False)
                self._local_radio.setChecked(
                    self._item.resolution_type == ResolutionType.Local
                )
                self._local_radio.setAutoExclusive(True)

        if self._remote_radio is not None:
            with QSignalBlocker(self._remote_radio):
                self._remote_radio.setAutoExclusive(False)
                self._remote_radio.setChecked(
                    self._item.resolution_type == ResolutionType.Remote
                )
                self._remote_radio.setAutoExclusive(True)

        changed_fields: Dict[int, Any] = {}
        has_geometry_change = False
        if data_change is not None:
            changed_fields = self._extract_changed_fields(data_change)
            has_geometry_change = self._is_geometry_changed(data_change)

        edits = (
            self._remote_edits
            if deleted_side == _Side.LOCAL
            else self._local_edits
        )

        # Fields
        for field in self._fields:
            marker = self._markers[field.keyname]
            marker.setVisible(field.ngw_id in changed_fields)
            value_widget = edits[field.keyname]
            self._set_field_value(
                value_widget,
                field,
                feature.attribute(field.attribute),
            )

        # Geometry
        geometry_marker = self._markers["__geometry__"]
        geometry_marker.setVisible(has_geometry_change)

        geometry_widget = edits["__geometry__"]
        assert isinstance(geometry_widget, QStackedWidget)
        self._set_feature_to_canvas(geometry_widget, feature)

        # Description
        self._markers["__description_changed__"].setVisible(
            has_description_change
        )
        description = (
            self._item.local_description
            if deleted_side == _Side.REMOTE
            else self._item.remote_description
        )
        self._set_text_widget_value(
            edits["__description__"],
            description,
            is_rich_text=True,
        )
        has_description = self._has_description(description)
        self._set_description_row_visible(has_description)

        attachments = (
            self._item.local_attachments
            if deleted_side == _Side.REMOTE
            else self._item.remote_attachments
        )

        self._fill_attachments_rows(attachments, deleted_side)
        self._set_deleted_side(deleted_side)

    def _set_text_widget_value(
        self,
        widget: QWidget,
        value: Optional[str],
        is_rich_text: bool = False,
    ) -> None:
        if not isinstance(widget, QLabel):
            return

        text = value
        if text is None or text.strip() == "":
            text = self.tr("NULL")

        widget.setTextFormat(
            Qt.TextFormat.RichText if is_rich_text else Qt.TextFormat.PlainText
        )
        widget.setText(text)

    def _has_description(self, description: Optional[str]) -> bool:
        if description is None:
            return False

        normalized = description.strip()
        if normalized == "":
            return False

        normalized = re.sub(r"<[^>]+>", "", normalized)
        normalized = normalized.replace("&nbsp;", " ")
        normalized = normalized.strip()
        return normalized != ""

    def _set_description_row_visible(self, visible: bool) -> None:
        self._is_description_row_visible = visible

        if self._description_label is not None:
            self._description_label.setVisible(visible)

        local_widget = self._local_edits.get("__description__")
        if local_widget is not None:
            local_widget.setVisible(visible)

        remote_widget = self._remote_edits.get("__description__")
        if remote_widget is not None:
            remote_widget.setVisible(visible)

    def _clear_attachments_rows(self) -> None:
        if self._grid_layout is None:
            return

        for widgets in (
            self._attachment_markers,
            self._attachment_labels,
            self._attachment_local_widgets,
            self._attachment_remote_widgets,
        ):
            for widget in widgets:
                self._grid_layout.removeWidget(widget)
                widget.deleteLater()

        self._attachment_markers = []
        self._attachment_labels = []
        self._attachment_local_widgets = []
        self._attachment_remote_widgets = []

    def _attachment_text(
        self, attachment: Optional[AttachmentMetadata]
    ) -> str:
        if attachment is None:
            return self.tr("NULL")

        attachment_name = attachment.name or self.tr("Unnamed attachment")
        return attachment_name

    def _create_attachment_value_widget(
        self,
        parent: QWidget,
        attachment: Optional[AttachmentMetadata],
        is_added: bool,
        is_changed: bool,
        is_deleted: bool,
    ) -> QWidget:
        widget = QWidget(parent)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        icon_label = QLabel(widget)
        icon_label.setAlignment(
            Qt.Alignment()
            | Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignVCenter
        )
        draw_icon(
            icon_label,
            plugin_icon("files/no_extension_file.svg"),
            size=24,
        )
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_container = QWidget(widget)
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        attachment_name = self._attachment_text(attachment)
        if is_deleted:
            attachment_name = f"<s>{attachment_name}</s>"
        elif is_changed or is_added:
            attachment_name = f"<i>{attachment_name}</i>"

        name_label = QLabel(attachment_name, text_container)
        name_label.setTextFormat(Qt.TextFormat.RichText)
        name_label.setWordWrap(True)
        name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text_layout.addWidget(name_label)

        layout.addWidget(text_container, 1)

        return widget

    def _update_deleted_groupboxes_span(self, last_row: int) -> None:
        if self._grid_layout is None:
            return

        row_span = max(1, last_row)
        if self._local_deleted_groupbox is not None:
            self._grid_layout.removeWidget(self._local_deleted_groupbox)
            self._grid_layout.addWidget(
                self._local_deleted_groupbox, 1, 2, row_span, 1
            )

        if self._remote_deleted_groupbox is not None:
            self._grid_layout.removeWidget(self._remote_deleted_groupbox)
            self._grid_layout.addWidget(
                self._remote_deleted_groupbox, 1, 3, row_span, 1
            )

    def _fill_attachments_rows(
        self,
        attachments: List[AttachmentMetadata],
        deleted_side: _Side,
    ) -> None:
        if self._grid_layout is None:
            return

        self._clear_attachments_rows()
        if len(attachments) == 0:
            self._update_deleted_groupboxes_span(self._base_last_row)
            return

        added_ids, changed_ids, deleted_ids = self._changed_attachment_ids()

        for row_offset, attachment in enumerate(attachments):
            row = self._attachments_start_row + row_offset

            attachment_key = self._attachment_key(attachment)

            is_added = attachment_key in added_ids
            is_changed = attachment_key in changed_ids
            is_deleted = attachment_key in deleted_ids

            marker_tooltip = ""
            if is_added:
                marker_tooltip = self.tr("Added attachment")
            if is_changed:
                marker_tooltip = self.tr("Changed attachment")
            if is_deleted:
                marker_tooltip = self.tr("Deleted attachment")

            marker = QLabel(self._grid_widget)
            marker.setVisible(marker_tooltip != "")
            marker.setToolTip(marker_tooltip)
            draw_icon(marker, self._unresolved_marker_icon)
            self._grid_layout.addWidget(marker, row, 0)
            self._attachment_markers.append(marker)

            attachment_label = QLabel(
                f"Attachment #{attachment_key}",
                self._grid_widget,
            )
            self._grid_layout.addWidget(attachment_label, row, 1)
            self._attachment_labels.append(attachment_label)

            if deleted_side == _Side.LOCAL:
                widget_list = self._attachment_remote_widgets
                column = 3
            else:
                widget_list = self._attachment_local_widgets
                column = 2

            widget = self._create_attachment_value_widget(
                self._grid_widget,
                attachment,
                is_added,
                is_changed,
                is_deleted,
            )
            self._grid_layout.addWidget(widget, row, column)
            widget_list.append(widget)

        last_row = self._attachments_start_row + len(attachments) - 1
        self._update_deleted_groupboxes_span(last_row)

    def _changed_attachment_ids(
        self,
    ) -> Tuple[
        Set[NgwAttachmentId], Set[NgwAttachmentId], Set[NgwAttachmentId]
    ]:
        if self._item is None:
            return set(), set(), set()

        conflict = self._item.conflict
        actions: Any = []
        if isinstance(conflict, LocalFeatureDeletionConflict):
            actions = conflict.remote_actions
        elif isinstance(conflict, RemoteFeatureDeletionConflict):
            actions = conflict.local_changes

        added_ids = set()
        changed_ids = set()
        deleted_ids = set()

        for action in actions:
            if isinstance(
                action, (AttachmentCreateAction, AttachmentCreation)
            ):
                added_ids.add(self._attachment_key(action))
                continue

            if isinstance(
                action, (AttachmentDeleteAction, AttachmentDeletion)
            ):
                deleted_ids.add(self._attachment_key(action))
                continue

            if isinstance(
                action, (AttachmentUpdateAction, ExistingAttachmentChange)
            ):
                changed_ids.add(self._attachment_key(action))
                continue

        return added_ids, changed_ids, deleted_ids

    def _extract_local_feature_data_change(
        self,
        local_changes: List[FeatureChange],
    ) -> Optional[FeatureDataMixin]:
        for local_change in local_changes:
            if isinstance(local_change, FeatureDataMixin):
                return local_change

        return None

    def _extract_remote_feature_data_change(
        self,
        remote_actions: Sequence[VersioningAction],
    ) -> Optional[FeatureDataChangeMixin]:
        for remote_action in remote_actions:
            if isinstance(remote_action, FeatureDataChangeMixin):
                return remote_action

        return None

    def _extract_changed_fields(self, data_change: Any) -> Dict[int, Any]:
        if isinstance(data_change, FeatureDataMixin):
            return data_change.fields_dict

        if isinstance(data_change, FeatureDataChangeMixin):
            return data_change.fields_dict

        return {}

    def _is_geometry_changed(
        self, data_change: Union[FeatureChange, VersioningAction]
    ) -> bool:
        if isinstance(data_change, FeatureDataMixin):
            return data_change.geometry is not UnsetType

        if isinstance(data_change, FeatureDataChangeMixin):
            return data_change.geom is not UnsetType

        return False

    def _is_description_changed(
        self, actions: Sequence[Union[FeatureChange, VersioningAction]]
    ) -> bool:
        for action in actions:
            if isinstance(action, (DescriptionPut, DescriptionPutAction)):
                return True

        return False

    def _reset_view(self) -> None:
        self._set_enabled(False)
        self._set_deleted_side(None)
        self._clear_values()
        for marker in self._markers.values():
            marker.setVisible(False)

        if self._local_radio is not None:
            with QSignalBlocker(self._local_radio):
                self._local_radio.setAutoExclusive(False)
                self._local_radio.setChecked(False)
                self._local_radio.setAutoExclusive(True)
        if self._remote_radio is not None:
            with QSignalBlocker(self._remote_radio):
                self._remote_radio.setAutoExclusive(False)
                self._remote_radio.setChecked(False)
                self._remote_radio.setAutoExclusive(True)

    def _attachment_key(
        self, attachment_change: Any
    ) -> Union[NgwAttachmentId, AttachmentId]:
        key = None
        if hasattr(attachment_change, "ngw_aid"):
            key = cast(
                Optional[NgwAttachmentId],
                getattr(attachment_change, "ngw_aid"),  # noqa: B009
            )

        if key is None and hasattr(attachment_change, "aid"):
            key = cast(
                Optional[AttachmentId],
                getattr(attachment_change, "aid"),  # noqa: B009
            )

        if key is None:
            raise ValueError(
                f"Attachment change {attachment_change} has no attachment id"
            )

        return key

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
