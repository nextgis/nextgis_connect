from typing import Optional

from qgis.PyQt.QtCore import QEvent, Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QMouseEvent
from qgis.PyQt.QtWidgets import QLabel, QWidget


class NgwButton(QLabel):
    clicked = pyqtSignal()

    __cursor: QCursor

    def __init__(self, text: str, parent: Optional[QWidget]) -> None:
        super().__init__(text, parent)
        self.setObjectName("NgwButton")
        self.setStyleSheet(
            """
            border-radius: 16px;
            background-color: #006fc4;
            color: white;
            padding: 8px 10px;
            """
        )
        self.__cursor = self.cursor()

    def mousePressEvent(self, ev: Optional[QMouseEvent]) -> None:
        self.clicked.emit()

    def enterEvent(self, a0: Optional[QEvent]) -> None:
        self.__cursor = self.cursor()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            """
            border-radius: 16px;
            background-color: #00599f;
            color: white;
            padding: 8px 10px;
            """
        )
        super().enterEvent(a0)

    def leaveEvent(self, a0: Optional[QEvent]) -> None:
        self.setCursor(self.__cursor)
        self.setStyleSheet(
            """
            border-radius: 16px;
            background-color: #006fc4;
            color: white;
            padding: 8px 10px;
            """
        )
        super().leaveEvent(a0)
