from abc import ABCMeta, abstractmethod
from typing import Optional

from qgis.PyQt.QtCore import Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QKeyEvent
from qgis.PyQt.QtWidgets import QCompleter, QLineEdit, QWidget


class MetaLineEdit(ABCMeta, type(QLineEdit)): ...


class AbstractSearchLineEdit(QLineEdit, metaclass=MetaLineEdit):
    search_requested = pyqtSignal(str)
    reset_requested = pyqtSignal()

    _completer: QCompleter

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setClearButtonEnabled(True)

        # Completer
        self._completer = QCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(self._completer)

        # Search
        self.returnPressed.connect(self.search)
        self.textEdited.connect(self.__reset_if_empty)

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        if (
            len(self.text()) != 0
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
