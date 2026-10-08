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

from qgis.PyQt.QtGui import QColor, QPalette

from nextgis_connect.ui_kit.widgets.information_notice import InformationNotice


def test_notice_updates_frame_and_icon_for_palette(qgis_app) -> None:
    notice = InformationNotice("Search criteria changed")
    notice.show()
    qgis_app.processEvents()
    light = QPalette()
    light.setColor(QPalette.ColorRole.Window, QColor("white"))
    light.setColor(QPalette.ColorRole.WindowText, QColor("black"))
    original_palette = QPalette(qgis_app.palette())
    qgis_app.setPalette(light)
    qgis_app.processEvents()
    assert "#d7dee5" in notice.styleSheet()
    assert not notice._icon.pixmap().isNull()
    dark = QPalette(light)
    dark.setColor(QPalette.ColorRole.Window, QColor("black"))
    dark.setColor(QPalette.ColorRole.WindowText, QColor("white"))
    qgis_app.setPalette(dark)
    qgis_app.processEvents()
    assert "#2a3a49" in notice.styleSheet(), (
        notice.palette().color(QPalette.ColorRole.Window).name(),
        notice.palette().color(QPalette.ColorRole.WindowText).name(),
    )
    assert not notice._icon.pixmap().isNull()
    qgis_app.setPalette(original_palette)
    notice.close()
