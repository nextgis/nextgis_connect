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
    """Map identification tool for detached layers.

    Manage map canvas identification interactions and delegate event
    processing to an internal `IdentificationSelectionHandler` used for
    detached editing workflows.

    :ivar geometry_changed: Signal emitted when selection geometry changes.
    :vartype geometry_changed: pyqtSignal(QgsGeometry, Qt.MouseButton, Qt.KeyboardModifier)
    :ivar clear: Signal emitted to request clearing current selection.
    :vartype clear: pyqtSignal
    """

    geometry_changed = pyqtSignal(
        QgsGeometry, Qt.MouseButton, Qt.KeyboardModifier
    )
    clear = pyqtSignal()

    def __init__(self, canvas: QgsMapCanvas) -> None:
        """Initialize the identification tool.

        Set up the mouse cursor, allow multiple identify returns and
        connect the internal selection handler.

        :param canvas: Map canvas used by the tool.
        :type canvas: QgsMapCanvas
        """
        super().__init__(canvas)
        self.setCursor(create_cursor(NgConnectCursor.IDENTIFY))

        self.identifyMenu().setAllowMultipleReturn(True)

        self._selection_handler = IdentificationSelectionHandler(canvas, self)
        self._selection_handler.geometry_changed.connect(self.geometry_changed)
        self.deactivated.connect(self._selection_handler.cancel)

    def canvasPressEvent(self, e: Optional[QgsMapMouseEvent]) -> None:
        """Handle canvas press events and delegate to the selection handler.

        :param e: Mouse event provided by QGIS on canvas press.
        :type e: Optional[QgsMapMouseEvent]
        """
        assert e is not None
        self._selection_handler.process_press_event(e)

    def canvasMoveEvent(self, e: Optional[QgsMapMouseEvent]) -> None:
        """Handle canvas move events and delegate to the selection handler.

        :param e: Mouse event provided by QGIS on canvas move.
        :type e: Optional[QgsMapMouseEvent]
        """
        assert e is not None
        self._selection_handler.process_move_event(e)

    def canvasReleaseEvent(self, e: Optional[QgsMapMouseEvent]) -> None:
        """Handle canvas release events and delegate to the selection handler.

        :param e: Mouse event provided by QGIS on canvas release.
        :type e: Optional[QgsMapMouseEvent]
        """
        assert e is not None
        self._selection_handler.process_release_event(e)

    def keyReleaseEvent(self, e: Optional[QKeyEvent]) -> None:
        """Handle key release events.

        The key event is first offered to the selection handler. If the
        handler consumes it, no further action is taken. If the Escape
        key is pressed the `clear` signal is emitted. Otherwise the
        default superclass handling is invoked.

        :param e: Key event provided by QGIS.
        :type e: Optional[QKeyEvent]
        """
        assert e is not None
        if self._selection_handler.process_key_release_event(e):
            return

        if e.key() == Qt.Key.Key_Escape:
            self.clear.emit()
            return

        super().keyReleaseEvent(e)
