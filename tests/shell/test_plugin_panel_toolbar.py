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

from typing import Tuple

from qgis.PyQt.QtCore import QPoint, QSize, Qt, QTimer
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QMainWindow,
    QMenu,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from nextgis_connect.shell.presentation.plugin_panel import (
    PluginPanelToolBar,
    PluginPanelToolBarActions,
)


class TestPluginPanelToolBar:
    def test_toolbar_uses_native_actions(self, qgis_app) -> None:
        del qgis_app
        parent = QWidget()
        actions = self._create_actions(parent)
        toolbar = PluginPanelToolBar(actions, parent)

        command_actions = tuple(
            action for action in toolbar.actions() if not action.isSeparator()
        )

        assert command_actions == self._command_actions(actions)
        assert not any(
            isinstance(action, QWidgetAction) for action in toolbar.actions()
        )
        for action in command_actions:
            button = toolbar.widgetForAction(action)
            assert isinstance(button, QToolButton)
            assert button.defaultAction() is action

        parent.deleteLater()

    def test_menu_actions_use_standard_popup_modes(self, qgis_app) -> None:
        del qgis_app
        parent = QWidget()
        actions = self._create_actions(parent)
        toolbar = PluginPanelToolBar(actions, parent)

        expected_modes = {
            actions.add_to_qgis: (
                QToolButton.ToolButtonPopupMode.InstantPopup
            ),
            actions.add_to_web_gis: (
                QToolButton.ToolButtonPopupMode.InstantPopup
            ),
            actions.create_resource: (
                QToolButton.ToolButtonPopupMode.MenuButtonPopup
            ),
            actions.search: (QToolButton.ToolButtonPopupMode.MenuButtonPopup),
        }
        for action, expected_mode in expected_modes.items():
            button = toolbar.widgetForAction(action)
            assert isinstance(button, QToolButton)
            assert button.popupMode() == expected_mode

        parent.deleteLater()

    def test_action_menu_changes_propagate_through_qt_event_loop(
        self,
        qgis_app,
    ) -> None:
        application = qgis_app
        parent = QWidget()
        actions = self._create_actions(parent)
        actions.add_to_qgis.setMenu(None)
        toolbar = PluginPanelToolBar(actions, parent)
        button = toolbar.widgetForAction(actions.add_to_qgis)
        assert isinstance(button, QToolButton)
        assert button.menu() is None

        menu = QMenu(parent)
        menu.addAction("Alternative import")
        actions.add_to_qgis.setMenu(menu)
        application.processEvents()

        assert button.defaultAction() is actions.add_to_qgis
        assert button.defaultAction().menu() is menu

        parent.deleteLater()

    def test_instant_popup_action_triggers_without_menu(
        self,
        qgis_app,
    ) -> None:
        application = qgis_app
        main_window = QMainWindow()
        actions = self._create_actions(main_window)
        actions.add_to_qgis.setMenu(None)
        toolbar = PluginPanelToolBar(actions, main_window)
        triggered_actions = []
        actions.add_to_qgis.triggered.connect(
            lambda: triggered_actions.append(actions.add_to_qgis)
        )
        main_window.setCentralWidget(toolbar)

        main_window.show()
        application.processEvents()

        button = toolbar.widgetForAction(actions.add_to_qgis)
        assert isinstance(button, QToolButton)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        assert triggered_actions == [actions.add_to_qgis]

        main_window.deleteLater()

    def test_overflow_keeps_settings_and_help_as_actions(
        self,
        qgis_app,
    ) -> None:
        application = qgis_app
        main_window = QMainWindow()
        container = QWidget(main_window)
        layout = QVBoxLayout(container)
        actions = self._create_actions(main_window)
        toolbar = PluginPanelToolBar(actions, container)
        layout.addWidget(toolbar)
        layout.addStretch()
        main_window.setCentralWidget(container)

        main_window.resize(180, 120)
        main_window.show()
        application.processEvents()

        extension_button = toolbar.findChild(
            QToolButton,
            "qt_toolbar_ext_button",
        )
        settings_button = toolbar.widgetForAction(actions.settings)
        help_button = toolbar.widgetForAction(actions.help)

        assert extension_button is not None
        assert extension_button.isVisible()
        assert extension_button.geometry().right() <= toolbar.rect().right()
        assert isinstance(settings_button, QToolButton)
        assert isinstance(help_button, QToolButton)
        assert not settings_button.isVisible()
        assert not help_button.isVisible()
        assert actions.settings in toolbar.actions()
        assert actions.help in toolbar.actions()

        overflow_actions = []

        def capture_overflow_actions() -> None:
            popup = QApplication.activePopupWidget()
            if not isinstance(popup, QMenu):
                return

            overflow_actions.extend(popup.actions())
            popup.close()

        QTimer.singleShot(0, capture_overflow_actions)
        QTest.mouseClick(
            extension_button,
            Qt.MouseButton.LeftButton,
        )

        assert actions.settings in overflow_actions
        assert actions.help in overflow_actions

        main_window.deleteLater()

    def test_settings_right_click_requests_popup_without_triggering_action(
        self,
        qgis_app,
    ) -> None:
        application = qgis_app
        main_window = QMainWindow()
        actions = self._create_actions(main_window)
        toolbar = PluginPanelToolBar(actions, main_window)
        triggered_actions = []
        popup_positions = []
        actions.settings.triggered.connect(
            lambda: triggered_actions.append(actions.settings)
        )
        toolbar.settings_right_clicked.connect(popup_positions.append)
        main_window.setCentralWidget(toolbar)

        main_window.show()
        application.processEvents()

        settings_button = toolbar.widgetForAction(actions.settings)
        assert isinstance(settings_button, QToolButton)
        expected_popup_position = settings_button.mapToGlobal(
            QPoint(0, settings_button.height())
        )

        QTest.mouseClick(
            settings_button,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
            settings_button.rect().center(),
        )

        assert triggered_actions == []
        assert popup_positions == [expected_popup_position]

        QTest.mouseClick(
            settings_button,
            Qt.MouseButton.LeftButton,
        )

        assert triggered_actions == [actions.settings]

        main_window.deleteLater()

    def test_toolbar_restores_icon_size_after_external_update(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        actions = self._create_actions(parent)
        toolbar = PluginPanelToolBar(actions, parent)
        expected_size = QSize(
            PluginPanelToolBar.ICON_SIZE,
            PluginPanelToolBar.ICON_SIZE,
        )

        QToolBar.setIconSize(toolbar, QSize(16, 16))

        assert toolbar.iconSize() == expected_size

        parent.deleteLater()

    def _create_actions(
        self,
        parent: QWidget,
    ) -> PluginPanelToolBarActions:
        actions = PluginPanelToolBarActions(
            add_to_qgis=QAction("Add to QGIS", parent),
            add_to_web_gis=QAction("Add to Web GIS", parent),
            identify=QAction("Identify", parent),
            create_resource=QAction("Create resource", parent),
            search=QAction("Search", parent),
            refresh=QAction("Refresh", parent),
            open_in_browser=QAction("Open in browser", parent),
            settings=QAction("Settings", parent),
            help=QAction("Help", parent),
        )
        icon = parent.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        for action in self._command_actions(actions):
            action.setIcon(icon)

        for action in (
            actions.add_to_qgis,
            actions.add_to_web_gis,
            actions.create_resource,
            actions.search,
        ):
            menu = QMenu(parent)
            menu.addAction(f"{action.text()} command")
            action.setMenu(menu)

        return actions

    def _command_actions(
        self,
        actions: PluginPanelToolBarActions,
    ) -> Tuple[QAction, ...]:
        return (
            actions.add_to_qgis,
            actions.add_to_web_gis,
            actions.identify,
            actions.create_resource,
            actions.search,
            actions.refresh,
            actions.open_in_browser,
            actions.settings,
            actions.help,
        )
