from typing import Optional

from qgis.PyQt.QtCore import QAbstractItemModel, QModelIndex, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from nextgis_connect.resources.ngw_data_type import NgwDataType
from nextgis_connect.resources.ngw_fields_model import NgwFieldsModel


class NgwDataTypeDelegate(QStyledItemDelegate):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

    def createEditor(
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QWidget:
        if index.column() != NgwFieldsModel.Column.DATATYPE:
            return super().createEditor(parent, option, index)

        editor = QComboBox(parent)
        for datatype in NgwDataType:
            editor.addItem(datatype.icon, datatype.name, datatype.qt_value)
        return editor

    def setEditorData(self, editor: QComboBox, index: QModelIndex):
        if index.column() != NgwFieldsModel.Column.DATATYPE:
            super().setEditorData(editor, index)

        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        found_index = editor.findData(value)
        editor.setCurrentIndex(found_index)

    def setModelData(
        self,
        editor: QComboBox,
        model: Optional[QAbstractItemModel],
        index: QModelIndex,
    ) -> None:
        if index.column() != NgwFieldsModel.Column.DATATYPE:
            super().setModelData(editor, model, index)

        model.setData(index, editor.currentData(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(
        self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        editor.setGeometry(option.rect)
