from enum import Enum, auto
from typing import Optional

from qgis.PyQt.QtCore import QEvent, Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QMouseEvent
from qgis.PyQt.QtWidgets import QLabel, QWidget


class NgwButton(QLabel):
    clicked = pyqtSignal()

    class Style(str, Enum):
        Normal = auto()
        Hover = auto()

    __cursor: QCursor

    def __init__(self, text: str, parent: Optional[QWidget]) -> None:
        super().__init__(text, parent)
        self.setObjectName("NgwButton")
        self.setStyleSheet(self.__stylesheet(self.Style.Normal))
        self.__cursor = self.cursor()

    def mousePressEvent(self, ev: Optional[QMouseEvent]) -> None:
        self.clicked.emit()

    def enterEvent(self, a0: Optional[QEvent]) -> None:
        self.__cursor = self.cursor()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self.__stylesheet(self.Style.Hover))
        super().enterEvent(a0)

    def leaveEvent(self, a0: Optional[QEvent]) -> None:
        self.setCursor(self.__cursor)
        self.setStyleSheet(self.__stylesheet(self.Style.Normal))
        super().leaveEvent(a0)

    def __stylesheet(self, style: Style) -> str:
        background_color = "#006fc4"
        if style == self.Style.Hover:
            background_color = "#00599f"

        vertical_padding = 8
        horizontal_padding = 10

        text_height = self.fontMetrics().boundingRect(self.text()).height()
        border_radius = (text_height + vertical_padding * 2) // 2

        return f"""
            border-radius: {border_radius}px;
            background-color: {background_color};
            color: white;
            padding: {vertical_padding}px {horizontal_padding}px;
        """
