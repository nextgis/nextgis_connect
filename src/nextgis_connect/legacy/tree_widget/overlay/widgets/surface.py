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

import math
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Optional

from qgis.PyQt.QtCore import (
    QEasingCurve,
    QEvent,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QColor, QPainter, QPalette
from qgis.PyQt.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from nextgis_connect.legacy.tree_widget.overlay.state import (
    OverlayAction,
    OverlayButtonState,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.ui_kit.graphics import (
    CustomSvgRenderer,
    NextgisBackgroundPainter,
    NextgisDecorator,
    NextgisRadius,
)
from nextgis_connect.ui_kit.icons import material_icon_path


@dataclass(frozen=True)
class ResponsiveMetrics:
    """Store geometry and spacing calculated for a single overlay resize."""

    card_geometry: QRect
    card_padding: int
    content_spacing: int
    logo_geometry: QRect
    logo_visible: bool


@dataclass(frozen=True)
class WidthMetrics:
    """Store horizontal metrics for one deterministic resize pass."""

    outer_margin: int
    card_width: int
    card_padding: int
    content_width: int
    content_spacing: int


class LogoLinkWidget(QWidget):
    """Clickable NextGIS logo rendered as a subtle footer link."""

    _MONOCHROME_OPACITY = 0.20
    _COLOR_HOVER_OPACITY = 0.80

    clicked = pyqtSignal()

    def __init__(
        self,
        source: Path,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._monochrome_renderer = CustomSvgRenderer(
            source, self, themed=True
        )
        self._color_renderer = CustomSvgRenderer(source, self, themed=False)
        self._clickable = False
        self._size_hint = self._monochrome_renderer.size_for(height=14)
        self._color_opacity = 0.0

        self._opacity_animation = QVariantAnimation(self)
        self._opacity_animation.setDuration(180)
        self._opacity_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._opacity_animation.valueChanged.connect(self._set_color_opacity)

        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self._sync_logo_renderers()

    def set_clickable(self, clickable: bool) -> None:
        self._clickable = clickable
        if not clickable:
            self._animate_color_opacity(0.0)

        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if clickable
            else Qt.CursorShape.ArrowCursor
        )

    def sizeHint(self) -> QSize:
        return self._size_hint

    def minimumSizeHint(self) -> QSize:
        return self._size_hint

    def enterEvent(self, event) -> None:
        if self._clickable:
            self._animate_color_opacity(self._COLOR_HOVER_OPACITY)
            self.update()

        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_color_opacity(0.0)
        self.update()
        super().leaveEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            self._sync_logo_renderers()

        super().changeEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            self._clickable
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.pos())
        ):
            self.clicked.emit()

        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        painter.save()
        painter.setOpacity(self._MONOCHROME_OPACITY)
        self._monochrome_renderer.render(painter, rect)
        painter.restore()

        if self._color_opacity <= 0.0:
            return

        painter.save()
        painter.setOpacity(self._color_opacity)
        self._color_renderer.render(painter, rect)
        painter.restore()

    def _animate_color_opacity(self, target_opacity: float) -> None:
        self._opacity_animation.stop()
        self._opacity_animation.setStartValue(self._color_opacity)
        self._opacity_animation.setEndValue(target_opacity)
        self._opacity_animation.start()

    def _set_color_opacity(self, value: float) -> None:
        self._color_opacity = value
        self.update()

    def _sync_logo_renderers(self) -> None:
        replacement_color = NextgisDecorator.system_text_color(self.palette())
        self._monochrome_renderer.set_fill_color(replacement_color)
        self._monochrome_renderer.set_stroke_color(replacement_color)
        self._color_renderer.set_replacements(
            {
                "#231F20": replacement_color,
                "#231f20": replacement_color,
            }
        )


