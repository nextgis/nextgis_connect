# NextGIS Connect
# Copyright (C) 2026  NextGIS
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>.

from dataclasses import dataclass
from typing import Optional

from qgis.PyQt.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QSize,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QMouseEvent, QWheelEvent
from qgis.PyQt.QtWidgets import QAction, QToolBar, QToolButton, QWidget


@dataclass(frozen=True)
class PluginPanelToolBarActions:
    add_to_qgis: QAction
    add_to_web_gis: QAction
    identify: QAction
    create_resource: QAction
    search: QAction
    refresh: QAction
    open_in_browser: QAction
    settings: QAction
    help: QAction


class _RightClickFilter(QObject):
    """Translate a complete right-button click into a Qt signal."""

    clicked = pyqtSignal()

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._is_pressed = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not isinstance(event, QMouseEvent):
            return super().eventFilter(watched, event)

        if event.button() != Qt.MouseButton.RightButton:
            return super().eventFilter(watched, event)

        if event.type() == QEvent.Type.MouseButtonPress:
            self._is_pressed = True
            event.accept()
            return True

        if event.type() != QEvent.Type.MouseButtonRelease:
            return super().eventFilter(watched, event)

        was_pressed = self._is_pressed
        self._is_pressed = False
        event.accept()
        if (
            was_pressed
            and isinstance(watched, QWidget)
            and watched.rect().contains(event.pos())
        ):
            self.clicked.emit()

        return True


class _MenuWheelFilter(QObject):
    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        if not isinstance(a0, QToolButton) or not isinstance(a1, QWheelEvent):
            return super().eventFilter(a0, a1)
        menu = a0.menu()
        if menu is None and a0.defaultAction() is not None:
            menu = a0.defaultAction().menu()
        if not a0.isEnabled() or menu is None or not a1.angleDelta().y():
            return super().eventFilter(a0, a1)
        actions = [
            action
            for action in menu.actions()
            if action.isCheckable()
            and action.isEnabled()
            and action.isVisible()
        ]
        if not actions:
            return super().eventFilter(a0, a1)
        current_index = next(
            (
                index
                for index, action in enumerate(actions)
                if action.isChecked()
            ),
            0,
        )
        step = -1 if a1.angleDelta().y() > 0 else 1
        next_index = current_index + step
        if 0 <= next_index < len(actions):
            actions[next_index].trigger()
        a1.accept()
        return True


class PluginPanelToolBar(QToolBar):
    """Display plugin panel commands using native toolbar actions."""

    settings_right_clicked = pyqtSignal(QPoint)

    ICON_SIZE = 20

    def __init__(
        self,
        actions: PluginPanelToolBarActions,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NgConnectPluginPanelToolBar")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.setFloatable(False)
        self.setMovable(False)
        self._fixed_icon_size = QSize(self.ICON_SIZE, self.ICON_SIZE)
        self.iconSizeChanged.connect(self._restore_fixed_icon_size)
        self.setIconSize(self._fixed_icon_size)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self._add_action(
            actions.add_to_qgis,
            QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        self._add_action(
            actions.add_to_web_gis,
            QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        self.addSeparator()
        self._add_action(actions.identify)
        self.addSeparator()
        self._add_action(
            actions.create_resource,
            QToolButton.ToolButtonPopupMode.MenuButtonPopup,
        )
        self._search_button = self._add_action(
            actions.search,
            QToolButton.ToolButtonPopupMode.MenuButtonPopup,
        )
        self._search_wheel_filter = _MenuWheelFilter(self)
        self._search_button.installEventFilter(self._search_wheel_filter)
        self._add_action(actions.refresh)
        self.addSeparator()
        self._add_action(actions.open_in_browser)
        self.addSeparator()
        self._settings_button = self._add_action(actions.settings)
        self._settings_right_click_filter = _RightClickFilter(self)
        self._settings_right_click_filter.clicked.connect(
            self._emit_settings_right_clicked
        )
        self._settings_button.installEventFilter(
            self._settings_right_click_filter
        )
        self._add_action(actions.help)

    def _add_action(
        self,
        action: QAction,
        popup_mode: Optional[QToolButton.ToolButtonPopupMode] = None,
    ) -> QToolButton:
        self.addAction(action)
        button = self.widgetForAction(action)
        if not isinstance(button, QToolButton):
            raise RuntimeError("QToolBar did not create an action button")

        if popup_mode is not None:
            button.setPopupMode(popup_mode)

        return button

    @pyqtSlot(QSize)
    def _restore_fixed_icon_size(self, icon_size: QSize) -> None:
        if icon_size == self._fixed_icon_size:
            return

        self.setIconSize(self._fixed_icon_size)

    @pyqtSlot()
    def _emit_settings_right_clicked(self) -> None:
        popup_position = self._settings_button.mapToGlobal(
            QPoint(0, self._settings_button.height())
        )
        self.settings_right_clicked.emit(popup_position)
