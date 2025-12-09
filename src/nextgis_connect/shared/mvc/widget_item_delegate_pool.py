"""Widget pool and event forwarding for widget-based item delegates.

Manages widget instances per model index, wires event forwarding from
embedded widgets back to the view's viewport, and handles lifecycle
operations such as clearing and validation.
"""

from enum import IntEnum
from typing import TYPE_CHECKING, Dict, List, Optional, cast

from qgis.PyQt import sip
from qgis.PyQt.QtCore import (
    QAbstractProxyModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPointF,
)
from qgis.PyQt.QtGui import QInputEvent, QMouseEvent, QTabletEvent, QWheelEvent
from qgis.PyQt.QtWidgets import (
    QApplication,
    QStyleOptionViewItem,
    QWidget,
)

from nextgis_connect.logging import logger

if TYPE_CHECKING:
    from src.nextgis_connect.shared.mvc.widget_item_delegate import (
        WidgetItemDelegate,
    )


class WidgetItemDelegateEventListener(QObject):
    """Forward input events from embedded widgets to the viewport.

    Handles safe destruction notifications and regenerates input events
    in the viewport coordinate system, unless they are explicitly
    blocked by the delegate for a particular widget.

    Python port of KWidgetItemDelegateEventListener (KItemViews)

    :ivar _pool: Pool managing widgets and related state.
    :vartype _pool: WidgetItemDelegatePool
    """

    def __init__(
        self, pool: "WidgetItemDelegatePool", parent: Optional[QObject] = None
    ) -> None:
        """Initialize event listener.

        :param pool: Owning widget pool instance.
        :type pool: WidgetItemDelegatePool
        :param parent: Optional QObject parent.
        :type parent: Optional[QObject]
        """
        super().__init__(parent)
        self._pool = pool

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        """Filter widget events and forward to the view's viewport.

        :param watched: Observed object (expected to be a QWidget).
        :type watched: QObject
        :param event: Event to filter and possibly forward.
        :type event: QEvent
        :return: ``True`` if handled; otherwise calls base implementation.
        :rtype: bool
        """
        widget = watched

        if not isinstance(widget, QWidget):
            return super().eventFilter(watched, event)

        DestroyType = QEvent.Type(16)  # QEvent.Type.Destroy
        if event.type() == DestroyType and not self._pool.is_clearing:
            logger.warning(
                "User of WidgetItemDelegate should not delete widgets created by createItemWidgets!"
            )
            # assume the application has kept a list of widgets and tries to
            # delete them manually they have been reparented to the view in
            # any case, so no leaking occurs
            self._pool._widget_in_index.pop(widget, None)
            viewport = self._pool.delegate.item_view().viewport()
            QApplication.sendEvent(viewport, event)
            return super().eventFilter(watched, event)

        # Forward input events to the viewport if the type is not blocked
        blocked_types = self._pool.delegate._blocked_event_types(widget)
        if not isinstance(event, QInputEvent) or event.type() in blocked_types:
            return super().eventFilter(watched, event)

        viewport = self._pool.delegate.item_view().viewport()

        try:
            if event.type() in (
                QEvent.Type.MouseMove,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
            ):
                mouse_event: QMouseEvent = cast(QMouseEvent, event)
                new_mouse_event = QMouseEvent(
                    event.type(),
                    viewport.mapFromGlobal(mouse_event.globalPos()),
                    mouse_event.button(),
                    mouse_event.buttons(),
                    mouse_event.modifiers(),
                )

                QApplication.sendEvent(viewport, new_mouse_event)

            elif event.type() == QEvent.Type.Wheel:
                wheel_event: QWheelEvent = cast(QWheelEvent, event)

                new_wheel_event = QWheelEvent(
                    viewport.mapFromGlobal(wheel_event.position().toPoint()),
                    viewport.mapFromGlobal(
                        wheel_event.globalPosition().toPoint()
                    ),
                    wheel_event.pixelDelta(),
                    wheel_event.angleDelta(),
                    wheel_event.buttons(),
                    wheel_event.modifiers(),
                    wheel_event.phase(),
                    wheel_event.inverted(),
                    wheel_event.source(),
                )
                QApplication.sendEvent(viewport, new_wheel_event)

            elif event.type() in (
                QEvent.Type.TabletMove,
                QEvent.Type.TabletPress,
                QEvent.Type.TabletRelease,
                QEvent.Type.TabletEnterProximity,
                QEvent.Type.TabletLeaveProximity,
            ):
                tablet_event: QTabletEvent = cast(QTabletEvent, event)
                # Qt5/Qt6 compatibility: compute global/local positions
                if hasattr(tablet_event, "globalPosition"):
                    new_tablet_event = QTabletEvent(
                        event.type(),
                        tablet_event.pointingDevice(),  # type: ignore
                        viewport.mapFromGlobal(tablet_event.globalPosition()),  # type: ignore
                        tablet_event.globalPosition(),  # type: ignore
                        tablet_event.pressure(),  # type: ignore
                        tablet_event.xTilt(),
                        tablet_event.yTilt(),
                        tablet_event.tangentialPressure(),  # type: ignore
                        tablet_event.rotation(),
                        tablet_event.z(),
                        tablet_event.modifiers(),
                        tablet_event.button(),  # type: ignore
                        tablet_event.buttons(),
                    )
                else:
                    new_tablet_event = QTabletEvent(
                        event.type(),
                        QPointF(
                            viewport.mapFromGlobal(tablet_event.globalPos())
                        ),
                        tablet_event.globalPosF(),
                        tablet_event.deviceType(),
                        tablet_event.pointerType(),
                        tablet_event.pressure(),
                        tablet_event.xTilt(),
                        tablet_event.yTilt(),
                        tablet_event.tangentialPressure(),
                        tablet_event.rotation(),
                        tablet_event.z(),
                        tablet_event.modifiers(),
                        tablet_event.uniqueId(),
                        tablet_event.button(),
                        tablet_event.buttons(),
                    )

                QApplication.sendEvent(viewport, new_tablet_event)

            else:
                # Forward the original event
                QApplication.sendEvent(viewport, event)

        except Exception:
            # Do not break event loop on unexpected errors
            logger.exception(
                "Error forwarding event %s from widget %s to viewport",
                event,
                widget,
            )

        return super().eventFilter(watched, event)


