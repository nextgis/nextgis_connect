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

from typing import Iterable, Protocol, Tuple

from qgis.PyQt.QtXml import QDomDocument


class QmlDocumentHandler(Protocol):
    """Transform a parsed QML document."""

    def process(self, document: QDomDocument) -> bool:
        """Apply a transformation and return whether the document changed."""
        ...


class QmlProcessor:
    """Apply an ordered sequence of transformations to a QML document."""

    def __init__(
        self,
        qml_xml: str,
        handlers: Iterable[QmlDocumentHandler],
    ) -> None:
        self._qml_xml = qml_xml
        self._handlers: Tuple[QmlDocumentHandler, ...] = tuple(handlers)

    def process(self) -> str:
        """Return processed QML, preserving the original when unchanged."""
        if not self._handlers:
            return self._qml_xml

        document = QDomDocument()
        parse_result = document.setContent(self._qml_xml)
        is_valid = (
            parse_result[0]
            if isinstance(parse_result, tuple)
            else parse_result
        )
        if not is_valid or document.documentElement().tagName() != "qgis":
            raise ValueError("QML document is not valid")

        has_changes = False
        for handler in self._handlers:
            has_changes = handler.process(document) or has_changes

        return document.toString() if has_changes else self._qml_xml
