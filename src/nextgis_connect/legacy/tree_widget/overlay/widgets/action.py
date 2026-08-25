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

from qgis.PyQt.QtCore import QEvent, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import QBoxLayout, QLabel, QSizePolicy, QWidget

from nextgis_connect.legacy.tree_widget.overlay.state import (
    OverlayAction,
    OverlayButtonState,
    OverlayKind,
    OverlayState,
)
from nextgis_connect.legacy.tree_widget.overlay.widgets.surface import (
    FooterLinkLabel,
    MaterialIllustrationWidget,
    OverlaySurfaceWidget,
)
from nextgis_connect.ui_kit.buttons import (
    PrimaryButton,
    SecondaryButton,
    ShiningButton,
)
from nextgis_connect.ui_kit.graphics.decorator import (
    NextgisDecorator,
)
from nextgis_connect.ui_kit.icons import material_icon


class ActionOverlayWidget(OverlaySurfaceWidget):
    """Overlay card for actionable empty, error, and unavailable states."""

    _BUTTON_LAYOUT_RESERVE = 24
    _MINIMUM_BUTTON_SPACING = 6
    _ICON_HIDE_WIDTH = 360
    _ICON_SHOW_WIDTH = 400
    _TITLE_ICON_SIZE = 24

    action_requested = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._title_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._title_layout.setContentsMargins(0, 0, 0, 0)
        self._title_layout.setSpacing(8)

        self._title_icon_label = QLabel(self._content_widget)
        self._title_icon_label.setFixedSize(
            QSize(self._TITLE_ICON_SIZE, self._TITLE_ICON_SIZE)
        )
        self._title_icon_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self._title_icon_label.hide()

        self._title_label = QLabel(self._content_widget)
        title_font = self._title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 3)
        self._title_label.setFont(title_font)
        self._title_label.setWordWrap(True)
        self._title_label.setTextFormat(Qt.TextFormat.RichText)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )

        self._title_layout.addWidget(
            self._title_icon_label,
            alignment=Qt.AlignmentFlag.AlignVCenter,
        )
        self._title_layout.addWidget(self._title_label)

        self._illustration_widget = MaterialIllustrationWidget(
            self._content_widget
        )

        self._message_label = QLabel(self._content_widget)
        self._message_label.setWordWrap(True)
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        self._details_label = QLabel(self._content_widget)
        self._details_label.setWordWrap(True)
        self._details_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        details_palette = QPalette(self._details_label.palette())
        details_palette.setColor(
            QPalette.ColorRole.WindowText,
            NextgisDecorator.system_muted_text_color(self.palette()),
        )
        self._details_label.setPalette(details_palette)

        self._buttons_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._buttons_layout.setContentsMargins(0, 8, 0, 0)
        self._buttons_layout.setSpacing(NextgisDecorator.CARD_BUTTON_SPACING)

        self._welcome_primary_button = ShiningButton("", self._content_widget)
        self._primary_button = PrimaryButton("", self._content_widget)
        self._secondary_button = SecondaryButton("", self._content_widget)

        for button in (
            self._welcome_primary_button,
            self._primary_button,
            self._secondary_button,
        ):
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

        self._welcome_primary_button.clicked.connect(self._emit_primary_action)
        self._primary_button.clicked.connect(self._emit_primary_action)
        self._secondary_button.clicked.connect(self._emit_secondary_action)

        self._footer_link = FooterLinkLabel(self._content_widget)
        self._footer_link.action_requested.connect(self.action_requested.emit)

        self._buttons_layout.addWidget(self._welcome_primary_button)
        self._buttons_layout.addWidget(self._primary_button)
        self._buttons_layout.addWidget(self._secondary_button)

        self._content_layout.addWidget(
            self._illustration_widget,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        self._content_layout.addLayout(self._title_layout)
        self._content_layout.addWidget(self._message_label)
        self._content_layout.addWidget(self._details_label)
        self._content_layout.addLayout(self._buttons_layout)
        self._content_layout.addWidget(
            self._footer_link,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        self._primary_action = OverlayButtonState()
        self._secondary_action = OverlayButtonState()
        self._buttons_direction = QBoxLayout.Direction.LeftToRight
        self._is_icon_visible_by_layout = True
        self._title_icon_name = ""

    def set_state(self, state: OverlayState) -> None:
        """Apply a new state to the action overlay."""
        self.set_draw_background(state.draw_background)
        self.set_logo_action(state.logo_action)

        self._set_title_icon(state.title_icon_name)
        self._title_label.setText(self._display_text(state.title))
        self._message_label.setText(self._display_text(state.message))

        details = state.details or ""
        self._details_label.setVisible(details != "")
        self._details_label.setText(self._display_text(details))

        self._illustration_widget.set_icon(
            state.illustration_name,
            size=state.illustration_size,
            themed=state.illustration_themed,
        )
        self._is_icon_visible_by_layout = self._illustration_widget.has_icon()
        if self._title_icon_name != "":
            title_alignment = Qt.AlignmentFlag.AlignLeft
        elif self._illustration_widget.has_icon():
            title_alignment = Qt.AlignmentFlag.AlignCenter
        else:
            title_alignment = Qt.AlignmentFlag.AlignLeft
        self._title_label.setAlignment(title_alignment)

        is_welcome = state.kind == OverlayKind.WELCOME
        self._apply_button_state(
            self._welcome_primary_button,
            state.primary_action,
            visible=is_welcome,
        )
        self._apply_button_state(
            self._primary_button,
            state.primary_action,
            visible=not is_welcome,
        )
        self._apply_button_state(
            self._secondary_button, state.secondary_action
        )
        self._footer_link.set_action(state.footer_action)

        self._primary_action = state.primary_action
        self._secondary_action = state.secondary_action

        self.sync_layout()

    def changeEvent(self, event) -> None:
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        ):
            details_palette = QPalette(self._details_label.palette())
            details_palette.setColor(
                QPalette.ColorRole.WindowText,
                NextgisDecorator.system_muted_text_color(self.palette()),
            )
            self._details_label.setPalette(details_palette)
            self._sync_title_icon()

        super().changeEvent(event)

    def _set_title_icon(self, icon_name: str) -> None:
        self._title_icon_name = icon_name
        self._title_icon_label.setVisible(icon_name != "")
        self._sync_title_icon()

    def _sync_title_icon(self) -> None:
        if self._title_icon_name == "":
            self._title_icon_label.clear()
            return

        icon = material_icon(self._title_icon_name, size=self._TITLE_ICON_SIZE)
        self._title_icon_label.setPixmap(
            icon.pixmap(self._TITLE_ICON_SIZE, self._TITLE_ICON_SIZE)
        )

    def _horizontal_content_width_for_preferred_layout(self) -> int:
        visible_buttons = [
            button
            for button in (
                self._welcome_primary_button,
                self._primary_button,
                self._secondary_button,
            )
            if not button.isHidden()
        ]
        if len(visible_buttons) <= 1:
            return 0

        return (
            self._minimum_horizontal_buttons_width(
                visible_buttons,
                spacing=NextgisDecorator.CARD_BUTTON_SPACING,
            )
            + self._BUTTON_LAYOUT_RESERVE
        )

    def _update_responsive_layout(
        self,
        content_width: int,
        card_width: int,
    ) -> None:
        visible_buttons = [
            button
            for button in (
                self._welcome_primary_button,
                self._primary_button,
                self._secondary_button,
            )
            if not button.isHidden()
        ]
        required_width = self._horizontal_content_width_for_preferred_layout()
        if len(visible_buttons) <= 1 or content_width >= required_width:
            direction = QBoxLayout.Direction.LeftToRight
            spacing = NextgisDecorator.CARD_BUTTON_SPACING
        else:
            direction = QBoxLayout.Direction.TopToBottom
            spacing = self._MINIMUM_BUTTON_SPACING

        self._buttons_direction = direction
        if self._buttons_layout.direction() != direction:
            self._buttons_layout.setDirection(direction)

        if self._buttons_layout.spacing() != spacing:
            self._buttons_layout.setSpacing(spacing)

        margins = self._buttons_layout.contentsMargins()
        if (
            margins.left() != 0
            or margins.top() != 8
            or margins.right() != 0
            or margins.bottom() != 0
        ):
            self._buttons_layout.setContentsMargins(0, 8, 0, 0)

        self._buttons_layout.invalidate()
        self._content_layout.invalidate()
        self._content_widget.updateGeometry()
        self._footer_link.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._update_icon_layout(card_width)

    def _minimum_content_width_for_readable_layout(self) -> int:
        visible_buttons = self._visible_buttons()
        minimum_width = 0
        if visible_buttons:
            minimum_width = max(
                button.minimumSizeHint().width() for button in visible_buttons
            )

        if not self._footer_link.isHidden():
            minimum_width = max(
                minimum_width,
                self._footer_link.minimumSizeHint().width(),
            )

        return minimum_width

    def _visible_buttons(self) -> list:
        return [
            button
            for button in (
                self._welcome_primary_button,
                self._primary_button,
                self._secondary_button,
            )
            if not button.isHidden()
        ]

    def _buttons_minimum_width_sum(self, buttons: list) -> int:
        return sum(button.minimumSizeHint().width() for button in buttons)

    def _minimum_horizontal_buttons_width(
        self,
        buttons: list,
        *,
        spacing: int,
    ) -> int:
        return self._buttons_minimum_width_sum(buttons) + (
            spacing * (len(buttons) - 1)
        )

    def _prepare_content_for_layout(self) -> None:
        self._buttons_direction = QBoxLayout.Direction.LeftToRight
        if self._buttons_layout.direction() != self._buttons_direction:
            self._buttons_layout.setDirection(self._buttons_direction)

        if (
            self._buttons_layout.spacing()
            != NextgisDecorator.CARD_BUTTON_SPACING
        ):
            self._buttons_layout.setSpacing(
                NextgisDecorator.CARD_BUTTON_SPACING
            )

        if self._illustration_widget.has_icon():
            self._is_icon_visible_by_layout = True
            self._illustration_widget.set_icon_visible(True)
            self._illustration_widget.reset_size()

    def _prepare_content_for_minimum_layout(self) -> None:
        if self._illustration_widget.has_icon():
            self._is_icon_visible_by_layout = False
            self._illustration_widget.set_icon_visible(False)

        self._buttons_direction = QBoxLayout.Direction.TopToBottom
        if self._buttons_layout.direction() != self._buttons_direction:
            self._buttons_layout.setDirection(self._buttons_direction)

        if self._buttons_layout.spacing() != self._MINIMUM_BUTTON_SPACING:
            self._buttons_layout.setSpacing(self._MINIMUM_BUTTON_SPACING)

        self._buttons_layout.invalidate()

    def _shrink_content_to_height(
        self,
        width: int,
        available_height: int,
    ) -> bool:
        if not self._illustration_widget.has_icon():
            return False

        did_shrink = False
        for _ in range(2):
            required_height = self._content_height_for_width(width)
            overflow = required_height - available_height
            if overflow <= 0:
                return did_shrink

            current_size = self._illustration_widget.current_size()
            minimum_size = self._illustration_widget.minimum_icon_size()
            if current_size <= minimum_size:
                self._is_icon_visible_by_layout = False
                return (
                    self._illustration_widget.set_icon_visible(False)
                    or did_shrink
                )

            did_shrink = (
                self._illustration_widget.set_render_size(
                    current_size - overflow
                )
                or did_shrink
            )

        return did_shrink

    def _update_icon_layout(self, card_width: int) -> None:
        if not self._illustration_widget.has_icon():
            return

        if card_width < self._ICON_HIDE_WIDTH:
            self._is_icon_visible_by_layout = False
            self._illustration_widget.set_icon_visible(False)
            return

        self._is_icon_visible_by_layout = True
        self._illustration_widget.set_icon_visible(True)
        compact_range = self._ICON_SHOW_WIDTH - self._ICON_HIDE_WIDTH
        if compact_range <= 0 or card_width >= self._ICON_SHOW_WIDTH:
            self._illustration_widget.reset_size()
            return

        factor = max(
            0.0,
            min(
                1.0,
                (card_width - self._ICON_HIDE_WIDTH) / compact_range,
            ),
        )
        minimum_size = self._illustration_widget.minimum_icon_size()
        preferred_size = self._illustration_widget.preferred_size()
        self._illustration_widget.set_render_size(
            round(minimum_size + (preferred_size - minimum_size) * factor)
        )

    def _apply_button_state(
        self,
        button: QWidget,
        state: OverlayButtonState,
        *,
        visible: bool = True,
    ) -> None:
        is_visible = (
            visible and state.action != OverlayAction.NONE and state.text != ""
        )
        button.setVisible(is_visible)
        button.setText(state.text)
        tooltip = state.tooltip if state.tooltip != state.text else ""
        button.setToolTip(tooltip if is_visible else "")

    def _emit_primary_action(self) -> None:
        if self._primary_action.action == OverlayAction.NONE:
            return

        self.action_requested.emit(self._primary_action.action)

    def _emit_secondary_action(self) -> None:
        if self._secondary_action.action == OverlayAction.NONE:
            return

        self.action_requested.emit(self._secondary_action.action)

    def _emit_logo_action(self) -> None:
        if self._logo_action == OverlayAction.NONE:
            return

        self.action_requested.emit(self._logo_action)
