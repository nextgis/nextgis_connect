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

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QWidget


@dataclass(frozen=True)
class NextgisToken:
    """Store a theme token path and fallback value.

    Describe a value inside the NextGIS theme JSON and the fallback to
    use when the token cannot be resolved.

    :ivar path: Dot-separated theme path.
    :ivar fallback: Value used when the token is missing.
    """

    path: str
    fallback: Any


TokenSource = Union[NextgisToken, str]


class NextgisBrandColor(Enum):
    """Represent brand color theme tokens.

    Provide token references for default, interactive, accent, and
    foreground brand colors.
    """

    DEFAULT = NextgisToken("color.shared.brand", "#0c65af")
    HOVER = NextgisToken("color.shared.brandHover", "#0952a5")
    ACTIVE = NextgisToken("color.shared.brandActive", "#063f80")
    ACCENT = NextgisToken("color.shared.brandAccent", "#0070c5")
    ON_BRAND = NextgisToken("color.shared.onBrand", "#ffffff")


class NextgisRadius(Enum):
    """Represent radius theme tokens.

    Provide token references for field, button, card, panel, and pill
    corner radii.
    """

    FIELD = NextgisToken("radiusPx.field", 8)
    BUTTON = NextgisToken("radiusPx.button", 4)
    CARD = NextgisToken("radiusPx.card", 6)
    PANEL = NextgisToken("radiusPx.panel", 18)
    PILL = NextgisToken("radiusPx.pill", 999)


class NextgisSpacing(Enum):
    """Represent spacing theme tokens.

    Provide token references for reusable pixel spacing values.
    """

    XS = NextgisToken("spacingPx.1", 4)
    SM = NextgisToken("spacingPx.2", 8)
    MD = NextgisToken("spacingPx.3", 12)
    LG = NextgisToken("spacingPx.4", 16)
    XL = NextgisToken("spacingPx.6", 24)


class NextgisSize(Enum):
    """Represent size theme tokens.

    Provide token references for icons, controls, and layout bounds.
    """

    ICON_SMALL = NextgisToken("sizePx.iconSmall", 16)
    ICON = NextgisToken("sizePx.icon", 20)
    ICON_LARGE = NextgisToken("sizePx.iconLarge", 24)
    CONTROL_COMPACT = NextgisToken("sizePx.controlCompact", 32)
    CONTROL = NextgisToken("sizePx.control", 40)
    CONTROL_LARGE = NextgisToken("sizePx.controlLarge", 48)
    CONTAINER_MAX = NextgisToken("sizePx.containerMax", 1200)


class NextgisTheme:
    """Read values from a NextGIS theme file.

    Load theme JSON lazily and resolve typed values through token paths
    with caller-provided fallbacks.
    """

    def __init__(self, path: Path) -> None:
        """Initialize the theme reader.

        :param path: Theme JSON path.
        """
        self._path = path
        self._data_cache: Optional[Dict[str, Any]] = None

    @property
    def data(self) -> Mapping[str, Any]:
        """Return parsed theme data.

        :return: Parsed theme mapping.
        """
        if self._data_cache is None:
            self._data_cache = self._load()

        return self._data_cache

    def value(self, token: TokenSource, fallback: Any = None) -> Any:
        """Return a raw theme value.

        :param token: Theme token or dot-separated token path.
        :param fallback: Fallback value for missing tokens.
        :return: Resolved theme value or fallback.
        """
        key_path, fallback_value = self._normalize_token(token, fallback)
        value: Any = self.data

        for key in key_path.split("."):
            if not isinstance(value, dict) or key not in value:
                return fallback_value
            value = value[key]

        return value

    def color(
        self, token: TokenSource, fallback: Optional[str] = None
    ) -> QColor:
        """Return a theme color.

        :param token: Theme token or dot-separated token path.
        :param fallback: Fallback color text.
        :return: Resolved color.
        """
        _, fallback_value = self._normalize_token(token, fallback)
        value = self.value(token, fallback)
        if not isinstance(value, str):
            value = "" if value is None else str(value)

        color = QColor(value)
        if color.isValid():
            return color

        fallback_text = "" if fallback_value is None else str(fallback_value)
        fallback_color = QColor(fallback_text)
        return fallback_color if fallback_color.isValid() else QColor()

    def integer(
        self, token: TokenSource, fallback: Optional[int] = None
    ) -> int:
        """Return a theme integer.

        :param token: Theme token or dot-separated token path.
        :param fallback: Fallback integer value.
        :return: Resolved integer.
        """
        _, fallback_value = self._normalize_token(token, fallback)
        value = self.value(token, fallback)
        if isinstance(value, bool):
            return self._fallback_integer(fallback_value)

        try:
            return int(value)
        except (TypeError, ValueError):
            return self._fallback_integer(fallback_value)

    def _normalize_token(
        self,
        token: TokenSource,
        fallback: Any,
    ) -> Tuple[str, Any]:
        if isinstance(token, NextgisToken):
            return token.path, token.fallback if fallback is None else fallback

        return token, fallback

    def _load(self) -> Dict[str, Any]:
        try:
            with self._path.open(encoding="utf-8") as theme_file:
                theme_data = json.load(theme_file)
        except (OSError, ValueError, TypeError):
            return {}

        if not isinstance(theme_data, dict):
            return {}

        return theme_data

    def _fallback_integer(self, fallback: Any) -> int:
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return 0


