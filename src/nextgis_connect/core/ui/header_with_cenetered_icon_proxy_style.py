from typing import Optional, cast

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QIcon, QPainter
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

        header = cast(QStyleOptionHeader, option)

        # Get header icon
        icon = header.icon
        if icon.isNull():
            super().drawControl(element, option, painter, widget)
            return

        icon_extent = self.pixelMetric(
            QStyle.PixelMetric.PM_SmallIconSize, option
        )

        # Set icon size
        icon_size = QSize(icon_extent, icon_extent)
        rect = header.rect

        # Create icon pixmap
        pixmap = icon.pixmap(
            icon_size,
            QIcon.Mode.Normal
            if header.state & QStyle.StateFlag.State_Enabled
            else QIcon.Mode.Disabled,
        )

        # Calculate rect
        aligned_rect = self.alignedRect(
            header.direction,
            Qt.AlignmentFlag.AlignCenter,
            pixmap.size() / pixmap.devicePixelRatio(),
            rect,
        )
        intersection = aligned_rect.intersected(rect)

        # Draw icon
        painter.drawPixmap(
            intersection.x(),
            intersection.y(),
            pixmap,
            intersection.x() - aligned_rect.x(),
            intersection.y() - aligned_rect.y(),
            int(aligned_rect.width() * pixmap.devicePixelRatio()),
            int(pixmap.height() * pixmap.devicePixelRatio()),
        )
