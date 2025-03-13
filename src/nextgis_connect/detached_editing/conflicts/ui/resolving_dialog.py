from enum import IntEnum, auto
from pathlib import Path
from typing import Any, List, Optional, cast

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import (
    QgsDateEdit,
    QgsDateTimeEdit,
    QgsDoubleSpinBox,
    QgsFilterLineEdit,
    QgsMapCanvas,
    QgsMapToolPan,
    QgsRubberBand,
    QgsSpinBox,
    QgsTimeEdit,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QDate,
    QDateTime,
    QItemSelection,
    QMetaObject,
    QPoint,
    QSignalBlocker,
    Qt,
    QTime,
    QUrl,
    QVariant,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QColor, QDesktopServices, QIcon, QKeyEvent
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMenu,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.compat import GeometryType
from nextgis_connect.detached_editing.actions import (
    ActionType,
    DataChangeAction,
    FeatureId,
)
from nextgis_connect.detached_editing.conflicts.conflict import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ConflictResolution,
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    ConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflicts_model import (
    ConflictsResolvingModel,
)
from nextgis_connect.detached_editing.serialization import simplify_value
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    detached_layer_uri,
)
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.resources.ngw_data_type import NgwDataType
from nextgis_connect.resources.ngw_field import NgwField
from nextgis_connect.utils import draw_icon, material_icon

WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "resolving_dialog_base.ui")
)

RED_COLOR = "#d65252"
YELLOW_COLOR = "#f1ea64"
GREEN_COLOR = "#7bab4d"

MARKER_SIZE = 12


