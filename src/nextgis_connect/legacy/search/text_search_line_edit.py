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

from typing import Optional

from qgis.PyQt.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QRect,
    QSize,
    Qt,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices, QPainter, QPalette
from qgis.PyQt.QtWidgets import (
    QAction,
    QLineEdit,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.legacy.search.abstract_search_line_edit import (
    AbstractSearchLineEdit,
)
from nextgis_connect.legacy.search.resource_url import SearchResourceUrlParser
from nextgis_connect.legacy.search.search_help_overlay import SearchHelpOverlay
from nextgis_connect.legacy.search.text_search_completer_model import (
    TextSearchCompleterModel,
)
from nextgis_connect.legacy.settings.ng_connect_settings import (
    NgConnectSettings,
)
from nextgis_connect.platform.qgis.utils import nextgis_domain, utm_tags
from nextgis_connect.ui_kit.buttons.highlightable import (
    HighlightableToolButton,
)
from nextgis_connect.ui_kit.icons import material_icon
from nextgis_connect.ui_kit.widgets.loading_indicator import (
    LoadingIndicatorIconAnimator,
)


class SearchTagDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: Optional[QPainter],
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        if painter is None:
            return

        descriptions = {
            "@id": self.tr("by resource id"),
            "@parent": self.tr("by parent resource id"),
            "@root": self.tr("by root resource id"),
            "@owner": self.tr("by owner"),
            "@type": self.tr("by resource type"),
            "@name": self.tr("by resource name"),
            "@keyname": self.tr("by keyname"),
            "@metadata": self.tr("by metadata"),
        }
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "").strip()
        description = (
            descriptions.get(text)
            if index.data(TextSearchCompleterModel.TAG_DESCRIPTION_ROLE)
            else None
        )
        if description is None:
            super().paint(painter, option, index)
            return
        width = option.fontMetrics.horizontalAdvance(description) + 16
        if (
            option.rect.width()
            < width + option.fontMetrics.horizontalAdvance(text) + 24
        ):
            super().paint(painter, option, index)
            return
        super().paint(painter, option, index)
        painter.save()
        painter.setPen(
            option.palette.color(
                QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text
            )
        )
        painter.drawText(
            option.rect.adjusted(0, 0, -8, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            description,
        )
        painter.restore()


class TextSearchLineEdit(AbstractSearchLineEdit):
    help_visibility_changed = pyqtSignal(bool)
    __completer_model: TextSearchCompleterModel

    __loading_action: Optional[QAction]
    __open_help_action: Optional[QAction]
    __loading_icon: LoadingIndicatorIconAnimator

    __connection_id: Optional[str]
    __resource_url_parser: SearchResourceUrlParser

    def __init__(
        self, connection_id: Optional[str], parent: Optional[QWidget] = None
    ) -> None:
        self.__help_button_rect: Optional[QRect] = None
        self.__positioning_help_button = False
        super().__init__(parent)
        self.__help_button.installEventFilter(self)
        self.setPlaceholderText(self.tr("Search request..."))
        self.setToolTip(
            self.tr(
                "Search by resource name, resource URLs and simple filters"
            )
        )
        self.__connection_id = connection_id
        self.__resource_url_parser = SearchResourceUrlParser()

        # Animation
        self.__loading_action = None
        self.__loading_icon = LoadingIndicatorIconAnimator(
            QSize(16, 16),
            parent=self,
        )
        self.__loading_icon.frame_changed.connect(self.__update_loading_icon)

        # Completer model
        self.__completer_model = TextSearchCompleterModel(connection_id, self)
        self.textEdited.connect(self.__completer_model.set_prefix)
        self.__completer_model.fetching_started.connect(
            self.__show_loading_icon
        )
        self.__completer_model.fetching_finished.connect(
            self.__hide_loading_icon
        )
        self.__completer_model.complete_requested.connect(
            self.__show_completions
        )
        self.search_requested.connect(self.__completer_model.stop_fetching)
        self._completer.setModel(self.__completer_model)
        popup = self._completer.popup()
        self._tag_delegate = SearchTagDelegate(popup)
        popup.setItemDelegate(self._tag_delegate)

        # Search
        self.search_requested.connect(
            self.update_history,
            Qt.ConnectionType.QueuedConnection,  # type: ignore
        )

    @pyqtSlot(str)
    def set_connection_id(self, connection_id: str) -> None:
        self.__connection_id = connection_id
        self.__completer_model.set_connection_id(connection_id)
        self.__update_help_url()

    def _init_search_actions(self) -> None:
        self.__open_help_action = QWidgetAction(self)
        self.__open_help_action.setCheckable(True)
        self.__open_help_action.setIcon(material_icon("help"))
        self.__open_help_action.setToolTip(self.tr("Search help"))
        self.__help_button = HighlightableToolButton(self)
        self.__help_button.setAutoRaise(True)
        self.__help_button.setCircularAppearance(True)
        self.__help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.__help_button.setDefaultAction(self.__open_help_action)
        self.__help_button.setPulsating(
            not NgConnectSettings().search.help_viewed
        )
        self.__open_help_action.setDefaultWidget(self.__help_button)
        self.addAction(
            self.__open_help_action, QLineEdit.ActionPosition.TrailingPosition
        )
        self.__help_overlay: Optional[SearchHelpOverlay] = None
        self.__help_host: Optional[QWidget] = None
        self.__help_editor_enabled: Optional[bool] = None
        self.__help_button_rect: Optional[QRect] = None
        self.__help_button_right_margin = 0
        self.__search_mode_button: Optional[QToolButton] = None
        self.__open_help_action.toggled.connect(self.__toggle_help)

    @pyqtSlot()
    def search(self) -> None:
        if not self.isEnabled() or self.__open_help_action.isChecked():
            return

        search_string = self.text().strip()
        if len(search_string) == 0:
            self.reset_requested.emit()
            return

        settings = NgConnectSettings().search
        settings.add_text_query_to_history(search_string)

        if self.__connection_id is not None:
            connection = NgwConnectionsManager().connection(
                self.__connection_id
            )
            if connection is not None:
                resource_id = self.__resource_url_parser.resource_id(
                    search_string,
                    connection,
                )
                if resource_id is not None:
                    search_string = f"@id = {resource_id}"

        self.search_requested.emit(search_string)

    @pyqtSlot()
    def __show_completions(self) -> None:
        if self.__open_help_action.isChecked():
            return
        self._completer.setCompletionPrefix("")
        self._completer.complete()
        popup = self._completer.popup()
        if not isinstance(popup.itemDelegate(), SearchTagDelegate):
            popup.setItemDelegate(self._tag_delegate)
        self.installEventFilter(self)
        popup.installEventFilter(self)

    @pyqtSlot()
    def update_history(self) -> None:
        self.__completer_model.update_history()

    @pyqtSlot()
    def __show_loading_icon(self) -> None:
        if self.__loading_action is not None:
            return

        self.__loading_action = self.addAction(
            self.__loading_icon.current_icon(
                palette=self.palette(),
                device_pixel_ratio=self.devicePixelRatioF(),
            ),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.__loading_icon.start()

    @pyqtSlot()
    def __update_loading_icon(self) -> None:
        if self.__loading_action is None:
            return

        self.__loading_action.setIcon(
            self.__loading_icon.current_icon(
                palette=self.palette(),
                device_pixel_ratio=self.devicePixelRatioF(),
            )
        )

    def set_help_host(self, host: QWidget) -> None:
        self.__help_host = host
        if self.__help_overlay is not None:
            self.__help_overlay.set_host(host, self.__help_button)

    def set_search_mode_button(self, button: QToolButton) -> None:
        self.__search_mode_button = button
        if self.__help_overlay is not None:
            self.__help_overlay.set_search_mode_button(button)

    @property
    def is_help_visible(self) -> bool:
        return self.__open_help_action.isChecked()

    def __update_help_url(self) -> None:
        if self.__help_overlay is None:
            return
        connection = (
            NgwConnectionsManager().connection(self.__connection_id)
            if self.__connection_id is not None
            else None
        )
        self.__help_overlay.set_web_gis_url(
            connection.url if connection is not None else ""
        )

    @pyqtSlot(bool)
    def __toggle_help(self, checked: bool) -> None:
        if self.__help_overlay is None:
            if not checked:
                return
            self.__help_overlay = SearchHelpOverlay(self)
            host = (
                self.__help_host
                if self.__help_host is not None
                else self.window()
            )
            self.__help_overlay.set_host(
                host if host is not None else self,
                self.__help_button,
            )
            self.__help_overlay.closed.connect(
                lambda: self.__open_help_action.setChecked(False)
            )
            self.__help_overlay.documentation_requested.connect(
                self.__open_help_in_browser
            )
            if self.__search_mode_button is not None:
                self.__help_overlay.set_search_mode_button(
                    self.__search_mode_button
                )
        if checked:
            NgConnectSettings().search.help_viewed = True
            self.__update_help_url()
            self._completer.popup().hide()
            self.__help_editor_enabled = self.isEnabled()
            self.__help_button_rect = self.__help_button.geometry()
            self.__help_button_right_margin = (
                self.width() - self.__help_button_rect.right()
            )
            parent = self.parentWidget()
            if parent is None:
                parent = self.__help_overlay.parentWidget()
            # A child cannot stay enabled under a disabled line edit.
            # Keep the help action beside the editor until it is re-enabled.
            self.__help_button.setParent(parent)
            self.__position_help_button()
            self.__help_button.show()
            self.setEnabled(False)
        elif self.__help_editor_enabled is not None:
            self.setEnabled(self.__help_editor_enabled)
            self.__help_editor_enabled = None
            self.__help_button.setParent(self)
            if self.__help_button_rect is not None:
                self.__help_button.setGeometry(self.__help_button_rect)
            self.__help_button_rect = None
            self.__help_button.show()
        self.__help_button.setPulsating(
            not checked and not NgConnectSettings().search.help_viewed
        )
        self.__help_button.setCircleHighlighted(checked)
        self.__help_overlay.setVisible(checked)
        if checked:
            self.__help_overlay.raise_()
            self.__help_button.raise_()
            self.__help_overlay.setFocus()
        self.help_visibility_changed.emit(checked)

    def __position_help_button(self) -> None:
        if self.__help_button_rect is None or self.__positioning_help_button:
            return
        parent = self.__help_button.parentWidget()
        if parent is None:
            return
        position = parent.mapFromGlobal(
            self.mapToGlobal(self.__help_button_rect.topLeft())
        )
        self.__positioning_help_button = True
        try:
            self.__help_button.setGeometry(
                QRect(position, self.__help_button_rect.size())
            )
        finally:
            self.__positioning_help_button = False

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        if a0 is self.__help_button:
            if a1 is not None and a1.type() in (
                QEvent.Type.Move,
                QEvent.Type.Resize,
            ):
                # QLineEdit still positions its action in editor coordinates.
                self.__position_help_button()
            return False
        return super().eventFilter(a0, a1)

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        if self.__help_button_rect is not None:
            self.__help_button_rect.moveRight(
                self.width() - self.__help_button_right_margin
            )
            self.__position_help_button()

    def moveEvent(self, a0) -> None:
        super().moveEvent(a0)
        self.__position_help_button()

    def hideEvent(self, a0) -> None:
        self.__open_help_action.setChecked(False)
        super().hideEvent(a0)

    def keyPressEvent(self, a0) -> None:
        if (
            self.__open_help_action.isChecked()
            and a0.key() == Qt.Key.Key_Escape
        ):
            self.__open_help_action.setChecked(False)
            a0.accept()
            return
        super().keyPressEvent(a0)

    @pyqtSlot()
    def __open_help_in_browser(self) -> None:
        domain = nextgis_domain("docs")
        utm = utm_tags("search_panel")
        url = f"{domain}/docs_ngconnect/source/filter.html?{utm}"
        QDesktopServices.openUrl(QUrl(url, QUrl.ParsingMode.TolerantMode))

    @pyqtSlot()
    def __hide_loading_icon(self) -> None:
        self.__loading_icon.stop()
        if self.__loading_action is not None:
            self.__loading_action.deleteLater()
            self.__loading_action = None
