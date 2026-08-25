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

from qgis.PyQt.QtCore import QSize, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QWidget,
)

from nextgis_connect.legacy.tree_widget.overlay.state import (
    OverlayAction,
    OverlayButtonState,
    OverlayState,
)
from nextgis_connect.legacy.tree_widget.overlay.widgets.surface import (
    ElidedLabel,
    OverlaySurfaceWidget,
)
from nextgis_connect.ui_kit.buttons import CancelButton
from nextgis_connect.ui_kit.graphics.decorator import (
    NextgisDecorator,
)


class LoadingOverlayWidget(OverlaySurfaceWidget):
    """Overlay card for long-running loading and cancellation states."""

    _NORMAL_CARD_PADDING = 16
    _COMPACT_CARD_PADDING = 12
    _MINIMUM_CARD_PADDING = 10
    _NORMAL_CONTENT_SPACING = 4
    _COMPACT_CONTENT_SPACING = 3
    _MINIMUM_CONTENT_SPACING = 2
    _MAXIMUM_VERTICAL_CARD_PADDING = 10
    _PROGRESS_CANCEL_SPACING = 6
    _MINIMUM_PROGRESS_CANCEL_SPACING = 2
    _LAYOUT_RESERVE = 24
    _UNBOUNDED_WIDGET_HEIGHT = 16777215

    action_requested = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._title_label = QLabel(self._content_widget)
        title_font = self._title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        self._title_label.setFont(title_font)
        self._title_label.setWordWrap(True)
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        self._progress_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._progress_layout.setContentsMargins(0, 0, 0, 0)
        self._progress_layout.setSpacing(self._PROGRESS_CANCEL_SPACING)

        self._progress_bar = QProgressBar(self._content_widget)
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setPalette(
            NextgisDecorator.progress_palette(self._progress_bar.palette())
        )
        self._progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self._cancel_button = CancelButton(self._content_widget)
        self._cancel_button.hide()
        self._cancel_button.clicked.connect(self._emit_cancel_action)

        self._message_label = ElidedLabel(self._content_widget)

        self._details_label = ElidedLabel(self._content_widget)

        self._progress_layout.addWidget(self._progress_bar)
        self._progress_layout.addWidget(self._cancel_button)

        self._content_layout.addWidget(self._title_label)
        self._content_layout.addLayout(self._progress_layout)
        self._content_layout.addWidget(self._message_label)
        self._content_layout.addWidget(self._details_label)

        self._cancel_action = OverlayButtonState()
        self._progress_direction = QBoxLayout.Direction.LeftToRight
        self._card_top_anchor: Optional[int] = None
        self._card_top_anchor_size: Optional[QSize] = None
        self._title_height_anchor: Optional[int] = None
        self._progress_height_anchor: Optional[int] = None

    def reset_card_growth(self) -> None:
        self._card_top_anchor = None
        self._card_top_anchor_size = None
        self._title_height_anchor = None
        self._progress_height_anchor = None
        self._title_label.setMinimumHeight(0)
        self._title_label.setMaximumHeight(self._UNBOUNDED_WIDGET_HEIGHT)
        self._progress_bar.setMinimumHeight(0)
        self._progress_bar.setMaximumHeight(self._UNBOUNDED_WIDGET_HEIGHT)
        super().reset_card_growth()

    def set_state(self, state: OverlayState) -> None:
        """Apply a new state to the loading overlay."""
        self.set_draw_background(state.draw_background)
        self.set_logo_action(state.logo_action)

        self._title_label.setText(self._display_text(state.title))
        self._message_label.setText(self._display_text(state.message))
        self._details_label.setVisible(bool(state.details))
        self._details_label.setText(self._display_text(state.details or ""))

        self._cancel_action = state.secondary_action
        is_cancel_visible = state.secondary_action.action != OverlayAction.NONE
        self._cancel_button.setVisible(is_cancel_visible)
        self._cancel_button.set_waiting(state.cancel_pending)
        if is_cancel_visible:
            tooltip = (
                self.tr("Waiting for cancellation to finish.")
                if state.cancel_pending
                else state.secondary_action.tooltip
                or self.tr("Cancel current operation.")
            )
            self._cancel_button.setToolTip(tooltip)
        else:
            self._cancel_button.setToolTip("")

        self._set_minimum_header_heights()
        self.sync_layout()

    def _set_minimum_header_heights(self) -> None:
        """Keep the header baseline stable while allowing wrapped title growth."""
        title_height = self._title_label.sizeHint().height()
        progress_height = self._progress_bar.sizeHint().height()
        if self._title_height_anchor is None:
            self._title_height_anchor = title_height
        if self._progress_height_anchor is None:
            self._progress_height_anchor = progress_height

        self._title_label.setMinimumHeight(self._title_height_anchor)
        self._progress_bar.setFixedHeight(self._progress_height_anchor)

    def _set_content_metrics(
        self,
        padding: int,
        spacing: int,
    ) -> None:
        vertical_padding = min(padding, self._MAXIMUM_VERTICAL_CARD_PADDING)
        margins = self._content_layout.contentsMargins()
        if (
            margins.left() != padding
            or margins.top() != vertical_padding
            or margins.right() != padding
            or margins.bottom() != vertical_padding
        ):
            self._content_layout.setContentsMargins(
                padding,
                vertical_padding,
                padding,
                vertical_padding,
            )

        if self._content_layout.spacing() != spacing:
            self._content_layout.setSpacing(spacing)

        if self._compact_label.margin() != padding:
            self._compact_label.setMargin(padding)

    def _horizontal_content_width_for_preferred_layout(self) -> int:
        if self._cancel_button.isHidden():
            return 0

        return (
            self._progress_bar.minimumSizeHint().width()
            + self._PROGRESS_CANCEL_SPACING
            + self._cancel_button.minimumSizeHint().width()
            + self._LAYOUT_RESERVE
        )

    def _update_responsive_layout(
        self,
        content_width: int,
        card_width: int,
    ) -> None:
        del card_width
        progress_height = self._progress_bar.sizeHint().height()
        if progress_height > 0:
            self._cancel_button.set_button_height(progress_height)

        required_width = self._horizontal_content_width_for_preferred_layout()
        if self._cancel_button.isHidden() or content_width >= required_width:
            direction = QBoxLayout.Direction.LeftToRight
            spacing = self._PROGRESS_CANCEL_SPACING
        else:
            direction = QBoxLayout.Direction.TopToBottom
            spacing = self._MINIMUM_PROGRESS_CANCEL_SPACING

        self._progress_direction = direction
        if self._progress_layout.direction() != direction:
            self._progress_layout.setDirection(direction)

        if self._progress_layout.spacing() != spacing:
            self._progress_layout.setSpacing(spacing)

        self._progress_layout.invalidate()
        self._content_layout.invalidate()
        self._content_widget.updateGeometry()

    def _minimum_content_width_for_readable_layout(self) -> int:
        minimum_width = self._progress_bar.minimumSizeHint().width()
        if not self._cancel_button.isHidden():
            minimum_width = max(
                minimum_width,
                self._cancel_button.minimumSizeHint().width(),
            )

        return minimum_width

    def _card_top_for_height(self, size: QSize, card_height: int) -> int:
        centered_top = super()._card_top_for_height(size, card_height)
        if self._card_top_anchor is None or self._card_top_anchor_size != size:
            self._card_top_anchor = centered_top
            self._card_top_anchor_size = QSize(size)
            return centered_top

        max_top = max(
            self._MINIMUM_OUTER_MARGIN,
            size.height() - self._MINIMUM_OUTER_MARGIN - card_height,
        )
        anchored_top = self._clamp(
            self._card_top_anchor,
            self._MINIMUM_OUTER_MARGIN,
            max_top,
        )
        self._card_top_anchor = anchored_top
        return anchored_top

    def _prepare_content_for_minimum_layout(self) -> None:
        self._progress_direction = QBoxLayout.Direction.TopToBottom
        if self._progress_layout.direction() != self._progress_direction:
            self._progress_layout.setDirection(self._progress_direction)

        if self._progress_layout.spacing() != (
            self._MINIMUM_PROGRESS_CANCEL_SPACING
        ):
            self._progress_layout.setSpacing(
                self._MINIMUM_PROGRESS_CANCEL_SPACING
            )

        self._progress_layout.invalidate()

    def _prepare_content_for_layout(self) -> None:
        self._progress_direction = QBoxLayout.Direction.LeftToRight
        if self._progress_layout.direction() != self._progress_direction:
            self._progress_layout.setDirection(self._progress_direction)

        if self._progress_layout.spacing() != self._PROGRESS_CANCEL_SPACING:
            self._progress_layout.setSpacing(self._PROGRESS_CANCEL_SPACING)

    def _emit_cancel_action(self) -> None:
        if self._cancel_button.is_waiting():
            return

        if self._cancel_action.action == OverlayAction.NONE:
            return

        self.action_requested.emit(self._cancel_action.action)

    def _emit_logo_action(self) -> None:
        if self._logo_action == OverlayAction.NONE:
            return

        self.action_requested.emit(self._logo_action)
