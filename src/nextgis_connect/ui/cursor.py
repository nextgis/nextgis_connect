import math
from dataclasses import dataclass
from enum import Enum

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtGui import QCursor, QFontMetrics

from nextgis_connect.ui.icon import plugin_icon


@dataclass
class _CursorMetadata:
    """
    Represents information about a cursor.

    :param icon: Path to the cursor icon.
    :type icon: str
    :param active_x: X-coordinate of the cursor's active point.
    :type active_x: int
    :param active_y: Y-coordinate of the cursor's active point.
    :type active_y: int
    """

    icon: str
    active_x: int
    active_y: int


class NgConnectCursor(Enum):
    """
    Enum representing available cursors for the NextGIS Connect plugin.

    :cvar IDENTIFY: Cursor for the "Identify" tool.
    """

    IDENTIFY = _CursorMetadata("cursors/identification.svg", 3, 6)


def create_cursor(cursor: NgConnectCursor) -> QCursor:
    """
    Generate a QCursor object based on the provided NgConnectCursor.

    This function creates a cursor using the icon and active point
    specified in the `_CursorMetadata` of the given `NgConnectCursor`.
    Based on QgsApplication::getThemeCursor.

    :param cursor: The cursor type to generate.
    :type cursor: NgConnectCursor
    :return: A QCursor object for the specified cursor type.
    :rtype: QCursor
    """
    DEFAULT_ICON_SIZE = 32.0

    icon = plugin_icon(cursor.value.icon)
    if icon is None or icon.isNull():
        return QCursor()

    font_metrics = QFontMetrics(QgsApplication.font())
    scale = Qgis.UI_SCALE_FACTOR * font_metrics.height() / DEFAULT_ICON_SIZE
    cursor = QCursor(
        icon.pixmap(
            math.ceil(DEFAULT_ICON_SIZE * scale),
            math.ceil(DEFAULT_ICON_SIZE * scale),
        ),
        math.ceil(cursor.value.active_x * scale),
        math.ceil(cursor.value.active_y * scale),
    )

    return cursor
