from typing import Any, Dict, Optional, Union  # noqa: I001
from typing import cast

from qgis.PyQt.QtCore import QTime, Qt, pyqtSlot
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractSpinBox,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QWidget,
)
from qgis.core import QgsFeature
from qgis.gui import QgsFilterLineEdit

from nextgis_connect.compat import GeometryType
from nextgis_connect.detached_editing.conflicts.ui.base_feature_conflict_tab import (
    FeatureConflictBaseTab,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    FeatureDataConflictResolvingItem,
)
from nextgis_connect.detached_editing.sync.common.serialization import (
    simplify_value,
)
from nextgis_connect.resources.ngw_data_type import NgwDataType
from nextgis_connect.resources.ngw_field import NgwField
from nextgis_connect.types import UnsetType
from nextgis_connect.ui.icon import draw_icon, material_icon


class FeatureDataConflictTab(
    FeatureConflictBaseTab[FeatureDataConflictResolvingItem]
):
    def __init__(
        self,
        unresolved_marker_icon: QIcon,
        resolved_marker_icon: QIcon,
        geometry_type: GeometryType,
        fields: Any,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(geometry_type, parent)
        self._unresolved_marker_icon = unresolved_marker_icon
        self._resolved_marker_icon = resolved_marker_icon
        self._fields = list(fields)

        self._is_filling = False
        self._field_markers: Dict[str, QLabel] = {}
        self._local_edits: Dict[str, QWidget] = {}
        self._result_edits: Dict[str, QWidget] = {}
        self._remote_edits: Dict[str, QWidget] = {}
        self._apply_local_buttons: Dict[str, QToolButton] = {}
        self._apply_remote_buttons: Dict[str, QToolButton] = {}

        self._geometry_marker: Optional[QLabel] = None
        self._local_geometry_button: Optional[QToolButton] = None
        self._remote_geometry_button: Optional[QToolButton] = None
        self._local_canvas: Optional[QStackedWidget] = None
        self._result_canvas: Optional[QStackedWidget] = None
        self._remote_canvas: Optional[QStackedWidget] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        scroll_content, scroll_content_layout = (
            self._create_scroll_content_layout(self.tr("Changes"))
        )

        self.updates_widget = QWidget(scroll_content)
        self.updates_widget.setObjectName("updates_widget")
        self.updates_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )

        grid_layout = QGridLayout(self.updates_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setColumnStretch(2, 1)
        grid_layout.setColumnStretch(4, 1)
        grid_layout.setColumnStretch(6, 1)

        local_label = QLabel(
            self.tr("<b>Local version</b>"), self.updates_widget
        )
        local_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(local_label, 0, 2)

        result_label = QLabel(self.tr("<b>Result</b>"), self.updates_widget)
        result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(result_label, 0, 4)

        remote_label = QLabel(
            self.tr("<b>Remote version</b>"), self.updates_widget
        )
        remote_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(remote_label, 0, 6)

        grid_layout.addWidget(QWidget(self.updates_widget), 0, 0)
        grid_layout.addWidget(QWidget(self.updates_widget), 0, 1)
        grid_layout.addWidget(QWidget(self.updates_widget), 0, 3)
        grid_layout.addWidget(QWidget(self.updates_widget), 0, 5)

        left_arrow_icon = material_icon("keyboard_arrow_left")
        right_arrow_icon = material_icon("keyboard_arrow_right")

        for row, field in enumerate(self._fields, start=1):
            marker = QLabel(self.updates_widget)
            marker.setToolTip(self.tr("Unresolved conflict"))
            draw_icon(marker, self._unresolved_marker_icon)
            self._field_markers[field.keyname] = marker
            grid_layout.addWidget(marker, row, 0)

            field_name = QLabel(field.display_name, self.updates_widget)
            field_name.setToolTip(field.keyname)
            grid_layout.addWidget(field_name, row, 1)

            local_edit_widget = self._create_field_widget(
                self.updates_widget,
                field,
                self._on_field_changed,
            )
            self._set_read_only(local_edit_widget, True)
            self._local_edits[field.keyname] = local_edit_widget
            grid_layout.addWidget(local_edit_widget, row, 2)

            local_button = QToolButton(self.updates_widget)
            local_button.setIcon(right_arrow_icon)
            local_button.clicked.connect(
                lambda _, f=field: self._set_local_field_value(f)
            )
            self._apply_local_buttons[field.keyname] = local_button
            grid_layout.addWidget(local_button, row, 3)

            result_edit_widget = self._create_field_widget(
                self.updates_widget,
                field,
                self._on_field_changed,
            )
            self._set_read_only(result_edit_widget, True)
            self._result_edits[field.keyname] = result_edit_widget
            grid_layout.addWidget(result_edit_widget, row, 4)

            remote_button = QToolButton(self.updates_widget)
            remote_button.setIcon(left_arrow_icon)
            remote_button.clicked.connect(
                lambda _, f=field: self._set_remote_field_value(f)
            )
            self._apply_remote_buttons[field.keyname] = remote_button
            grid_layout.addWidget(remote_button, row, 5)

            remote_edit_widget = self._create_field_widget(
                self.updates_widget,
                field,
                self._on_field_changed,
            )
            self._set_read_only(remote_edit_widget, True)
            self._remote_edits[field.keyname] = remote_edit_widget
            grid_layout.addWidget(remote_edit_widget, row, 6)

        geometry_row = len(self._fields) + 1

        marker = QLabel(self.updates_widget)
        marker.setToolTip(self.tr("Unresolved conflict"))
        draw_icon(marker, self._unresolved_marker_icon)
        self._geometry_marker = marker
        grid_layout.addWidget(marker, geometry_row, 0)

        field_name = QLabel(self.tr("Geometry"), self.updates_widget)
        grid_layout.addWidget(field_name, geometry_row, 1)

        local_canvas = self._create_geometry_widget(self.updates_widget)
        self._local_canvas = local_canvas
        grid_layout.addWidget(local_canvas, geometry_row, 2)

        local_button = QToolButton(self.updates_widget)
        local_button.setIcon(right_arrow_icon)
        local_button.clicked.connect(self._set_local_geometry)
        self._local_geometry_button = local_button
        grid_layout.addWidget(local_button, geometry_row, 3)

        result_canvas = self._create_geometry_widget(self.updates_widget)
        self._result_canvas = result_canvas
        grid_layout.addWidget(result_canvas, geometry_row, 4)

        remote_button = QToolButton(self.updates_widget)
        remote_button.setIcon(left_arrow_icon)
        remote_button.clicked.connect(self._set_remote_geometry)
        self._remote_geometry_button = remote_button
        grid_layout.addWidget(remote_button, geometry_row, 5)

        remote_canvas = self._create_geometry_widget(self.updates_widget)
        self._remote_canvas = remote_canvas
        grid_layout.addWidget(remote_canvas, geometry_row, 6)

        scroll_content_layout.addWidget(self.updates_widget)
        scroll_content_layout.addStretch(1)

        self._set_enabled(False)
        self._clear()

    def _set_enabled(self, enabled: bool) -> None:
        if not enabled:
            for button in self._apply_local_buttons.values():
                button.setEnabled(False)
            for button in self._apply_remote_buttons.values():
                button.setEnabled(False)
            if self._local_geometry_button is not None:
                self._local_geometry_button.setEnabled(False)
            if self._remote_geometry_button is not None:
                self._remote_geometry_button.setEnabled(False)

    def _clear(self) -> None:
        self._is_filling = True
        for field in self._fields:
            keyname = field.keyname
            self._set_field_value(self._local_edits[keyname], field, None)
            self._set_field_value(self._remote_edits[keyname], field, None)
            self._set_field_value(self._result_edits[keyname], field, None)
            self._field_markers[keyname].setVisible(False)

        self._clear_canvas(self._local_canvas)
        self._clear_canvas(self._result_canvas)
        self._clear_canvas(self._remote_canvas)
        if self._geometry_marker is not None:
            self._geometry_marker.setVisible(False)

        self._is_filling = False

    def _fill(self) -> None:
        if self._item is None:
            self._clear()
            self._set_enabled(False)
            return

        assert self._item.local_feature is not None
        assert self._item.remote_feature is not None
        assert not isinstance(self._item.result_feature, UnsetType)
        assert self._item.result_feature is not None

        self._is_filling = True

        for field in self._fields:
            keyname = field.keyname
            self._set_field_value(
                self._local_edits[keyname],
                field,
                self._item.local_feature.attribute(field.attribute),
            )
            self._set_field_value(
                self._remote_edits[keyname],
                field,
                self._item.remote_feature.attribute(field.attribute),
            )

        self._set_feature_to_canvas(
            self._local_canvas, self._item.local_feature
        )
        self._set_feature_to_canvas(
            self._remote_canvas, self._item.remote_feature
        )

        # Update result feature fields and geometry

        for field in self._fields:
            self._update_result_feature_field(field)

        self._update_result_feature_geometry()

        self._is_filling = False

    @pyqtSlot()
    def _set_local_geometry(self) -> None:
        if self._item is None:
            return

        assert not isinstance(self._item.result_feature, UnsetType)
        assert self._item.result_feature is not None
        assert self._item.local_feature is not None

        self._item.result_feature.setGeometry(
            self._item.local_feature.geometry()
        )
        self._item.is_geometry_changed = True
        self._update_result_feature_geometry()
        self._on_item_modified()

    @pyqtSlot()
    def _set_remote_geometry(self) -> None:
        if self._item is None:
            return

        assert not isinstance(self._item.result_feature, UnsetType)
        assert self._item.result_feature is not None
        assert self._item.remote_feature is not None

        self._item.result_feature.setGeometry(
            self._item.remote_feature.geometry()
        )
        self._item.is_geometry_changed = True
        self._update_result_feature_geometry()
        self._on_item_modified()

    def _set_local_field_value(self, field: NgwField) -> None:
        if self._item is None:
            return

        assert not isinstance(self._item.result_feature, UnsetType)
        assert self._item.result_feature is not None
        assert self._item.local_feature is not None

        value = self._item.local_feature.attribute(field.attribute)
        self._item.result_feature.setAttribute(field.attribute, value)
        self._item.changed_fields.add(field.ngw_id)

        self._update_result_feature_field(field)
        self._on_item_modified()

    def _set_remote_field_value(self, field: NgwField) -> None:
        if self._item is None:
            return

        assert not isinstance(self._item.result_feature, UnsetType)
        assert self._item.result_feature is not None
        assert self._item.remote_feature is not None

        value = self._item.remote_feature.attribute(field.attribute)
        self._item.result_feature.setAttribute(field.attribute, value)
        self._item.changed_fields.add(field.ngw_id)

        self._update_result_feature_field(field)
        self._on_item_modified()

    def _update_result_feature_field(self, field: NgwField) -> None:
        if self._item is None:
            return

        def values_equal(
            lhs_feature: QgsFeature, rhs_feature: QgsFeature
        ) -> bool:
            lhs_value = simplify_value(lhs_feature.attribute(field.attribute))
            rhs_value = simplify_value(rhs_feature.attribute(field.attribute))

            if field.datatype == NgwDataType.TIME:
                lhs_value = QTime.fromString(lhs_value)
                rhs_value = QTime.fromString(rhs_value)

            return lhs_value == rhs_value

        marker = self._field_markers[field.keyname]
        is_conflicting_field = (
            field.ngw_id in self._item.conflict.conflicting_fields
        )
        is_changed = field.ngw_id in self._item.changed_fields

        draw_icon(
            marker,
            self._resolved_marker_icon
            if is_changed
            else self._unresolved_marker_icon,
        )
        marker.setToolTip(
            self.tr("Resolved conflict")
            if is_changed
            else self.tr("Unresolved conflict")
        )
        marker.setVisible(is_conflicting_field)

        assert self._item.local_feature is not None
        assert self._item.remote_feature is not None
        assert not isinstance(self._item.result_feature, UnsetType)
        assert self._item.result_feature is not None

        local_button = self._apply_local_buttons[field.keyname]
        local_button.setEnabled(
            is_conflicting_field
            and not values_equal(
                self._item.local_feature, self._item.result_feature
            )
        )

        remote_button = self._apply_remote_buttons[field.keyname]
        remote_button.setEnabled(
            is_conflicting_field
            and not values_equal(
                self._item.remote_feature, self._item.result_feature
            )
        )

        result_edit_widget = self._result_edits[field.keyname]
        self._set_field_value(
            result_edit_widget,
            field,
            self._item.result_feature.attribute(field.attribute),
        )
        self._set_read_only(result_edit_widget, not is_conflicting_field)

    def _update_result_feature_geometry(self) -> None:
        if self._item is None:
            return

        assert self._geometry_marker is not None
        assert self._local_geometry_button is not None
        assert self._remote_geometry_button is not None
        assert not isinstance(self._item.result_feature, UnsetType)
        assert self._item.result_feature is not None
        assert self._item.local_feature is not None
        assert self._item.remote_feature is not None

        draw_icon(
            self._geometry_marker,
            self._resolved_marker_icon
            if self._item.is_geometry_changed
            else self._unresolved_marker_icon,
        )
        self._geometry_marker.setToolTip(
            self.tr("Resolved conflict")
            if self._item.is_geometry_changed
            else self.tr("Unresolved conflict")
        )
        self._geometry_marker.setVisible(
            self._item.conflict.has_geometry_conflict
        )

        self._local_geometry_button.setEnabled(
            self._item.conflict.has_geometry_conflict
            and not self._item.result_feature.geometry().isGeosEqual(
                self._item.local_feature.geometry()
            )
        )
        self._remote_geometry_button.setEnabled(
            self._item.conflict.has_geometry_conflict
            and not self._item.result_feature.geometry().isGeosEqual(
                self._item.remote_feature.geometry()
            )
        )

        self._set_feature_to_canvas(
            self._result_canvas,
            self._item.result_feature,
            is_unresolved=self._item.conflict.has_geometry_conflict
            and not self._item.is_geometry_changed,
        )

    def _set_field_value(
        self, edit_widget: QWidget, field: NgwField, value: Any
    ) -> None:
        was_filling = self._is_filling
        self._is_filling = True

        try:
            super()._set_field_value(edit_widget, field, value)
        finally:
            self._is_filling = was_filling

    @pyqtSlot(NgwField, object)
    def _on_field_changed(self, field: NgwField, value: Any) -> None:
        if self._is_filling:
            return
        if self._item is None:
            return

        sender = cast(
            Union[QAbstractSpinBox, QgsFilterLineEdit], self.sender()
        )
        if sender.isReadOnly():
            return

        assert not isinstance(self._item.result_feature, UnsetType)
        assert self._item.result_feature is not None

        if (
            field.datatype
            in (NgwDataType.INTEGER, NgwDataType.BIGINT, NgwDataType.REAL)
            and sender.clearValue() == value
        ):
            value = None

        self._item.result_feature.setAttribute(
            field.attribute, simplify_value(value)
        )
        self._item.changed_fields.add(field.ngw_id)

        self._update_result_feature_field(field)
        self._on_item_modified()

    def _set_read_only(self, edit_widget: QWidget, is_read_only: bool) -> None:
        edit_widget.setReadOnly(is_read_only)
