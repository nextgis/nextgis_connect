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

from typing import Optional, Tuple
from weakref import ref

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QObject
from qgis.PyQt.QtWidgets import QAction, QApplication, QWidget


class InteractionGuard(QObject):
    def __init__(
        self, scope: QWidget, allowed: Tuple[QWidget, ...], parent: QObject
    ) -> None:
        super().__init__(parent)
        self._scope = ref(scope)
        self._allowed = tuple(ref(widget) for widget in allowed)

    def set_active(self, active: bool) -> None:
        application = QApplication.instance()
        if application is None:
            return
        if active:
            application.installEventFilter(self)
        else:
            application.removeEventFilter(self)

    def eventFilter(self, a0: Optional[QObject], a1: Optional[QEvent]) -> bool:
        if not isinstance(a0, (QWidget, QAction)) or a1 is None:
            return False
        scope = self._scope()
        if scope is None or sip.isdeleted(scope):
            return False
        if not self._belongs_to(a0, scope):
            return False
        for reference in self._allowed:
            widget = reference()
            if widget is None or sip.isdeleted(widget):
                continue
            if self._belongs_to(a0, widget):
                return False
        if a1.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
            QEvent.Type.Shortcut,
            QEvent.Type.ShortcutOverride,
            QEvent.Type.ContextMenu,
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            a1.accept()
            return True
        return False

    @staticmethod
    def _belongs_to(obj: Optional[QObject], root: QObject) -> bool:
        while obj is not None:
            if sip.isdeleted(obj):
                return False
            if obj is root:
                return True
            obj = obj.parent()
        return False
