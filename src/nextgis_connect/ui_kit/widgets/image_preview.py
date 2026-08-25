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

import re
import shutil
from dataclasses import dataclass
from enum import Enum
from html import escape
from pathlib import Path
from typing import Callable, Optional, Sequence, Set

from qgis.PyQt.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from qgis.PyQt.QtGui import (
    QCloseEvent,
    QCursor,
    QDesktopServices,
    QFontMetrics,
    QIcon,
    QImage,
    QImageReader,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QTransform,
    QWheelEvent,
)
from qgis.PyQt.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.platform.clipboard import Clipboard
from nextgis_connect.platform.filesystem import reveal_in_file_manager
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.opengl import panorama_renderer_available
from nextgis_connect.ui_kit.icons import material_icon, qgis_icon
from nextgis_connect.ui_kit.widgets.image_projection import (
    is_equirectangular_projection,
    projection_type_from_image,
)
from nextgis_connect.ui_kit.widgets.loading_indicator import (
    LoadingIndicatorWidget,
)
from nextgis_connect.ui_kit.widgets.panorama import PanoramaWidget


@dataclass(frozen=True)
class ImagePreviewItem:
    file_path: Optional[Path]
    file_name: str
    description: Optional[str] = None
    projection_type: Optional[str] = None


class ImagePreviewMode(Enum):
    """Available image-preview renderers."""

    FLAT = "flat"
    PANORAMA = "panorama"