class ResolvingDialog(QDialog, WIDGET):
    class Page(IntEnum):
        WELCOME = 0
        UPDATE_UPDATE = auto()
        UPDATE_DELETE = auto()
        DELETE_UPDATE = auto()

    __container_path: Path
    __container_metadata: DetachedContainerMetaData
    __geometry_type: GeometryType
    __conflicts: List[VersioningConflict]
    __resolving_model: ConflictsResolvingModel
    __resolutions: List[ConflictResolution]
    __is_filling: bool

    __unresolved_marker_icon: QIcon
    __resolved_marker_icon: QIcon

    def __init__(
        self,
        container_path: Path,
        metadata: DetachedContainerMetaData,
        conflicts: List[VersioningConflict],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.__container_path = container_path
        self.__container_metadata = metadata
        self.__geometry_type = QgsVectorLayer(
            detached_layer_uri(container_path, metadata), "", "ogr"
        ).geometryType()
        self.__conflicts = conflicts
        self.__resolutions = []
        self.__is_filling = False
        self.__setup_ui()

    @property
    def resolutions(self) -> List[ConflictResolution]:
        return self.__resolutions

    @pyqtSlot()
    def accept(self) -> None:
        self.__resolutions = self.__resolving_model.resulutions
        return super().accept()

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        assert a0 is not None
        if a0.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Escape,
        ):
            a0.accept()
            return

        super().keyPressEvent(a0)

    def __setup_ui(self) -> None:
        self.setupUi(self)
        self.setWindowTitle(
            self.tr(
                f'Conflict resolution in layer "{self.__container_metadata.layer_name}"'
            )
        )

        self.__unresolved_marker_icon = material_icon(
            "fiber_manual_record", color=YELLOW_COLOR, size=MARKER_SIZE
        )
        self.__resolved_marker_icon = material_icon(
            "fiber_manual_record", color=GREEN_COLOR, size=MARKER_SIZE
        )

        self.__setup_update_update()
        self.__setup_update_delete()
        self.__setup_delete_update()
        self.__setup_left_side()

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Workaround for wrong scale on points at start
        QMetaObject.invokeMethod(
            self,
            "updateSelection",
            Qt.ConnectionType.QueuedConnection,
        )

        self.__validate()

    def __setup_left_side(self) -> None:
        self.__resolving_model = ConflictsResolvingModel(
            self.__container_path,
            self.__container_metadata,
            self.__conflicts,
            self,
        )
        self.__resolving_model.dataChanged.connect(self.__validate)
        self.features_view.setModel(self.__resolving_model)
        self.features_view.selectAll()
        self.features_view.selectionModel().selectionChanged.connect(
            self.__update_selection
        )
        self.features_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.features_view.customContextMenuRequested.connect(
            self.__open_context_menu
        )

        self.apply_local_button.setIcon(material_icon("computer"))
        self.apply_local_button.clicked.connect(self.__resolve_as_local)
        self.apply_remote_button.setIcon(material_icon("cloud"))
        self.apply_remote_button.clicked.connect(self.__resolve_as_remote)

    def __setup_update_update(self) -> None:
        left_arrow_icon = material_icon("keyboard_arrow_left")
        right_arrow_icon = material_icon("keyboard_arrow_right")

        grid_widget = self.updates_widget
        grid_layout = cast(QGridLayout, self.updates_widget.layout())

        for i, field in enumerate(self.__container_metadata.fields, start=1):
            # Resolving marker
            marker = QLabel(grid_widget)
            marker.setToolTip(self.tr("Unresolved conflict"))
            marker.setObjectName(f"FieldChangedMarker_{field.keyname}")
            draw_icon(marker, self.__unresolved_marker_icon)
            grid_layout.addWidget(marker, i, 0)

            # Field name
            field_name = QLabel(field.display_name, grid_widget)
            field_name.setToolTip(field.keyname)
            grid_layout.addWidget(field_name, i, 1)

            # Local value widget
            local_edit_widget = self.__create_field_widget(field, grid_widget)
            local_edit_widget.setObjectName(
                f"FieldEditWidget_local_{field.keyname}"
            )
            self.__set_read_only(local_edit_widget, True)
            grid_layout.addWidget(local_edit_widget, i, 2)

            # Apply local value button
            local_button = QToolButton(grid_widget)
            local_button.setObjectName(
                f"ApplyLocalFieldButton_{field.keyname}"
            )
            local_button.setIcon(right_arrow_icon)
            local_button.clicked.connect(
                lambda _, field=field: self.__set_local_field_value(field)
            )
            grid_layout.addWidget(local_button, i, 3)

            # Result value widget
            result_edit_widget = self.__create_field_widget(field, grid_widget)
            result_edit_widget.setObjectName(
                f"FieldEditWidget_result_{field.keyname}"
            )
            self.__set_read_only(result_edit_widget, True)
            grid_layout.addWidget(result_edit_widget, i, 4)

            # Apply remote value button
            remote_button = QToolButton(grid_widget)
            remote_button.setObjectName(
                f"ApplyRemoteFieldButton_{field.keyname}"
            )
            remote_button.setIcon(left_arrow_icon)
            remote_button.clicked.connect(
                lambda _, field=field: self.__set_remote_field_value(field)
            )
            grid_layout.addWidget(remote_button, i, 5)

            # Remote value widget
            remote_edit_widget = self.__create_field_widget(field, grid_widget)
            remote_edit_widget.setObjectName(
                f"FieldEditWidget_remote_{field.keyname}"
            )
            self.__set_read_only(remote_edit_widget, True)
            grid_layout.addWidget(remote_edit_widget, i, 6)

        geometry_row = len(self.__container_metadata.fields) + 1

        # Marker
        marker = QLabel(grid_widget)
        marker.setObjectName("GeometryChangedMarker")
        marker.setToolTip(self.tr("Unresolved conflict"))
        draw_icon(marker, self.__unresolved_marker_icon)
        grid_layout.addWidget(marker, geometry_row, 0)

        # Label
        field_name = QLabel(self.tr("Geometry"), grid_widget)
        grid_layout.addWidget(field_name, geometry_row, 1)

        # Local geometry canvas
        canvas_widget = self.__create_geometry_widget(grid_widget)
        canvas_widget.setObjectName("CanvasWidget_local")
        grid_layout.addWidget(canvas_widget, geometry_row, 2)

        # Apply local geometry button
        local_button = QToolButton(grid_widget)
        local_button.setObjectName("ApplyLocalGeometryButton")
        local_button.setIcon(right_arrow_icon)
        local_button.clicked.connect(lambda _: self.__set_local_geometry())
        grid_layout.addWidget(local_button, geometry_row, 3)

        # Result geometry canvas
        canvas_widget = self.__create_geometry_widget(grid_widget)
        canvas_widget.setObjectName("CanvasWidget_result")
        grid_layout.addWidget(canvas_widget, geometry_row, 4)

        # Apply remote geometry button
        remote_button = QToolButton(grid_widget)
        remote_button.setObjectName("ApplyRemoteGeometryButton")
        remote_button.setIcon(left_arrow_icon)
        remote_button.clicked.connect(lambda _: self.__set_remote_geometry())
        grid_layout.addWidget(remote_button, geometry_row, 5)

        # Remote geometry canvas
        canvas_widget = self.__create_geometry_widget(grid_widget)
        canvas_widget.setObjectName("CanvasWidget_remote")
        grid_layout.addWidget(canvas_widget, geometry_row, 6)

    def __setup_update_delete(self) -> None:
        self.update_delete_local_radiobutton.toggled.connect(
            self.__local_toggled
        )
        self.update_delete_remote_radiobutton.toggled.connect(
            self.__remote_toggled
        )
        self.__setup_layout_with_one_deleted(
            self.update_delete_widget, existed_column=2, deleted_column=3
        )

    def __setup_delete_update(self) -> None:
        self.delete_update_local_radiobutton.toggled.connect(
            self.__local_toggled
        )
        self.delete_update_remote_radiobutton.toggled.connect(
            self.__remote_toggled
        )
        self.__setup_layout_with_one_deleted(
            self.delete_update_widget, existed_column=3, deleted_column=2
        )

    def __setup_layout_with_one_deleted(
        self, grid_widget: QWidget, *, existed_column: int, deleted_column: int
    ) -> None:
        grid_layout = cast(QGridLayout, grid_widget.layout())

        # Groupbox for deleted feature representation
        deleted_groupbox = QGroupBox(grid_widget)
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

        # Deleted feature label
        deleted_label = QLabel(
            self.tr("Feature was deleted"), deleted_groupbox
        )
        deleted_label.setAlignment(
            Qt.Alignment()
            | Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignVCenter
        )
        deleted_groupbox.layout().addWidget(deleted_label)

        grid_layout.addWidget(deleted_groupbox, 1, deleted_column, -1, 1)

        # Add existed feature fields
        for i, field in enumerate(self.__container_metadata.fields, start=1):
            # Changed label
            marker = QLabel(grid_widget)
            marker.setToolTip(self.tr("Field changed"))
            marker.setObjectName(f"FieldChangedMarker_{field.keyname}")
            draw_icon(marker, self.__unresolved_marker_icon)
            grid_layout.addWidget(marker, i, 0)

            # Field name
            field_name = QLabel(field.display_name, grid_widget)
            field_name.setToolTip(field.keyname)
            grid_layout.addWidget(field_name, i, 1)

            # Value widget
            edit_widget = self.__create_field_widget(field, grid_widget)
            edit_widget.setObjectName(f"FieldEditWidget_{field.keyname}")
            self.__set_read_only(edit_widget, True)
            grid_layout.addWidget(edit_widget, i, existed_column)

        geometry_row = len(self.__container_metadata.fields) + 1

        # Geometry changed label
        marker = QLabel(grid_widget)
        marker.setObjectName("GeometryChangedMarker")
        marker.setToolTip(self.tr("Geometry changed"))
        draw_icon(marker, self.__unresolved_marker_icon)
        grid_layout.addWidget(marker, geometry_row, 0)

        # Label
        field_name = QLabel(self.tr("Geometry"), grid_widget)
        grid_layout.addWidget(field_name, geometry_row, 1)

        # Existed geometry canvas
        canvas_widget = self.__create_geometry_widget(grid_widget)
        canvas_widget.setObjectName("CanvasWidget")
        grid_layout.addWidget(canvas_widget, geometry_row, existed_column)

    def __fill_update_update(self, item: ConflictResolvingItem) -> None:
        grid_widget = self.updates_widget

        for field in self.__container_metadata.fields:
            # Fill result value widget and update markers
            self.__update_item_field(item, field)

            # Fill local value widget
            edit_widget = grid_widget.findChild(
                QWidget, f"FieldEditWidget_local_{field.keyname}"
            )
            self.__set_field_value(
                edit_widget,
                field,
                item.local_feature.attribute(field.attribute),
            )
            self.__set_read_only(edit_widget, True)

            # Fill remote value widget
            edit_widget = grid_widget.findChild(
                QWidget, f"FieldEditWidget_remote_{field.keyname}"
            )
            self.__set_field_value(
                edit_widget,
                field,
                item.remote_feature.attribute(field.attribute),
            )
            self.__set_read_only(edit_widget, True)

        # Set result canvas geometry and update marker
        self.__update_item_geometry(item)

        # Set local canvas geometry
        canvas_widget = grid_widget.findChild(
            QStackedWidget, "CanvasWidget_local"
        )
        assert item.local_feature is not None
        self.__set_feature_to_canvas(canvas_widget, item.local_feature)

        # Set remote canvas geometry
        canvas_widget = grid_widget.findChild(
            QStackedWidget, "CanvasWidget_remote"
        )
        assert item.remote_feature is not None
        self.__set_feature_to_canvas(canvas_widget, item.remote_feature)

    def __fill_update_delete(self, item: ConflictResolvingItem) -> None:
        assert item.local_feature
        assert isinstance(item.conflict.local_action, DataChangeAction)

        with QSignalBlocker(self.update_delete_local_radiobutton):
            self.update_delete_local_radiobutton.setAutoExclusive(False)
            self.update_delete_local_radiobutton.setChecked(
                item.resolution_type == ResolutionType.Local
            )
            self.update_delete_local_radiobutton.setAutoExclusive(True)
        with QSignalBlocker(self.update_delete_remote_radiobutton):
            self.update_delete_remote_radiobutton.setAutoExclusive(False)
            self.update_delete_remote_radiobutton.setChecked(
                item.resolution_type == ResolutionType.Remote
            )
            self.update_delete_remote_radiobutton.setAutoExclusive(True)

        self.__fill_with_one_deleted(
            self.update_delete_widget,
            item.local_feature,
            item.conflict.local_action,
        )

    def __fill_delete_update(self, item: ConflictResolvingItem) -> None:
        assert item.remote_feature
        assert isinstance(item.conflict.remote_action, DataChangeAction)

        with QSignalBlocker(self.delete_update_local_radiobutton):
            self.delete_update_local_radiobutton.setAutoExclusive(False)
            self.delete_update_local_radiobutton.setChecked(
                item.resolution_type == ResolutionType.Local
            )
            self.delete_update_local_radiobutton.setAutoExclusive(True)
        with QSignalBlocker(self.delete_update_remote_radiobutton):
            self.delete_update_remote_radiobutton.setAutoExclusive(False)
            self.delete_update_remote_radiobutton.setChecked(
                item.resolution_type == ResolutionType.Remote
            )
            self.delete_update_remote_radiobutton.setAutoExclusive(True)

        self.__fill_with_one_deleted(
            self.delete_update_widget,
            item.remote_feature,
            item.conflict.remote_action,
        )

    def __fill_with_one_deleted(
        self,
        grid_widget: QWidget,
        feature: QgsFeature,
        action: DataChangeAction,
    ) -> None:
        changed_fields = action.fields_dict

        for field in self.__container_metadata.fields:
            # Update marker
            marker = grid_widget.findChild(
                QLabel, f"FieldChangedMarker_{field.keyname}"
            )
            marker.setVisible(field.ngw_id in changed_fields)

            # Set field value
            edit_widget = grid_widget.findChild(
                QWidget, f"FieldEditWidget_{field.keyname}"
            )
            self.__set_field_value(
                edit_widget,
                field,
                feature.attribute(field.attribute),
            )

        # Update marker
        marker = grid_widget.findChild(QLabel, "GeometryChangedMarker")
        marker.setVisible(action.geom is not None)

        # Set geometry to canvas
        canvas_widget = grid_widget.findChild(QStackedWidget, "CanvasWidget")
        self.__set_feature_to_canvas(canvas_widget, feature)

    @pyqtSlot(name="updateSelection")
    def __update_selection(self) -> None:
        self.__on_selection_changed(QItemSelection(), QItemSelection())

    @pyqtSlot("QItemSelection", "QItemSelection", name="onSelectionChanged")
    def __on_selection_changed(
        self, selected: QItemSelection, deselected: QItemSelection
    ) -> None:
        selected_indexes = (
            self.features_view.selectionModel().selectedIndexes()
        )

        selected_count = len(selected_indexes)
        is_empty = selected_count == 0

        self.apply_local_button.setEnabled(not is_empty)
        self.apply_remote_button.setEnabled(not is_empty)

        if selected_count != 1:
            self.stacked_widget.setCurrentIndex(self.Page.WELCOME)
            return

        item = cast(
            ConflictResolvingItem,
            self.__resolving_model.data(
                selected_indexes[0],
                ConflictsResolvingModel.Roles.RESOLVING_ITEM,
            ),
        )
        if item.conflict.local_action.action == ActionType.FEATURE_DELETE:
            self.stacked_widget.setCurrentIndex(self.Page.DELETE_UPDATE)
            self.__fill_delete_update(item)
        elif item.conflict.remote_action.action == ActionType.FEATURE_DELETE:
            self.stacked_widget.setCurrentIndex(self.Page.UPDATE_DELETE)
            self.__fill_update_delete(item)
        else:
            self.stacked_widget.setCurrentIndex(self.Page.UPDATE_UPDATE)
            self.__fill_update_update(item)

    @pyqtSlot(bool)
    def __local_toggled(self, state: bool) -> None:
        if not state:
            return
        self.__resolve_as_local()

    @pyqtSlot(bool)
    def __remote_toggled(self, state: bool) -> None:
        if not state:
            return
        self.__resolve_as_remote()

    @pyqtSlot()
    def __resolve_as_local(self) -> None:
        selected_indexes = (
            self.features_view.selectionModel().selectedIndexes()
        )
        if len(selected_indexes) == self.__resolving_model.rowCount():
            self.__resolving_model.resolve_all_as_local()
        else:
            for index in selected_indexes:
                self.__resolving_model.resolve_as_local(index)

        self.__on_selection_changed(QItemSelection(), QItemSelection())

    @pyqtSlot()
    def __resolve_as_remote(self) -> None:
        selected_indexes = (
            self.features_view.selectionModel().selectedIndexes()
        )
        if len(selected_indexes) == self.__resolving_model.rowCount():
            self.__resolving_model.resolve_all_as_remote()
        else:
            for index in selected_indexes:
                self.__resolving_model.resolve_as_remote(index)

        self.__on_selection_changed(QItemSelection(), QItemSelection())

    @pyqtSlot()
    def __validate(self) -> None:
        resolved_count = self.__resolving_model.resolved_count
        total_count = self.__resolving_model.rowCount()

        self.resolved_count_label.setText(
            f"({resolved_count} / {total_count})"
        )

        self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        ).setEnabled(resolved_count == total_count)

    def __create_field_widget(
        self, field: NgwField, parent: QWidget
    ) -> QWidget:
        if field.datatype == NgwDataType.INTEGER:
            widget = QgsSpinBox(parent)
            widget.setMinimum(-(1 << 31))
            widget.setMaximum((1 << 31) - 1)
            widget.setClearValueMode(
                QgsSpinBox.ClearValueMode.MinimumValue, "NULL"
            )
            widget.setShowClearButton(True)
            widget.valueChanged.connect(
                lambda value: self.__on_field_changed(field, value)
            )
        elif field.datatype == NgwDataType.BIGINT:
            widget = QgsDoubleSpinBox(parent)
            widget.setMinimum(-(1 << 63))
            widget.setMaximum((1 << 63) - 1)
            widget.setSingleStep(1)
            widget.setDecimals(0)
            widget.setClearValueMode(
                QgsDoubleSpinBox.ClearValueMode.MinimumValue, "NULL"
            )
            widget.setShowClearButton(True)
            widget.valueChanged.connect(
                lambda value: self.__on_field_changed(field, int(value))
            )
        elif field.datatype == NgwDataType.REAL:
            widget = QgsDoubleSpinBox(parent)
            widget.setMinimum(-1e37)
            widget.setMaximum(1e37)
            widget.setDecimals(6)
            widget.setClearValueMode(
                QgsDoubleSpinBox.ClearValueMode.MinimumValue, "NULL"
            )
            widget.setShowClearButton(True)
            widget.valueChanged.connect(
                lambda value: self.__on_field_changed(field, value)
            )
        elif field.datatype == NgwDataType.DATE:
            widget = QgsDateEdit(parent)
            widget.setAllowNull(True)
            widget.setDisplayFormat("dd.MM.yyyy")
            widget.dateValueChanged.connect(
                lambda value: self.__on_field_changed(field, value)
            )
        elif field.datatype == NgwDataType.TIME:
            widget = QgsTimeEdit(parent)
            widget.setAllowNull(True)
            widget.setDisplayFormat("HH:mm:ss")
            widget.timeValueChanged.connect(
                lambda value: self.__on_field_changed(field, value)
            )
        elif field.datatype == NgwDataType.DATETIME:
            widget = QgsDateTimeEdit(parent)
            widget.setAllowNull(True)
            widget.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
            widget.valueChanged.connect(
                lambda value: self.__on_field_changed(field, value)
            )
        else:  # STRING
            widget = QgsFilterLineEdit(parent)
            widget.setShowClearButton(True)
            widget.setClearMode(QgsFilterLineEdit.ClearMode.ClearToNull)
            widget.setPlaceholderText("NULL")
            widget.valueChanged.connect(
                lambda value: self.__on_field_changed(field, value)
            )

        return widget

    def __set_field_value(
        self, edit_widget: QWidget, field: NgwField, value: Any
    ) -> None:
        self.__is_filling = True

        is_null = isinstance(value, QVariant) and value.isNull()

        if field.datatype in (
            NgwDataType.INTEGER,
            NgwDataType.BIGINT,
            NgwDataType.REAL,
        ):
            edit_widget.setValue(
                value if not is_null else edit_widget.clearValue()
            )

        elif field.datatype == NgwDataType.DATE:
            if isinstance(value, str):
                date = QDate.fromString(value, Qt.DateFormat.ISODate)
                edit_widget.setDate(date)
            elif isinstance(value, QDate):
                date = value
                edit_widget.setDate(date)
            else:
                edit_widget.clear()
                edit_widget.displayNull()

        elif field.datatype == NgwDataType.TIME:
            if isinstance(value, str):
                time = QTime.fromString(value, Qt.DateFormat.ISODate)
                edit_widget.setTime(time)
            elif isinstance(value, QTime):
                time = value
                edit_widget.setTime(time)
            else:
                edit_widget.clear()
                edit_widget.displayNull()

        elif field.datatype == NgwDataType.DATETIME:
            if isinstance(value, str):
                date_time = QDateTime.fromString(value, Qt.DateFormat.ISODate)
                edit_widget.setDateTime(date_time)
            elif isinstance(value, QDateTime):
                date_time = value
                edit_widget.setDateTime(date_time)
            else:
                edit_widget.clear()
                edit_widget.displayNull()

        else:  # STRING
            if not is_null:
                edit_widget.setValue(value)
            else:
                edit_widget.clearValue()

        self.__is_filling = False

    def __set_local_field_value(self, field: NgwField) -> None:
        item = self.__selected_item()
        assert item is not None

        value = item.local_feature.attribute(field.attribute)
        item.result_feature.setAttribute(field.attribute, value)
        item.changed_fields.add(field.ngw_id)

        index = self.features_view.selectedIndexes()[0]
        self.__resolving_model.update_state(index)

        # Update marker and widget
        self.__update_item_field(item, field)

    def __set_remote_field_value(self, field: NgwField) -> None:
        item = self.__selected_item()
        assert item is not None

        value = item.remote_feature.attribute(field.attribute)
        item.result_feature.setAttribute(field.attribute, value)
        item.changed_fields.add(field.ngw_id)

        index = self.features_view.selectedIndexes()[0]
        self.__resolving_model.update_state(index)

        # Update marker and widget
        self.__update_item_field(item, field)

    def __update_item_field(
        self,
        item: ConflictResolvingItem,
        field: NgwField,
        *,
        set_widget_value: bool = True,
    ) -> None:
        def values_equal(
            lhs_feature: QgsFeature, rhs_feature: QgsFeature
        ) -> bool:
            lhs = simplify_value(lhs_feature.attribute(field.attribute))
            rhs = simplify_value(rhs_feature.attribute(field.attribute))

            if field.datatype == NgwDataType.TIME:
                # GPKG is not support time datatype and value represented as
                # strings
                lhs = QTime.fromString(lhs)
                rhs = QTime.fromString(rhs)

            return lhs == rhs

        grid_widget = self.updates_widget

        is_conflicting_field = field.ngw_id in item.conflict.conflicting_fields
        is_changed = field.ngw_id in item.changed_fields

        # Update marker state
        marker = grid_widget.findChild(
            QLabel, f"FieldChangedMarker_{field.keyname}"
        )
        draw_icon(
            marker,
            self.__resolved_marker_icon
            if is_changed
            else self.__unresolved_marker_icon,
        )
        marker.setToolTip(
            self.tr("Resolved conflict")
            if is_changed
            else self.tr("Unresolved conflict")
        )
        marker.setVisible(is_conflicting_field)

        assert item.local_feature is not None
        assert item.result_feature is not None
        assert item.remote_feature is not None

        # Update apply local value button
        local_button = grid_widget.findChild(
            QToolButton, f"ApplyLocalFieldButton_{field.keyname}"
        )
        local_button.setEnabled(
            is_conflicting_field
            and not values_equal(item.local_feature, item.result_feature)
        )

        # Update apply remote value button
        remote_button = grid_widget.findChild(
            QToolButton, f"ApplyRemoteFieldButton_{field.keyname}"
        )
        remote_button.setEnabled(
            is_conflicting_field
            and not values_equal(item.remote_feature, item.result_feature)
        )

        # Update result field widget
        result_edit_widget = grid_widget.findChild(
            QWidget, f"FieldEditWidget_result_{field.keyname}"
        )

        if set_widget_value:
            self.__set_field_value(
                result_edit_widget,
                field,
                item.result_feature.attribute(field.attribute),
            )

        self.__set_read_only(result_edit_widget, not is_conflicting_field)

    def __set_local_geometry(self) -> None:
        item = self.__selected_item()
        assert item is not None
        assert item.result_feature is not None

        item.result_feature.setGeometry(item.local_feature.geometry())
        item.is_geometry_changed = True

        index = self.features_view.selectedIndexes()[0]
        self.__resolving_model.update_state(index)

        # Update marker and set geometry
        self.__update_item_geometry(item)

    def __set_remote_geometry(self) -> None:
        item = self.__selected_item()
        assert item is not None
        assert item.result_feature is not None

        item.result_feature.setGeometry(item.remote_feature.geometry())
        item.is_geometry_changed = True

        index = self.features_view.selectedIndexes()[0]
        self.__resolving_model.update_state(index)

        # Update marker and set geometry
        self.__update_item_geometry(item)

    def __update_item_geometry(self, item: ConflictResolvingItem) -> None:
        grid_widget = self.updates_widget

        assert item.result_feature is not None

        # Update marker state
        marker = grid_widget.findChild(QLabel, "GeometryChangedMarker")
        draw_icon(
            marker,
            self.__resolved_marker_icon
            if item.is_geometry_changed
            else self.__unresolved_marker_icon,
        )
        marker.setToolTip(
            self.tr("Resolved conflict")
            if item.is_geometry_changed
            else self.tr("Unresolved conflict")
        )
        marker.setVisible(item.conflict.has_geometry_conflict)

        # Update apply local geometry button
        local_button = grid_widget.findChild(
            QToolButton, "ApplyLocalGeometryButton"
        )
        local_button.setEnabled(
            item.conflict.has_geometry_conflict
            and not item.result_feature.geometry().isGeosEqual(
                item.local_feature.geometry()
            )
        )

        # Update remote local geometry button
        remote_button = grid_widget.findChild(
            QToolButton, "ApplyRemoteGeometryButton"
        )
        remote_button.setEnabled(
            item.conflict.has_geometry_conflict
            and not item.result_feature.geometry().isGeosEqual(
                item.remote_feature.geometry()
            )
        )

        # Set geometry to result canvas
        result_canvas_widget = grid_widget.findChild(
            QWidget, "CanvasWidget_result"
        )
        self.__set_feature_to_canvas(
            result_canvas_widget,
            item.result_feature,
            is_unresolved=item.conflict.has_geometry_conflict
            and not item.is_geometry_changed,
        )

    def __create_geometry_widget(self, parent: QWidget) -> QWidget:
        widget = QStackedWidget(parent)
        widget.setMinimumHeight(200)

        canvas = QgsMapCanvas(widget)
        canvas.setObjectName("Canvas")
        canvas.setCanvasColor(Qt.GlobalColor.white)
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem.fromEpsgId(3857))

        pan_tool = QgsMapToolPan(canvas)
        pan_tool.setParent(canvas)
        canvas.setMapTool(pan_tool)

        canvas_size_policy = canvas.sizePolicy()
        canvas_size_policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        canvas_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        canvas.setSizePolicy(canvas_size_policy)

        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if (
                isinstance(layer, QgsRasterLayer)
                and layer.providerType() == "wms"
            ):
                canvas.setLayers([layer])
                canvas.setExtent(layer.extent())
                break

        canvas.refresh()

        rubber_band = QgsRubberBand(canvas, self.__geometry_type)
        rubber_band.setColor(QColor(255, 0, 0, 100))
        rubber_band.show()

        canvas.setProperty("rubber_band", rubber_band)

        widget.addWidget(canvas)

        deleted_groupbox = QGroupBox(widget)
        deleted_groupbox.setTitle("")
        deleted_groupbox_size_policy = deleted_groupbox.sizePolicy()
        deleted_groupbox_size_policy.setVerticalPolicy(
            QSizePolicy.Policy.Ignored
        )
        deleted_groupbox_size_policy.setHorizontalPolicy(
            QSizePolicy.Policy.Ignored
        )
        deleted_groupbox.setSizePolicy(deleted_groupbox_size_policy)
        deleted_groupbox.setLayout(QVBoxLayout())

        deleted_label = QLabel(self.tr("Geometry is not set"))
        deleted_label.setWordWrap(True)
        deleted_label.setObjectName("GeometryDeletedLabel")
        deleted_label.setAlignment(
            Qt.Alignment()
            | Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignVCenter
        )
        deleted_groupbox.layout().addWidget(deleted_label)

        widget.addWidget(deleted_groupbox)

        widget.setCurrentIndex(0)

        return widget

    def __set_feature_to_canvas(
        self,
        canvas_widget: QStackedWidget,
        feature: QgsFeature,
        *,
        is_unresolved: bool = False,
    ) -> None:
        deleted_label = canvas_widget.findChild(QLabel, "GeometryDeletedLabel")
        deleted_label.setText(
            self.tr("Geometry conflict is not resolved")
            if is_unresolved
            else self.tr("Geometry is not set")
        )

        geometry = feature.geometry()
        if geometry is None or geometry.isEmpty():
            canvas_widget.setCurrentIndex(1)
            return

        canvas_widget.setCurrentIndex(0)
        canvas = canvas_widget.findChild(QgsMapCanvas, "Canvas")

        canvas.property("rubber_band").setToGeometry(geometry, None)

        if (
            geometry.type() == GeometryType.Point
            and not QgsWkbTypes.isMultiType(geometry.wkbType())
        ):
            canvas.setCenter(geometry.asPoint())
            canvas.zoomScale(50000)
        else:
            canvas.setExtent(geometry.boundingBox())
            canvas.zoomOut()

        canvas.refresh()

    def __on_field_changed(self, field: NgwField, value: Any) -> None:
        if self.__is_filling:
            return

        item = self.__selected_item()
        assert item is not None
        assert item.result_feature is not None

        if (
            field.datatype
            in (
                NgwDataType.INTEGER,
                NgwDataType.BIGINT,
                NgwDataType.REAL,
            )
            and self.sender().clearValue() == value
        ):  # type: ignore
            value = None

        item.result_feature.setAttribute(
            field.attribute, simplify_value(value)
        )
        item.changed_fields.add(field.ngw_id)

        self.__update_item_field(item, field, set_widget_value=False)

        index = self.features_view.selectedIndexes()[0]
        self.__resolving_model.update_state(index)

    def __selected_item(self) -> Optional[ConflictResolvingItem]:
        indexes = self.features_view.selectedIndexes()
        if len(indexes) != 1:
            return None

        return indexes[0].data(ConflictsResolvingModel.Roles.RESOLVING_ITEM)

    @pyqtSlot(QPoint)
    def __open_context_menu(self, point: QPoint) -> None:
        indexes = self.features_view.selectedIndexes()

        menu = QMenu(self)
        if len(indexes) == 1:
            webgis_action = menu.addAction(self.tr("Open in Web GIS"))
            fid = (
                indexes[0]
                .data(ConflictsResolvingModel.Roles.RESOLVING_ITEM)
                .conflict.fid
            )
            webgis_action.triggered.connect(
                lambda _, fid=fid: self.__open_feature_in_web_gis(fid)
            )

            menu.addSeparator()

        menu.exec(self.features_view.viewport().mapToGlobal(point))

    def __open_feature_in_web_gis(self, feature_id: FeatureId) -> None:
        connection_manager = NgwConnectionsManager()
        connection = connection_manager.connection(
            self.__container_metadata.connection_id
        )
        assert connection is not None

        resource_id = self.__container_metadata.resource_id

        url = QUrl(connection.url)
        url.setPath(f"/resource/{resource_id}/feature/{feature_id}")
        QDesktopServices.openUrl(url)

    def __set_read_only(
        self, edit_widget: QWidget, is_read_only: bool
    ) -> None:
        edit_widget.setReadOnly(is_read_only)
