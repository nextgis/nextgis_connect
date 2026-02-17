from typing import Any, Callable, Generic, Optional, Tuple, TypeVar  # noqa: I001

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsProject,
    QgsRasterLayer,
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
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime, QVariant, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.compat import GeometryType
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    BaseConflictResolvingItem,
)
from nextgis_connect.detached_editing.identification.settings import (
    IdentificationSettings,
)
from nextgis_connect.resources.ngw_data_type import NgwDataType
from nextgis_connect.resources.ngw_field import NgwField


TConflictItem = TypeVar("TConflictItem", bound=BaseConflictResolvingItem)


class ConflictTabBase(QWidget, Generic[TConflictItem]):
    item_changed = pyqtSignal(BaseConflictResolvingItem)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._item: Optional[TConflictItem] = None

    @property
    def item(self) -> Optional[TConflictItem]:
        return self._item

    @item.setter
    def item(self, item: Optional[TConflictItem]) -> None:
        self._item = item
        self._fill()

    def _on_item_modified(self) -> None:
        if self._item is None:
            return

        self.item_changed.emit(self._item)

    def _fill(self) -> None:
        raise NotImplementedError

    def _create_scroll_content_layout(
        self,
        header_text: str,
    ) -> Tuple[QWidget, QVBoxLayout]:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        header_widget = QWidget(self)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        changes_label = QLabel(header_text, header_widget)
        changes_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        header_layout.addWidget(changes_label)
        main_layout.addWidget(header_widget)

        scroll_area = QScrollArea(self)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)

        scroll_content = QWidget(scroll_area)
        scroll_content_layout = QVBoxLayout(scroll_content)
        scroll_content_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        return scroll_content, scroll_content_layout


