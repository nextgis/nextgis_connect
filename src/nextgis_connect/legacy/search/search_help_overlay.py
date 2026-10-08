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

from html import escape
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

from qgis.PyQt import sip
from qgis.PyQt.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    Qt,
    QUrl,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QTextDocument
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QToolButton,
    QWidget,
)

from nextgis_connect.legacy.tree_widget.overlay.widgets.surface import (
    OverlaySurfaceWidget,
)
from nextgis_connect.ui_kit.buttons import SecondaryButton
from nextgis_connect.ui_kit.icons import material_icon
from nextgis_connect.ui_kit.widgets.interaction_guard import InteractionGuard
from nextgis_connect.ui_kit.widgets.tool_button_preview import (
    render_menu_button_preview,
)


class SearchHelpOverlay(OverlaySurfaceWidget):
    closed = pyqtSignal()
    documentation_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._interaction_scope: Optional[QWidget] = None
        self._help_button: Optional[QToolButton] = None
        self._host: Optional[QWidget] = None
        self._geometry_hosts: List[QWidget] = []
        self._interaction_guard: Optional[InteractionGuard] = None
        self._search_mode_button: Optional[QToolButton] = None
        self._web_gis_url = ""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, True)
        self._title = QLabel(self.tr("Search help"), self._content_widget)
        font = self._title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self._title.setFont(font)
        self._title_icon = QLabel(self._content_widget)
        self._title_icon.setFixedSize(24, 24)
        self._title_icon.setPixmap(material_icon("help").pixmap(24, 24))
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        title_layout.addWidget(self._title_icon)
        title_layout.addWidget(self._title, 1)
        self._browser = QTextBrowser(self._content_widget)
        self._browser.setFrameShape(QFrame.Shape.NoFrame)
        self._browser.setOpenLinks(False)
        self._browser.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._documentation_button = SecondaryButton(
            self.tr("Full documentation"), self._content_widget
        )
        self._documentation_button.setIcon(material_icon("open_in_new"))
        self._documentation_button.clicked.connect(
            self.documentation_requested
        )
        self._content_layout.addLayout(title_layout)
        self._content_layout.addWidget(self._browser, 1)
        self._content_layout.addWidget(self._documentation_button)
        self.set_web_gis_url("")
        self.hide()

    def set_web_gis_url(self, url: str) -> None:
        self._web_gis_url = url
        parts = urlsplit(url)
        resource_url = (
            urlunsplit(
                (
                    parts.scheme,
                    parts.netloc.rsplit("@", 1)[-1],
                    "/resource/0",
                    "",
                    "",
                )
            )
            if parts.scheme and parts.netloc
            else ""
        )
        paragraphs = [
            self.tr(
                "<b>Resource name</b><br>Enter a name or part of a name. "
                "Enclose it in quotation marks for an exact match. "
                "Results are highlighted in bold in the resource tree."
            ),
            self.tr(
                "<b>Filters</b><br>Use <b><code>@id</code></b>, "
                "<b><code>@parent</code></b>, <b><code>@root</code></b>, "
                "<b><code>@owner</code></b>, <b><code>@type</code></b>, "
                "<b><code>@name</code></b>, <b><code>@keyname</code></b> "
                "and <b><code>@metadata</code></b>."
            ),
            "<code>@id = 123</code>",
            self.tr(
                "Combine conditions with <b>AND</b> or <b>OR</b>, but do not "
                "mix them in one request. Use <b>LIKE</b> for a "
                "case-sensitive match and <b>ILIKE</b> for a "
                "case-insensitive match; <b><code>%</code></b> matches any "
                "number of characters and <b><code>_</code></b> matches "
                "one character."
            ),
            '<code>@type ILIKE "wfs%" OR @name ILIKE "%wfs%"</code>',
            '<code>@owner = me AND @type = "raster_layer"</code>',
            self.tr(
                "<b><code>@parent</code></b> finds direct child resources; "
                "<b><code>@root</code></b> "
                "also includes all nested resources."
            ),
            self.tr(
                "<b>Resource URL</b><br>Paste a resource URL from any "
                "Web GIS. A link to another Web GIS lets you switch "
                "to its connection or create one. Root resource example:"
            ),
        ]
        if resource_url:
            paragraphs.append(f"<code>{escape(resource_url)}</code>")
        else:
            paragraphs.append(self.tr("Select a connection to see its URL."))
        paragraphs.extend(
            [
                self.tr(
                    "<b>Suggestions and history</b><br>Suggestions help select "
                    "filters and values. Previous requests are available "
                    "in search history."
                ),
                self.tr(
                    "<b>Other search modes</b><br>Search by metadata or resource "
                    "type using the search mode menu."
                ),
                self.tr(
                    "Press <b>Enter</b> or the <b>search button</b> to apply "
                    "the request."
                ),
            ]
        )
        if self._search_mode_button is not None and not sip.isdeleted(
            self._search_mode_button
        ):
            preview = render_menu_button_preview(self._search_mode_button)
            self._browser.document().addResource(
                QTextDocument.ResourceType.ImageResource,
                QUrl("search-mode-button"),
                preview,
            )
            ratio = preview.devicePixelRatioF()
            paragraphs.insert(
                -1,
                '<img src="search-mode-button" '
                f'width="{round(preview.width() / ratio)}" '
                f'height="{round(preview.height() / ratio)}"><br>'
                + self.tr(
                    "Open the search mode menu using the highlighted arrow."
                ),
            )
        self._browser.setHtml(
            "".join(
                f'<p align="left">{paragraph}</p>' for paragraph in paragraphs
            )
        )

    def set_search_mode_button(self, button: QToolButton) -> None:
        if self._search_mode_button is not None and not sip.isdeleted(
            self._search_mode_button
        ):
            self._search_mode_button.removeEventFilter(self)
        self._search_mode_button = button
        button.installEventFilter(self)
        self.set_web_gis_url(self._web_gis_url)

    def _sync_responsive_geometry(self) -> None:
        self.setMinimumSize(0, 0)
        self._logo_widget.hide()
        self._set_content_metrics(12, 8)
        self._card_stack.setCurrentWidget(self._content_widget)
        self._card.setGeometry(self.rect().adjusted(8, 8, -8, -8))

    def set_host(self, host: QWidget, help_button: QToolButton) -> None:
        for old_host in self._geometry_hosts:
            old_host.removeEventFilter(self)
        self._geometry_hosts.clear()
        self._host = host
        self._help_button = help_button
        scope = host
        while scope.parentWidget() is not None and not isinstance(
            scope, QDockWidget
        ):
            scope = scope.parentWidget()
        self._interaction_scope = scope
        self.setParent(scope)
        geometry_host: Optional[QWidget] = host
        while geometry_host is not None:
            geometry_host.installEventFilter(self)
            self._geometry_hosts.append(geometry_host)
            if geometry_host is scope:
                break
            geometry_host = geometry_host.parentWidget()
        self._sync_host_geometry()

    def _sync_host_geometry(self) -> None:
        if self._host is not None and self.parentWidget() is not None:
            self.setGeometry(
                QRect(
                    self._host.mapTo(self.parentWidget(), QPoint()),
                    self._host.size(),
                )
            )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._block_interaction()

    def hideEvent(self, a0) -> None:
        self._unblock_interaction()
        super().hideEvent(a0)

    def _block_interaction(self) -> None:
        if self._interaction_scope is None or self._help_button is None:
            return
        if self._interaction_guard is not None and not sip.isdeleted(
            self._interaction_guard
        ):
            self._interaction_guard.set_active(False)
            self._interaction_guard.deleteLater()
        self._interaction_guard = InteractionGuard(
            self._interaction_scope, (self, self._help_button), self
        )
        self._interaction_guard.set_active(True)

    def _unblock_interaction(self) -> None:
        if self._interaction_guard is not None and not sip.isdeleted(
            self._interaction_guard
        ):
            self._interaction_guard.set_active(False)

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        if a1 is None:
            return False
        if a0 is self._search_mode_button and a1.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            scroll_position = self._browser.verticalScrollBar().value()
            self.set_web_gis_url(self._web_gis_url)
            self._browser.verticalScrollBar().setValue(scroll_position)
        if a0 in self._geometry_hosts and a1.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
        ):
            self._sync_host_geometry()
        return super().eventFilter(a0, a1)

    def mousePressEvent(self, a0) -> None:
        a0.accept()

    def mouseReleaseEvent(self, a0) -> None:
        a0.accept()

    def mouseDoubleClickEvent(self, a0) -> None:
        a0.accept()

    def wheelEvent(self, a0) -> None:
        a0.accept()

    def keyPressEvent(self, a0) -> None:
        if a0.key() == Qt.Key.Key_Escape:
            self.closed.emit()
        else:
            super().keyPressEvent(a0)
