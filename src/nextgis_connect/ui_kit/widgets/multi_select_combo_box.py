# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

from html import escape
from typing import List, Optional

from qgis.PyQt.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QSignalBlocker,
    Qt,
    pyqtSignal,
)
from qgis.PyQt.QtGui import (
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QStandardItemModel,
    QWheelEvent,
)
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QLineEdit,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionMenuItem,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
)

from nextgis_connect.ui_kit.icons import material_icon

GROUP_HEADER_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class CheckableItemDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: Optional[QPainter],
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        if painter is None:
            return

        if index.data(GROUP_HEADER_ROLE):
            section = QStyleOptionMenuItem()
            section.rect = option.rect
            section.palette = option.palette
            section.font = option.font
            section.state = QStyle.StateFlag.State_Enabled
            section.menuItemType = QStyleOptionMenuItem.MenuItemType.Separator
            section.text = str(index.data(Qt.ItemDataRole.DisplayRole))
            widget = option.widget
            if widget is not None:
                section.palette = widget.palette()
                section.font = widget.font()
                widget.style().drawControl(
                    QStyle.ControlElement.CE_MenuItem, section, painter, widget
                )
            return

        item_option = QStyleOptionViewItem(option)
        if item_option.state & QStyle.StateFlag.State_MouseOver:
            item_option.state |= QStyle.StateFlag.State_Selected
        item_option.showDecorationSelected = True
        super().paint(painter, item_option, index)


