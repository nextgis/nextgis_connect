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

from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QPainter, QPalette, QPen, QPixmap
from qgis.PyQt.QtWidgets import QStyle, QStyleOptionToolButton, QToolButton

from nextgis_connect.ui_kit.graphics import NextgisDecorator


def render_menu_button_preview(button: QToolButton) -> QPixmap:
    """Render a themed tool button with its menu-arrow area highlighted.

    Preserve the live button state while drawing an enabled preview through
    its actual Qt style, palette, icon and device pixel ratio.

    :param button: Split tool button to illustrate.
    :return: Preview with the menu subcontrol outlined.
    """
    option = QStyleOptionToolButton()
    # Native toolbar buttons cannot expose protected methods through PyQt.
    option.initFrom(button)
    option.icon = button.icon()
    option.iconSize = button.iconSize()
    option.text = button.text()
    option.font = button.font()
    option.toolButtonStyle = button.toolButtonStyle()
    option.arrowType = button.arrowType()
    if button.autoRaise():
        option.state |= QStyle.StateFlag.State_AutoRaise
    if button.isChecked():
        option.state |= QStyle.StateFlag.State_On
    if button.arrowType() != Qt.ArrowType.NoArrow:
        option.features |= QStyleOptionToolButton.ToolButtonFeature.Arrow
    if button.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup:
        option.features |= (
            QStyleOptionToolButton.ToolButtonFeature.MenuButtonPopup
        )
    option.state |= (
        QStyle.StateFlag.State_Enabled
        | QStyle.StateFlag.State_MouseOver
        | QStyle.StateFlag.State_Raised
    )
    option.state &= ~QStyle.StateFlag.State_Sunken
    palette = QPalette(button.palette())
    palette.setCurrentColorGroup(QPalette.ColorGroup.Active)
    option.palette = palette
    option.features |= QStyleOptionToolButton.ToolButtonFeature.HasMenu
    option.activeSubControls = QStyle.SubControl.SC_ToolButtonMenu
    option.subControls = (
        QStyle.SubControl.SC_ToolButton | QStyle.SubControl.SC_ToolButtonMenu
    )
    ratio = button.devicePixelRatioF()
    pixmap = QPixmap(
        round(button.width() * ratio), round(button.height() * ratio)
    )
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    button.style().drawComplexControl(
        QStyle.ComplexControl.CC_ToolButton, option, painter, button
    )
    menu_rect = button.style().subControlRect(
        QStyle.ComplexControl.CC_ToolButton,
        option,
        QStyle.SubControl.SC_ToolButtonMenu,
        button,
    )
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(NextgisDecorator.brand_color(), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(menu_rect).adjusted(1, 1, -1, -1), 2, 2)
    painter.end()
    return pixmap
