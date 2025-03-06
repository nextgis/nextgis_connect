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
    QgsMapCanvas,
    QgsMapToolPan,
    QgsRubberBand,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QDate,
    QDateTime,
    QItemSelection,
    QSignalBlocker,
    Qt,
    QTime,
    QVariant,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.compat import GeometryType
from nextgis_connect.detached_editing.actions import (
    ActionType,
    DataChangeAction,
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
from nextgis_connect.detached_editing.utils import (
    DetachedContainerMetaData,
    detached_layer_uri,
)
from nextgis_connect.resources.ngw_data_type import NgwDataType
from nextgis_connect.resources.ngw_field import NgwField
from nextgis_connect.utils import draw_icon, material_icon

WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "resolving_dialog_base.ui")
)


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
        ).geometryType()  # TODO
        self.__conflicts = conflicts
        self.__resolutions = []
        self.__setup_ui()

    @property
    def resolutions(self) -> List[ConflictResolution]:
        return self.__resolutions

    def accept(self) -> None:
        self.__resolutions = self.__resolving_model.resulutions
        return super().accept()

    def __setup_ui(self) -> None:
        self.setupUi(self)
        self.setWindowTitle(
            self.tr(
                f'Conflict resolution in layer "{self.__container_metadata.layer_name}"'
            )
        )
        self.__setup_left_side()
        self.__setup_modified_modified()
        self.__setup_update_delete()
        self.__setup_delete_update()

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

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
        self.features_view.selectionModel().selectionChanged.connect(
            self.__on_selection_changed
        )
        self.features_view.selectAll()

        self.apply_local_button.setIcon(material_icon("computer"))
        self.apply_local_button.clicked.connect(self.__resolve_as_local)
        self.apply_remote_button.setIcon(material_icon("cloud"))
        self.apply_remote_button.clicked.connect(self.__resolve_as_remote)

    def __setup_modified_modified(self) -> None:
        pass

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

        grid_layout.setContentsMargins(0, 0, 0, 0)

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

        deleted_label = QLabel(self.tr("Feature was deleted"))
        deleted_label.setAlignment(
            Qt.Alignment()
            | Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignVCenter
        )
        deleted_groupbox.layout().addWidget(deleted_label)

        grid_layout.addWidget(deleted_groupbox, 1, deleted_column, -1, 1)

        marker_icon = material_icon(
            "fiber_manual_record", color="#f1ea64", size=16
        )
        for i, field in enumerate(self.__container_metadata.fields, start=1):
            marker = QLabel(grid_widget)
            marker.setToolTip(self.tr("Field changed"))
            marker.setObjectName(f"FieldChangedMarker_{field.keyname}")
            draw_icon(marker, marker_icon)
            grid_layout.addWidget(marker, i, 0)

            field_name = QLabel(field.display_name, self.delete_update_widget)
            field_name.setToolTip(field.keyname)
            grid_layout.addWidget(field_name, i, 1)

            edit_widget = self.__create_field_widget(field, grid_widget)
            edit_widget.setObjectName(f"FieldEditWidget_{field.keyname}")
            edit_widget.setReadOnly(True)
            grid_layout.addWidget(edit_widget, i, existed_column)

        # Geometry
        geometry_row = len(self.__container_metadata.fields) + 1

        marker = QLabel(grid_widget)
        marker.setObjectName("GeometryChangedMarker")
        marker.setToolTip(self.tr("Geometry changed"))
        draw_icon(marker, marker_icon)
        grid_layout.addWidget(marker, geometry_row, 0)

        field_name = QLabel(self.tr("Geometry"), grid_widget)
        grid_layout.addWidget(field_name, geometry_row, 1)

        canvas_widget = self.__create_geometry_widget(grid_widget)
        canvas_widget.setObjectName("CanvasWidget")
        grid_layout.addWidget(canvas_widget, geometry_row, existed_column)

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
            marker = grid_widget.findChild(
                QLabel, f"FieldChangedMarker_{field.keyname}"
            )
            marker.setVisible(field.ngw_id in changed_fields)
            edit_widget = grid_widget.findChild(
                QWidget, f"FieldEditWidget_{field.keyname}"
            )
            self.__set_field_value(
                edit_widget,
                field,
                feature.attribute(field.attribute),
            )

        marker = grid_widget.findChild(QLabel, "GeometryChangedMarker")
        marker.setVisible(action.geom is not None)

        canvas_widget = grid_widget.findChild(QStackedWidget, "CanvasWidget")
        self.__set_feature_to_canvas(canvas_widget, feature)

    def __fill_update_update(self, item: ConflictResolvingItem) -> None:
        pass

    @pyqtSlot(QItemSelection, QItemSelection)
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
            widget = QSpinBox(parent)
            widget.setMinimum(-(1 << 31))
            widget.setMaximum((1 << 31) - 1)
            widget.setSpecialValueText("NULL")
        elif field.datatype == NgwDataType.BIGINT:
            widget = QDoubleSpinBox(parent)
            widget.setMinimum(-(1 << 63))
            widget.setMaximum((1 << 63) - 1)
            widget.setSingleStep(1)
            widget.setDecimals(0)
            widget.setSpecialValueText("NULL")
        elif field.datatype == NgwDataType.REAL:
            widget = QDoubleSpinBox(parent)
            widget.setMinimum(-1e37)
            widget.setMaximum(1e37)
            widget.setDecimals(6)
            widget.setSpecialValueText("NULL")
        elif field.datatype == NgwDataType.DATE:
            widget = QDateEdit(parent)
            widget.setSpecialValueText("NULL")
        elif field.datatype == NgwDataType.TIME:
            widget = QTimeEdit(parent)
            widget.setSpecialValueText("NULL")
        elif field.datatype == NgwDataType.DATETIME:
            widget = QDateTimeEdit(parent)
            widget.setSpecialValueText("NULL")
        else:  # STRING
            widget = QLineEdit(parent)
            widget.setPlaceholderText("NULL")

        return widget

    def __set_field_value(
        self, edit_widget: QWidget, field: NgwField, value: Any
    ) -> None:
        edit_widget.blockSignals(True)

        is_null = isinstance(value, QVariant) and value.isNull()

        if field.datatype in (
            NgwDataType.INTEGER,
            NgwDataType.BIGINT,
            NgwDataType.REAL,
        ):
            edit_widget.setValue(
                value if not is_null else edit_widget.minimum()
            )
        elif field.datatype == NgwDataType.DATE:
            time = (
                QDate.fromString(value, Qt.DateFormat.ISODate)
                if not is_null
                else edit_widget.minimumDate()
            )
            edit_widget.setDate(time)
        elif field.datatype == NgwDataType.TIME:
            date = (
                QTime.fromString(value, Qt.DateFormat.ISODate)
                if not is_null
                else edit_widget.minimumTime()
            )
            edit_widget.setTime(date)
        elif field.datatype == NgwDataType.DATETIME:
            date_time = (
                QDateTime.fromString(value, Qt.DateFormat.ISODate)
                if not is_null
                else edit_widget.minimumDateTime()
            )
            edit_widget.setDateTime(date_time)
        else:  # STRING
            edit_widget.setText(str(value) if not is_null else "")

        edit_widget.blockSignals(False)

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

        rubber_band = QgsRubberBand(canvas, self.__geometry_type)
        rubber_band.setColor(QColor(255, 0, 0, 100))
        rubber_band.show()

        canvas.setProperty("rubber_band", rubber_band)

        widget.addWidget(canvas)

        deleted_groupbox = QGroupBox(widget)
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

        deleted_label = QLabel(self.tr("Geometry is not set"))
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
        self, canvas_widget: QStackedWidget, feature: QgsFeature
    ) -> None:
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