class ImagePreviewDialog(QDialog):
    MIN_ZOOM = 0.1
    MAX_ZOOM = 8.0
    ZOOM_STEP = 1.25
    ACTIVE_PANEL_OPACITY = 1.0
    IDLE_PANEL_OPACITY = 0.48
    MOUSE_IDLE_DELAY_MS = 1600
    RESIZE_DEBOUNCE_MS = 100
    PANEL_FADE_MS = 260
    SIDE_BUTTON_WIDTH = 42
    SIDE_BUTTON_HEIGHT = 42
    PANEL_MARGIN = 16
    PANEL_MAX_WIDTH = 400
    DESCRIPTION_HEIGHT = 20
    COUNTER_LABEL_MIN_WIDTH = 44
    COUNTER_LABEL_HORIZONTAL_PADDING = 20
    NAVIGATION_SPACING = 8
    TOOL_BUTTON_SIZE = 28
    TOOL_ICON_SIZE = 18
    TOOL_BUTTON_SPACING = 8
    ZOOM_LABEL_MIN_WIDTH = 0
    ZOOM_LABEL_HEIGHT = 34
    ZOOM_LABEL_VISIBLE_MS = 1400
    ZOOM_LABEL_FADE_MS = 220
    IMAGE_READY_CHECK_INTERVAL_MS = 150
    IMAGE_READY_MAX_WAIT_MS = 120000
    BACKGROUND_COLOR = "#202326"
    ACTIVE_ICON_COLOR = "#ffffff"
    UNAVAILABLE_ICON_COLOR = "#8f8f8f"
    ANCHOR_PATTERN = re.compile(
        r"<a\s+href=[\"'](?P<url>https?://[^\"']+)[\"'][^>]*>"
        r"(?P<label>.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")

    def __init__(
        self,
        items: Sequence[ImagePreviewItem],
        current_index: int,
        parent: Optional[QWidget] = None,
        *,
        ensure_item_ready: Optional[Callable[[int], Optional[bool]]] = None,
        prefetch_radius: int = 0,
        window_title_suffix: str = "",
        initial_mode: ImagePreviewMode = ImagePreviewMode.PANORAMA,
        preview_mode_changed: Optional[
            Callable[[ImagePreviewMode], None]
        ] = None,
    ) -> None:
        super().__init__(parent)

        self._items = list(items)
        self._current_index = max(0, min(current_index, len(items) - 1))
        self._ensure_item_ready = ensure_item_ready
        self._prefetch_radius = max(0, prefetch_radius)
        self._window_title_suffix = window_title_suffix.strip()
        self._preferred_preview_mode = initial_mode
        self._preview_mode = ImagePreviewMode.FLAT
        self._preview_mode_changed = preview_mode_changed
        self._clipboard = Clipboard()
        self._source_pixmap = QPixmap()
        self._panorama_image = QImage()
        self._panorama_widget: Optional[PanoramaWidget] = None
        self._zoom = 1.0
        self._rotation = 0
        self._is_fit_to_window = True
        self._is_panning = False
        self._last_pan_pos = QPoint()
        self._temporary_pan_offset = QPoint()
        self._description = ""
        self._is_description_expanded = False
        self._requested_item_indices: Set[int] = set()
        self._loading_attempts_remaining = 0
        self._is_panorama_available = False
        self._is_panorama_renderer_available = panorama_renderer_available()
        self._panorama_renderer_failed = False
        self._flat_view_initialized = False
        self._view_mode_positioning_scheduled = False
        self._base_panel_width = 0
        self._expanded_panel_width = 0
        self._was_maximized_before_fullscreen = False

        self.setObjectName("imagePreviewDialog")
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(self.MOUSE_IDLE_DELAY_MS)
        self._idle_timer.timeout.connect(self._set_idle_panel_opacity)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(self.RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._update_after_resize)

        self._zoom_label_timer = QTimer(self)
        self._zoom_label_timer.setSingleShot(True)
        self._zoom_label_timer.setInterval(self.ZOOM_LABEL_VISIBLE_MS)
        self._zoom_label_timer.timeout.connect(self._fade_zoom_label)

        self._image_ready_check_timer = QTimer(self)
        self._image_ready_check_timer.setSingleShot(True)
        self._image_ready_check_timer.setInterval(
            self.IMAGE_READY_CHECK_INTERVAL_MS
        )
        self._image_ready_check_timer.timeout.connect(
            self._try_load_current_item
        )

        self._update_window_title()
        self.resize(900, 700)
        self.setMouseTracking(True)
        self.setStyleSheet(
            "QDialog#imagePreviewDialog {"
            f"background: {self.BACKGROUND_COLOR};"
            "}"
        )

        self._load_ui()
        self._setup_shortcuts()
        self._show_current_item()

    @property
    def window_title_suffix(self) -> str:
        return self._window_title_suffix

    @window_title_suffix.setter
    def window_title_suffix(self, suffix: str) -> None:
        self._window_title_suffix = suffix.strip()
        self._update_window_title()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._refit_current_image()
        if (
            self._is_panorama_available
            and self._is_panorama_renderer_available
            and self._preferred_preview_mode == ImagePreviewMode.PANORAMA
        ):
            QTimer.singleShot(0, self._activate_preferred_panorama_mode)
        if self._view_mode_button.isHidden():
            self._schedule_expanded_panel_position()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._panorama_widget is not None:
            self._panorama_widget.shutdown()
        super().closeEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (
            QEvent.Type.Enter,
            QEvent.Type.HoverMove,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Wheel,
        ):
            self._set_active_panel_opacity()

        if isinstance(watched, (QPushButton, QToolButton)):
            if isinstance(event, QMouseEvent):
                self._collapse_description_on_outside_click(watched, event)
            return False

        if not hasattr(self, "_scroll_area") or not hasattr(self, "_overlay"):
            return False

        if (
            event.type() == QEvent.Type.Resize
            and isinstance(watched, QWidget)
            and watched in (self._content, self._scroll_area.viewport())
        ):
            self._sync_overlay_geometry()

        interactive_view_widgets = (
            self._image_label,
            self._scroll_area,
            self._scroll_area.viewport(),
            self._overlay,
        )
        if watched not in interactive_view_widgets:
            return False

        if isinstance(event, QMouseEvent):
            self._collapse_description_on_outside_click(watched, event)
            if self._is_control_event(watched, event):
                return False

            if event.type() == QEvent.Type.MouseButtonPress:
                self._start_panning(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.MouseMove:
                self._continue_panning(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._finish_panning(event)
                return event.isAccepted()
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._toggle_fullscreen(event)
                return event.isAccepted()

        if isinstance(event, QWheelEvent):
            self._handle_wheel(event)
            return event.isAccepted()

        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_L):
            self._show_next_item()
            return

        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_H):
            self._show_previous_item()
            return

        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        self._collapse_description_on_outside_click(self, event)
        if self._is_control_event(self, event):
            super().mousePressEvent(event)
            return

        self._start_panning(event)
        if event.isAccepted():
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        self._continue_panning(event)
        if event.isAccepted():
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        self._finish_panning(event)
        if event.isAccepted():
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if self._is_control_event(self, event):
            super().mouseDoubleClickEvent(event)
            return
        self._toggle_fullscreen(event)
        if event.isAccepted():
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        self._handle_wheel(event)
        if event.isAccepted():
            return

        super().wheelEvent(event)

    def _start_panning(self, event: QMouseEvent) -> None:
        if self._source_pixmap.isNull():
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._preview_mode == ImagePreviewMode.PANORAMA:
            panorama_widget = self._panorama_widget
            if panorama_widget is None:
                return
            panorama_widget.start_drag(event.pos())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        self._is_panning = True
        self._last_pan_pos = event.pos()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def _is_control_event(self, watched: QObject, event: QMouseEvent) -> bool:
        if not hasattr(self, "_panel") or not isinstance(watched, QWidget):
            return False

        dialog_position = watched.mapTo(self, event.pos())
        return self._panel.geometry().contains(
            dialog_position
        ) or self._zoom_label.geometry().contains(dialog_position)

    def _is_panel_event(self, watched: QObject, event: QMouseEvent) -> bool:
        if not hasattr(self, "_panel") or not isinstance(watched, QWidget):
            return False

        dialog_position = watched.mapTo(self, event.pos())
        return self._panel.geometry().contains(dialog_position)

    def _collapse_description_on_outside_click(
        self,
        watched: QObject,
        event: QMouseEvent,
    ) -> None:
        if event.type() != QEvent.Type.MouseButtonPress:
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if not self._is_description_expanded:
            return

        if self._is_panel_event(watched, event):
            return

        self._collapse_description()

    def _continue_panning(self, event: QMouseEvent) -> None:
        self._set_active_panel_opacity()
        if self._preview_mode == ImagePreviewMode.PANORAMA:
            panorama_widget = self._panorama_widget
            if panorama_widget is None:
                return
            panorama_widget.drag_to(event.pos())
            if panorama_widget.is_dragging:
                event.accept()
            return
        if not self._is_panning:
            return

        delta = event.pos() - self._last_pan_pos
        self._last_pan_pos = event.pos()
        self._pan(delta)
        event.accept()

    def _finish_panning(self, event: QMouseEvent) -> None:
        if self._preview_mode == ImagePreviewMode.PANORAMA:
            if event.button() == Qt.MouseButton.LeftButton:
                panorama_widget = self._panorama_widget
                if panorama_widget is None:
                    return
                panorama_widget.end_drag()
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                event.accept()
            return
        if (
            event.button()
            not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton)
            or not self._is_panning
        ):
            return

        self._is_panning = False
        self.unsetCursor()
        self._reset_temporary_pan()
        event.accept()

    def _handle_wheel(self, event: QWheelEvent) -> None:
        if self._source_pixmap.isNull():
            return

        if event.angleDelta().y() > 0:
            self._zoom_in()
        elif event.angleDelta().y() < 0:
            self._zoom_out()
        else:
            return

        event.accept()

    def _toggle_fullscreen(self, event: Optional[QMouseEvent] = None) -> None:
        if event is not None and event.button() != Qt.MouseButton.LeftButton:
            return
        if self._source_pixmap.isNull():
            return

        if self.isFullScreen():
            if self._was_maximized_before_fullscreen:
                self.showMaximized()
            else:
                self.showNormal()
        else:
            self._was_maximized_before_fullscreen = self.isMaximized()
            self.showFullScreen()
        self._update_fullscreen_button()
        QTimer.singleShot(0, self._restore_overlay_interaction)
        if event is not None:
            event.accept()

    def _restore_overlay_interaction(self) -> None:
        self._sync_overlay_geometry()
        self._overlay.raise_()
        self._panel.raise_()
        if self._loading_overlay.isVisible():
            self._loading_overlay.raise_()
        self._update_fullscreen_button()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_resize_timer"):
            self._resize_timer.start()

    def _load_ui(self) -> None:
        layout = QStackedLayout(self)
        layout.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self._image_label.installEventFilter(self)
        self._image_label.setMouseTracking(True)
        self._image_label.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._image_label.customContextMenuRequested.connect(
            self._show_context_menu
        )

        self._content = QWidget(self)
        self._content.installEventFilter(self)
        self._content_layout = QStackedLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll_area = QScrollArea(self._content)
        self._scroll_area.setWidget(self._image_label)
        self._scroll_area.setWidgetResizable(False)
        self._scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setStyleSheet(
            f"QScrollArea {{background: {self.BACKGROUND_COLOR};}}"
        )
        self._scroll_area.viewport().setStyleSheet(
            f"background: {self.BACKGROUND_COLOR};"
        )
        self._image_label.setStyleSheet(
            f"background: {self.BACKGROUND_COLOR};"
        )
        self._scroll_area.viewport().installEventFilter(self)
        self._scroll_area.installEventFilter(self)
        self._scroll_area.viewport().setMouseTracking(True)
        self._scroll_area.viewport().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._scroll_area.viewport().customContextMenuRequested.connect(
            self._show_context_menu
        )
        self._content_layout.addWidget(self._scroll_area)

        layout.addWidget(self._content)

        self._overlay = QWidget(self)
        self._overlay.installEventFilter(self)
        self._overlay.setMouseTracking(True)
        self._overlay.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._overlay.customContextMenuRequested.connect(
            self._show_context_menu
        )
        overlay_layout = QGridLayout(self._overlay)
        overlay_layout.setContentsMargins(
            self.PANEL_MARGIN,
            self.PANEL_MARGIN,
            self.PANEL_MARGIN,
            self.PANEL_MARGIN,
        )
        overlay_layout.setSpacing(0)
        overlay_layout.setColumnStretch(0, 0)
        overlay_layout.setColumnStretch(1, 1)
        overlay_layout.setColumnStretch(2, 0)
        overlay_layout.setRowStretch(0, 1)
        overlay_layout.setRowStretch(1, 0)
        overlay_layout.setRowStretch(2, 1)

        self._previous_area = self._side_button("chevron_left")
        self._previous_area.clicked.connect(self._show_previous_item)
        self._next_area = self._side_button("chevron_right")
        self._next_area.clicked.connect(self._show_next_item)
        self._side_button_opacity_effects = [
            QGraphicsOpacityEffect(self._previous_area),
            QGraphicsOpacityEffect(self._next_area),
        ]
        self._side_button_fade_animations = [
            QPropertyAnimation(effect, b"opacity", self)
            for effect in self._side_button_opacity_effects
        ]
        for button, effect in zip(
            (self._previous_area, self._next_area),
            self._side_button_opacity_effects,
        ):
            button.setGraphicsEffect(effect)
        for animation in self._side_button_fade_animations:
            animation.setDuration(self.PANEL_FADE_MS)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        overlay_layout.addWidget(
            self._previous_area,
            1,
            0,
            alignment=Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
        )
        overlay_layout.addWidget(
            self._next_area,
            1,
            2,
            alignment=Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter,
        )

        self._panel = QFrame(self)
        self._panel.installEventFilter(self)
        self._panel.setMouseTracking(True)
        self._panel.setObjectName("imagePreviewPanel")
        self._panel.setStyleSheet(
            """
            QFrame#imagePreviewPanel {
                background: rgba(24, 24, 24, 225);
                border-radius: 4px;
            }
            QLabel {
                color: white;
            }
            QToolButton {
                border: none;
                color: white;
                font-weight: 600;
                min-width: 28px;
                max-width: 28px;
                min-height: 28px;
                max-height: 28px;
                padding: 4px;
            }
            QToolButton:disabled {
                color: rgba(255, 255, 255, 90);
            }
            """
        )
        self._panel.setMaximumWidth(self.PANEL_MAX_WIDTH)
        self._panel_opacity = QGraphicsOpacityEffect(self._panel)
        self._panel.setGraphicsEffect(self._panel_opacity)
        self._panel_fade_animation = QPropertyAnimation(
            self._panel_opacity,
            b"opacity",
            self,
        )
        self._panel_fade_animation.setDuration(self.PANEL_FADE_MS)
        self._panel_fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(2)

        self._description_label = QLabel(self._panel)
        self._description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._description_label.setFixedHeight(self.DESCRIPTION_HEIGHT)
        self._description_label.setTextFormat(Qt.TextFormat.RichText)
        self._description_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._description_label.linkActivated.connect(self._expand_description)
        panel_layout.addWidget(self._description_label)

        tools_layout = QHBoxLayout()
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(self.TOOL_BUTTON_SPACING)
        self._previous_button = self._tool_button(icon_name="chevron_left")
        self._previous_button.clicked.connect(self._show_previous_item)
        self._next_button = self._tool_button(icon_name="chevron_right")
        self._next_button.clicked.connect(self._show_next_item)
        self._zoom_in_button = self._tool_button(icon_name="zoom_in")
        self._zoom_in_button.clicked.connect(self._zoom_in)
        self._zoom_out_button = self._tool_button(icon_name="zoom_out")
        self._zoom_out_button.clicked.connect(self._zoom_out)
        self._rotate_left_button = self._tool_button(
            icon_name="rotate_90_degrees_ccw"
        )
        self._rotate_left_button.clicked.connect(self._rotate_left)
        self._rotate_right_button = self._tool_button(
            icon_name="rotate_90_degrees_cw"
        )
        self._rotate_right_button.clicked.connect(self._rotate_right)
        self._fullscreen_button = self._tool_button(icon_name="fullscreen")
        self._fullscreen_button.clicked.connect(
            lambda: self._toggle_fullscreen()
        )
        self._view_mode_button = self._tool_button(icon_name="vrpano")
        self._view_mode_button.clicked.connect(self._toggle_preview_mode)

        self._navigation_widget = QWidget(self._panel)
        self._navigation_widget.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        navigation_layout = QHBoxLayout(self._navigation_widget)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(self.NAVIGATION_SPACING)
        navigation_layout.addWidget(self._previous_button)
        self._counter_label = QLabel(self._navigation_widget)
        self._counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._counter_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        navigation_layout.addWidget(
            self._counter_label,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        navigation_layout.addWidget(self._next_button)
        tools_layout.addWidget(self._navigation_widget)

        for widget in (
            self._zoom_in_button,
            self._zoom_out_button,
            self._rotate_left_button,
            self._rotate_right_button,
            self._fullscreen_button,
            self._view_mode_button,
        ):
            tools_layout.addWidget(widget)

        panel_layout.addLayout(tools_layout)
        self._view_mode_button.hide()

        self._zoom_label = QFrame(self)
        self._zoom_label.setMinimumWidth(self.ZOOM_LABEL_MIN_WIDTH)
        self._zoom_label.setFixedHeight(self.ZOOM_LABEL_HEIGHT)
        self._zoom_label.setStyleSheet(
            """
            QFrame {
                background: rgba(24, 24, 24, 225);
                border-radius: 4px;
            }
            QLabel {
                background: transparent;
                color: white;
                font-weight: 600;
            }
            """
        )
        zoom_label_layout = QHBoxLayout(self._zoom_label)
        zoom_label_layout.setContentsMargins(10, 0, 10, 0)
        zoom_label_layout.setSpacing(6)
        self._zoom_label_icon = QLabel(self._zoom_label)
        self._zoom_label_icon.setPixmap(
            material_icon("zoom_in", color="#ffffff").pixmap(
                self.TOOL_ICON_SIZE,
                self.TOOL_ICON_SIZE,
            )
        )
        self._zoom_label_text = QLabel(self._zoom_label)
        self._zoom_label_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_label_layout.addWidget(self._zoom_label_icon)
        zoom_label_layout.addWidget(self._zoom_label_text)
        self._zoom_label_opacity = QGraphicsOpacityEffect(self._zoom_label)
        self._zoom_label.setGraphicsEffect(self._zoom_label_opacity)
        self._zoom_label_fade_animation = QPropertyAnimation(
            self._zoom_label_opacity,
            b"opacity",
            self,
        )
        self._zoom_label_fade_animation.setDuration(self.ZOOM_LABEL_FADE_MS)
        self._zoom_label_fade_animation.setStartValue(1.0)
        self._zoom_label_fade_animation.setEndValue(0.0)
        self._zoom_label_fade_animation.setEasingCurve(
            QEasingCurve.Type.OutCubic
        )
        self._zoom_label_fade_animation.finished.connect(self._hide_zoom_label)
        self._zoom_label.hide()
        self._loading_overlay = QWidget(self)
        self._loading_overlay.setStyleSheet(
            f"background: {self.BACKGROUND_COLOR};"
        )
        loading_layout = QVBoxLayout(self._loading_overlay)
        loading_layout.addStretch()
        loading_layout.addWidget(
            LoadingIndicatorWidget(self._loading_overlay, size=QSize(36, 36)),
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        loading_layout.addStretch()
        self._loading_overlay.hide()
        layout.addWidget(self._loading_overlay)

        self._raise_overlays()
        self._set_active_panel_opacity()

    def _setup_shortcuts(self) -> None:
        shortcuts = {
            Qt.Key.Key_Left: self._show_previous_item,
            Qt.Key.Key_H: self._show_previous_item,
            Qt.Key.Key_Right: self._show_next_item,
            Qt.Key.Key_L: self._show_next_item,
        }
        for key, slot in shortcuts.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(slot)

        zoom_in_shortcut = QShortcut(QKeySequence("Ctrl++"), self)
        zoom_in_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        zoom_in_shortcut.activated.connect(self._zoom_in)

        zoom_in_alt_shortcut = QShortcut(QKeySequence("Ctrl+="), self)
        zoom_in_alt_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        zoom_in_alt_shortcut.activated.connect(self._zoom_in)

        zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        zoom_out_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        zoom_out_shortcut.activated.connect(self._zoom_out)

        copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        copy_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        copy_shortcut.activated.connect(self._copy_current_image)

    def _side_button(self, icon_name: str) -> QPushButton:
        button = QPushButton(self)
        button.setProperty("materialIconName", icon_name)
        button.setIcon(self._navigation_icon(icon_name, available=True))
        button.setIconSize(QSize(self.TOOL_ICON_SIZE, self.TOOL_ICON_SIZE))
        button.setFixedSize(self.SIDE_BUTTON_WIDTH, self.SIDE_BUTTON_HEIGHT)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.installEventFilter(self)
        button.setMouseTracking(True)
        button.setStyleSheet(
            """
            QPushButton {
                background: rgba(24, 24, 24, 90);
                border: none;
                border-radius: 21px;
                color: white;
                font-size: 24px;
            }
            QPushButton:hover {
                background: rgba(24, 24, 24, 150);
            }
            QPushButton:pressed {
                background: rgba(24, 24, 24, 210);
            }
            QPushButton:disabled {
                background: rgba(24, 24, 24, 54);
                color: rgba(255, 255, 255, 80);
            }
            QPushButton[navUnavailable="true"] {
                background: rgba(24, 24, 24, 54);
                color: rgba(255, 255, 255, 80);
            }
            QPushButton[navUnavailable="true"]:hover {
                background: rgba(24, 24, 24, 80);
            }
            QPushButton[navUnavailable="true"]:pressed {
                background: rgba(24, 24, 24, 110);
            }
            """
        )
        button.pressed.connect(self._set_active_panel_opacity)
        return button

    def _tool_button(
        self,
        text: str = "",
        *,
        icon_name: Optional[str] = None,
    ) -> QToolButton:
        button = QToolButton(self._panel)
        if icon_name is not None:
            button.setProperty("materialIconName", icon_name)
            button.setIcon(self._navigation_icon(icon_name, available=True))
            button.setIconSize(QSize(self.TOOL_ICON_SIZE, self.TOOL_ICON_SIZE))
        else:
            button.setText(text)
        button.setFixedSize(self.TOOL_BUTTON_SIZE, self.TOOL_BUTTON_SIZE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.installEventFilter(self)
        button.setMouseTracking(True)
        button.setStyleSheet(
            """
            QToolButton:hover {
                background: rgba(255, 255, 255, 32);
                border-radius: 3px;
            }
            QToolButton:pressed {
                background: rgba(255, 255, 255, 54);
                border-radius: 3px;
            }
            QToolButton[navUnavailable="true"] {
                background: transparent;
                color: rgba(255, 255, 255, 90);
            }
            QToolButton[navUnavailable="true"]:hover {
                background: rgba(255, 255, 255, 20);
                border-radius: 3px;
            }
            QToolButton[navUnavailable="true"]:pressed {
                background: rgba(255, 255, 255, 32);
                border-radius: 3px;
            }
            """
        )
        button.setToolTip("")
        button.pressed.connect(self._set_active_panel_opacity)
        button.released.connect(lambda button=button: button.setDown(False))
        button.clicked.connect(self._raise_interactive_panel)
        return button

    def _navigation_icon(self, icon_name: str, available: bool) -> QIcon:
        color = (
            self.ACTIVE_ICON_COLOR
            if available
            else self.UNAVAILABLE_ICON_COLOR
        )
        return material_icon(icon_name, color=color)

    def _raise_overlays(self) -> None:
        self._overlay.raise_()
        self._panel.raise_()
        self._zoom_label.raise_()
        self._loading_overlay.raise_()

    def _raise_interactive_panel(self) -> None:
        self._overlay.raise_()
        self._panel.raise_()

    def _show_current_item(self) -> None:
        if not self._items:
            self._show_empty_state()
            return

        self._set_active_panel_opacity()
        self._zoom = 1.0
        self._rotation = 0
        self._is_fit_to_window = True
        self._temporary_pan_offset = QPoint()
        self._source_pixmap = QPixmap()
        self._panorama_image = QImage()
        self._image_label.clear()
        self._is_panorama_available = False
        self._is_panorama_renderer_available = False
        self._flat_view_initialized = False
        self._set_preview_mode(ImagePreviewMode.FLAT, persist=False)
        self._is_description_expanded = False
        self._set_image_controls_enabled(False)
        self._image_ready_check_timer.stop()
        self._loading_attempts_remaining = (
            self.IMAGE_READY_MAX_WAIT_MS // self.IMAGE_READY_CHECK_INTERVAL_MS
        )

        item = self._current_item()
        if item is None:
            self._show_empty_state()
            return

        self._update_panel_state()
        self._request_ready_items()
        self._try_load_current_item()

    def _request_ready_items(self) -> None:
        if self._ensure_item_ready is None:
            return

        for item_index in self._item_indices_to_request():
            self._request_item_ready(item_index)

    def _item_indices_to_request(self) -> Sequence[int]:
        item_indices = [self._current_index]
        for offset in range(1, self._prefetch_radius + 1):
            item_indices.append(self._current_index + offset)
            item_indices.append(self._current_index - offset)

        return [
            item_index
            for item_index in item_indices
            if 0 <= item_index < len(self._items)
        ]

    def _request_item_ready(self, item_index: int) -> None:
        if item_index in self._requested_item_indices:
            return

        item = self._items[item_index]
        if item.file_path is not None and item.file_path.exists():
            return

        assert self._ensure_item_ready is not None
        self._requested_item_indices.add(item_index)
        is_request_accepted = self._ensure_item_ready(item_index)
        if is_request_accepted is False:
            self._requested_item_indices.discard(item_index)

    def _try_load_current_item(self) -> None:
        item = self._current_item()
        if item is None:
            self._show_empty_state()
            return

        if self._load_pixmap(item.file_path):
            self._requested_item_indices.discard(self._current_index)
            self._image_ready_check_timer.stop()
            self._set_loading_visible(False)
            return

        if not self._should_wait_for_current_item(item):
            if self._loading_attempts_remaining <= 0:
                self._requested_item_indices.discard(self._current_index)
            self._image_ready_check_timer.stop()
            self._set_loading_visible(False)
            return

        self._loading_attempts_remaining -= 1
        self._set_loading_visible(True)
        self._image_ready_check_timer.start()

    def _should_wait_for_current_item(self, item: ImagePreviewItem) -> bool:
        return (
            self._ensure_item_ready is not None
            and item.file_path is not None
            and self._current_index in self._requested_item_indices
            and self._loading_attempts_remaining > 0
        )

    def _show_empty_state(self) -> None:
        self._source_pixmap = QPixmap()
        self._image_label.clear()
        self._flat_view_initialized = False
        self._description = ""
        self._description_label.setVisible(False)
        self._set_counter_text("0 / 0")
        self._previous_button.setEnabled(False)
        self._previous_area.setEnabled(False)
        self._next_button.setEnabled(False)
        self._next_area.setEnabled(False)
        self._set_image_controls_enabled(False)
        self._update_view_mode_button()
        self._update_window_title()
        self._panel.adjustSize()
        self._schedule_expanded_panel_position()

    def _load_pixmap(self, image_path: Optional[Path]) -> bool:
        if image_path is None or not image_path.is_file():
            self._source_pixmap = QPixmap()
            self._image_label.clear()
            self._update_window_title()
            self._set_image_controls_enabled(False)
            return False

        image_reader = QImageReader(str(image_path))
        image_reader.setAutoTransform(True)
        image = image_reader.read()
        if image.isNull():
            self._source_pixmap = QPixmap()
            self._image_label.clear()
            self._update_window_title()
            self._set_image_controls_enabled(False)
            return False

        self._source_pixmap = QPixmap.fromImage(image)
        if self._source_pixmap.isNull():
            self._image_label.clear()
            self._update_window_title()
            self._set_image_controls_enabled(False)
            return False

        projection_type = self._current_projection_type(image_path)
        is_equirectangular = is_equirectangular_projection(projection_type)
        logger.debug(
            "Image preview probe: projection=%s, panorama_renderer_available=%s, "
            "renderer_failed=%s",
            projection_type or "none",
            self._is_panorama_renderer_available,
            self._panorama_renderer_failed,
        )
        self._is_panorama_available = is_equirectangular
        self._is_panorama_renderer_available = (
            panorama_renderer_available()
            and not self._panorama_renderer_failed
        )
        if is_equirectangular and not self._is_panorama_renderer_available:
            logger.warning(
                "Panorama renderer unavailable; opening the image in flat mode"
            )
        if self._is_panorama_available:
            self._panorama_image = QImage(image)
            if (
                self._is_panorama_renderer_available
                and self._panorama_widget is not None
            ):
                self._panorama_widget.set_image(self._panorama_image)
                self._panorama_widget.reset_view()
            mode = (
                self._preferred_preview_mode
                if self.isVisible() and self._is_panorama_renderer_available
                else ImagePreviewMode.FLAT
            )
            self._set_preview_mode(mode, persist=False)
        else:
            self._panorama_image = QImage()
            self._set_preview_mode(ImagePreviewMode.FLAT, persist=False)

        self._update_window_title()
        self._set_image_controls_enabled(True)
        self._update_view_mode_button()
        self._refit_current_image()
        return True

    def _current_projection_type(self, image_path: Path) -> Optional[str]:
        item = self._current_item()
        if item is None:
            return None
        return item.projection_type or projection_type_from_image(image_path)

    def _refit_current_image(self) -> None:
        if self._source_pixmap.isNull():
            return

        self._fit_to_window()
        self._update_image()

    def _update_image(self) -> None:
        if self._preview_mode == ImagePreviewMode.PANORAMA:
            return
        if self._source_pixmap.isNull():
            self._image_label.clear()
            return

        pixmap = self._rotated_source_pixmap()
        size = QSize(
            max(1, int(pixmap.width() * self._zoom)),
            max(1, int(pixmap.height() * self._zoom)),
        )
        scaled_pixmap = pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled_pixmap)
        self._image_label.resize(scaled_pixmap.size())
        self._flat_view_initialized = True
        self._raise_overlays()

    def _update_after_resize(self) -> None:
        self._update_description_text()
        if self._is_fit_to_window:
            self._refit_current_image()
        if self._zoom_label.isVisible():
            self._position_zoom_label()

    def _fit_to_window(self) -> None:
        if self._preview_mode == ImagePreviewMode.PANORAMA:
            return
        if self._source_pixmap.isNull():
            return

        pixmap = self._rotated_source_pixmap()
        viewport_size = self._scroll_area.viewport().size()
        if pixmap.isNull() or viewport_size.isEmpty():
            return

        width_ratio = viewport_size.width() / pixmap.width()
        height_ratio = viewport_size.height() / pixmap.height()
        self._zoom = min(1.0, width_ratio, height_ratio)

    def _rotated_source_pixmap(self) -> QPixmap:
        if self._source_pixmap.isNull():
            return QPixmap()

        if self._rotation == 0:
            return self._source_pixmap

        return self._source_pixmap.transformed(
            QTransform().rotate(self._rotation),
            Qt.TransformationMode.SmoothTransformation,
        )

    def _show_zoom_label(self) -> None:
        if self._preview_mode == ImagePreviewMode.PANORAMA:
            panorama_widget = self._panorama_widget
            if panorama_widget is None:
                return
            self._show_transient_status(
                f"{round(panorama_widget.fov)}°",
                "vrpano",
            )
            return
        self._show_transient_status(
            f"{round(self._zoom * 100)}%",
            "zoom_in",
        )

    def _show_transient_status(
        self,
        text: str,
        icon_name: str,
        *,
        fade_ms: int = ZOOM_LABEL_FADE_MS,
        visible_ms: int = ZOOM_LABEL_VISIBLE_MS,
    ) -> None:
        self._zoom_label_fade_animation.stop()
        self._zoom_label_fade_animation.setDuration(fade_ms)
        self._zoom_label_timer.setInterval(visible_ms)
        self._zoom_label_icon.setPixmap(
            material_icon(icon_name, color="#ffffff").pixmap(
                self.TOOL_ICON_SIZE,
                self.TOOL_ICON_SIZE,
            )
        )
        self._zoom_label_text.setText(text)
        self._zoom_label_opacity.setOpacity(1.0)
        self._zoom_label_timer.start()
        QTimer.singleShot(0, self._show_positioned_zoom_label)

    def _show_positioned_zoom_label(self) -> None:
        self._position_zoom_label()
        self._zoom_label.show()
        self._zoom_label.raise_()

    def _position_zoom_label(self) -> None:
        self._zoom_label_text.setMinimumWidth(0)
        self._zoom_label_text.setMaximumWidth(16777215)
        self._zoom_label_text.setFixedWidth(
            self._zoom_label_text.sizeHint().width()
        )
        self._zoom_label.adjustSize()
        width = max(
            self.ZOOM_LABEL_MIN_WIDTH, self._zoom_label.sizeHint().width()
        )
        height = self.ZOOM_LABEL_HEIGHT
        panel_position = self._panel.mapTo(self, QPoint())
        if self._preview_mode == ImagePreviewMode.FLAT:
            viewport = self._scroll_area.viewport()
            right_edge = viewport.mapTo(self, QPoint()).x() + viewport.width()
        else:
            right_edge = (
                self._content.mapTo(self, QPoint()).x() + self._content.width()
            )
        self._zoom_label.setFixedSize(width, height)
        self._zoom_label.move(
            max(0, right_edge - width - self.PANEL_MARGIN),
            max(0, panel_position.y() + (self._panel.height() - height) // 2),
        )

    def _fade_zoom_label(self) -> None:
        if not self._zoom_label.isVisible():
            return

        self._zoom_label_fade_animation.start()

    def _hide_zoom_label(self) -> None:
        self._zoom_label.hide()

    def _pan(self, delta: QPoint) -> None:
        horizontal_bar = self._scroll_area.horizontalScrollBar()
        vertical_bar = self._scroll_area.verticalScrollBar()
        if horizontal_bar.maximum() > 0 or vertical_bar.maximum() > 0:
            horizontal_bar.setValue(horizontal_bar.value() - delta.x())
            vertical_bar.setValue(vertical_bar.value() - delta.y())
            return

        self._temporary_pan_offset += delta
        self._image_label.move(self._image_label.pos() + delta)

    def _reset_temporary_pan(self) -> None:
        if self._temporary_pan_offset.isNull():
            return

        self._temporary_pan_offset = QPoint()
        self._update_image()

    def _show_previous_item(self) -> None:
        if not self._items:
            return

        if self._current_index <= 0:
            self._show_transient_status(
                self.tr("First image"),
                "info",
                fade_ms=self.PANEL_FADE_MS,
                visible_ms=self.MOUSE_IDLE_DELAY_MS,
            )
            self._set_active_panel_opacity()
            return

        self._current_index -= 1
        self._show_current_item()

    def _show_next_item(self) -> None:
        if not self._items:
            return

        if self._current_index >= len(self._items) - 1:
            self._show_transient_status(
                self.tr("Last image"),
                "info",
                fade_ms=self.PANEL_FADE_MS,
                visible_ms=self.MOUSE_IDLE_DELAY_MS,
            )
            self._set_active_panel_opacity()
            return

        self._current_index += 1
        self._show_current_item()

    def _zoom_in(self) -> None:
        if self._source_pixmap.isNull():
            return

        if self._preview_mode == ImagePreviewMode.PANORAMA:
            panorama_widget = self._panorama_widget
            if panorama_widget is None:
                return
            panorama_widget.zoom_in()
            self._show_zoom_label()
            return

        self._is_fit_to_window = False
        self._temporary_pan_offset = QPoint()
        self._zoom = min(self.MAX_ZOOM, self._zoom * self.ZOOM_STEP)
        self._update_image()
        self._show_zoom_label()

    def _zoom_out(self) -> None:
        if self._source_pixmap.isNull():
            return

        if self._preview_mode == ImagePreviewMode.PANORAMA:
            panorama_widget = self._panorama_widget
            if panorama_widget is None:
                return
            panorama_widget.zoom_out()
            self._show_zoom_label()
            return

        self._is_fit_to_window = False
        self._temporary_pan_offset = QPoint()
        self._zoom = max(self.MIN_ZOOM, self._zoom / self.ZOOM_STEP)
        self._update_image()
        self._show_zoom_label()

    def _rotate_left(self) -> None:
        if self._source_pixmap.isNull():
            return

        self._rotation = (self._rotation - 90) % 360
        if self._is_fit_to_window:
            self._fit_to_window()
        self._update_image()

    def _rotate_right(self) -> None:
        if self._source_pixmap.isNull():
            return

        self._rotation = (self._rotation + 90) % 360
        if self._is_fit_to_window:
            self._fit_to_window()
        self._update_image()

    def _open_current_file(self) -> None:
        item = self._current_item()
        if item is None:
            return

        if item.file_path is None or not item.file_path.exists():
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.file_path)))

    def _update_panel_state(self) -> None:
        item = self._current_item()
        if item is None:
            self._show_empty_state()
            return

        self._description = item.description or ""
        self._description_label.setVisible(bool(self._description))
        self._update_description_text()
        self._set_counter_text(
            f"{self._current_index + 1} / {len(self._items)}",
        )

        self._set_navigation_available(
            can_go_previous=self._current_index > 0,
            can_go_next=self._current_index < len(self._items) - 1,
        )

        for button in (
            self._previous_button,
            self._next_button,
            self._zoom_in_button,
            self._zoom_out_button,
            self._rotate_left_button,
            self._rotate_right_button,
        ):
            button.setToolTip(item.file_name)

        self._zoom_in_button.setToolTip(self.tr("Zoom in"))
        self._zoom_out_button.setToolTip(self.tr("Zoom out"))
        self._rotate_left_button.setToolTip(self.tr("Rotate left"))
        self._rotate_right_button.setToolTip(self.tr("Rotate right"))
        self._previous_button.setToolTip(self.tr("Previous image"))
        self._next_button.setToolTip(self.tr("Next image"))
        self._previous_area.setToolTip(self.tr("Previous image"))
        self._next_area.setToolTip(self.tr("Next image"))

        self._panel.adjustSize()

    def _set_navigation_available(
        self,
        *,
        can_go_previous: bool,
        can_go_next: bool,
    ) -> None:
        self._set_navigation_button_available(
            self._previous_button,
            "chevron_left",
            can_go_previous,
        )
        self._set_navigation_button_available(
            self._previous_area,
            "chevron_left",
            can_go_previous,
        )
        self._set_navigation_button_available(
            self._next_button,
            "chevron_right",
            can_go_next,
        )
        self._set_navigation_button_available(
            self._next_area,
            "chevron_right",
            can_go_next,
        )

    def _set_navigation_button_available(
        self,
        button: QAbstractButton,
        icon_name: str,
        available: bool,
    ) -> None:
        button.setEnabled(True)
        button.setProperty("navUnavailable", not available)
        button.setIcon(self._navigation_icon(icon_name, available))
        self._refresh_widget_style(button)

    def _refresh_widget_style(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _set_counter_text(self, text: str) -> None:
        self._counter_label.setText(text)
        self._counter_label.setFixedWidth(self._counter_label_width())
        self._update_navigation_widget_width()

    def _counter_label_width(self) -> int:
        text = self._counter_label_width_sample()
        text_width = self._counter_label.fontMetrics().horizontalAdvance(text)
        padded_width = text_width + self.COUNTER_LABEL_HORIZONTAL_PADDING
        return max(self.COUNTER_LABEL_MIN_WIDTH, padded_width)

    def _update_navigation_widget_width(self) -> None:
        width = (
            self._previous_button.width()
            + self._counter_label.width()
            + self._next_button.width()
            + self.NAVIGATION_SPACING * 2
        )
        self._navigation_widget.setFixedWidth(width)

    def _counter_label_width_sample(self) -> str:
        if not self._items:
            return "0 / 0"

        total = str(len(self._items))
        return f"{total} / {total}"

    def _set_image_controls_enabled(self, enabled: bool) -> None:
        for button in (
            self._zoom_in_button,
            self._zoom_out_button,
            self._fullscreen_button,
        ):
            button.setEnabled(enabled)
        rotations_enabled = (
            enabled and self._preview_mode == ImagePreviewMode.FLAT
        )
        self._rotate_left_button.setEnabled(rotations_enabled)
        self._rotate_right_button.setEnabled(rotations_enabled)

    def _update_fullscreen_button(self) -> None:
        is_fullscreen = self.isFullScreen()
        self._fullscreen_button.setIcon(
            material_icon(
                "fullscreen_exit" if is_fullscreen else "fullscreen",
                color=self.ACTIVE_ICON_COLOR,
            )
        )
        self._fullscreen_button.setToolTip(
            self.tr("Exit full screen")
            if is_fullscreen
            else self.tr("Show full screen")
        )

    def _toggle_preview_mode(self) -> None:
        if not self._is_panorama_available:
            return
        mode = (
            ImagePreviewMode.FLAT
            if self._preview_mode == ImagePreviewMode.PANORAMA
            else ImagePreviewMode.PANORAMA
        )
        if (
            mode == ImagePreviewMode.PANORAMA
            and not self._is_panorama_renderer_available
        ):
            QMessageBox.warning(
                self,
                self.tr("Panorama preview unavailable"),
                self.tr(
                    "Panorama preview is unavailable because OpenGL is not "
                    "supported by this QGIS runtime. The image is shown in "
                    "flat mode."
                ),
            )
            return
        self._set_preview_mode(mode, persist=True)

    def _on_panorama_initialization_failed(self) -> None:
        panorama_widget = self._panorama_widget
        self._panorama_renderer_failed = True
        self._is_panorama_renderer_available = False
        self._set_preview_mode(ImagePreviewMode.FLAT, persist=True)
        if panorama_widget is not None:
            self._content_layout.removeWidget(panorama_widget)
            panorama_widget.shutdown()
            panorama_widget.hide()
            panorama_widget.deleteLater()
            self._panorama_widget = None
        self._refit_current_image()
        logger.warning("Panorama renderer failed; switched to flat preview")

    def _activate_preferred_panorama_mode(self) -> None:
        if (
            not self._is_panorama_available
            or not self._is_panorama_renderer_available
            or not self.isVisible()
        ):
            return
        self._set_preview_mode(self._preferred_preview_mode, persist=False)

    def _ensure_panorama_widget(self) -> Optional[PanoramaWidget]:
        if self._panorama_widget is not None:
            return self._panorama_widget
        if not self._is_panorama_renderer_available:
            return None

        logger.debug("Creating panorama OpenGL widget")
        panorama_widget = PanoramaWidget(self._content)
        panorama_widget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        panorama_widget.customContextMenuRequested.connect(
            self._show_context_menu
        )
        panorama_widget.initialization_failed.connect(
            self._on_panorama_initialization_failed
        )
        panorama_widget.rendering_failed.connect(
            self._on_panorama_initialization_failed
        )
        self._content_layout.addWidget(panorama_widget)
        panorama_widget.set_image(self._panorama_image)
        panorama_widget.reset_view()
        self._panorama_widget = panorama_widget
        return panorama_widget

    def _set_preview_mode(
        self,
        mode: ImagePreviewMode,
        *,
        persist: bool,
    ) -> None:
        if (
            mode == ImagePreviewMode.PANORAMA
            and not self._is_panorama_renderer_available
        ):
            mode = ImagePreviewMode.FLAT

        panorama_widget = None
        if mode == ImagePreviewMode.PANORAMA:
            panorama_widget = self._ensure_panorama_widget()
            if panorama_widget is None:
                mode = ImagePreviewMode.FLAT

        self._preview_mode = mode
        if mode == ImagePreviewMode.PANORAMA:
            assert panorama_widget is not None
            self._content_layout.setCurrentWidget(panorama_widget)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self._content_layout.setCurrentWidget(self._scroll_area)
            self.unsetCursor()
            if (
                not self._flat_view_initialized
                and not self._source_pixmap.isNull()
            ):
                self._refit_current_image()
        self._sync_overlay_geometry()
        if persist:
            self._preferred_preview_mode = mode
            if self._preview_mode_changed is not None:
                self._preview_mode_changed(mode)
        self._set_image_controls_enabled(not self._source_pixmap.isNull())
        self._update_view_mode_button()

    def _sync_overlay_geometry(self) -> None:
        parent = (
            self._content
            if self._preview_mode == ImagePreviewMode.PANORAMA
            else self._scroll_area.viewport()
        )
        self._overlay.setGeometry(
            QRect(parent.mapTo(self, QPoint()), parent.size())
        )
        if hasattr(self, "_panel"):
            self._position_panel()
        self._overlay.raise_()
        self._panel.raise_()
        if (
            hasattr(self, "_loading_overlay")
            and self._loading_overlay.isVisible()
        ):
            self._loading_overlay.raise_()

    def _update_view_mode_button(self) -> None:
        is_visible = (
            self._is_panorama_available and not self._source_pixmap.isNull()
        )
        if not is_visible:
            self._view_mode_button.hide()
            self._panel.setMinimumWidth(0)
            self._panel.setMaximumWidth(self.PANEL_MAX_WIDTH)
            self._panel.adjustSize()
            self._position_panel()
            return

        is_panorama = self._preview_mode == ImagePreviewMode.PANORAMA
        self._set_view_mode_button_icon(
            "vrpano" if is_panorama else "panorama_photosphere"
        )
        self._view_mode_button.setToolTip(
            self.tr("Show image") if is_panorama else self.tr("Show panorama")
        )
        if self._view_mode_button.isVisible():
            return
        if self._expanded_panel_width:
            self._panel.setFixedWidth(self._expanded_panel_width)
            self._view_mode_button.show()
            self._position_panel()
            return
        self._schedule_expanded_panel_position()

    def _set_view_mode_button_icon(self, icon_name: str) -> None:
        self._view_mode_button.setIcon(
            material_icon(icon_name, color=self.ACTIVE_ICON_COLOR)
        )
        self._view_mode_button.setIconSize(
            QSize(self.TOOL_ICON_SIZE, self.TOOL_ICON_SIZE)
        )

    def _schedule_expanded_panel_position(self) -> None:
        if (
            self._view_mode_positioning_scheduled
            or not self._is_panorama_available
            or self._source_pixmap.isNull()
        ):
            return

        self._view_mode_positioning_scheduled = True
        self._view_mode_button.hide()
        self._panel.setMinimumWidth(0)
        self._panel.setMaximumWidth(self.PANEL_MAX_WIDTH)
        self._panel.adjustSize()
        self._position_panel()

        # Let Qt finish the flat layout before measuring its actual position.
        QTimer.singleShot(0, self._expand_panel_for_view_mode)

    def _expand_panel_for_view_mode(self) -> None:
        self._view_mode_positioning_scheduled = False
        if not self._is_panorama_available or self._source_pixmap.isNull():
            return

        self._base_panel_width = self._panel.width()
        self._panel.setMaximumWidth(
            self.PANEL_MAX_WIDTH
            + self.TOOL_BUTTON_SIZE
            + self.TOOL_BUTTON_SPACING
        )
        self._view_mode_button.show()
        self._panel.adjustSize()

        # Record Qt's expanded size once, then reuse it for all resizes.
        QTimer.singleShot(0, self._store_expanded_panel_size)

    def _store_expanded_panel_size(self) -> None:
        if not self._view_mode_button.isVisible():
            return
        self._expanded_panel_width = self._panel.width()
        self._panel.setFixedWidth(self._expanded_panel_width)
        self._position_panel()

    def _position_panel(self) -> None:
        if self._overlay.size().isEmpty():
            return
        reference_width = self._base_panel_width or self._panel.width()
        self._panel.move(
            max(0, (self._overlay.width() - reference_width) // 2),
            max(
                0,
                self._overlay.height()
                - self._panel.height()
                - self.PANEL_MARGIN,
            ),
        )

    def _update_description_text(self) -> None:
        if not self._description:
            self._description_label.setText("")
            self._description_label.setFixedHeight(self.DESCRIPTION_HEIGHT)
            self._description_label.setWordWrap(False)
            return

        if self._is_description_expanded:
            self._description_label.setWordWrap(True)
            self._description_label.setMaximumHeight(16777215)
            self._description_label.setMinimumHeight(0)
            self._description_label.setText(
                self._description_html(self._description)
            )
            self._description_label.setToolTip("")
            return

        self._description_label.setWordWrap(False)
        self._description_label.setFixedHeight(self.DESCRIPTION_HEIGHT)
        horizontal_margin = 24
        available_width = max(0, self._panel.width() - horizontal_margin)
        metrics = QFontMetrics(self._description_label.font())
        if metrics.horizontalAdvance(self._description) <= available_width:
            self._description_label.setText(
                self._description_html(self._description)
            )
            self._description_label.setToolTip("")
            return

        suffix = self._description_expand_suffix()
        suffix_width = self._description_expand_suffix_width(metrics)
        text = metrics.elidedText(
            self._description,
            Qt.TextElideMode.ElideRight,
            max(0, available_width - suffix_width),
        )
        self._description_label.setText(f"{escape(text)}{suffix}")
        self._description_label.setToolTip(self._description)

    def _description_expand_suffix(self) -> str:
        return f" {self._description_expand_link()}"

    def _description_expand_suffix_width(self, metrics: QFontMetrics) -> int:
        return metrics.horizontalAdvance(
            f" ...{self._description_expand_text()}"
        )

    def _description_expand_link(self) -> str:
        return (
            f'<a href="expand">{escape(self._description_expand_text())}</a>'
        )

    def _description_expand_text(self) -> str:
        return self.tr("more")

    def _expand_description(self, link: str) -> None:
        if link == "expand":
            self._is_description_expanded = True
            self._update_description_text()
            self._panel.adjustSize()
            return

        QDesktopServices.openUrl(QUrl(link))

    def _collapse_description(self) -> None:
        self._is_description_expanded = False
        self._update_description_text()
        self._panel.adjustSize()

    def _description_html(self, text: str) -> str:
        parts = []
        cursor = 0
        for match in self.ANCHOR_PATTERN.finditer(text):
            parts.append(
                self._plain_description_html(text[cursor : match.start()])
            )
            parts.append(
                self._anchor_html(
                    match.group("url"),
                    match.group("label"),
                )
            )
            cursor = match.end()

        parts.append(self._plain_description_html(text[cursor:]))
        return "".join(parts)

    def _plain_description_html(self, text: str) -> str:
        escaped_text = self._escape_description_text(text)
        return self.URL_PATTERN.sub(self._url_link_html, escaped_text)

    def _anchor_html(self, url: str, label: str) -> str:
        return (
            f'<a href="{escape(url)}">'
            f"{self._escape_description_text(label)}</a>"
        )

    def _url_link_html(self, match: re.Match) -> str:
        url = match.group(0)
        escaped_url = escape(url)
        return f'<a href="{escaped_url}">{escaped_url}</a>'

    def _escape_description_text(self, text: str) -> str:
        return escape(text).replace("\n", "<br>")

    def _update_window_title(self) -> None:
        item = self._current_item()
        if item is None:
            self.setWindowTitle(
                self._format_window_title([self.tr("Image preview")])
            )
            return

        title = item.file_name or self.tr("Image preview")
        if self._source_pixmap.isNull():
            self.setWindowTitle(self._format_window_title([title]))
            return

        width = self._source_pixmap.width()
        height = self._source_pixmap.height()
        self.setWindowTitle(
            self._format_window_title([title, f"{width}x{height}"])
        )

    def _format_window_title(self, parts: Sequence[str]) -> str:
        title_parts = [part for part in parts if part]
        if self._window_title_suffix:
            title_parts.append(self._window_title_suffix)

        if not title_parts:
            return self.tr("Image preview")

        return " - ".join(title_parts)

    def _current_item(self) -> Optional[ImagePreviewItem]:
        if not self._items:
            return None

        if self._current_index < 0 or self._current_index >= len(self._items):
            return None

        return self._items[self._current_index]

    def _show_context_menu(self, position: QPoint) -> None:
        item = self._current_item()
        if item is None:
            return

        menu = QMenu(self)
        open_action = menu.addAction(
            material_icon("file_open"),
            self.tr("Open"),
            self._open_current_file,
        )
        reveal_action = menu.addAction(
            qgis_icon("mIconFolderLink.svg"),
            self.tr("Show in Folder"),
            self._show_current_file_in_folder,
        )
        copy_action = menu.addAction(
            qgis_icon("mActionEditCopy.svg"),
            self.tr("Copy"),
            self._copy_current_image,
        )
        save_as_action = menu.addAction(
            qgis_icon("mActionFileSaveAs.svg"),
            self.tr("Save As…"),
            self._save_current_file_as,
        )

        has_file = item.file_path is not None and item.file_path.exists()
        open_action.setEnabled(has_file)
        reveal_action.setEnabled(has_file)
        copy_action.setEnabled(not self._source_pixmap.isNull())
        save_as_action.setEnabled(has_file)

        sender = self.sender()
        if isinstance(sender, QWidget):
            global_position = sender.mapToGlobal(position)
        else:
            global_position = self.mapToGlobal(position)

        menu.exec(global_position)

    def _show_current_file_in_folder(self) -> None:
        item = self._current_item()
        if item is None:
            return

        if item.file_path is None or not item.file_path.exists():
            return

        reveal_in_file_manager(item.file_path)

    def _copy_current_image(self) -> None:
        if self._source_pixmap.isNull():
            return

        self._clipboard.copy_image(self._rotated_source_pixmap())
        self._show_transient_status(self.tr("Copied"), "check")

    def _save_current_file_as(self) -> None:
        item = self._current_item()
        if item is None:
            return

        if item.file_path is None or not item.file_path.exists():
            return

        file_dialog = QFileDialog(self)
        file_dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setWindowTitle(self.tr("Save Image As"))
        file_dialog.selectFile(item.file_name)
        file_dialog.setNameFilter(self.tr("Images (*)"))
        suffix = item.file_path.suffix.lstrip(".")
        if suffix:
            file_dialog.setDefaultSuffix(suffix)

        if not file_dialog.exec():
            return

        target_path_text = file_dialog.selectedFiles()[0]
        shutil.copy2(item.file_path, Path(target_path_text))

    def _set_loading_visible(self, visible: bool) -> None:
        self._loading_overlay.setVisible(visible)
        if visible:
            self._loading_overlay.raise_()
        self.repaint()

    def _set_active_panel_opacity(self) -> None:
        self._panel_fade_animation.stop()
        self._panel_opacity.setOpacity(self.ACTIVE_PANEL_OPACITY)
        for animation in self._side_button_fade_animations:
            animation.stop()
        for effect in self._side_button_opacity_effects:
            effect.setOpacity(self.ACTIVE_PANEL_OPACITY)
        self._idle_timer.start()

    def _set_idle_panel_opacity(self) -> None:
        if self._is_cursor_over_panel():
            self._idle_timer.start()
            return

        self._panel_fade_animation.stop()
        self._panel_fade_animation.setStartValue(self._panel_opacity.opacity())
        self._panel_fade_animation.setEndValue(self.IDLE_PANEL_OPACITY)
        self._panel_fade_animation.start()
        for animation, effect in zip(
            self._side_button_fade_animations,
            self._side_button_opacity_effects,
        ):
            animation.stop()
            animation.setStartValue(effect.opacity())
            animation.setEndValue(self.IDLE_PANEL_OPACITY)
            animation.start()

    def _is_cursor_over_panel(self) -> bool:
        return self._is_global_position_over_panel(QCursor.pos())

    def _is_global_position_over_panel(
        self,
        global_position: QPoint,
    ) -> bool:
        if not hasattr(self, "_panel") or not self._panel.isVisible():
            return False

        panel_position = self._panel.mapFromGlobal(global_position)
        return self._panel.rect().contains(panel_position)
