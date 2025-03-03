from dataclasses import replace
from enum import IntEnum, auto
from pathlib import Path
from typing import Any, Optional

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    QObject,
    Qt,
    QVariant,
)
from qgis.PyQt.QtGui import QIcon, QPainter, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer

from nextgis_connect.resources.ngw_field import NgwDataType, NgwField
from nextgis_connect.resources.ngw_fields import NgwFields


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

        icon_path = Path(__file__).parents[1] / "icons" / "material"
        self.__is_visible_icon = self.__colorized_qicon(
            icon_path / "table_chart.svg"
        )
        self.__is_used_for_search_icon = self.__colorized_qicon(
            icon_path / "manage_search.svg"
        )
        self.__is_label_icon = self.__colorized_qicon(
            icon_path / "font_download.svg"
        )

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
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                if section == NgwFieldsModel.Column.DISPLAY_NAME:
                    return self.tr("Display name")
                elif section == NgwFieldsModel.Column.KEYNAME:
                    return self.tr("Keyname")
                elif section == NgwFieldsModel.Column.DATATYPE:
                    return self.tr("Type")
            else:
                return 1 + section

        elif role == Qt.ItemDataRole.ToolTipRole:
            if orientation == Qt.Orientation.Horizontal:
                if section == NgwFieldsModel.Column.IS_VISIBLE:
                    return self.tr("Feature table")
                elif section == NgwFieldsModel.Column.IS_USED_FOR_SEARCH:
                    return self.tr("Text search")
                elif section == NgwFieldsModel.Column.IS_LABEL:
                    return self.tr("Label Attribute")

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

    def __colorized_qicon(
        self, icon_path: Path, fill_color: str = ""
    ) -> QIcon:
        svg_path = Path(icon_path)

        if not svg_path.exists():
            raise FileNotFoundError(f"SVG file not found: {svg_path}")

        with open(svg_path, encoding="utf-8") as file:
            svg_content = file.read()

        if not fill_color:
            fill_color = QgsApplication.palette().text().color().name()

        modified_svg = svg_content.replace(
            'fill="#ffffff"', f'fill="{fill_color}"'
        )

        byte_array = QByteArray(modified_svg.encode("utf-8"))
        renderer = QSvgRenderer()
        if not renderer.load(byte_array):
            raise ValueError("Failed to render modified SVG.")

        pixmap = QPixmap(renderer.defaultSize())
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        return QIcon(pixmap)
