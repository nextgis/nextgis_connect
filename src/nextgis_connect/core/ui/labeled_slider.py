from typing import List, Optional

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QFontMetrics, QPaintEvent
from qgis.PyQt.QtWidgets import (
    QSlider,
    QStyleOptionSlider,
    QStylePainter,
    QWidget,
)


class LabeledSlider(QSlider):
    """
    QSlider subclass with text labels under each tick.
    """

    __labels: List[str]

    SPACE_SIZE = 10

    def __init__(self, labels: List[str], parent: Optional[QWidget]) -> None:
        """
        Initialize the labeled slider.

        :param labels: List of labels to display under the ticks.
        :param parent: Optional parent widget.
        """
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
        """
        Get the current slider index.

        :return: Current slider value.
        """
        return self.value()

    def paintEvent(self, event: QPaintEvent) -> None:
        """
        Paint the slider and draw labels under each tick.

        :param event: Paint event.
        """
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
            text_width = font_metricts.horizontalAdvance(text)
            if tick == self.minimum():
                align_x = x
            elif tick == self.maximum():
                align_x = x - text_width
            else:
                align_x = round(x - text_width / 2)

            y = self.height()
            painter.drawText(align_x, y, text)

    def sizeHint(self) -> QSize:
        """
        Return the recommended size for the slider, accounting for label height.

        :return: Recommended size.
        """
        size = super().sizeHint()
        font_metrics = QFontMetrics(self.font())
        size.setHeight(size.height() + font_metrics.height())
        return size
