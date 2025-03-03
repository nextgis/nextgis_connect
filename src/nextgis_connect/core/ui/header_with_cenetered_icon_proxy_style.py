from typing import Optional

from qgis.PyQt.QtCore import QRect, QSize
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleOption,
    QStyleOptionHeader,
    QWidget,
)


class HeaderWithCenteredIconProxyStyle(QProxyStyle):
    def drawControl(
        self,
        element: QStyle.ControlElement,
        option: QStyleOption,
        painter: QPainter,
        widget: Optional[QWidget] = None,
    ) -> None:
        """
        Custom header drawing with centered icon
        """
        if element != QStyle.ControlElement.CE_HeaderLabel or not isinstance(
            option, QStyleOptionHeader
        ):
            super().drawControl(element, option, painter, widget)
            return

        # Get header icon
        icon = option.icon
        if icon.isNull():
            super().drawControl(element, option, painter, widget)
            return

        # Set icon size
        icon_size = QSize(16, 16)
        rect = option.rect

        # Create icon pixmap
        icon_pixmap = icon.pixmap(icon_size.width(), icon_size.height())

        # Calculate text width
        icon_x_offset = (rect.width() - icon_size.width()) // 2
        icon_y_offset = (rect.height() - icon_size.height()) // 2

        icon_rect = QRect(
            rect.left() + icon_x_offset,
            rect.top() + icon_y_offset,
            icon_pixmap.width(),
            icon_pixmap.height(),
        )

        # Draw icon and text
        painter.drawPixmap(icon_rect, icon_pixmap)
