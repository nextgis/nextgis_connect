from typing import Optional

from qgis.PyQt.QtCore import QAbstractItemModel, QModelIndex, Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)


class CheckBoxDelegate(QStyledItemDelegate):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

    def createEditor(
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QWidget:
        checkbox = QCheckBox(parent)
        checkbox.stateChanged.connect(lambda: self.commitData.emit(checkbox))
        return checkbox

    def setEditorData(self, editor: QComboBox, index: QModelIndex):
        value = index.model().data(index, Qt.ItemDataRole.EditRole)
        editor.setChecked(bool(value))

    def setModelData(
        self,
        editor: QComboBox,
        model: Optional[QAbstractItemModel],
        index: QModelIndex,
    ) -> None:
        model.setData(index, editor.isChecked(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(
        self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        rect = option.rect
        editor.setGeometry(
            rect.x() + (rect.width() - editor.sizeHint().width()) // 2,
            rect.y() + (rect.height() - editor.sizeHint().height()) // 2,
            editor.sizeHint().width(),
            editor.sizeHint().height(),
        )
