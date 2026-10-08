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

from pathlib import Path
from types import SimpleNamespace

import pytest
from qgis.PyQt.QtCore import QAbstractAnimation, QPoint, Qt, QUrl
from qgis.PyQt.QtGui import QPainter, QTextDocument
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import (
    QMenu,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.search.search_help_overlay import SearchHelpOverlay
from nextgis_connect.legacy.search.search_panel import SearchPanel
from nextgis_connect.legacy.search.text_search_line_edit import (
    TextSearchLineEdit,
)
from nextgis_connect.legacy.settings.ng_connect_settings import (
    NgConnectSettings,
)
from nextgis_connect.legacy.tree_widget.overlay.widgets.surface import (
    OverlaySurfaceWidget,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.ui_kit.buttons import SecondaryButton
from nextgis_connect.ui_kit.buttons.highlightable import (
    HighlightableToolButton,
)
from nextgis_connect.ui_kit.icons import material_icon


@pytest.fixture
def search_overlay_environment(monkeypatch):
    plugin = SimpleNamespace(
        path=Path(__file__).resolve().parents[2] / "src" / "nextgis_connect"
    )
    monkeypatch.setattr(NgConnectInterface, "instance", lambda: plugin)


def test_help_toggle_persists_first_view(
    qgis_app, reset_qgis_settings, search_overlay_environment
):
    host = QWidget()
    host.resize(400, 350)
    host.show()
    field = TextSearchLineEdit(None)
    field.set_help_host(host)
    field.show()
    qgis_app.processEvents()
    action = next(
        action
        for action in field.actions()
        if isinstance(action, QWidgetAction)
    )
    button = action.defaultWidget()
    assert not NgConnectSettings().search.help_viewed
    assert host.findChild(SearchHelpOverlay) is None
    assert isinstance(button, HighlightableToolButton)
    assert button.isVisible()
    assert action.isCheckable()
    assert button._pulsating
    assert button._pulse.state() == QAbstractAnimation.State.Running

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    overlay = host.findChild(SearchHelpOverlay)
    assert isinstance(overlay, OverlaySurfaceWidget)
    assert action.isChecked()
    assert overlay.isVisible()
    assert overlay.geometry() == host.rect()
    assert NgConnectSettings().search.help_viewed
    assert not field.isEnabled()
    assert button.isEnabled()
    assert not button._pulsating
    assert button._circle_highlighted
    assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert button._pulse.state() == QAbstractAnimation.State.Stopped
    assert overlay._draw_background
    assert not overlay._title_icon.pixmap().isNull()
    assert overlay._card.objectName() == "overlayCard"
    assert isinstance(overlay._documentation_button, SecondaryButton)
    assert not overlay._documentation_button.icon().isNull()
    assert overlay.findChildren(QPushButton) == [overlay._documentation_button]
    assert overlay._browser.verticalScrollBar().maximum() > 0
    assert overlay._card_stack.currentWidget() is overlay._content_widget

    host.resize(500, 400)
    qgis_app.processEvents()
    assert overlay.geometry() == host.rect()
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    assert not action.isChecked()
    assert not overlay.isVisible()
    assert not button._pulsating
    assert field.isEnabled()
    assert button.parentWidget() is field
    assert not button._circle_highlighted

    action.trigger()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not action.isChecked()
    assert not overlay.isVisible()

    action.trigger()
    field.hide()
    assert not action.isChecked()
    assert not overlay.isVisible()
    another_field = TextSearchLineEdit(None)
    another_button = another_field.findChild(HighlightableToolButton)
    assert not another_button._pulsating
    another_field.close()
    host.close()


def test_unseen_help_animation_stops_when_hidden(
    qgis_app, reset_qgis_settings
):
    field = TextSearchLineEdit(None)
    field.show()
    qgis_app.processEvents()
    button = field.findChild(HighlightableToolButton)
    assert button._pulse.state() == QAbstractAnimation.State.Running
    field.hide()
    assert button._pulse.state() == QAbstractAnimation.State.Stopped
    field.show()
    assert button._pulse.state() == QAbstractAnimation.State.Running
    field.close()


def test_help_pulse_is_fixed_circle_with_animated_opacity(
    qgis_app, monkeypatch
):
    from nextgis_connect.ui_kit.buttons import highlightable

    rings = []
    standard_paints = []
    monkeypatch.setattr(
        QToolButton,
        "paintEvent",
        lambda _, event: standard_paints.append(event),
    )

    class RecordingPainter(QPainter):
        def drawEllipse(self, rect):
            rings.append(
                (rect, self.pen().color().alpha(), self.pen().widthF())
            )
            super().drawEllipse(rect)

        def drawRoundedRect(self, *args):
            pytest.fail("The help pulse must not draw a rectangular outline")

    monkeypatch.setattr(highlightable, "QPainter", RecordingPainter)
    button = HighlightableToolButton()
    button.setCircularAppearance(True)
    button.setIcon(material_icon("help"))
    button.resize(26, 26)
    button.setPulsating(True)
    button.show()
    qgis_app.processEvents()
    button._pulse.pause()
    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)

    rings.clear()
    button._pulse.setCurrentTime(0)
    button.grab()
    transparent_ring = rings[-1]
    button._pulse.setCurrentTime(1200)
    button.grab()
    opaque_ring = rings[-1]

    assert transparent_ring[0] == opaque_ring[0]
    assert opaque_ring[0].width() == opaque_ring[0].height()
    # The SVG ring spans 80% of the icon; the hover pen must touch it.
    icon_diameter = min(button.iconSize().width(), button.iconSize().height())
    assert opaque_ring[0].width() - opaque_ring[2] == pytest.approx(
        icon_diameter * 0.8
    )
    assert transparent_ring[1] == 0
    assert opaque_ring[1] == 255
    assert transparent_ring[2] == opaque_ring[2] == 2
    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    button._pulse.setCurrentTime(0)
    button.grab()
    assert rings[-1] == opaque_ring
    assert standard_paints == []
    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    button.setPulsating(False)
    button.setCheckable(True)
    button.setChecked(True)
    button.setCircleHighlighted(True)
    button.grab()
    assert rings[-1] == opaque_ring
    assert standard_paints == []
    button.close()


def test_help_blocks_panel_input_and_restores_it(
    qgis_app, reset_qgis_settings, search_overlay_environment, monkeypatch
):
    monkeypatch.setattr(
        "nextgis_connect.legacy.search.text_search_line_edit.QDesktopServices.openUrl",
        lambda _: True,
    )
    container = QWidget()
    layout = QVBoxLayout(container)
    other_button = QPushButton("Other action", container)
    disabled_button = QPushButton("Already disabled", container)
    disabled_button.setEnabled(False)
    panel = SearchPanel(None, container)
    resource_clicks = []

    class ResourceHost(QWidget):
        def mousePressEvent(self, event):
            resource_clicks.append(True)
            super().mousePressEvent(event)

    host = ResourceHost(container)
    layout.addWidget(other_button)
    layout.addWidget(disabled_button)
    layout.addWidget(panel)
    layout.addWidget(host, 1)
    panel.set_help_host(host)
    container.resize(450, 600)
    container.show()
    field = panel.findChild(TextSearchLineEdit)
    field.setText("Roads")
    help_button = field.findChild(HighlightableToolButton)
    search_button = panel._SearchPanel__search_button
    searches, clicks = [], []
    panel.search_requested.connect(searches.append)
    other_button.clicked.connect(lambda: clicks.append(True))
    qgis_app.processEvents()
    QTest.mouseClick(help_button, Qt.MouseButton.LeftButton)
    overlay = container.findChild(SearchHelpOverlay)
    assert other_button.isEnabled()
    assert not search_button.isEnabled()
    assert host.isEnabled()
    assert help_button.isEnabled()
    assert overlay._documentation_button.isEnabled()
    assert not field.isEnabled()
    assert not search_button._highlighted
    QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    QTest.mouseClick(host, Qt.MouseButton.LeftButton)
    assert resource_clicks == []
    QTest.mouseClick(other_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(search_button, Qt.MouseButton.LeftButton)
    QTest.keyClick(field, Qt.Key.Key_Return)
    field.search()
    assert clicks == []
    assert searches == []

    docs = []
    overlay.documentation_requested.connect(lambda: docs.append(True))
    QTest.mouseClick(overlay._documentation_button, Qt.MouseButton.LeftButton)
    assert docs == [True]
    QTest.mouseClick(help_button, Qt.MouseButton.LeftButton)
    assert other_button.isEnabled()
    assert search_button.isEnabled()
    assert host.isEnabled()
    assert not disabled_button.isEnabled()
    assert field.isEnabled()
    assert search_button._highlighted
    QTest.mouseClick(other_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(search_button, Qt.MouseButton.LeftButton)
    assert clicks == [True]
    assert searches == ["Roads"]
    QTest.mouseClick(host, Qt.MouseButton.LeftButton)
    assert resource_clicks == [True]
    container.close()


def test_help_loading_action_stays_left_of_help(qgis_app, reset_qgis_settings):
    field = TextSearchLineEdit(None)
    field.resize(300, 30)
    field.setText("Roads")
    field.show()
    field._TextSearchLineEdit__show_loading_icon()
    qgis_app.processEvents()
    help_action = field._TextSearchLineEdit__open_help_action
    assert field.actions()[0] is help_action
    help_button = help_action.defaultWidget()
    for button in field.findChildren(HighlightableToolButton):
        assert button is help_button
    for button in field.findChildren(QToolButton):
        if button is not help_button and button.isVisible():
            assert button.geometry().right() < help_button.geometry().left()
    field._TextSearchLineEdit__hide_loading_icon()
    assert field.actions()[0] is help_action
    field.close()


def test_help_uses_current_root_url_and_formatted_text(
    qgis_app, search_overlay_environment
):
    overlay = SearchHelpOverlay()
    overlay.set_web_gis_url("https://example.test/")
    assert "https://example.test/resource/0" in overlay._browser.toPlainText()
    assert "@id = 123" in overlay._browser.toPlainText().splitlines()
    assert (
        '@type ILIKE "wfs%" OR @name ILIKE "%wfs%"'
        in overlay._browser.toPlainText().splitlines()
    )
    assert (
        '@owner = me AND @type = "raster_layer"'
        in overlay._browser.toPlainText().splitlines()
    )
    assert "any Web GIS" in overlay._browser.toPlainText()
    document = overlay._browser.document()
    for token in (
        "@id",
        "@parent",
        "@root",
        "@owner",
        "@type",
        "@name",
        "@keyname",
        "@metadata",
        "LIKE",
        "ILIKE",
        "%",
        "_",
    ):
        cursor = document.find(token)
        assert not cursor.isNull(), token
        assert cursor.charFormat().fontWeight() > overlay.font().weight(), (
            token
        )
    assert (
        document.firstBlock().blockFormat().alignment()
        & Qt.AlignmentFlag.AlignLeft
    )
    assert (
        document.find("Resource name").charFormat().fontWeight()
        > overlay.font().weight()
    )
    overlay.set_web_gis_url("https://second.test/")
    assert "https://second.test/resource/0" in overlay._browser.toPlainText()
    assert "example.test" not in overlay._browser.toPlainText()
    overlay.close()


def test_help_updates_root_url_when_connection_changes(
    qgis_app, reset_qgis_settings, search_overlay_environment, monkeypatch
):
    connections = {
        "first": SimpleNamespace(url="https://first.test/"),
        "second": SimpleNamespace(url="https://second.test/"),
    }
    monkeypatch.setattr(
        NgwConnectionsManager,
        "connection",
        lambda _, connection_id: connections.get(connection_id),
    )
    host = QWidget()
    host.resize(400, 350)
    host.show()
    field = TextSearchLineEdit("first")
    field.set_help_host(host)
    field.show()
    help_action = field._TextSearchLineEdit__open_help_action
    help_action.trigger()
    overlay = host.findChild(SearchHelpOverlay)
    assert "https://first.test/resource/0" in overlay._browser.toPlainText()
    field.set_connection_id("second")
    assert "https://second.test/resource/0" in overlay._browser.toPlainText()
    assert "first.test" not in overlay._browser.toPlainText()
    field.close()
    host.close()


def test_help_disables_tree_but_keeps_overlay_enabled(
    qgis_app, reset_qgis_settings, search_overlay_environment
):
    container = QWidget()
    field = TextSearchLineEdit(None, container)
    tree = QTreeView(container)
    field.setGeometry(10, 10, 350, 30)
    tree.setGeometry(10, 50, 350, 300)
    field.set_help_host(tree.viewport())
    container.resize(450, 450)
    container.show()
    qgis_app.processEvents()
    field._TextSearchLineEdit__open_help_action.trigger()
    overlay = container.findChild(SearchHelpOverlay)
    assert tree.isEnabled()
    assert overlay.isEnabled()
    assert overlay._documentation_button.isEnabled()
    assert overlay.pos() == tree.viewport().mapTo(container, QPoint())
    assert overlay.size() == tree.viewport().size()
    tree.move(30, 70)
    qgis_app.processEvents()
    assert overlay.pos() == tree.viewport().mapTo(container, QPoint())
    field._TextSearchLineEdit__open_help_action.trigger()
    assert tree.isEnabled()
    container.close()


def test_help_embeds_actual_search_menu_button_preview(
    qgis_app, search_overlay_environment
):
    button = QToolButton()
    button.resize(42, 28)
    button.setIcon(material_icon("help"))
    button.setMenu(QMenu(button))
    button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    overlay = SearchHelpOverlay()
    overlay.set_search_mode_button(button)
    assert "search-mode-button" in overlay._browser.toHtml()
    resource = overlay._browser.document().resource(
        QTextDocument.ResourceType.ImageResource, QUrl("search-mode-button")
    )
    assert resource is not None and not resource.isNull()
    assert resource.width() / resource.devicePixelRatioF() == button.width()
    assert "highlighted arrow" in overlay._browser.toPlainText()
    overlay.close()
    button.close()