class WidgetItemDelegatePool:
    """Manage widgets created by a widget-based item delegate.

    Stores per-index widget lists, installs event filters to forward
    input to the viewport, and updates or clears widgets on model/view
    changes.

    Python port of KWidgetItemDelegatePool (KItemViews)

    :ivar _delegate: Owning delegate instance.
    :vartype _delegate: WidgetItemDelegate
    :ivar _event_listener: Event listener instance for forwarding.
    :vartype _event_listener: WidgetItemDelegateEventListener
    :ivar _used_widgets: Mapping from persistent index to widgets list.
    :vartype _used_widgets: Dict[QPersistentModelIndex, List[QWidget]]
    :ivar _widget_in_index: Reverse mapping from widget to index.
    :vartype _widget_in_index: Dict[QWidget, QPersistentModelIndex]
    :ivar _is_clearing: Internal flag to suppress warnings during clear.
    :vartype _is_clearing: bool
    """

    class UpdateWidgetsEnum(IntEnum):
        """Control whether to update widget geometry/state."""

        UpdateWidgets = 0
        NotUpdateWidgets = 1

    def __init__(self, delegate: "WidgetItemDelegate") -> None:
        """Initialize widget pool for the provided delegate.

        :param delegate: Delegate owning this pool.
        :type delegate: WidgetItemDelegate
        """
        self._delegate = delegate
        self._event_listener = WidgetItemDelegateEventListener(self)
        self._used_widgets: Dict[QPersistentModelIndex, list[QWidget]] = {}
        self._widget_in_index: Dict[QWidget, QPersistentModelIndex] = {}
        self._is_clearing: bool = False

    @property
    def is_clearing(self) -> bool:
        """Return whether the pool is currently clearing widgets.

        :return: ``True`` if in clearing phase, otherwise ``False``.
        :rtype: bool
        """
        return self._is_clearing

    @property
    def delegate(self) -> "WidgetItemDelegate":
        """Return the owning delegate.

        :return: Delegate associated with this pool.
        :rtype: WidgetItemDelegate
        """
        return self._delegate

    def find_and_update_widgets(
        self,
        index: QPersistentModelIndex,
        option: QStyleOptionViewItem,
        updateWidgets: UpdateWidgetsEnum = UpdateWidgetsEnum.UpdateWidgets,
    ) -> List[QWidget]:
        """Return and optionally update widgets for an index.

        Creates widgets on first use, reuses them subsequently, and when
        requested updates their visible state and geometry.

        :param index: Persistent index for which to obtain widgets.
        :type index: QPersistentModelIndex
        :param option: Style option describing item rectangle/state.
        :type option: QStyleOptionViewItem
        :param updateWidgets: Whether to update widget state/geometry.
        :type updateWidgets: WidgetItemDelegatePool.UpdateWidgetsEnum
        :return: List of widgets associated with the index.
        :rtype: List[QWidget]
        """
        result: List[QWidget] = []

        if not index or not index.isValid():
            return result

        # If idx belongs to a proxy model, map to source
        model = index.model()
        if isinstance(model, QAbstractProxyModel):
            source_index = model.mapToSource(QModelIndex(index))
        else:
            source_index = QModelIndex(index)

        if not source_index.isValid():
            return result

        persistent_source_index = QPersistentModelIndex(source_index)

        if persistent_source_index in self._used_widgets:
            result = self._used_widgets[persistent_source_index]
        else:
            # Create item widgets via delegate and register them
            result = list(self._delegate._create_item_widgets(source_index))
            self._used_widgets[persistent_source_index] = result
            viewport = self._delegate.item_view().viewport()
            for widget in result:
                self._widget_in_index[widget] = persistent_source_index
                widget.setParent(viewport)
                widget.installEventFilter(self._event_listener)
                widget.setVisible(True)

        if updateWidgets == self.UpdateWidgetsEnum.UpdateWidgets:
            for widget in result:
                widget.setVisible(True)

            # Ask delegate to update widgets
            self._delegate._update_item_widgets(result, option, index)

            # Move according to option.rect
            rect = option.rect
            left = rect.left()
            top = rect.top()
            for widget in result:
                widget.move(widget.x() + left, widget.y() + top)

        return result

    def invalid_indexes_widgets(self) -> List[QWidget]:
        """Return widgets whose associated indexes are invalid.

        :return: Widgets bound to invalid or stale indexes.
        :rtype: List[QWidget]
        """
        result: List[QWidget] = []

        # Delegate's model can be a proxy; map from source to proxy before validation
        delegate_model = self._delegate.item_view().model()
        for widget, persistent_index in list(self._widget_in_index.items()):
            index: QModelIndex

            if isinstance(delegate_model, QAbstractProxyModel):
                index = delegate_model.mapFromSource(
                    QModelIndex(persistent_index)
                )

            else:
                index = QModelIndex(persistent_index)

            if not index.isValid():
                result.append(widget)

        return result

    def full_clear(self) -> None:
        """Delete all managed widgets and reset internal mappings."""
        self._is_clearing = True

        for widget in list(self._widget_in_index.keys()):
            sip.delete(widget)

        self._is_clearing = False

        self._used_widgets.clear()
        self._widget_in_index.clear()