class MaterialIllustrationWidget(QWidget):
    """Material SVG illustration with controllable render size."""

    _MINIMUM_ICON_SIZE = 40

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._renderer: Optional[CustomSvgRenderer] = None
        self._size_hint = QSize(0, 0)
        self._preferred_size = 0
        self._current_size = 0

        self.hide()
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )

    def set_icon(
        self,
        icon_name: str,
        *,
        size: int = 64,
        themed: bool = True,
    ) -> None:
        if icon_name == "":
            self._renderer = None
            self._size_hint = QSize(0, 0)
            self._preferred_size = 0
            self._current_size = 0
            self.hide()
            self.updateGeometry()
            self.update()
            return

        icon_path = material_icon_path(icon_name)
        if icon_path is None:
            self._renderer = None
            self._size_hint = QSize(0, 0)
            self._preferred_size = 0
            self._current_size = 0
            self.hide()
            self.updateGeometry()
            self.update()
            return

        self._renderer = CustomSvgRenderer(icon_path, self, themed=themed)
        self._preferred_size = max(self._MINIMUM_ICON_SIZE, size)
        self._current_size = self._preferred_size
        self._apply_current_size()
        self.show()
        self.updateGeometry()
        self.update()

    def has_icon(self) -> bool:
        return self._renderer is not None

    def current_size(self) -> int:
        return self._current_size

    def preferred_size(self) -> int:
        return self._preferred_size

    def minimum_icon_size(self) -> int:
        return self._MINIMUM_ICON_SIZE

    def reset_size(self) -> None:
        if self._renderer is not None:
            self.show()

        self.set_render_size(self._preferred_size)

    def set_icon_visible(self, visible: bool) -> bool:
        if self._renderer is None:
            return False

        if self.isHidden() == (not visible):
            return False

        self.setVisible(visible)
        self.updateGeometry()
        return True

    def set_render_size(self, size: int) -> bool:
        if self._renderer is None:
            return False

        next_size = max(
            self._MINIMUM_ICON_SIZE,
            min(self._preferred_size, size),
        )
        if next_size == self._current_size:
            return False

        self._current_size = next_size
        self._apply_current_size()
        self.updateGeometry()
        self.update()
        return True

    def sizeHint(self) -> QSize:
        return self._size_hint

    def minimumSizeHint(self) -> QSize:
        if self._renderer is None:
            return self._size_hint

        return QSize(self._MINIMUM_ICON_SIZE, self._MINIMUM_ICON_SIZE)

    def paintEvent(self, event) -> None:
        del event
        if self._renderer is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._renderer.render(painter, QRectF(self.rect()))

    def _apply_current_size(self) -> None:
        self._size_hint = QSize(self._current_size, self._current_size)
        self.setFixedSize(self._size_hint)


