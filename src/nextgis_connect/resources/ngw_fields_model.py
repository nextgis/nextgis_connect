from dataclasses import replace
from enum import IntEnum, auto
from typing import Any, Optional

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Qt,
    QVariant,
)

from nextgis_connect.resources.ngw_field import NgwDataType, NgwField
from nextgis_connect.resources.ngw_fields import NgwFields
from nextgis_connect.utils import material_icon


class NgwFieldsModel(QAbstractTableModel):
    class Column(IntEnum):
        DISPLAY_NAME = 0
        KEYNAME = auto()
        DATATYPE = auto()
        IS_VISIBLE = auto()
        IS_USED_FOR_SEARCH = auto()
        IS_LABEL = auto()

    __fields: NgwFields

    def __init__(
        self,
        fields: Optional[NgwFields] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.__fields = NgwFields([]) if fields is None else fields

        self.__is_visible_icon = material_icon("table_chart")
        self.__is_used_for_search_icon = material_icon("manage_search")
        self.__is_label_icon = material_icon("font_download")

    @property
    def fields(self) -> NgwFields:
        return self.__fields

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        flags = super().flags(index)
        if index.column() != self.Column.KEYNAME:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(self.__fields)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return len(NgwFieldsModel.Column)

    def headerData(
        self, section, orientation, role=Qt.ItemDataRole.DisplayRole
    ):
        # QgsApplication.translated due to incorrect handling of nested classes
        # by pylupdate

        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                if section == NgwFieldsModel.Column.DISPLAY_NAME:
                    return QgsApplication.translate(
                        "NgwFieldsModel", "Display name"
                    )
                elif section == NgwFieldsModel.Column.KEYNAME:
                    return QgsApplication.translate(
                        "NgwFieldsModel", "Keyname"
                    )
                elif section == NgwFieldsModel.Column.DATATYPE:
                    return QgsApplication.translate("NgwFieldsModel", "Type")
            else:
                return 1 + section

        elif role == Qt.ItemDataRole.ToolTipRole:
            if orientation == Qt.Orientation.Horizontal:
                if section == NgwFieldsModel.Column.IS_VISIBLE:
                    return QgsApplication.translate(
                        "NgwFieldsModel", "Feature table"
                    )
                elif section == NgwFieldsModel.Column.IS_USED_FOR_SEARCH:
                    return QgsApplication.translate(
                        "NgwFieldsModel", "Text search"
                    )
                elif section == NgwFieldsModel.Column.IS_LABEL:
                    return QgsApplication.translate(
                        "NgwFieldsModel", "Label Attribute"
                    )

        elif role == Qt.ItemDataRole.DecorationRole:
            if orientation == Qt.Orientation.Horizontal:
                if section == NgwFieldsModel.Column.IS_VISIBLE:
                    return self.__is_visible_icon
                elif section == NgwFieldsModel.Column.IS_USED_FOR_SEARCH:
                    return self.__is_used_for_search_icon
                elif section == NgwFieldsModel.Column.IS_LABEL:
                    return self.__is_label_icon

        return QVariant()

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return QVariant()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            field = self.__fields[index.row()]
            if index.column() == NgwFieldsModel.Column.DISPLAY_NAME:
                return field.display_name
            elif index.column() == NgwFieldsModel.Column.KEYNAME:
                return field.keyname
            elif index.column() == NgwFieldsModel.Column.DATATYPE:
                return (
                    field.datatype.name
                    if role == Qt.ItemDataRole.DisplayRole
                    else field.datatype.qt_value
                )

        if role == Qt.ItemDataRole.EditRole:
            field = self.__fields[index.row()]
            if index.column() == NgwFieldsModel.Column.IS_VISIBLE:
                return field.is_visible
            elif index.column() == NgwFieldsModel.Column.IS_USED_FOR_SEARCH:
                return field.is_used_for_search
            elif index.column() == NgwFieldsModel.Column.IS_LABEL:
                return field.is_label

        elif role == Qt.ItemDataRole.DecorationRole:
            field = self.__fields[index.row()]
            if index.column() == NgwFieldsModel.Column.DATATYPE:
                return field.datatype.icon

        return QVariant()

    def setData(
        self,
        index: QModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return super().setData(index, value, role)

        column_to_field = {
            self.Column.DISPLAY_NAME: "display_name",
            self.Column.KEYNAME: "keyname",
            self.Column.DATATYPE: "datatype",
            self.Column.IS_VISIBLE: "is_visible",
            self.Column.IS_USED_FOR_SEARCH: "is_used_for_search",
            self.Column.IS_LABEL: "is_label",
        }

        field_name = column_to_field[self.Column(index.column())]
        if index.column() == self.Column.DATATYPE:
            value = NgwDataType.from_qt_value(value)
        changed_value = {field_name: value}

        self.__fields[index.row()] = replace(
            self.__fields[index.row()], **changed_value
        )

        if index.column() == self.Column.IS_LABEL:
            self.dataChanged.emit(
                self.index(0, self.Column.IS_LABEL),
                self.index(self.rowCount() - 1, self.Column.IS_LABEL),
            )
        else:
            self.dataChanged.emit(index, index)

        return True

    def removeRow(self, row: int, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: B008
        self.beginRemoveRows(parent, row, row)
        del self.__fields[row]
        self.endRemoveRows()
        return True

    def moveRow(
        self,
        sourceParent: QModelIndex,
        sourceRow: int,
        destinationParent: QModelIndex,
        destinationChild: int,
    ) -> bool:
        if (
            sourceRow < 0
            or sourceRow >= len(self.__fields)
            or destinationChild < 0
            or destinationChild >= len(self.__fields)
        ):
            return False

        # https://doc.qt.io/qt-6/qabstractitemmodel.html#beginMoveRows
        target_row = (
            destinationChild + 1
            if destinationChild > sourceRow
            else destinationChild
        )

        self.beginMoveRows(
            sourceParent, sourceRow, sourceRow, destinationParent, target_row
        )
        self.__fields.move(sourceRow, destinationChild)
        self.endMoveRows()

        return True

    def create_field(
        self,
        display_name: str,
        keyname: str,
        datatype: NgwDataType,
        is_label: bool,
        is_visible: bool,
        is_used_for_search: bool,
    ):
        new_field = NgwField(
            ngw_id=-1,
            datatype=datatype,
            keyname=keyname,
            display_name=display_name,
            is_label=is_label,
            is_visible=is_visible,
            is_used_for_search=is_used_for_search,
        )

        self.beginInsertRows(
            QModelIndex(), len(self.__fields), len(self.__fields)
        )
        self.__fields.append(new_field)
        self.endInsertRows()

        if new_field.is_label:
            self.dataChanged.emit(
                self.index(0, self.Column.IS_LABEL),
                self.index(self.rowCount() - 1, self.Column.IS_LABEL),
            )

    def has_field(self, keyname: str) -> bool:
        return self.__fields.find_with(keyname=keyname) is not None
