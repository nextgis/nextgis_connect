from typing import ClassVar, Optional

from qgis.core import QgsApplication, QgsGeometry, QgsPointXY
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsRubberBand
from qgis.PyQt.QtCore import (
    QObject,
    QPoint,
    QRect,
    Qt,
    QVariantAnimation,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QColor, QKeyEvent

from nextgis_connect.compat import GeometryType
from nextgis_connect.core.constants import NEXTGIS_COLOR


class IdentificationSelectionHandler(QObject):
    """Track interactive point and rectangle selection on the canvas.

    Convert mouse interaction into a selection geometry, manage temporary
    rubber-band feedback for both drag rectangles and point highlights,
    and emit the completed selection context to the identification tool.
    Also emit a clear signal when the current interaction is cancelled.

    :ivar geometry_changed: Emit the selected geometry together with the
        mouse button and keyboard modifiers that completed the selection.
    :ivar clear: Emit a request to clear the current selection results.
    """

    POINT_SIZE: ClassVar[int] = 5
    POINT_STROKE_WIDTH: ClassVar[int] = 3

    FILL_COLOR_ALPHA: ClassVar[int] = 75
    STROKE_COLOR_ALPHA: ClassVar[int] = 150

    ANIMATION_DURATION: ClassVar[int] = 1000

    geometry_changed = pyqtSignal(
        QgsGeometry, Qt.MouseButton, Qt.KeyboardModifier
    )
    clear = pyqtSignal()

    def __init__(
        self, canvas: QgsMapCanvas, parent: Optional[QObject] = None
    ) -> None:
        """Initialize selection handler.

        :param canvas: Map canvas used for coordinate transforms and
            rubber band rendering.
        :param parent: Parent object.
        """
        super().__init__(parent)
        self._canvas = canvas
        self._init_position = QPoint()
        self._is_current_cancelled = False
        self._is_selection_active = False

        self._rectangle_fill_color = QColor(NEXTGIS_COLOR)
        self._rectangle_fill_color.setAlpha(self.FILL_COLOR_ALPHA)

        self._rectangle_stroke_color = QColor(NEXTGIS_COLOR)
        self._rectangle_stroke_color.setAlpha(self.STROKE_COLOR_ALPHA)

        self._point_color = QColor(NEXTGIS_COLOR)
        self._point_color.setAlpha(self.STROKE_COLOR_ALPHA)

        self._rubber_band = self._create_rectangle_rubber_band()
        self._point_rubber_band = self._create_point_rubber_band()
        self._point_fade_animation = QVariantAnimation(self)
        self._point_fade_animation.setDuration(self.ANIMATION_DURATION)
        self._point_fade_animation.setStartValue(self._point_color.alpha())
        self._point_fade_animation.setEndValue(0)
        self._point_fade_animation.valueChanged.connect(
            self._on_point_fade_animation_value_changed
        )
        self._point_fade_animation.finished.connect(
            self._on_point_fade_animation_finished
        )

    def __del__(self) -> None:
        """Release transient selection resources.

        Clear rubber bands and stop the point highlight animation.
        """
        self.cancel()

    @pyqtSlot()
    def cancel(self) -> None:
        """Cancel the current selection interaction.

        Reset temporary canvas feedback, stop the point fade animation,
        mark the handler as inactive, and emit ``clear`` without
        emitting ``geometry_changed``.
        """
        self._reset_visual_state()
        self._is_selection_active = False
        self._is_current_cancelled = True
        self.clear.emit()

    def process_press_event(self, event: QgsMapMouseEvent) -> None:
        """Start tracking a new selection interaction.

        Store the initial cursor position and clear any existing visual
        feedback from a previous interaction. Reset the cancelled flag so
        the new interaction can proceed.

        :param event: Mouse press event from the map canvas.
        """
        self._init_position = event.pos()
        self._is_current_cancelled = False
        self._reset_visual_state()

    def process_move_event(self, event: QgsMapMouseEvent) -> None:
        """Update rectangle feedback during a drag interaction.

        Ignore moves while the left mouse button is not pressed. Once the
        drag interaction starts, update the rectangle rubber band between
        the initial press position and the current cursor position. Ignore
        move events after the current interaction has been cancelled.

        :param event: Mouse move event from the map canvas.
        """
        if (
            not bool(event.buttons() & Qt.MouseButton.LeftButton)
            or self._is_current_cancelled
        ):
            return

        rectangle = QRect()
        if not self._is_selection_active:
            self._is_selection_active = True
            rectangle = QRect(event.pos(), event.pos())
        else:
            rectangle = QRect(event.pos(), self._init_position)

        self._rubber_band.setToCanvasRectangle(rectangle)

    def process_release_event(self, event: QgsMapMouseEvent) -> None:
        """Finalize the current selection and emit its geometry.

        Interpret short movement as a point selection and show a temporary
        point highlight. Interpret a completed drag interaction as a
        rectangle selection. Emit ``geometry_changed`` with the resulting
        geometry, released mouse button, and active keyboard modifiers.
        Ignore release events after cancellation.

        :param event: Mouse release event from the map canvas.
        """
        if self._is_current_cancelled:
            return

        movement_vector = event.pos() - self._init_position

        if not self._is_selection_active or (
            movement_vector.manhattanLength()
            < QgsApplication.startDragDistance()
        ):
            self._is_selection_active = False

            result_geometry = QgsGeometry.fromPointXY(
                self._to_map_coordinates(event.pos())
            )
            self._highlight_point(result_geometry)
            self._set_selected_geometry(
                result_geometry,
                event.button(),
                event.modifiers(),
            )

        if self._rubber_band is not None and self._is_selection_active:
            self._set_selected_geometry(
                self._rubber_band.asGeometry(),
                event.button(),
                event.modifiers(),
            )

        if self._rubber_band is not None:
            self._rubber_band.reset()

        self._is_selection_active = False

    def process_key_release_event(self, event: QKeyEvent) -> bool:
        """Handle key release events related to selection state.

        Consume Escape and cancel the current selection. Leave all other
        keys unhandled.

        :param event: Key event to process.
        :return: Return True when the event was handled.
        """
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
            return True

        return False

    def _create_rectangle_rubber_band(self) -> QgsRubberBand:
        """Create the rubber band used for rectangle feedback.

        Configure polygon fill and stroke colors for the drag-selection
        overlay shown on the map canvas.

        :return: Configured rubber band for rectangle selection feedback.
        """
        rubber_band = QgsRubberBand(self._canvas, GeometryType.Polygon)
        rubber_band.setFillColor(self._rectangle_fill_color)
        rubber_band.setStrokeColor(self._rectangle_stroke_color)
        return rubber_band

    def _create_point_rubber_band(self) -> QgsRubberBand:
        """Create the rubber band used for point feedback.

        Configure the point marker icon, color, size, and stroke width
        used to highlight a clicked location on the map canvas.

        :return: Configured rubber band for point selection feedback.
        """
        rubber_band = QgsRubberBand(self._canvas, GeometryType.Point)
        rubber_band.setIcon(QgsRubberBand.IconType.ICON_CIRCLE)
        rubber_band.setColor(self._point_color)
        rubber_band.setIconSize(self.POINT_SIZE)
        rubber_band.setWidth(self.POINT_STROKE_WIDTH)
        return rubber_band

    def _reset_visual_state(self) -> None:
        """Reset rubber bands and point fade animation state.

        Clear the rectangle overlay, stop the active point fade animation,
        and restore the point highlight color for the next interaction.
        """
        self._rubber_band.reset(GeometryType.Polygon)

        self._point_fade_animation.stop()
        self._point_rubber_band.reset(GeometryType.Point)
        self._point_rubber_band.setColor(self._point_color)

    def _highlight_point(self, geometry: QgsGeometry) -> None:
        """Highlight the selected point geometry.

        Display the point geometry on the canvas and start the fade-out
        animation for the temporary marker.

        :param geometry: Point geometry to highlight.
        """
        self._point_rubber_band.reset(GeometryType.Point)
        self._point_rubber_band.setToGeometry(
            geometry,
            self._canvas.mapSettings().destinationCrs(),
        )
        self._point_rubber_band.update()
        self._start_fade_animation()

    def _start_fade_animation(self) -> None:
        """Start the fade-out animation for the point rubber band.

        Restart the shared animation and fade the point rubber band to
        transparent.
        """
        self._point_fade_animation.stop()
        self._point_fade_animation.setStartValue(self._point_color.alpha())
        self._point_fade_animation.setEndValue(0)
        self._point_rubber_band.setColor(self._point_color)
        self._point_fade_animation.start()

    def _on_point_fade_animation_value_changed(self, value: int) -> None:
        """Apply the current animation alpha to the point rubber band.

        :param value: Alpha value produced by the fade animation.
        """
        color = QColor(self._point_color)
        color.setAlpha(value)
        self._point_rubber_band.setColor(color)
        self._point_rubber_band.update()

    def _on_point_fade_animation_finished(self) -> None:
        """Clear the temporary point highlight after fade-out finishes.

        Reset the point rubber band and restore its base color for the
        next point selection.
        """
        self._point_rubber_band.reset(GeometryType.Point)
        self._point_rubber_band.setColor(self._point_color)

    def _set_selected_geometry(
        self,
        geometry: QgsGeometry,
        button: Qt.MouseButton,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Emit the completed selection context.

        :param geometry: Geometry representing point or rectangle selection.
        :param button: Mouse button that completed the selection.
        :param modifiers: Keyboard modifiers active when selection completed.
        """
        self.geometry_changed.emit(geometry, button, modifiers)

    def _to_map_coordinates(self, point: QPoint) -> QgsPointXY:
        """Convert a canvas position to map coordinates.

        :param point: Point in canvas pixel coordinates.
        :return: Point converted to the current map coordinates.
        """
        return self._canvas.getCoordinateTransform().toMapCoordinates(point)
