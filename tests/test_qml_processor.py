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
# with this program.  If not, see <https://www.gnu.org/licenses/>.

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtXml import QDomDocument

from nextgis_connect.qml_processor import QMLProcessor


def test_qml_processor_preserves_quoted_text_in_boolean_expression(
    qgis_app,
) -> None:
    del qgis_app
    layer = QgsVectorLayer("Point?field=enabled:boolean", "test", "memory")
    assert layer.isValid()
    qml = """
        <qgis>
            <renderer-v2 type="categorizedSymbol">
                <categories>
                    <category type="bool" value="true"/>
                </categories>
            </renderer-v2>
            <text-style fieldName="&quot;enabled&quot; || 'literal'"/>
        </qgis>
    """

    processed_qml = QMLProcessor(qml, layer).process()

    document = QDomDocument()
    document.setContent(processed_qml)
    category = document.elementsByTagName("category").at(0).toElement()
    text_style = document.elementsByTagName("text-style").at(0).toElement()
    assert category.attribute("type") == "integer"
    assert category.attribute("value") == "1"
    assert text_style.attribute("fieldName") == (
        "if(\"enabled\", true, false) || 'literal'"
    )
