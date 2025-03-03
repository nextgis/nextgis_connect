from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, cast

from qgis.core import (
    QgsApplication,
    QgsIconUtils,
    QgsWkbTypes,
)
from qgis.gui import QgsGui
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QSize,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QIcon, QKeyEvent
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QWidget,
)

from nextgis_connect.compat import FieldType, WkbType
from nextgis_connect.core.ui.checkbox_delegate import (
    CheckBoxDelegate,
)
from nextgis_connect.core.ui.header_with_cenetered_icon_proxy_style import (
    HeaderWithCenteredIconProxyStyle,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.resources.ngw_data_type_delegate import (
    NgwDataTypeDelegate,
)
from nextgis_connect.resources.ngw_field import NgwDataType
from nextgis_connect.resources.ngw_fields_model import NgwFieldsModel
from nextgis_connect.resources.utils import generate_unique_name
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings
from nextgis_connect.tree_widget.item import QNGWResourceItem

VectorLayerCreationDialogBase, _ = uic.loadUiType(
    str(Path(__file__).parent / "vector_layer_creation_dialog_base.ui")
)


class VectorLayerCreationDialog(QDialog, VectorLayerCreationDialogBase):
    SUPPORTED_WKB_TYPES: ClassVar[List[WkbType]] = [
        WkbType.Point,
        WkbType.LineString,
        WkbType.Polygon,
        WkbType.MultiPoint,
        WkbType.MultiLineString,
        WkbType.MultiPolygon,
    ]

    SUPPORTED_FIELD_TYPES: ClassVar[List[FieldType]] = [
        FieldType.Int,
        FieldType.LongLong,
        FieldType.Double,
        FieldType.QString,
        FieldType.QDate,
        FieldType.QDateTime,
    ]

    validity_changed = pyqtSignal(bool)

    __resources_model: QAbstractItemModel
    __parent_resource_index: QModelIndex

    def __init__(
        self,
        resources_model: QAbstractItemModel,
        parent_resource_index: QModelIndex,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.__resources_model = resources_model
        self.__parent_resource_index = parent_resource_index
        self.__result_resource = None
        self.__setup_ui()

    def accept(self) -> None:
        parent_id = self.__resources_model.data(
            self.__parent_resource_index, QNGWResourceItem.NGWResourceIdRole
        )
        display_name = self.layer_name_lineedit.text()
        fields = self.fields_view.model().fields.to_json()
        is_versioning_enabled = self.versioning_checkbox.isChecked()
        geometry_type = WkbType(self.geometry_combobox.currentData())
        if self.z_checkbox.isChecked():
            geometry_type = QgsWkbTypes.addZ(geometry_type)
        geometry_type = QgsWkbTypes.displayString(geometry_type).upper()

        self.__result_resource = dict(
            resource=dict(
                cls=NGWVectorLayer.type_id,
                parent=dict(id=parent_id),
                display_name=display_name,
            ),
            feature_layer=dict(versioning=dict(enabled=is_versioning_enabled)),
            vector_layer=dict(
                srs=dict(id=3857),
                geometry_type=geometry_type,
                fields=fields,
            ),
        )

        NgConnectSettings().add_vector_layer_after_creation = (
            self.add_to_project_checkbox.isChecked()
        )
        return super().accept()

    @property
    def resource(self) -> Optional[Dict[str, Any]]:
        return self.__result_resource

    @property
    def add_to_project(self) -> bool:
        return self.add_to_project_checkbox.isChecked()

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        assert a0 is not None
        if a0.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            a0.accept()
            return
        super().keyPressEvent(a0)

    def __setup_ui(self) -> None:
        self.setupUi(self)
        QgsGui.enableAutoGeometryRestore(self)

        self.__setup_tabs()
        self.__setup_new_field_ui()
        self.__setup_fields_view()
        self.__setup_button_box()

    def __setup_tabs(self) -> None:
        # Init validation
        self.layer_name_lineedit.setText(
            generate_unique_name(
                self.tr("Vector Layer"), self.__siblings_names()
            )
        )
        self.layer_name_lineedit.textChanged.connect(self.__validate)
        self.geometry_combobox.currentIndexChanged.connect(self.__validate)

        # Init parent
        self.parent_combobox.setModel(self.__resources_model)
        self.parent_combobox.setRootModelIndex(
            self.__parent_resource_index.parent()
        )
        self.parent_combobox.setCurrentIndex(
            self.__parent_resource_index.row()
        )

        # Init warnings
        warning_icon = QgsApplication.getThemeIcon("mIconWarning.svg")
        size = int(max(24.0, self.layer_name_lineedit.minimumSize().height()))
        pixmap = warning_icon.pixmap(
            warning_icon.actualSize(QSize(size, size))
        )

        self.layer_name_warning_label.setPixmap(pixmap)
        self.layer_name_warning_label.hide()

        for geometry_type in self.SUPPORTED_WKB_TYPES:
            self.geometry_combobox.addItem(
                QgsIconUtils.iconForWkbType(geometry_type),
                QgsWkbTypes.translatedDisplayString(geometry_type),
                int(geometry_type),
            )

        # Set invalid geometry type for conscious choice
        self.geometry_combobox.setCurrentIndex(-1)

        # Versioning
        self.versioning_checkbox.setChecked(
            NgConnectSettings().upload_vector_with_versioning
        )

        icon_path = Path(__file__).parents[2] / "icons" / "experimental.svg"
        experimental_icon = QIcon(str(icon_path))
        size = int(
            max(18.0, self.versioning_warning_label.minimumSize().height())
        )
        pixmap = experimental_icon.pixmap(
            experimental_icon.actualSize(QSize(size, size))
        )

        self.versioning_warning_label.setPixmap(pixmap)
        self.versioning_warning_label.setToolTip(
            self.tr(
                "Experimental feature. Some operations may not work if feature"
                " versioning is enabled."
            )
        )

    def __setup_new_field_ui(self) -> None:
        # Init warning
        warning_icon = QgsApplication.getThemeIcon("mIconWarning.svg")
        size = int(
            max(24.0, self.field_keyname_lineedit.minimumSize().height())
        )
        pixmap = warning_icon.pixmap(
            warning_icon.actualSize(QSize(size, size))
        )
        self.field_keyname_warning_label.setPixmap(pixmap)
        self.field_keyname_warning_label.hide()

        # Init field name
        self.add_field_button.setEnabled(False)
        self.__display_name_last_value = ""
        self.field_display_name_lineedit.textChanged.connect(
            self.__on_display_name_changed
        )
        self.field_keyname_lineedit.textChanged.connect(
            self.__validate_new_field
        )
        self.field_keyname_lineedit.returnPressed.connect(self.__add_field)
        self.field_display_name_lineedit.returnPressed.connect(
            self.__add_field
        )

        # Init field types
        for ngw_type in NgwDataType:
            self.field_type_combobox.addItem(
                ngw_type.icon, ngw_type.name, ngw_type.qt_value
            )

        # Setup button
        self.add_field_button.setIcon(
            QgsApplication.getThemeIcon("mActionNewAttribute.svg")
        )
        self.add_field_button.clicked.connect(self.__add_field)

    def __setup_fields_view(self):
        # Init icons
        self.remove_field_button.setIcon(
            QgsApplication.getThemeIcon("mActionDeleteAttribute.svg")
        )
        self.move_up_button.setIcon(
            QgsApplication.getThemeIcon("mActionArrowUp.svg")
        )
        self.move_down_button.setIcon(
            QgsApplication.getThemeIcon("mActionArrowDown.svg")
        )

        # Init buttons
        self.remove_field_button.clicked.connect(self.__remove_fields)
        self.move_up_button.clicked.connect(self.__move_field_up)
        self.move_down_button.clicked.connect(self.__move_field_down)

        # Init model
        model = NgwFieldsModel(None, self.fields_view)

        # Setup view
        self.fields_view.setModel(model)
        self.fields_view.horizontalHeader().setSectionResizeMode(
            NgwFieldsModel.Column.DISPLAY_NAME, QHeaderView.ResizeMode.Stretch
        )
        self.fields_view.horizontalHeader().setSectionResizeMode(
            NgwFieldsModel.Column.KEYNAME, QHeaderView.ResizeMode.Stretch
        )
        self.fields_view.setColumnWidth(NgwFieldsModel.Column.IS_LABEL, 20)
        self.fields_view.setColumnWidth(
            NgwFieldsModel.Column.IS_USED_FOR_SEARCH, 20
        )
        self.fields_view.setColumnWidth(NgwFieldsModel.Column.IS_VISIBLE, 20)
        self.__header_proxy_style = HeaderWithCenteredIconProxyStyle()
        self.fields_view.horizontalHeader().setStyle(self.__header_proxy_style)
        self.fields_view.doubleClicked.connect(self.__on_double_clicked)

        model.rowsInserted.connect(self.__update_fields_view_buttons)
        model.rowsInserted.connect(self.__validate)
        model.rowsRemoved.connect(self.__update_fields_view_buttons)
        model.rowsRemoved.connect(self.__validate)
        model.rowsMoved.connect(self.__update_fields_view_buttons)
        self.fields_view.selectionModel().selectionChanged.connect(
            self.__update_fields_view_buttons
        )
        self.__update_fields_view_buttons()

        datatype_delegate = NgwDataTypeDelegate(self.fields_view)
        self.fields_view.setItemDelegateForColumn(
            NgwFieldsModel.Column.DATATYPE, datatype_delegate
        )

        checkbox_delegate = CheckBoxDelegate(self.fields_view)
        self.fields_view.setItemDelegateForColumn(
            NgwFieldsModel.Column.IS_VISIBLE, checkbox_delegate
        )
        self.fields_view.setItemDelegateForColumn(
            NgwFieldsModel.Column.IS_USED_FOR_SEARCH, checkbox_delegate
        )
        self.fields_view.setItemDelegateForColumn(
            NgwFieldsModel.Column.IS_LABEL, checkbox_delegate
        )

    def __setup_button_box(
        self,
    ):
        self.add_to_project_checkbox.setChecked(
            NgConnectSettings().add_vector_layer_after_creation
        )

        add_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        )
        add_button.setText(self.tr("Create"))
        add_button.setEnabled(False)

        add_button.clicked.connect(self.accept)
        self.validity_changed.connect(add_button.setEnabled)

        close_button = self.button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        close_button.clicked.connect(self.reject)

    def __validate_new_field(self):
        keyname = self.field_keyname_lineedit.text()
        display_name = self.field_display_name_lineedit.text()

        need_tooltip = False
        tooltip = ""

        if self.fields_view.model().has_field(keyname):
            need_tooltip = True
            tooltip = self.tr("Keyname already exists")

        elif keyname in ("geom",):
            need_tooltip = True
            tooltip = self.tr("Keyname reserved by NextGIS Web")

        self.field_keyname_warning_label.setVisible(need_tooltip)
        self.field_keyname_warning_label.setToolTip(tooltip)

        is_valid = (
            len(display_name) > 0 and len(keyname) > 0 and not need_tooltip
        )

        self.add_field_button.setEnabled(is_valid)

    def __update_fields_view_buttons(self):
        selection = self.fields_view.selectionModel()
        selected_rows = selection.selectedRows()

        remove_enabled = False
        move_up_enabled = False
        move_down_enabled = False

        if len(selected_rows) == 1:
            remove_enabled = True
            selected_row = selected_rows[0].row()
            first_row = 0
            move_up_enabled = selected_row > first_row
            last_row = self.fields_view.model().rowCount() - 1
            move_down_enabled = selected_row < last_row
        elif len(selected_rows) > 1:
            remove_enabled = True

        self.remove_field_button.setEnabled(remove_enabled)
        self.move_up_button.setEnabled(move_up_enabled)
        self.move_down_button.setEnabled(move_down_enabled)

    def __validate(self):
        geometry_id_valid = self.geometry_combobox.currentIndex() >= 0
        layer_name = self.layer_name_lineedit.text()
        layer_name_is_valid = len(layer_name) > 0
        layer_name_is_unique = layer_name not in self.__siblings_names()

        self.layer_name_warning_label.setVisible(not layer_name_is_unique)

        self.validity_changed.emit(
            geometry_id_valid and layer_name_is_valid and layer_name_is_unique
        )

    def __add_field(self):
        if not self.add_field_button.isEnabled():
            return

        cast(NgwFieldsModel, self.fields_view.model()).create_field(
            self.field_display_name_lineedit.text(),
            self.field_keyname_lineedit.text(),
            NgwDataType.from_qt_value(self.field_type_combobox.currentData()),
            is_label=self.label_attribute_checkbox.isChecked(),
            is_visible=self.feature_table_checkbox.isChecked(),
            is_used_for_search=self.text_search_checkbox.isChecked(),
        )
        self.field_display_name_lineedit.clear()
        self.field_keyname_lineedit.clear()
        self.field_display_name_lineedit.setFocus()
        self.label_attribute_checkbox.setChecked(False)

        for column in (
            NgwFieldsModel.Column.IS_VISIBLE,
            NgwFieldsModel.Column.IS_USED_FOR_SEARCH,
            NgwFieldsModel.Column.IS_LABEL,
        ):
            self.fields_view.openPersistentEditor(
                self.fields_view.model().index(
                    self.fields_view.model().rowCount() - 1, column
                )
            )

    def __remove_fields(self):
        selection = self.fields_view.selectionModel()
        selected_rows = [index.row() for index in selection.selectedRows()]
        selected_rows.sort(reverse=True)

        for row in selected_rows:
            self.fields_view.model().removeRow(row)

        self.__validate_new_field()

    @pyqtSlot()
    def __move_field_up(self):
        model = self.fields_view.model()
        if model.rowCount() == 0:
            return

        selection = self.fields_view.selectionModel()
        selected_rows = selection.selectedRows()
        first_row = 0
        if len(selected_rows) != 1 or selected_rows[0].row() == first_row:
            return

        row = selected_rows[0].row()
        model.moveRow(QModelIndex(), row, QModelIndex(), row - 1)

    @pyqtSlot()
    def __move_field_down(self):
        model = self.fields_view.model()
        if model.rowCount() == 0:
            return

        selection = self.fields_view.selectionModel()
        selected_rows = selection.selectedRows()

        last_row = model.rowCount() - 1
        if len(selected_rows) != 1 or selected_rows[0].row() == last_row:
            return

        row = selected_rows[0].row()
        model.moveRow(QModelIndex(), row, QModelIndex(), row + 1)

    @pyqtSlot(str)
    def __on_display_name_changed(self, new_value: str) -> None:
        keyname = self.field_keyname_lineedit.text()
        keyname_from_last_value = self.__display_name_to_keyname(
            self.__display_name_last_value
        )
        if keyname_from_last_value == keyname:
            self.field_keyname_lineedit.setText(
                self.__display_name_to_keyname(new_value)
            )
        self.__display_name_last_value = new_value
        self.__validate_new_field()

    @pyqtSlot(QModelIndex)
    def __on_double_clicked(self, index: QModelIndex) -> None:
        if index.column() not in (
            NgwFieldsModel.Column.IS_VISIBLE,
            NgwFieldsModel.Column.IS_USED_FOR_SEARCH,
            NgwFieldsModel.Column.IS_LABEL,
        ):
            return

        model = self.fields_view.model()
        value = model.data(index, Qt.ItemDataRole.EditRole)
        model.setData(index, not value, Qt.ItemDataRole.EditRole)

    def __display_name_to_keyname(self, display_name: str) -> str:
        return "".join(
            char if char.isalnum() or char == "_" else "_"
            for char in display_name.lower()
        )

    def __siblings_names(self) -> List[str]:
        return [
            self.__resources_model.data(
                self.__resources_model.index(
                    row, 0, self.__parent_resource_index
                )
            )
            for row in range(
                self.__resources_model.rowCount(self.__parent_resource_index)
            )
        ]