class FeatureConflictBaseTab(
    ConflictTabBase[TConflictItem], Generic[TConflictItem]
):
    def __init__(
        self,
        geometry_type: GeometryType,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._geometry_type = geometry_type

    def _create_field_widget(
        self,
        parent: QWidget,
        field: NgwField,
        on_value_changed: Optional[Callable[[NgwField, Any], None]] = None,
    ) -> QWidget:
        if field.datatype == NgwDataType.INTEGER:
            widget = QgsSpinBox(parent)
            widget.setMinimum(-(1 << 31))
            widget.setMaximum((1 << 31) - 1)
            widget.setClearValueMode(
                QgsSpinBox.ClearValueMode.MinimumValue,
                "NULL",
            )
            widget.setShowClearButton(True)
            if on_value_changed is not None:
                widget.valueChanged.connect(
                    lambda value, f=field: on_value_changed(f, value)
                )
        elif field.datatype == NgwDataType.BIGINT:
            widget = QgsDoubleSpinBox(parent)
            widget.setMinimum(-(1 << 63))
            widget.setMaximum((1 << 63) - 1)
            widget.setSingleStep(1)
            widget.setDecimals(0)
            widget.setClearValueMode(
                QgsDoubleSpinBox.ClearValueMode.MinimumValue,
                "NULL",
            )
            widget.setShowClearButton(True)
            if on_value_changed is not None:
                widget.valueChanged.connect(
                    lambda value, f=field: on_value_changed(f, int(value))
                )
        elif field.datatype == NgwDataType.REAL:
            widget = QgsDoubleSpinBox(parent)
            widget.setMinimum(-1e37)
            widget.setMaximum(1e37)
            widget.setDecimals(6)
            widget.setClearValueMode(
                QgsDoubleSpinBox.ClearValueMode.MinimumValue,
                "NULL",
            )
            widget.setShowClearButton(True)
            if on_value_changed is not None:
                widget.valueChanged.connect(
                    lambda value, f=field: on_value_changed(f, value)
                )
        elif field.datatype == NgwDataType.DATE:
            widget = QgsDateEdit(parent)
            widget.setAllowNull(True)
            widget.setDisplayFormat("dd.MM.yyyy")
            if on_value_changed is not None:
                widget.dateValueChanged.connect(
                    lambda value, f=field: on_value_changed(f, value)
                )
        elif field.datatype == NgwDataType.TIME:
            widget = QgsTimeEdit(parent)
            widget.setAllowNull(True)
            widget.setDisplayFormat("HH:mm:ss")
            if on_value_changed is not None:
                widget.timeValueChanged.connect(
                    lambda value, f=field: on_value_changed(f, value)
                )
        elif field.datatype == NgwDataType.DATETIME:
            widget = QgsDateTimeEdit(parent)
            widget.setAllowNull(True)
            widget.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
            if on_value_changed is not None:
                widget.valueChanged.connect(
                    lambda value, f=field: on_value_changed(f, value)
                )
        else:
            widget = QgsFilterLineEdit(parent)
            widget.setShowClearButton(True)
            widget.setClearMode(QgsFilterLineEdit.ClearMode.ClearToNull)
            widget.setPlaceholderText("NULL")
            if on_value_changed is not None:
                widget.valueChanged.connect(
                    lambda value, f=field: on_value_changed(f, value)
                )

        return widget

    def _set_field_value(
        self,
        edit_widget: QWidget,
        field: NgwField,
        value: Any,
    ) -> None:
        is_null = value is None or (
            isinstance(value, QVariant) and value.isNull()
        )

        if field.datatype in (
            NgwDataType.INTEGER,
            NgwDataType.BIGINT,
            NgwDataType.REAL,
        ):
            if is_null:
                edit_widget.clear()
            else:
                edit_widget.setValue(value)
            return

        if field.datatype == NgwDataType.DATE:
            if isinstance(value, str):
                date = QDate.fromString(value, Qt.DateFormat.ISODate)
                edit_widget.setDate(date)
            elif isinstance(value, QDate):
                edit_widget.setDate(value)
            else:
                edit_widget.clear()
                edit_widget.displayNull()
            return

        if field.datatype == NgwDataType.TIME:
            if isinstance(value, str):
                time = QTime.fromString(value, Qt.DateFormat.ISODate)
                edit_widget.setTime(time)
            elif isinstance(value, QTime):
                edit_widget.setTime(value)
            else:
                edit_widget.clear()
                edit_widget.displayNull()
            return

        if field.datatype == NgwDataType.DATETIME:
            if isinstance(value, str):
                date_time = QDateTime.fromString(value, Qt.DateFormat.ISODate)
                edit_widget.setDateTime(date_time)
            elif isinstance(value, QDateTime):
                edit_widget.setDateTime(value)
            else:
                edit_widget.clear()
                edit_widget.displayNull()
            return

        if not is_null:
            edit_widget.setValue(value)
        else:
            edit_widget.clearValue()

    def _create_geometry_widget(self, parent: QWidget) -> QStackedWidget:
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

        rubber_band = QgsRubberBand(canvas, self._geometry_type)
        rubber_band.setColor(QColor(255, 0, 0, 100))
        rubber_band.show()

        canvas.setProperty("rubber_band", rubber_band)

        widget.addWidget(canvas)

        deleted_groupbox = QGroupBox(widget)
        deleted_groupbox.setTitle("")
        deleted_size_policy = deleted_groupbox.sizePolicy()
        deleted_size_policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        deleted_size_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        deleted_groupbox.setSizePolicy(deleted_size_policy)
        deleted_groupbox.setLayout(QVBoxLayout())

        deleted_label = QLabel(
            self.tr("Geometry is not set"), deleted_groupbox
        )
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

    def _set_feature_to_canvas(
        self,
        canvas_widget: Optional[QStackedWidget],
        feature: QgsFeature,
        *,
        is_unresolved: bool = False,
    ) -> None:
        if canvas_widget is None:
            return

        deleted_label = canvas_widget.findChild(QLabel, "GeometryDeletedLabel")
        if deleted_label is not None:
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
        if canvas is None:
            return

        canvas.property("rubber_band").setToGeometry(geometry, None)

        settings = IdentificationSettings()
        if (
            geometry.type() == GeometryType.Point
            and not QgsWkbTypes.isMultiType(geometry.wkbType())
        ):
            canvas.setCenter(geometry.asPoint())
            canvas.zoomScale(settings.zoom_map_scale)
        else:
            bounding_box = geometry.boundingBox()
            bounding_box.scale(settings.zoom_geometry_scale_factor)
            canvas.setExtent(bounding_box)
            canvas.zoomOut()

        canvas.refresh()

    def _clear_canvas(
        self,
        canvas_widget: Optional[QStackedWidget],
    ) -> None:
        if canvas_widget is None:
            return

        deleted_label = canvas_widget.findChild(QLabel, "GeometryDeletedLabel")
        if deleted_label is not None:
            deleted_label.setText(self.tr("Geometry is not set"))

        canvas = canvas_widget.findChild(QgsMapCanvas, "Canvas")
        if canvas is not None:
            rubber_band = canvas.property("rubber_band")
            if rubber_band is not None:
                rubber_band.reset(self._geometry_type)

        canvas_widget.setCurrentIndex(1)