PaletteKey = Union[
    QPalette.ColorRole,
    Tuple[QPalette.ColorGroup, QPalette.ColorRole],
]


def mix_colors(
    first_color: QColor,
    second_color: QColor,
    factor: float,
) -> QColor:
    """Mix two colors.

    :param first_color: Color used at factor ``0``.
    :param second_color: Color used at factor ``1``.
    :param factor: Blend factor clamped to the ``0`` to ``1`` range.
    :return: Mixed color.
    """
    clamped_factor = max(0.0, min(1.0, factor))
    inverse_factor = 1.0 - clamped_factor

    return QColor(
        round(
            first_color.red() * inverse_factor
            + second_color.red() * clamped_factor
        ),
        round(
            first_color.green() * inverse_factor
            + second_color.green() * clamped_factor
        ),
        round(
            first_color.blue() * inverse_factor
            + second_color.blue() * clamped_factor
        ),
        round(
            first_color.alpha() * inverse_factor
            + second_color.alpha() * clamped_factor
        ),
    )


class NextgisDecorator:
    """Provide shared NextGIS UI styling helpers.

    Resolve theme tokens, palette colors, brand colors, and stylesheet
    snippets used by reusable Qt components.
    """

    DEFAULT_BUTTON_HEIGHT = 32
    CARD_MARGIN = 28
    CARD_PADDING_HORIZONTAL = 28
    CARD_PADDING_VERTICAL = 24
    CARD_SPACING = 8
    CARD_BUTTON_SPACING = 10
    CARD_MAX_WIDTH = 350
    CARD_MIN_WIDTH = 320
    GRID_SIZE = 40

    _COLOR_GROUPS = (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    )
    _THEME_PATH = (
        Path(__file__).resolve().parents[2]
        / "assets"
        / "themes"
        / "nextgis.json"
    )
    _theme = NextgisTheme(_THEME_PATH)

    @classmethod
    def theme(cls) -> NextgisTheme:
        """Return the shared NextGIS theme.

        :return: Theme reader instance.
        """
        return cls._theme

    @classmethod
    def system_palette(cls, palette: Optional[QPalette] = None) -> QPalette:
        """Return a QGIS system palette copy.

        :param palette: Palette to copy instead of the application palette.
        :return: Palette copy.
        """
        if palette is not None:
            return QPalette(palette)

        return QPalette(QgsApplication.palette())

    @classmethod
    def system_color(
        cls,
        role: QPalette.ColorRole,
        palette: Optional[QPalette] = None,
        *,
        group: Optional[QPalette.ColorGroup] = None,
    ) -> QColor:
        """Return a color from a system palette.

        :param role: Palette color role.
        :param palette: Palette to read from.
        :param group: Optional palette color group.
        :return: Palette color.
        """
        active_palette = cls.system_palette(palette)
        if group is None:
            return active_palette.color(role)

        return active_palette.color(group, role)

    @classmethod
    def system_window_color(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QColor:
        """Return the system window color.

        :param palette: Palette to read from.
        :return: Window color.
        """
        return cls.system_color(QPalette.ColorRole.Window, palette)

    @classmethod
    def system_base_color(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QColor:
        """Return the system base color.

        :param palette: Palette to read from.
        :return: Base color.
        """
        return cls.system_color(QPalette.ColorRole.Base, palette)

    @classmethod
    def system_title_color(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QColor:
        """Return the system title text color.

        :param palette: Palette to read from.
        :return: Title text color.
        """
        return cls.system_color(QPalette.ColorRole.WindowText, palette)

    @classmethod
    def system_text_color(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QColor:
        """Return the system text color.

        :param palette: Palette to read from.
        :return: Text color.
        """
        return cls.system_color(QPalette.ColorRole.Text, palette)

    @classmethod
    def system_button_color(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QColor:
        """Return the system button color.

        :param palette: Palette to read from.
        :return: Button color.
        """
        return cls.system_color(QPalette.ColorRole.Button, palette)

    @classmethod
    def system_border_color(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QColor:
        """Return the system border color.

        :param palette: Palette to read from.
        :return: Border color.
        """
        return cls.system_color(QPalette.ColorRole.Mid, palette)

    @classmethod
    def system_muted_text_color(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QColor:
        """Return a muted text color.

        :param palette: Palette to read from.
        :return: Muted text color.
        """
        active_palette = cls.system_palette(palette)

        return mix_colors(
            cls.system_text_color(active_palette),
            cls.system_window_color(active_palette),
            0.45 if cls.is_dark_theme(active_palette) else 0.60,
        )

    @classmethod
    def is_dark_theme(cls, palette: Optional[QPalette] = None) -> bool:
        """Return whether a palette appears dark.

        :param palette: Palette to inspect.
        :return: ``True`` when the palette appears dark.
        """
        active_palette = cls.system_palette(palette)
        window_color = cls.system_window_color(active_palette)
        text_color = cls.system_title_color(active_palette)

        return window_color.lightnessF() < text_color.lightnessF()

    @classmethod
    def brand_color(
        cls,
        color: NextgisBrandColor = NextgisBrandColor.DEFAULT,
    ) -> QColor:
        """Return a brand color.

        :param color: Brand color token to resolve.
        :return: Brand color.
        """
        return cls.theme().color(color.value)

    @classmethod
    def brand_hover_color(cls) -> QColor:
        """Return the brand hover color.

        :return: Brand hover color.
        """
        return cls.brand_color(NextgisBrandColor.HOVER)

    @classmethod
    def brand_active_color(cls) -> QColor:
        """Return the brand active color.

        :return: Brand active color.
        """
        return cls.brand_color(NextgisBrandColor.ACTIVE)

    @classmethod
    def brand_overlay_color(
        cls,
        alpha_factor: float = 0.05,
    ) -> QColor:
        """Return the brand color with adjusted alpha.

        :param alpha_factor: Alpha factor clamped to the ``0`` to ``1`` range.
        :return: Brand overlay color.
        """
        color = cls.brand_color()
        color.setAlpha(round(255 * max(0.0, min(1.0, alpha_factor))))

        return color

    @classmethod
    def brand_on_color(cls) -> QColor:
        """Return the foreground color for brand backgrounds.

        :return: Brand foreground color.
        """
        return cls.brand_color(NextgisBrandColor.ON_BRAND)

    @classmethod
    def spacing(cls, spacing: NextgisSpacing) -> int:
        """Return a spacing token value.

        :param spacing: Spacing token to resolve.
        :return: Spacing in pixels.
        """
        return cls.theme().integer(spacing.value)

    @classmethod
    def radius(cls, radius: NextgisRadius) -> int:
        """Return a radius token value.

        :param radius: Radius token to resolve.
        :return: Radius in pixels.
        """
        return cls.theme().integer(radius.value)

    @classmethod
    def size(cls, size: NextgisSize) -> int:
        """Return a size token value.

        :param size: Size token to resolve.
        :return: Size in pixels.
        """
        return cls.theme().integer(size.value)

    @classmethod
    def create_palette(
        cls,
        overrides: Mapping[PaletteKey, QColor],
        *,
        base_palette: Optional[QPalette] = None,
    ) -> QPalette:
        """Create a palette with color overrides.

        :param overrides: Palette role overrides.
        :param base_palette: Base palette to copy.
        :return: Palette with applied overrides.
        """
        palette = cls.system_palette(base_palette)

        for key, color in overrides.items():
            normalized_color = QColor(color)
            if isinstance(key, tuple):
                color_group, color_role = key
                palette.setColor(color_group, color_role, normalized_color)
                continue

            for color_group in cls._COLOR_GROUPS:
                palette.setColor(color_group, key, normalized_color)

        return palette

    @classmethod
    def overlay_card_palette(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QPalette:
        """Create a palette for overlay cards.

        :param palette: Base palette to copy.
        :return: Overlay card palette.
        """
        active_palette = cls.system_palette(palette)
        base_color = cls.system_base_color(active_palette)
        window_color = cls.system_window_color(active_palette)
        title_color = cls.system_title_color(active_palette)
        helper_color = cls.system_muted_text_color(active_palette)
        card_color = mix_colors(window_color, base_color, 0.82)
        disabled_text = mix_colors(title_color, card_color, 0.60)

        return cls.create_palette(
            {
                QPalette.ColorRole.Window: card_color,
                QPalette.ColorRole.Base: card_color,
                QPalette.ColorRole.WindowText: title_color,
                QPalette.ColorRole.Text: title_color,
                QPalette.ColorRole.Mid: cls.system_border_color(
                    active_palette
                ),
                (
                    QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.WindowText,
                ): disabled_text,
                (
                    QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.Text,
                ): helper_color,
            },
            base_palette=active_palette,
        )

    @classmethod
    def progress_palette(
        cls,
        palette: Optional[QPalette] = None,
    ) -> QPalette:
        """Create a palette for progress controls.

        :param palette: Base palette to copy.
        :return: Progress palette.
        """
        active_palette = cls.system_palette(palette)

        return cls.create_palette(
            {
                QPalette.ColorRole.Highlight: cls.brand_color(),
                QPalette.ColorRole.HighlightedText: cls.brand_on_color(),
            },
            base_palette=active_palette,
        )

    @classmethod
    def stylesheet(
        cls,
        selector: str,
        declarations: Mapping[str, str],
    ) -> str:
        """Build a CSS stylesheet rule.

        :param selector: CSS selector.
        :param declarations: CSS declarations.
        :return: Stylesheet rule.
        """
        rules = [
            f"{property_name}: {value};"
            for property_name, value in declarations.items()
        ]

        return f"{selector} {{ {''.join(rules)} }}"

    @classmethod
    def merge_stylesheets(cls, *stylesheets: str) -> str:
        """Merge stylesheet snippets.

        :param stylesheets: Stylesheet snippets to merge.
        :return: Combined stylesheet text.
        """
        return "\n".join(
            stylesheet
            for stylesheet in stylesheets
            if stylesheet.strip() != ""
        )

    @classmethod
    def patch_widget(
        cls,
        widget: QWidget,
        *,
        palette: Optional[QPalette] = None,
        stylesheets: Iterable[str] = (),
        auto_fill_background: Optional[bool] = None,
    ) -> None:
        """Apply shared palette and stylesheet settings to a widget.

        :param widget: Widget to patch.
        :param palette: Palette to apply.
        :param stylesheets: Stylesheet snippets to merge and apply.
        :param auto_fill_background: Optional auto-fill-background value.
        """
        if palette is not None:
            widget.setPalette(QPalette(palette))

        if auto_fill_background is not None:
            widget.setAutoFillBackground(auto_fill_background)

        merged_stylesheet = cls.merge_stylesheets(*stylesheets)
        if merged_stylesheet != widget.styleSheet():
            widget.setStyleSheet(merged_stylesheet)

    @classmethod
    def as_rgba(cls, color: QColor) -> str:
        """Return a CSS rgba color string.

        :param color: Color to convert.
        :return: CSS rgba string.
        """
        return (
            f"rgba({color.red()}, {color.green()}, {color.blue()}, "
            f"{color.alphaF():.3f})"
        )