class ElidedLabel(QLabel):
    """Display dynamic status text without contributing its full width."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

    def setText(self, text: str) -> None:
        """Set the complete status text and display an elided version."""
        self._full_text = text
        self._update_elided_text()

    def minimumSizeHint(self) -> QSize:
        """Return a height without imposing the full status width."""
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_text()

    def changeEvent(self, event) -> None:
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._update_elided_text()

        super().changeEvent(event)

    def _update_elided_text(self) -> None:
        available_width = max(0, self.contentsRect().width())
        metrics = self.fontMetrics()
        text = "\n".join(
            metrics.elidedText(
                line,
                Qt.TextElideMode.ElideMiddle,
                available_width,
            )
            for line in self._full_text.split("\n")
        )
        if super().text() != text:
            super().setText(text)
            self.updateGeometry()

        self.setToolTip(self._full_text if text != self._full_text else "")


class FooterLinkLabel(QLabel):
    """Rich-text footer label that emits the configured overlay action."""

    _SKIP_UPDATE_HOVER_TEXT_OPACITY = 0.8

    action_requested = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._is_hovered = False
        self._action_state = OverlayButtonState()

        self.setOpenExternalLinks(False)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.setWordWrap(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def set_action(self, action_state: OverlayButtonState) -> None:
        self._action_state = action_state
        visible = (
            action_state.action != OverlayAction.NONE
            and action_state.text != ""
        )
        self.setVisible(visible)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if visible
            else Qt.CursorShape.ArrowCursor
        )
        tooltip = (
            action_state.tooltip
            if action_state.tooltip != action_state.text
            else ""
        )
        self.setToolTip(tooltip if visible else "")
        self._update_text()

    def enterEvent(self, event) -> None:
        self._is_hovered = True
        self._update_text()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._is_hovered = False
        self._update_text()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() != Qt.MouseButton.LeftButton
            or not self.rect().contains(event.pos())
        ):
            super().mouseReleaseEvent(event)
            return

        if self._action_state.action == OverlayAction.NONE:
            super().mouseReleaseEvent(event)
            return

        self.action_requested.emit(self._action_state.action)
        super().mouseReleaseEvent(event)

    def _update_text(self) -> None:
        if (
            self._action_state.action == OverlayAction.NONE
            or self._action_state.text == ""
        ):
            self.clear()
            return

        text_decoration = "underline" if self._is_hovered else "none"
        link_color = self._link_color()
        self.setText(
            '<a href="overlay" style="'
            f"color: {link_color}; text-decoration: {text_decoration};"
            '">'
            f"{self._action_state.text}"
            "</a>"
        )

    def _link_color(self) -> str:
        opacity = self._effective_text_opacity()
        link_color = QColor(NextgisDecorator.brand_color())
        if opacity >= 1.0:
            return link_color.name()

        background_color = self.palette().color(QPalette.ColorRole.Window)
        return QColor(
            round(
                background_color.red()
                + (link_color.red() - background_color.red()) * opacity
            ),
            round(
                background_color.green()
                + (link_color.green() - background_color.green()) * opacity
            ),
            round(
                background_color.blue()
                + (link_color.blue() - background_color.blue()) * opacity
            ),
        ).name()

    def _effective_text_opacity(self) -> float:
        return self._effective_text_opacity_for(
            self._action_state,
            is_hovered=self._is_hovered,
        )

    @classmethod
    def _effective_text_opacity_for(
        cls,
        action_state: OverlayButtonState,
        *,
        is_hovered: bool,
    ) -> float:
        opacity = action_state.text_opacity
        if (
            is_hovered
            and action_state.action == OverlayAction.SKIP_PLUGIN_UPDATE
        ):
            opacity = cls._SKIP_UPDATE_HOVER_TEXT_OPACITY

        return min(1.0, max(0.0, opacity))


class OverlaySurfaceWidget(QWidget):
    """Base widget for responsive overlay cards.

    The widget positions the card and decorative logo manually, while card
    contents remain managed by Qt layouts.
    """

    MINIMUM_OVERLAY_HEIGHT = 160
    _WRAP_RESERVE = 16
    _NORMAL_CARD_PADDING = max(
        NextgisDecorator.CARD_PADDING_HORIZONTAL,
        NextgisDecorator.CARD_PADDING_VERTICAL,
    )
    _COMPACT_CARD_PADDING = 22
    _MINIMUM_CARD_PADDING = 18
    _NORMAL_OUTER_MARGIN = NextgisDecorator.CARD_MARGIN
    _COMPACT_OUTER_MARGIN = 20
    _MINIMUM_OUTER_MARGIN = 12
    _NORMAL_CONTENT_SPACING = NextgisDecorator.CARD_SPACING
    _COMPACT_CONTENT_SPACING = 10
    _MINIMUM_CONTENT_SPACING = 8
    _LOGO_MARGIN_NORMAL = 12
    _CARD_HEIGHT_SLACK = 2
    _MINIMUM_COMPACT_CARD_WIDTH = 220
    _MINIMUM_COMPACT_CARD_HEIGHT = 72
    _NON_BREAKING_PHRASES: ClassVar[dict] = {
        "Web GIS": "Web\u00a0GIS",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._plugin_path = NgConnectInterface.instance().path
        self._background_painter = NextgisBackgroundPainter(
            self._plugin_path
            / "assets"
            / "icons"
            / "branding"
            / "isolines.svg",
            self,
        )
        self._draw_background = True
        self._logo_action = OverlayAction.NONE
        self._is_syncing_layout = False
        self.setMinimumHeight(self.MINIMUM_OVERLAY_HEIGHT)

        self._card = QFrame(self)
        self._card.setObjectName("overlayCard")
        self._card.setFrameShape(QFrame.Shape.NoFrame)
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Maximum,
        )

        self._card_stack = QStackedLayout(self._card)
        self._card_stack.setContentsMargins(0, 0, 0, 0)

        self._content_widget = QWidget(self._card)
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(
            self._NORMAL_CARD_PADDING,
            self._NORMAL_CARD_PADDING,
            self._NORMAL_CARD_PADDING,
            self._NORMAL_CARD_PADDING,
        )
        self._content_layout.setSpacing(self._NORMAL_CONTENT_SPACING)

        self._compact_label = QLabel(self._card)
        self._compact_label.setWordWrap(True)
        self._compact_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._compact_label.setText(
            self.tr("Increase the panel size to display this content.")
        )
        self._compact_label.setMargin(self._NORMAL_CARD_PADDING)
        self._compact_label.setMinimumHeight(self._MINIMUM_COMPACT_CARD_HEIGHT)

        self._card_stack.addWidget(self._content_widget)
        self._card_stack.addWidget(self._compact_label)

        self._logo_widget = LogoLinkWidget(
            self._plugin_path
            / "assets"
            / "icons"
            / "branding"
            / "nextgis_full_logo.svg",
            self,
        )
        self._logo_widget.clicked.connect(self._emit_logo_action)
        self._logo_widget.hide()

        self._apply_card_decoration()

    def set_draw_background(self, value: bool) -> None:
        """Set whether the overlay paints the branded background."""
        if self._draw_background == value:
            return

        self._draw_background = value
        self._sync_logo_visibility()
        self.sync_layout()
        self.update()

    def set_logo_action(self, action: OverlayAction) -> None:
        """Set the action emitted when the footer logo is clicked."""
        self._logo_action = action
        self._sync_logo_visibility()
        self.sync_layout()

    def reset_card_growth(self) -> None:
        """Reset legacy growth state.

        The responsive layout is stateless now; the method remains for callers
        that reset overlay state when switching screens.
        """
        return

    def resizeEvent(self, event) -> None:
        self.sync_layout()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:
        self.sync_layout()
        super().showEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        ):
            self._apply_card_decoration()
            self.sync_layout()
            self.update()

        if event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.LanguageChange,
        ):
            self.sync_layout()
            self.update()

        super().changeEvent(event)

    def paintEvent(self, event) -> None:
        palette = QPalette(self.palette())
        overlay_color = NextgisDecorator.system_window_color(palette)
        overlay_color.setAlpha(255 if self._draw_background else 210)
        full_rect = self.rect()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(full_rect, overlay_color)
        if not self._draw_background:
            return

        self._background_painter.paint_widget_background(
            painter,
            full_rect,
            palette=palette,
        )

    def _apply_card_decoration(self) -> None:
        NextgisDecorator.patch_widget(
            self._card,
            palette=NextgisDecorator.overlay_card_palette(self.palette()),
            auto_fill_background=False,
            stylesheets=(
                NextgisDecorator.stylesheet(
                    "QFrame#overlayCard",
                    {
                        "border": "1px solid palette(mid)",
                        "border-radius": (
                            f"{NextgisDecorator.radius(NextgisRadius.CARD)}px"
                        ),
                        "background-color": "palette(base)",
                    },
                ),
            ),
        )

        compact_palette = QPalette(self._compact_label.palette())
        compact_palette.setColor(
            QPalette.ColorRole.WindowText,
            NextgisDecorator.system_muted_text_color(self.palette()),
        )
        self._compact_label.setPalette(compact_palette)

    def sync_layout(self) -> None:
        """Recalculate card and logo geometry for the current widget size."""
        if self._is_syncing_layout:
            return

        self._is_syncing_layout = True
        try:
            self._sync_responsive_geometry()
        finally:
            self._is_syncing_layout = False

    def _sync_responsive_geometry(self) -> None:
        self._set_minimum_size(self._minimum_compact_window_size())

        if self.width() <= 0 or self.height() <= 0:
            self._logo_widget.hide()
            return

        metrics = self._calculate_responsive_metrics(self.size())
        if metrics is None:
            outer_margin = self._outer_margin_for_width(
                self.width(),
                self._minimum_readable_card_width(self._MINIMUM_CARD_PADDING),
            )
            available_width = max(0, self.width() - 2 * outer_margin)
            self._show_compact_card(available_width, outer_margin)
            return

        self._apply_responsive_metrics(metrics)
        self._card_stack.setCurrentWidget(self._content_widget)

    def _calculate_responsive_metrics(
        self,
        size: QSize,
    ) -> Optional[ResponsiveMetrics]:
        minimum_card_width = self._minimum_readable_card_width(
            self._MINIMUM_CARD_PADDING
        )
        minimum_available_width = max(
            0,
            size.width() - 2 * self._MINIMUM_OUTER_MARGIN,
        )
        if minimum_available_width < minimum_card_width:
            return None

        minimum_content_width = self._minimum_readable_content_width()
        preferred_content_width = max(
            minimum_content_width,
            self._horizontal_content_width_for_preferred_layout(),
        )
        width_metrics = self._width_metrics_for_target(
            size.width(),
            preferred_content_width,
        )

        for card_padding in self._padding_candidates_from(
            width_metrics.card_padding
        ):
            candidate = self._width_metrics_for_padding(
                size.width(),
                width_metrics.outer_margin,
                card_padding,
            )
            available_height = max(
                0,
                size.height() - 2 * self._MINIMUM_OUTER_MARGIN,
            )
            if available_height <= 0:
                continue

            self._prepare_content_for_layout()
            self._set_content_metrics(
                candidate.card_padding,
                candidate.content_spacing,
            )
            self._card.resize(
                candidate.card_width, max(0, self._card.height())
            )
            self._update_responsive_layout(
                candidate.content_width,
                candidate.card_width,
            )

            required_height = self._content_height_for_width(
                candidate.card_width
            )
            if required_height > available_height:
                did_shrink = self._shrink_content_to_height(
                    candidate.card_width,
                    available_height,
                )
                if did_shrink:
                    required_height = self._content_height_for_width(
                        candidate.card_width
                    )

            if required_height > available_height:
                continue

            card_geometry = QRect(
                self._centered_position(
                    size.width(),
                    candidate.card_width,
                ),
                self._card_top_for_height(size, required_height),
                candidate.card_width,
                required_height,
            )
            card_bottom = card_geometry.y() + card_geometry.height()
            logo_geometry = self._logo_geometry_for_card(
                size,
                card_bottom,
            )

            return ResponsiveMetrics(
                card_geometry=card_geometry,
                card_padding=candidate.card_padding,
                content_spacing=candidate.content_spacing,
                logo_geometry=logo_geometry or QRect(),
                logo_visible=logo_geometry is not None,
            )

        return None

    def _apply_responsive_metrics(self, metrics: ResponsiveMetrics) -> None:
        self._set_content_metrics(
            metrics.card_padding,
            metrics.content_spacing,
        )
        self._set_widget_geometry(self._card, metrics.card_geometry)
        if self._logo_widget.isHidden() == metrics.logo_visible:
            self._logo_widget.setVisible(metrics.logo_visible)

        if metrics.logo_visible:
            self._set_widget_geometry(self._logo_widget, metrics.logo_geometry)

    def _outer_margin_for_width(
        self,
        width: int,
        required_card_width: int,
    ) -> int:
        normal_width = required_card_width + 2 * self._NORMAL_OUTER_MARGIN
        if width >= normal_width:
            return self._NORMAL_OUTER_MARGIN

        margin = (width - required_card_width) // 2
        return self._clamp(
            margin,
            self._MINIMUM_OUTER_MARGIN,
            self._NORMAL_OUTER_MARGIN,
        )

    def _card_top_for_height(self, size: QSize, card_height: int) -> int:
        return self._centered_position(size.height(), card_height)

    def _width_metrics_for_target(
        self,
        width: int,
        target_content_width: int,
    ) -> WidthMetrics:
        required_card_width = (
            target_content_width + 2 * self._NORMAL_CARD_PADDING
        )
        outer_margin = self._outer_margin_for_width(
            width,
            required_card_width,
        )
        available_width = max(0, width - 2 * outer_margin)
        card_padding = self._card_padding_for_available_width(
            available_width,
            target_content_width,
        )

        return self._width_metrics_for_padding(
            width,
            outer_margin,
            card_padding,
        )

    def _width_metrics_for_padding(
        self,
        width: int,
        outer_margin: int,
        card_padding: int,
    ) -> WidthMetrics:
        available_width = max(0, width - 2 * outer_margin)
        minimum_card_width = self._minimum_readable_card_width(card_padding)
        card_width = self._clamp(
            available_width,
            minimum_card_width,
            NextgisDecorator.CARD_MAX_WIDTH,
        )
        content_width = max(0, card_width - 2 * card_padding)

        return WidthMetrics(
            outer_margin=outer_margin,
            card_width=card_width,
            card_padding=card_padding,
            content_width=content_width,
            content_spacing=self._content_spacing_for_padding(card_padding),
        )

    def _card_padding_for_available_width(
        self,
        available_width: int,
        target_content_width: int,
    ) -> int:
        card_width = min(available_width, NextgisDecorator.CARD_MAX_WIDTH)
        for padding in (
            self._NORMAL_CARD_PADDING,
            self._COMPACT_CARD_PADDING,
            self._MINIMUM_CARD_PADDING,
        ):
            content_width = card_width - 2 * padding
            if content_width >= target_content_width:
                return padding

        return self._MINIMUM_CARD_PADDING

    def _padding_candidates_from(self, card_padding: int) -> list:
        paddings = [
            self._NORMAL_CARD_PADDING,
            self._COMPACT_CARD_PADDING,
            self._MINIMUM_CARD_PADDING,
        ]
        for index, padding in enumerate(paddings):
            if card_padding >= padding:
                return paddings[index:]

        return [self._MINIMUM_CARD_PADDING]

    def _content_spacing_for_padding(self, card_padding: int) -> int:
        if card_padding >= self._NORMAL_CARD_PADDING:
            return self._NORMAL_CONTENT_SPACING

        if card_padding <= self._MINIMUM_CARD_PADDING:
            return self._MINIMUM_CONTENT_SPACING

        return self._COMPACT_CONTENT_SPACING

    def _horizontal_content_width_for_preferred_layout(self) -> int:
        return 0

    def _update_responsive_layout(
        self,
        content_width: int,
        card_width: int,
    ) -> None:
        del content_width
        del card_width
        return

    def _prepare_content_for_layout(self) -> None:
        return

    def _prepare_content_for_minimum_layout(self) -> None:
        self._prepare_content_for_layout()

    def _shrink_content_to_height(
        self,
        width: int,
        available_height: int,
    ) -> bool:
        del width
        del available_height
        return False

    def _content_height_for_width(self, width: int) -> int:
        measure_width = max(0, width - self._WRAP_RESERVE)
        if self._content_layout.hasHeightForWidth():
            height = self._content_layout.heightForWidth(measure_width)
        else:
            height = self._content_widget.sizeHint().height()

        return (
            max(height, self._content_widget.minimumSizeHint().height())
            + self._height_measurement_slack()
        )

    def _show_compact_card(
        self, available_width: int, outer_margin: int
    ) -> None:
        self._set_content_metrics(
            self._MINIMUM_CARD_PADDING,
            self._MINIMUM_CONTENT_SPACING,
        )
        self._logo_widget.hide()
        available_height = max(
            0,
            self.height() - 2 * self._MINIMUM_OUTER_MARGIN,
        )
        compact_height = max(
            self._compact_label.minimumSizeHint().height(),
            self._compact_label.sizeHint().height(),
        )
        width = min(
            max(0, available_width),
            NextgisDecorator.CARD_MAX_WIDTH,
        )
        compact_height = min(available_height, compact_height)
        card_x = self._centered_position(self.width(), width)
        card_y = self._centered_position(
            self.height(),
            compact_height,
        )
        self._set_widget_geometry(
            self._card,
            QRect(card_x, card_y, width, compact_height),
        )
        self._card_stack.setCurrentWidget(self._compact_label)

    def _minimum_content_width_for_readable_layout(self) -> int:
        return 0

    def _minimum_readable_window_size(self) -> QSize:
        self._prepare_content_for_minimum_layout()
        self._apply_minimum_content_metrics()

        card_width = self._minimum_readable_card_width(
            self._MINIMUM_CARD_PADDING
        )
        self._card.resize(card_width, max(0, self._card.height()))
        card_height = self._content_height_for_width(card_width)

        self._prepare_content_for_layout()
        return QSize(
            card_width + 2 * self._MINIMUM_OUTER_MARGIN,
            max(
                self.MINIMUM_OVERLAY_HEIGHT,
                card_height + 2 * self._MINIMUM_OUTER_MARGIN,
            ),
        )

    def _minimum_compact_window_size(self) -> QSize:
        compact_card_width = max(
            self._MINIMUM_COMPACT_CARD_WIDTH,
            self._compact_label.minimumSizeHint().width(),
        )
        compact_card_height = max(
            self._MINIMUM_COMPACT_CARD_HEIGHT,
            self._compact_label.minimumSizeHint().height(),
        )

        return QSize(
            compact_card_width + 2 * self._MINIMUM_OUTER_MARGIN,
            max(
                self.MINIMUM_OVERLAY_HEIGHT,
                compact_card_height + 2 * self._MINIMUM_OUTER_MARGIN,
            ),
        )

    def _minimum_readable_content_width(self) -> int:
        return self._minimum_content_width_for_readable_layout()

    def _minimum_readable_card_width(self, padding: int) -> int:
        return padding + self._minimum_readable_content_width() + padding

    def _apply_minimum_content_metrics(self) -> None:
        self._set_content_metrics(
            self._MINIMUM_CARD_PADDING,
            self._MINIMUM_CONTENT_SPACING,
        )

    def _set_content_metrics(
        self,
        padding: int,
        spacing: int,
    ) -> None:
        margins = self._content_layout.contentsMargins()
        if (
            margins.left() != padding
            or margins.top() != padding
            or margins.right() != padding
            or margins.bottom() != padding
        ):
            self._content_layout.setContentsMargins(
                padding,
                padding,
                padding,
                padding,
            )

        if self._content_layout.spacing() != spacing:
            self._content_layout.setSpacing(spacing)

        if self._compact_label.margin() != padding:
            self._compact_label.setMargin(padding)

    def _height_measurement_slack(self) -> int:
        line_spacing = 0
        for label in self._content_widget.findChildren(QLabel):
            if (
                label.isHidden()
                or label.text() == ""
                or isinstance(label, ElidedLabel)
            ):
                continue

            line_spacing = max(line_spacing, label.fontMetrics().lineSpacing())

        if line_spacing <= 0:
            return self._CARD_HEIGHT_SLACK

        return self._CARD_HEIGHT_SLACK + math.ceil(line_spacing * 0.25)

    def _logo_geometry_for_card(
        self,
        size: QSize,
        card_bottom: int,
    ) -> Optional[QRect]:
        if not self._is_logo_requested():
            return None

        logo_size = self._logo_widget.sizeHint()
        space_below_card = size.height() - card_bottom
        required_space = logo_size.height() + 2 * self._LOGO_MARGIN_NORMAL
        if space_below_card < required_space:
            return None

        logo_x = (size.width() - logo_size.width()) // 2
        logo_y = size.height() - logo_size.height() - self._LOGO_MARGIN_NORMAL
        return QRect(logo_x, logo_y, logo_size.width(), logo_size.height())

    def _is_logo_requested(self) -> bool:
        return (
            self._draw_background and self._logo_action != OverlayAction.NONE
        )

    def _set_minimum_size(self, size: QSize) -> None:
        if self.minimumSize() == size:
            return

        self.setMinimumSize(size)

    def _set_widget_geometry(self, widget: QWidget, geometry: QRect) -> None:
        if widget.geometry() == geometry:
            return

        widget.setGeometry(geometry)

    def _centered_position(
        self,
        parent_extent: int,
        child_extent: int,
    ) -> int:
        return max(0, (parent_extent - child_extent) // 2)

    def _clamp(self, value: int, minimum: int, maximum: int) -> int:
        if maximum < minimum:
            return minimum

        return max(minimum, min(maximum, value))

    def _display_text(self, text: str) -> str:
        result = text
        for phrase, replacement in self._NON_BREAKING_PHRASES.items():
            result = result.replace(phrase, replacement)

        return result

    def _emit_logo_action(self) -> None:
        return

    def _sync_logo_visibility(self) -> None:
        is_visible = self._is_logo_requested()
        self._logo_widget.set_clickable(is_visible)
        if not is_visible:
            self._logo_widget.hide()