class MultiSelectComboBox(QComboBox):
    checkedItemsChanged = pyqtSignal(list)
    returnPressed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._empty_tooltip = ""
        self._updating_selection = False
        self._default_text = ""
        self.setEditable(True)
        self.setView(QListView(self))
        self.setItemDelegate(CheckableItemDelegate(self))
        self.view().setMouseTracking(True)
        self.view().viewport().setMouseTracking(True)
        line_edit = self.lineEdit()
        assert line_edit is not None
        line_edit.setReadOnly(True)
        line_edit.installEventFilter(self)
        self.view().viewport().installEventFilter(self)
        self.view().installEventFilter(self)
        self._selection_icon_action = QAction(self)
        line_edit.addAction(
            self._selection_icon_action,
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self._selection_icon_button = next(
            button
            for button in line_edit.findChildren(QToolButton)
            if button.defaultAction() is self._selection_icon_action
        )
        self._selection_icon_button.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._selection_icon_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_action = QAction(material_icon("backspace"), "", self)
        self.clear_action.triggered.connect(self.clear_selection)
        line_edit.addAction(
            self.clear_action, QLineEdit.ActionPosition.TrailingPosition
        )
        self._clear_button = next(
            button
            for button in line_edit.findChildren(QToolButton)
            if button.defaultAction() is self.clear_action
        )
        self.model().dataChanged.connect(self._on_model_changed)
        self.model().rowsInserted.connect(self._update_selection)
        self.model().rowsRemoved.connect(self._update_selection)
        self.currentIndexChanged.connect(self._update_selection)
        self._update_selection()

    def setDefaultText(self, text: str) -> None:
        self._default_text = text
        self._update_selection()

    def defaultText(self) -> str:
        return self._default_text

    def addItemWithCheckState(
        self, text: str, state: Qt.CheckState, userData: object = None
    ) -> None:
        self.addItem(text, userData)
        self.setItemCheckState(self.count() - 1, state)

    def add_group_header(self, text: str) -> None:
        self.addItem(text)
        index = self.model().index(self.count() - 1, self.modelColumn())
        model = self.model()
        assert isinstance(model, QStandardItemModel)
        item = model.itemFromIndex(index)
        assert item is not None
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(True, GROUP_HEADER_ROLE)

    def itemCheckState(self, index: int) -> Qt.CheckState:
        value = self.itemData(index, Qt.ItemDataRole.CheckStateRole)
        return (
            Qt.CheckState.Unchecked if value is None else Qt.CheckState(value)
        )

    def setItemCheckState(self, index: int, state: Qt.CheckState) -> None:
        self.setItemData(index, state, Qt.ItemDataRole.CheckStateRole)

    def toggleItemCheckState(self, index: int) -> None:
        if not self._is_selectable(index):
            return
        self.setItemCheckState(
            index,
            Qt.CheckState.Unchecked
            if self.itemCheckState(index) == Qt.CheckState.Checked
            else Qt.CheckState.Checked,
        )

    def _is_selectable(self, index: int) -> bool:
        return bool(
            self.model().flags(self.model().index(index, self.modelColumn()))
            & Qt.ItemFlag.ItemIsEnabled
        )

    def checkedItems(self) -> List[str]:
        return [
            self.itemText(index)
            for index in range(self.count())
            if self.itemCheckState(index) == Qt.CheckState.Checked
        ]

    def checkedItemsData(self) -> List[object]:
        return [
            self.itemData(index)
            for index in range(self.count())
            if self.itemCheckState(index) == Qt.CheckState.Checked
        ]

    def _on_model_changed(self) -> None:
        self._update_selection()
        self.checkedItemsChanged.emit(self.checkedItems())

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        if a1 is None:
            return False
        if a0 in (self.lineEdit(), self.view()) and isinstance(a1, QKeyEvent):
            if a1.type() == QEvent.Type.KeyPress and a1.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                if self.isEnabled():
                    self.hidePopup()
                    self.returnPressed.emit()
                return True
        if a0 is self.lineEdit() and isinstance(a1, QMouseEvent):
            if a1.button() == Qt.MouseButton.LeftButton:
                if a1.type() == QEvent.Type.MouseButtonPress:
                    return True
                if a1.type() == QEvent.Type.MouseButtonRelease:
                    if self.isEnabled():
                        if self.view().isVisible():
                            self.hidePopup()
                        else:
                            self.showPopup()
                    return True
        if a0 is self.view() and isinstance(a1, QKeyEvent):
            if a1.type() == QEvent.Type.KeyPress and a1.key() in (
                Qt.Key.Key_Space,
            ):
                index = self.view().currentIndex()
                if self.isEnabled() and index.isValid():
                    self.toggleItemCheckState(index.row())
                return True
        if a0 is self.view().viewport() and isinstance(a1, QMouseEvent):
            if a1.type() == QEvent.Type.MouseButtonPress:
                return True
            if a1.type() == QEvent.Type.MouseButtonRelease:
                index = self.view().indexAt(a1.pos())
                if (
                    self.isEnabled()
                    and index.isValid()
                    and a1.button() == Qt.MouseButton.LeftButton
                ):
                    self.toggleItemCheckState(index.row())
                return True
        return super().eventFilter(a0, a1)

    def setToolTip(self, a0: Optional[str]) -> None:
        self._empty_tooltip = a0 or ""
        self._update_selection()

    def clear_selection(self) -> None:
        with QSignalBlocker(self.model()):
            for index in range(self.count()):
                self.setItemCheckState(index, Qt.CheckState.Unchecked)
        self._on_model_changed()

    def showPopup(self) -> None:
        if self.isEnabled():
            super().showPopup()

    def changeEvent(self, e: Optional[QEvent]) -> None:
        super().changeEvent(e)
        if not self.isEnabled():
            self.hidePopup()

    def _update_selection(self) -> None:
        if self._updating_selection:
            return
        self._updating_selection = True
        try:
            line_edit = self.lineEdit()
            assert line_edit is not None
            with QSignalBlocker(line_edit):
                self.setCurrentIndex(-1)
                line_edit.setText(
                    ", ".join(self.checkedItems()) or self._default_text
                )
            selected_labels = self.checkedItems()
            super().setToolTip(
                (
                    escape(
                        self.property("selectedToolTip") or self._empty_tooltip
                    )
                    + ":"
                    if self._empty_tooltip
                    else ""
                )
                + '<ul style="-qt-list-indent:0; margin:0; margin-left:14px; padding:0;">'
                + "".join(
                    f"<li>{escape(label)}</li>" for label in selected_labels
                )
                + "</ul>"
                if selected_labels
                else self._empty_tooltip
            )
            self.clear_action.setEnabled(bool(selected_labels))
            self.clear_action.setVisible(bool(selected_labels))
            self._clear_button.setVisible(bool(selected_labels))
            selected_indexes = [
                index
                for index in range(self.count())
                if self.itemCheckState(index) == Qt.CheckState.Checked
            ]
            show_icon = (
                len(selected_indexes) == 1
                and not self.itemIcon(selected_indexes[0]).isNull()
            )
            if show_icon:
                self._selection_icon_action.setIcon(
                    self.itemIcon(selected_indexes[0])
                )
            self._selection_icon_action.setVisible(show_icon)
            self._selection_icon_button.setVisible(show_icon)
            self.update()
        finally:
            self._updating_selection = False

    def keyPressEvent(self, e: Optional[QKeyEvent]) -> None:
        if e is not None and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.isEnabled():
                self.returnPressed.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e: Optional[QWheelEvent]) -> None:
        if not self.isEnabled():
            if e is not None:
                e.ignore()
            return
        selected_indexes = [
            index
            for index in range(self.count())
            if self.itemCheckState(index) == Qt.CheckState.Checked
        ]
        if len(selected_indexes) > 1:
            if e is not None:
                e.accept()
            return
        if e is None or not e.angleDelta().y() or not self.count():
            return
        previous_index = selected_indexes[0] if selected_indexes else -1
        step = -1 if e.angleDelta().y() > 0 else 1
        current_index = previous_index + step
        if previous_index == -1:
            current_index = 0
        while 0 <= current_index < self.count() and not self._is_selectable(
            current_index
        ):
            current_index += step
        e.accept()
        if (
            not 0 <= current_index < self.count()
            or current_index == previous_index
        ):
            return
        with QSignalBlocker(self.model()):
            for index in selected_indexes:
                self.setItemCheckState(index, Qt.CheckState.Unchecked)
            self.setItemCheckState(current_index, Qt.CheckState.Checked)
        self._on_model_changed()
