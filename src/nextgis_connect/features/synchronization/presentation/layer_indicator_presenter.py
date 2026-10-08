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

from typing import Dict, Tuple

from qgis.PyQt.QtCore import QObject, QRect, QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QIcon, QPainter, QPixmap

from nextgis_connect.features.synchronization.presentation.layer_indicator_state import (
    DetachedLayerIndicatorState,
    DetachedLayerIndicatorStateResolver,
    DetachedLayerIndicatorStateSource,
)
from nextgis_connect.legacy.detached_editing.utils import DetachedLayerState
from nextgis_connect.ui_kit.icons import plugin_icon


class DetachedLayerIndicatorPresenter(QObject):
    """Emit ready-to-display indicator icons and tooltip text."""

    _ANIMATION_DELAY_MS = 1000
    _ANIMATION_INTERVAL_MS = 25
    _BLINK_DURATION_TICKS = 10
    _BLINK_PERIOD_TICKS = 50
    _ICON_SIZE = QSize(33, 33)
    _ROTATION_STEP_DEGREES = 5

    icon_changed = pyqtSignal(QIcon, name="iconChanged")
    tooltip_changed = pyqtSignal(str, name="tooltipChanged")

    def __init__(
        self,
        source: DetachedLayerIndicatorStateSource,
        parent: QObject,
    ) -> None:
        """Initialize presenter.

        :param source: Detached synchronization state source.
        :param parent: Parent QObject.
        """
        super().__init__(parent)

        self._angle = 0
        self._current_icon = QIcon()
        self._current_tooltip = ""
        default_icon_path = (
            DetachedLayerIndicatorStateResolver.NOT_SYNCHRONIZED_ICON_PATH
        )
        self._indicator_state = DetachedLayerIndicatorState(
            icon_path=default_icon_path,
            tooltip="",
        )
        self._resolver = DetachedLayerIndicatorStateResolver(self)
        self._rotated_icons: Dict[Tuple[str, int], QIcon] = {}
        self._source = source
        self._tick = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._ANIMATION_INTERVAL_MS)
        self._timer.timeout.connect(self._sync_tick)
        self._animation_start_timer = QTimer(self)
        self._animation_start_timer.setSingleShot(True)
        self._animation_start_timer.setInterval(self._ANIMATION_DELAY_MS)
        self._animation_start_timer.timeout.connect(
            self._start_animation_if_synchronizing
        )

        self.refresh()

    @property
    def current_icon(self) -> QIcon:
        """Return last emitted icon."""
        return self._current_icon

    @property
    def current_tooltip(self) -> str:
        """Return last emitted tooltip."""
        return self._current_tooltip

    def refresh(self) -> None:
        """Refresh presentation state from the state source."""
        self._timer.stop()
        self._animation_start_timer.stop()
        self._angle = 0
        self._tick = 0

        self._indicator_state = self._resolver.resolve(self._source)
        self._emit_indicator_state(self._indicator_state)

        if not self._indicator_state.is_animation_enabled:
            return

        self._animation_start_timer.start()

    def _start_animation_if_synchronizing(self) -> None:
        if self._source.state != DetachedLayerState.Synchronization:
            return

        if not self._indicator_state.is_animation_enabled:
            return

        self._timer.start()

    def _sync_tick(self) -> None:
        self._tick += 1

        blink_tick = self._tick % self._BLINK_PERIOD_TICKS
        self._angle -= self._ROTATION_STEP_DEGREES
        if blink_tick < self._BLINK_DURATION_TICKS:
            self._set_current_icon(
                self._rotated_icon(
                    self._indicator_state.animation_blink_icon_path,
                    self._angle,
                )
            )
            return

        self._set_current_icon(
            self._rotated_icon(
                self._indicator_state.animation_icon_path,
                self._angle,
            )
        )

    def _emit_indicator_state(
        self,
        indicator_state: DetachedLayerIndicatorState,
    ) -> None:
        if indicator_state.is_animation_enabled:
            self._set_current_icon(
                self._rotated_icon(indicator_state.icon_path)
            )
        else:
            self._set_current_icon(plugin_icon(indicator_state.icon_path))

        self._current_tooltip = indicator_state.tooltip
        self.tooltip_changed.emit(self._current_tooltip)

    def _set_current_icon(self, icon: QIcon) -> None:
        self._current_icon = icon
        self.icon_changed.emit(self._current_icon)

    def _rotated_icon(
        self,
        icon_path: str,
        angle: int = 0,
    ) -> QIcon:
        normalized_angle = angle % 360
        cache_key = (icon_path, normalized_angle)
        if cache_key not in self._rotated_icons:
            self._rotated_icons[cache_key] = self._render_rotated_icon(
                icon_path,
                normalized_angle,
            )

        return self._rotated_icons[cache_key]

    def _render_rotated_icon(self, icon_path: str, angle: int) -> QIcon:
        icon = plugin_icon(icon_path)
        source_pixmap = icon.pixmap(self._ICON_SIZE)
        target_pixmap = QPixmap(self._ICON_SIZE)
        target_pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(target_pixmap)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(
            self._ICON_SIZE.width() / 2,
            self._ICON_SIZE.height() / 2,
        )
        painter.rotate(angle)
        painter.translate(
            -self._ICON_SIZE.width() / 2,
            -self._ICON_SIZE.height() / 2,
        )
        painter.drawPixmap(
            QRect(
                0,
                0,
                self._ICON_SIZE.width(),
                self._ICON_SIZE.height(),
            ),
            source_pixmap,
        )
        painter.end()

        return QIcon(target_pixmap)
