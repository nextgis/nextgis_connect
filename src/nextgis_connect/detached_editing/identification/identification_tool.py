from typing import Optional

from qgis.core import QgsGeometry
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsMapToolIdentify
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QKeyEvent

from nextgis_connect.detached_editing.identification.selection_handler import (
    IdentificationSelectionHandler,
)
from nextgis_connect.ui.cursor import NgConnectCursor, create_cursor


class IdentificationTool(QgsMapToolIdentify):
    """Handle detached-layer identification on the map canvas.

    Delegate mouse and key events to the internal selection handler and
    expose signals used by the identification manager to start feature
    lookup or clear the current results when the active interaction is
    cancelled.

    :ivar geometry_changed: Emit selected geometry together with the mouse
        button and keyboard modifiers that completed the interaction.
    :ivar clear: Emit a request to clear the current identification
        results.
    """

    geometry_changed = pyqtSignal(
        QgsGeometry, Qt.MouseButton, Qt.KeyboardModifier
    )
    clear = pyqtSignal()

    def __init__(self, canvas: QgsMapCanvas) -> None:
        """Initialize the identification tool.

        Configure the identify cursor, allow multiple identify results,
        and connect the internal selection handler signals.

        :param canvas: Map canvas used by the tool.
        """
        super().__init__(canvas)
        self.setCursor(create_cursor(NgConnectCursor.IDENTIFY))

        self.identifyMenu().setAllowMultipleReturn(True)

        self._selection_handler = IdentificationSelectionHandler(canvas, self)
        self._selection_handler.geometry_changed.connect(self.geometry_changed)
        self._selection_handler.clear.connect(self.clear)
        self.deactivated.connect(self._selection_handler.cancel)

    def canvasPressEvent(self, e: Optional[QgsMapMouseEvent]) -> None:
        """Forward canvas press events to the selection handler.

        :param e: Mouse event provided by QGIS on canvas press.
        """
        assert e is not None
        self._selection_handler.process_press_event(e)

    def canvasMoveEvent(self, e: Optional[QgsMapMouseEvent]) -> None:
        """Forward canvas move events to the selection handler.

        :param e: Mouse event provided by QGIS on canvas move.
        """
        assert e is not None
        self._selection_handler.process_move_event(e)

    def canvasReleaseEvent(self, e: Optional[QgsMapMouseEvent]) -> None:
        """Forward canvas release events to the selection handler.

        :param e: Mouse event provided by QGIS on canvas release.
        """
        assert e is not None
        self._selection_handler.process_release_event(e)

    def keyReleaseEvent(self, e: Optional[QKeyEvent]) -> None:
        """Handle key release events.

        Offer the event to the selection handler first. Stop processing
        when the handler consumes the event. Delegate all remaining keys
        to the base implementation.

        :param e: Key event provided by QGIS.
        """
        assert e is not None
        if self._selection_handler.process_key_release_event(e):
            return

        super().keyReleaseEvent(e)
