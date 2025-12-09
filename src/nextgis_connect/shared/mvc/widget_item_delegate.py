"""Widget-based item delegate for Qt item views.

Provides a Python port of KWidgetItemDelegate to embed interactive
widgets into Qt item views and synchronize them with the model state.
"""

from typing import Dict, List, Optional

from qgis.PyQt.QtCore import (
    QAbstractListModel,
    QEvent,
    QItemSelection,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QTimer,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QStyleOptionViewItem,
    QTreeView,
    QWidget,
)

from nextgis_connect.logging import logger
from nextgis_connect.shared.mvc.widget_item_delegate_pool import (
    WidgetItemDelegatePool,
)


class WidgetItemDelegate(QAbstractItemDelegate):
    """Provide widget-embedding delegate for Qt item views.

    Embeds lightweight widgets (e.g., buttons, line edits) inside view
    items and coordinates their geometry and interactions with the
    underlying model.

    Python port of KWidgetItemDelegate (KItemViews)

    :ivar _item_view: Item view monitored by this delegate.
    :vartype _item_view: QAbstractItemView
    :ivar _blocked_events: Mapping of widget ids to blocked event types.
    :vartype _blocked_events: Dict[int, List[QEvent.Type]]
    :ivar _pool: Internal widget pool and event wiring helper.
    :vartype _pool: WidgetItemDelegatePool
    :ivar _model: Currently attached model or ``None``.
    :vartype _model: Optional[QObject]
    :ivar _selection_model: Current selection model or ``None``.
    :vartype _selection_model: Optional[QObject]
    :ivar _is_view_destroyed: Whether the view is being destroyed.
    :vartype _is_view_destroyed: bool
    """

    def __init__(
        self, item_view: QAbstractItemView, parent: Optional[QObject] = None
    ) -> None:
        """Initialize delegate for a given item view.

        :param item_view: Item view to monitor and decorate with widgets.
        :type item_view: QAbstractItemView
        :param parent: Optional QObject parent.
        :type parent: Optional[QObject]
        """

        super().__init__(parent)

        self._item_view: QAbstractItemView = item_view
        self._blocked_events: Dict[int, List[QEvent.Type]] = {}

        # Internal state (port of private d pointer)
        self._pool: WidgetItemDelegatePool = WidgetItemDelegatePool(self)
        self._model = None
        self._selection_model = None
        self._is_view_destroyed: bool = False

        # View configuration
        self._item_view.setMouseTracking(True)
        self._item_view.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)

        # Install event filters
        self._item_view.viewport().installEventFilter(self)  # mouse events
        self._item_view.installEventFilter(self)  # keyboard events

        # Tree view expansion/collapse re-initialization
        if isinstance(self._item_view, QTreeView):
            self._item_view.collapsed.connect(self._initialize_model)
            self._item_view.expanded.connect(self._initialize_model)

        # Deferred model initialization
        QTimer.singleShot(0, self._initialize_model)

    def __del__(self) -> None:
        """Release widget resources if the view still exists."""
        if not self._is_view_destroyed:
            try:
                self._pool.full_clear()
            except Exception:
                pass

    def item_view(self) -> QAbstractItemView:
        """Return the monitored item view.

        :return: The item view associated with this delegate.
        :rtype: QAbstractItemView
        """
        return self._item_view

    def focused_index(self) -> QPersistentModelIndex:
        """Return the currently focused model index.

        If no widget holds focus, the index under the mouse cursor is
        returned. The returned index may be invalid.

        :return: Focused persistent model index or invalid index.
        :rtype: QPersistentModelIndex
        """
        focused_widget = QApplication.focusWidget()
        if focused_widget is not None:
            persistent = self._pool._widget_in_index.get(focused_widget)
            if persistent and persistent.isValid():
                return QPersistentModelIndex(persistent)

        # Use the mouse position, if the widget refused to take keyboard focus.
        pos = self._item_view.viewport().mapFromGlobal(QCursor.pos())
        return QPersistentModelIndex(self._item_view.indexAt(pos))

    @pyqtSlot()
    def reset_model(self) -> None:
        """Trigger model reset and re-initialize widgets."""
        self._on_model_reset()

    def _create_item_widgets(self, index: QModelIndex) -> List[QWidget]:
        """Create widgets required to interact with an item.

        Widgets should be created but not positioned here. Signal wiring
        may be established at creation time.

        :param index: Model index to create widgets for.
        :type index: QModelIndex
        :return: Newly created widgets for the item.
        :rtype: List[QWidget]
        :raises NotImplementedError: If not implemented in subclass.
        """
        del index
        raise NotImplementedError("_create_item_widgets must be implemented")

    def _update_item_widgets(
        self,
        widgets: List[QWidget],
        option: QStyleOptionViewItem,
        index: QPersistentModelIndex,
    ) -> None:
        """Update widgets for painting and event handling.

        Geometry should be specified in item coordinates. Avoid creating
        or connecting signals here as this method is called frequently.

        :param widgets: Widgets previously created for the item.
        :type widgets: List[QWidget]
        :param option: Style options for the current item view state.
        :type option: QStyleOptionViewItem
        :param index: Persistent index of the item being updated.
        :type index: QPersistentModelIndex
        :raises NotImplementedError: If not implemented in subclass.
        """
        del widgets, option, index
        raise NotImplementedError("_update_item_widgets must be implemented")

    def _set_blocked_event_types(
        self, widget: QWidget, types: List[QEvent.Type]
    ) -> None:
        """Set event types to be blocked by a widget.

        Blocked events are not forwarded to the view.

        :param widget: Target widget; ignored if ``None``.
        :type widget: QWidget
        :param types: Event types to block for the widget.
        :type types: List[QEvent.Type]
        """

        if widget is None:
            return

        widget.setProperty("goya:blockedEventTypes", types)
        self._blocked_events[id(widget)] = list(types) if types else []

    def _blocked_event_types(self, widget: QWidget) -> List[QEvent.Type]:
        """Return blocked event types for a widget.

        :param widget: Widget to query.
        :type widget: QWidget
        :return: List of blocked event types (empty if none or widget is ``None``).
        :rtype: List[QEvent.Type]
        """
        if widget is None:
            return []

        prop = widget.property("goya:blockedEventTypes")
        if isinstance(prop, list):
            return list(prop)
        return list(self._blocked_events.get(id(widget), []))

    def _option_view(self, index: QModelIndex) -> QStyleOptionViewItem:
        """Build style option for a given index.

        :param index: Model index to describe.
        :type index: QModelIndex
        :return: Style option describing the item view state.
        :rtype: QStyleOptionViewItem
        """
        option = QStyleOptionViewItem()
        option.initFrom(self._item_view.viewport())
        option.rect = self._item_view.visualRect(index)
        option.decorationSize = self._item_view.iconSize()
        return option

    def _initialize_model(self, parent: Optional[QModelIndex] = None) -> None:
        """Initialize widgets for all visible indexes recursively.

        :param parent: Parent index to start traversal or ``None``.
        :type parent: Optional[QModelIndex]
        """
        if parent is None:
            parent = QModelIndex()

        model = self._item_view.model()
        if model is None:
            return

        row_count = model.rowCount(parent)
        column_count = (
            1
            if isinstance(model, QAbstractListModel)
            else model.columnCount(parent)
        )

        for row in range(row_count):
            for column in range(column_count):
                index = model.index(row, column, parent)
                if index.isValid():
                    self._pool.find_and_update_widgets(
                        QPersistentModelIndex(index), self._option_view(index)
                    )

            # Check if we need to go recursively through the children of
            # parent (if any) to initialize all possible indexes that are shown.
            first_column_index = model.index(row, 0, parent)
            if (
                first_column_index.isValid()
                and not isinstance(model, QAbstractListModel)
                and model.hasChildren(first_column_index)
            ):
                self._initialize_model(first_column_index)

    def _update_row_range(
        self,
        parent: QModelIndex,
        start: int,
        end: int,
        is_removing: bool,
    ) -> None:
        """Update widgets for a row range and handle removals.

        :param parent: Parent index of the rows.
        :type parent: QModelIndex
        :param start: Start row (inclusive).
        :type start: int
        :param end: End row (inclusive).
        :type end: int
        :param is_removing: Whether rows are being removed.
        :type is_removing: bool
        """
        model = self._item_view.model()
        if model is None:
            logger.warning(
                "WidgetItemDelegate: model is None in _update_row_range"
            )
            return

        for row in range(start, end + 1):
            column_count = (
                1
                if isinstance(model, QAbstractListModel)
                else model.columnCount(parent)
            )
            for column in range(column_count):
                index = model.index(row, column, parent)
                find_and_update_widgets_mode = (
                    WidgetItemDelegatePool.UpdateWidgetsEnum.NotUpdateWidgets
                    if is_removing
                    else WidgetItemDelegatePool.UpdateWidgetsEnum.UpdateWidgets
                )
                widgets = self._pool.find_and_update_widgets(
                    QPersistentModelIndex(index),
                    self._option_view(index),
                    find_and_update_widgets_mode,
                )

                if not is_removing:
                    continue

                for widget in widgets:
                    persistent_index = self._pool._widget_in_index.get(widget)
                    if persistent_index:
                        self._pool._used_widgets.pop(persistent_index, None)
                    self._pool._widget_in_index.pop(widget, None)
                    widget.deleteLater()

    @pyqtSlot(QModelIndex, int, int)
    def _on_rows_inserted(
        self, parent: QModelIndex, start: int, end: int
    ) -> None:
        """Update widgets after row insertion.

        :param parent: Parent index of the inserted rows.
        :type parent: QModelIndex
        :param start: First inserted row.
        :type start: int
        :param end: Last inserted row (unused for update extent).
        :type end: int
        """
        del end
        model = self._item_view.model()
        if model is None:
            logger.warning(
                "WidgetItemDelegate: model is None in _on_rows_inserted"
            )
            return

        # We need to update the rows behind the inserted row as well because
        # the widgets need to be moved to their new position
        self._update_row_range(parent, start, model.rowCount(parent), False)

    @pyqtSlot(QModelIndex, int, int)
    def _on_rows_about_to_be_removed(
        self, parent: QModelIndex, start: int, end: int
    ) -> None:
        """Prepare widgets before row removal.

        :param parent: Parent index of the rows to remove.
        :type parent: QModelIndex
        :param start: First row to remove.
        :type start: int
        :param end: Last row to remove.
        :type end: int
        """
        self._update_row_range(parent, start, end, True)

    @pyqtSlot(QModelIndex, int, int)
    def _on_rows_removed(
        self, parent: QModelIndex, start: int, end: int
    ) -> None:
        """Update widgets after rows have been removed.

        :param parent: Parent index of the removed rows.
        :type parent: QModelIndex
        :param start: First removed row.
        :type start: int
        :param end: Last removed row (unused for update extent).
        :type end: int
        """
        del end
        model = self._item_view.model()
        if model is None:
            logger.warning(
                "WidgetItemDelegate: model is None in _on_rows_removed"
            )
            return

        # We need to update the rows that come behind the deleted rows because
        # the widgets need to be moved to the new position
        self._update_row_range(parent, start, model.rowCount(parent), False)

    @pyqtSlot(QModelIndex, QModelIndex)
    def _on_data_changed(
        self, top_left: QModelIndex, bottom_right: QModelIndex
    ) -> None:
        """Update widgets in the changed data range.

        :param top_left: Top-left index of the changed region.
        :type top_left: QModelIndex
        :param bottom_right: Bottom-right index of the changed region.
        :type bottom_right: QModelIndex
        """
        model = self._item_view.model()
        if model is None:
            logger.warning(
                "WidgetItemDelegate: model is None in _on_data_changed"
            )
            return

        for row in range(top_left.row(), bottom_right.row() + 1):
            for column in range(top_left.column(), bottom_right.column() + 1):
                index = model.index(row, column, top_left.parent())
                self._pool.find_and_update_widgets(
                    QPersistentModelIndex(index), self._option_view(index)
                )

    @pyqtSlot()
    def _on_layout_changed(self) -> None:
        """Handle layout changes and re-initialize widgets."""
        invalid = self._pool.invalid_indexes_widgets()
        for widget in invalid:
            widget.setVisible(False)
        QTimer.singleShot(0, self._initialize_model)

    @pyqtSlot()
    def _on_model_reset(self) -> None:
        """Reset internal state, clear pool, and re-initialize widgets."""
        self._pool.full_clear()
        QTimer.singleShot(0, self._initialize_model)

    @pyqtSlot(QItemSelection, QItemSelection)
    def _on_selection_changed(
        self, selected: QItemSelection, deselected: QItemSelection
    ) -> None:
        """Update widgets for selection changes.

        :param selected: Newly selected indexes.
        :type selected: QItemSelection
        :param deselected: Newly deselected indexes.
        :type deselected: QItemSelection
        """
        for index in selected.indexes():
            self._pool.find_and_update_widgets(
                QPersistentModelIndex(index), self._option_view(index)
            )

        for index in deselected.indexes():
            self._pool.find_and_update_widgets(
                QPersistentModelIndex(index), self._option_view(index)
            )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        """Filter events to maintain model/view wiring and widgets.

        Dynamically (dis)connects to model and selection model signals
        and triggers widget updates in response to relevant view events.

        :param watched: Object being watched.
        :type watched: QObject
        :param event: Event being filtered.
        :type event: QEvent
        :return: ``True`` if handled; otherwise delegates to base.
        :rtype: bool
        """
        # Manages dynamic connections and responds to view events.
        DestroyType = QEvent.Type(16)  # QEvent.Type.Destroy constant
        if event.type() == DestroyType:
            # we care for the view since it deletes the widgets (parentage).
            # if the view hasn't been deleted, it might be that just the
            # delegate is removed from it, in which case we need to remove the
            # widgets manually, otherwise they still get drawn.
            if watched == self._item_view:
                self._is_view_destroyed = True
            return False

        # Ensure model connections are up-to-date.
        current_model = self._item_view.model()
        if self._model is not current_model:
            if self._model is not None:
                try:
                    self._model.rowsInserted.disconnect(self._on_rows_inserted)
                    self._model.rowsAboutToBeRemoved.disconnect(
                        self._on_rows_about_to_be_removed
                    )
                    self._model.rowsRemoved.disconnect(self._on_rows_removed)
                    self._model.dataChanged.disconnect(self._on_data_changed)
                    self._model.layoutChanged.disconnect(
                        self._on_layout_changed
                    )
                    self._model.modelReset.disconnect(self._on_model_reset)
                except Exception:
                    logger.exception("Failed to disconnect model signals")

            self._model = current_model
            if self._model is not None:
                self._model.rowsInserted.connect(self._on_rows_inserted)
                self._model.rowsAboutToBeRemoved.connect(
                    self._on_rows_about_to_be_removed
                )
                self._model.rowsRemoved.connect(self._on_rows_removed)
                self._model.dataChanged.connect(self._on_data_changed)
                self._model.layoutChanged.connect(self._on_layout_changed)
                self._model.modelReset.connect(self._on_model_reset)
                QTimer.singleShot(0, self._initialize_model)

        current_selection = self._item_view.selectionModel()
        if self._selection_model is not current_selection:
            if self._selection_model is not None:
                try:
                    self._selection_model.selectionChanged.disconnect(
                        self._on_selection_changed
                    )
                except Exception:
                    logger.exception(
                        "Failed to disconnect selection model signals"
                    )

            self._selection_model = current_selection
            if self._selection_model is not None:
                self._selection_model.selectionChanged.connect(
                    self._on_selection_changed
                )
                QTimer.singleShot(0, self._initialize_model)

        # React on specific events
        if event.type() in (QEvent.Type.Polish, QEvent.Type.Resize):
            if not isinstance(watched, QAbstractItemView):
                QTimer.singleShot(0, self._initialize_model)

        elif event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            if (
                isinstance(watched, QAbstractItemView)
                and self._selection_model is not None
            ):
                for index in self._selection_model.selectedIndexes():
                    if index.isValid():
                        self._pool.find_and_update_widgets(
                            QPersistentModelIndex(index),
                            self._option_view(index),
                        )

        return QObject.eventFilter(self, watched, event)
