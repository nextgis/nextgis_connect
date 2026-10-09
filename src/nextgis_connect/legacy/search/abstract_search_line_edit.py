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

from abc import ABCMeta, abstractmethod
from typing import Optional

from qgis.PyQt.QtCore import QEvent, QObject, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QKeyEvent
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QLineEdit,
    QWidget,
)

from nextgis_connect.ui_kit.widgets.search_clear_action import (
    install_search_clear_action,
)


class MetaLineEdit(ABCMeta, type(QLineEdit)): ...


class SearchCompleter(QCompleter):
    def eventFilter(self, o: Optional[QObject], e: Optional[QEvent]) -> bool:
        editor = self.widget()
        if isinstance(
            editor, AbstractSearchLineEdit
        ) and editor._accept_completion_event(o, e):
            return True
        return super().eventFilter(o, e)


class AbstractSearchLineEdit(QLineEdit, metaclass=MetaLineEdit):
    search_requested = pyqtSignal(str)
    reset_requested = pyqtSignal()

    _completer: QCompleter
    _completion_popup: Optional[QAbstractItemView]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._init_search_actions()
        install_search_clear_action(self)

        # Completer
        self._completer = SearchCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(self._completer)
        # Accessing QCompleter.popup() from its event filter can re-enter the
        # filter on Qt 5 (QGIS 3.32).
        self._completion_popup = None
        self._completion_popup = self._completer.popup()
        self.installEventFilter(self)
        self._completion_popup.installEventFilter(self)

        # Search
        self.returnPressed.connect(self.search)
        self.textEdited.connect(self.__reset_if_empty)

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        if self._accept_completion_event(a0, a1):
            return True
        return super().eventFilter(a0, a1)

    def _init_search_actions(self) -> None:
        pass

    def _accept_completion_event(
        self, watched: Optional[QObject], event: Optional[QEvent]
    ) -> bool:
        popup = self._completion_popup
        if popup is None:
            return False
        if (
            watched in (self, popup)
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key()
            in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and popup.isVisible()
        ):
            index = popup.currentIndex()
            if not index.isValid() and popup.model().rowCount():
                index = popup.model().index(0, 0)
            if index.isValid():
                text = self._completer.pathFromIndex(index)
                popup.hide()
                self.setText(text)
                self.setFocus()
                self.setCursorPosition(len(text))
            event.accept()
            return True
        return False

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        if (
            self.isReadOnly()
            or len(self.text()) != 0
            or a0.key()
            not in (
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,
            )
            or self.completer() is None
            or self.completer().model() is None
        ):
            return super().keyPressEvent(a0)

        popup = self.completer().popup()
        if popup is None or popup.isVisible():
            return super().keyPressEvent(a0)

        self.completer().setCompletionPrefix("")
        self.completer().complete()
        a0.accept()

    @abstractmethod
    @pyqtSlot()
    def search(self) -> None: ...

    @pyqtSlot(str)
    def __reset_if_empty(self, search_string: str) -> None:
        if len(search_string) != 0:
            return

        self.reset_requested.emit()
