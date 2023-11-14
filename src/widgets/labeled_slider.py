from typing import Optional, List

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QPaintEvent, QFontMetrics
from qgis.PyQt.QtWidgets import (
    QSlider, QStyleOptionSlider, QStylePainter, QWidget
)


class LabeledSlider(QSlider):
    __labels: List[str]

    SPACE_SIZE = 10

    def __init__(
        self, labels: List[str], parent: Optional[QWidget]
    ) -> None:
        super().__init__(parent)
        self.__labels = labels

        self.setOrientation(Qt.Orientation.Horizontal)
        self.setMinimum(0)
        self.setMaximum(len(self.__labels) - 1)
        self.setSingleStep(1)
        self.setPageStep(1)
        self.setTickInterval(1)
        self.setTickPosition(self.TickPosition.TicksBelow)

    @property
    def index(self) -> int:
        return self.value()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)

        painter = QStylePainter(self)
        option = QStyleOptionSlider()
        self.initStyleOption(option)

        font_metricts = QFontMetrics(painter.font())

        minimum = self.minimum()
        maximum = self.maximum() + 1
        tick_interval = self.tickInterval()
        for tick in range(minimum, maximum, tick_interval):
            x = self.style().sliderPositionFromValue(
                self.minimum(), self.maximum(), tick, self.width()
            )
            text = self.__labels[tick]
            text_width = font_metricts.width(text)
            if tick == self.minimum():
                align_x = x
            elif tick == self.maximum():
                align_x = x - text_width
            else:
                align_x = round(x - text_width / 2)

            y = self.height()
            painter.drawText(align_x, y, text)

    def sizeHint(self) -> QSize:
        size = super().sizeHint()
        font_metrics = QFontMetrics(self.font())
        size.setHeight(size.height() + font_metrics.height())
        return size
