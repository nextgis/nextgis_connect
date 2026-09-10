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

import base64
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from qgis.core import QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtXml import QDomDocument

from nextgis_connect.features.qml_processing import (
    QmlProcessor,
    qml_handlers_for_layer,
)
from nextgis_connect.features.qml_processing.primary_key import (
    PrimaryKeyQmlHandler,
)
from nextgis_connect.legacy.ngw.qgis.ngw_resource_model_4qgis import (
    QGISResourceJob,
)
from nextgis_connect.legacy.settings.ng_connect_settings import (
    NgConnectSettings,
)
from nextgis_connect.platform.qgis.compat import FieldType


def _document(qml: str) -> QDomDocument:
    document = QDomDocument()
    parse_result = document.setContent(qml)
    is_valid = (
        parse_result[0] if isinstance(parse_result, tuple) else parse_result
    )
    assert is_valid
    return document


def _ogr_layer(primary_key_type=FieldType.LongLong) -> Mock:
    primary_key_field = Mock()
    primary_key_field.name.return_value = "fid"
    primary_key_field.type.return_value = primary_key_type

    layer = Mock(spec=QgsVectorLayer)
    layer.providerType.return_value = "ogr"
    layer.primaryKeyAttributes.return_value = [0]
    layer.fields.return_value = [primary_key_field]
    return layer


def test_qml_processor_preserves_boolean_values(qgis_app) -> None:
    del qgis_app
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

    processed_qml = QmlProcessor(
        qml,
        qml_handlers_for_layer(_ogr_layer()),
    ).process()

    document = _document(processed_qml)
    category = document.elementsByTagName("category").at(0).toElement()
    text_style = document.elementsByTagName("text-style").at(0).toElement()
    assert category.attribute("type") == "bool"
    assert category.attribute("value") == "true"
    assert text_style.attribute("fieldName") == "\"enabled\" || 'literal'"


def test_primary_key_handler_updates_supported_expressions(qgis_app) -> None:
    del qgis_app
    qml = """
        <qgis>
            <renderer-v2 type="RuleRenderer">
                <rules>
                    <rule filter="&quot;fid&quot; = 1 AND 'fid' = 'literal'"/>
                </rules>
            </renderer-v2>
            <renderer-v2 type="categorizedSymbol"/>
            <text-style fieldName="concat(&quot;fid&quot;, 'fid')"/>
            <text-style fieldName="concat('it''s fid', &quot;fid&quot;)"/>
            <data_defined_properties>
                <Option name="expression" value="&quot;fid&quot; + 1"/>
            </data_defined_properties>
            <labeling>
                <settings>
                    <dd_properties>
                        <Option type="Map">
                            <Option name="properties" type="Map">
                                <Option name="0" type="Map">
                                    <Option name="expression" type="QString" value="&quot;fid&quot; + 2"/>
                                </Option>
                            </Option>
                        </Option>
                    </dd_properties>
                </settings>
            </labeling>
            <customproperties>
                <property key="labeling/fieldName" value="concat(&quot;fid&quot;, 'fid')"/>
                <property key="labeling/isExpression" value="false"/>
            </customproperties>
            <data-defined>
                <FontSize active="true" useExpr="true" expr="concat('don\\'t use fid', &quot;fid&quot;)"/>
            </data-defined>
        </qgis>
    """

    processed_qml = QmlProcessor(
        qml,
        qml_handlers_for_layer(_ogr_layer()),
    ).process()

    document = _document(processed_qml)
    rule = document.elementsByTagName("rule").at(0).toElement()
    text_styles = document.elementsByTagName("text-style")
    text_style = text_styles.at(0).toElement()
    escaped_text_style = text_styles.at(1).toElement()
    options = document.elementsByTagName("Option")
    option = options.at(0).toElement()
    dd_expression = options.at(4).toElement()
    custom_properties = document.elementsByTagName("property")
    legacy_label = custom_properties.at(0).toElement()
    legacy_label_expression = custom_properties.at(1).toElement()
    legacy_data_defined = (
        document.elementsByTagName("FontSize").at(0).toElement()
    )
    assert rule.attribute("filter") == "@id = 1 AND 'fid' = 'literal'"
    assert text_style.attribute("fieldName") == "concat(@id, 'fid')"
    assert text_style.attribute("isExpression") == "1"
    assert (
        escaped_text_style.attribute("fieldName") == "concat('it''s fid', @id)"
    )
    assert option.attribute("value") == "@id + 1"
    assert dd_expression.attribute("value") == "@id + 2"
    assert legacy_label.attribute("value") == "concat(@id, 'fid')"
    assert legacy_label_expression.attribute("value") == "true"
    assert (
        legacy_data_defined.attribute("expr")
        == "concat('don\\'t use fid', @id)"
    )


def test_qml_processor_preserves_original_for_empty_handlers(qgis_app) -> None:
    del qgis_app
    qml = "not XML"

    assert QmlProcessor(qml, ()).process() == qml


def test_primary_key_handler_preserves_qgis_variables(qgis_app) -> None:
    del qgis_app
    qml = '<qgis><text-style fieldName="@id || $id || &quot;id&quot;"/></qgis>'

    processed_qml = QmlProcessor(
        qml,
        (PrimaryKeyQmlHandler("id"),),
    ).process()

    document = _document(processed_qml)
    text_style = document.elementsByTagName("text-style").at(0).toElement()
    assert text_style.attribute("fieldName") == "@id || $id || @id"


def test_qml_processor_uses_handlers_in_order(qgis_app) -> None:
    del qgis_app
    calls = []

    class RecordingHandler:
        def __init__(self, name: str) -> None:
            self._name = name

        def process(self, document: QDomDocument) -> bool:
            calls.append(self._name)
            document.documentElement().setAttribute(self._name, "1")
            return True

    processed_qml = QmlProcessor(
        "<qgis/>",
        (RecordingHandler("first"), RecordingHandler("second")),
    ).process()

    assert calls == ["first", "second"]
    document = _document(processed_qml)
    assert document.documentElement().attribute("first") == "1"
    assert document.documentElement().attribute("second") == "1"


def test_qml_processor_rejects_invalid_qml_with_handlers(qgis_app) -> None:
    del qgis_app

    with pytest.raises(ValueError, match="QML document is not valid"):
        QmlProcessor("not XML", (PrimaryKeyQmlHandler("fid"),)).process()


def test_svg_embedding_handler_embeds_local_svg(qgis_app, tmp_path) -> None:
    del qgis_app
    marker_svg_data = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    marker_svg_path = tmp_path / "marker.svg"
    marker_svg_path.write_bytes(marker_svg_data)
    fill_svg_data = b"<svg/>"
    fill_svg_path = tmp_path / "fill.svg"
    fill_svg_path.write_bytes(fill_svg_data)
    label_svg_data = b"<svg><path/></svg>"
    label_svg_path = tmp_path / "label.svg"
    label_svg_path.write_bytes(label_svg_data)
    qml = f"""<qgis><layer class="SvgMarker">
        <prop k="name" v="{marker_svg_path}"/>
    </layer><layer class="SVGFill">
        <Option type="Map">
            <Option name="svgFile" type="QString" value="{fill_svg_path}"/>
        </Option>
    </layer><text-format>
        <background shapeSVGFile="{label_svg_path}"/>
    </text-format></qgis>"""

    processed_qml = QmlProcessor(
        qml,
        qml_handlers_for_layer(
            Mock(spec=QgsRasterLayer),
            embed_svg_images=True,
        ),
    ).process()

    document = _document(processed_qml)
    marker_property = document.elementsByTagName("prop").at(0).toElement()
    fill_property = document.elementsByTagName("Option").at(1).toElement()
    label_background = (
        document.elementsByTagName("background").at(0).toElement()
    )
    assert marker_property.attribute("v") == (
        f"base64:{base64.b64encode(marker_svg_data).decode('ascii')}"
    )
    assert fill_property.attribute("value") == (
        f"base64:{base64.b64encode(fill_svg_data).decode('ascii')}"
    )
    assert label_background.attribute("shapeSVGFile") == (
        f"base64:{base64.b64encode(label_svg_data).decode('ascii')}"
    )


def test_svg_embedding_handler_preserves_unavailable_references(
    qgis_app,
) -> None:
    del qgis_app
    qml = """<qgis><layer class="SvgMarker">
        <prop k="name" v="base64:already-embedded"/>
        <prop k="name" v="https://example.com/marker.svg"/>
    </layer></qgis>"""

    processed_qml = QmlProcessor(
        qml,
        qml_handlers_for_layer(
            Mock(spec=QgsRasterLayer),
            embed_svg_images=True,
        ),
    ).process()

    assert processed_qml == qml


def test_qml_upload_uses_svg_embedding_setting(
    qgis_app,
    reset_qgis_settings,
    tmp_path,
) -> None:
    del qgis_app, reset_qgis_settings
    svg_data = b"<svg/>"
    svg_path = tmp_path / "marker.svg"
    svg_path.write_bytes(svg_data)
    qml = f'<qgis><layer class="SvgMarker"><prop k="name" v="{svg_path}"/></layer></qgis>'
    layer = Mock(spec=QgsRasterLayer)

    embedded_qml = QGISResourceJob._process_qml_for_upload(qml, layer)
    assert (
        f"base64:{base64.b64encode(svg_data).decode('ascii')}" in embedded_qml
    )

    NgConnectSettings().embed_svg_images_in_qml = False
    assert QGISResourceJob._process_qml_for_upload(qml, layer) == qml


def test_qml_handlers_for_layer_requires_ogr_integer_primary_key(
    qgis_app,
) -> None:
    del qgis_app
    layer = _ogr_layer()
    assert len(qml_handlers_for_layer(layer)) == 1

    layer.providerType.return_value = "memory"
    assert qml_handlers_for_layer(layer) == ()

    layer = _ogr_layer(FieldType.Int)
    assert len(qml_handlers_for_layer(layer)) == 1

    raster_layer = Mock(spec=QgsRasterLayer)
    assert qml_handlers_for_layer(raster_layer) == ()


@pytest.mark.parametrize("layer_class", (QgsVectorLayer, QgsRasterLayer))
def test_add_style_processes_qml_before_upload(qgis_app, layer_class) -> None:
    del qgis_app
    qml_data = '<qgis><text-style fieldName="fid"/></qgis>'
    layer = Mock(spec=layer_class)
    style_manager = layer.styleManager.return_value
    style_manager.style.return_value.xmlData.return_value = qml_data
    style_manager.isDefault.return_value = False
    resource = Mock()
    uploaded_qml = []

    def upload_qml(ngw_layer_resource, qml_filename, style_name=None):
        del ngw_layer_resource, style_name
        uploaded_qml.append(Path(qml_filename).read_text())
        return Mock()

    job = QGISResourceJob()
    with patch.object(job, "upload_qml_file", side_effect=upload_qml):
        with patch.object(
            job,
            "_process_qml_for_upload",
            return_value="processed qml",
        ) as process_qml:
            job.addStyle(resource, layer, "style")

    process_qml.assert_called_once_with(qml_data, layer)
    assert uploaded_qml == ["processed qml"]


@pytest.mark.parametrize("layer_class", (QgsVectorLayer, QgsRasterLayer))
def test_update_style_processes_qml_before_upload(
    qgis_app, layer_class
) -> None:
    del qgis_app
    qml_data = '<qgis><text-style fieldName="fid"/></qgis>'
    layer = Mock(spec=layer_class)
    style_manager = layer.styleManager.return_value
    style_manager.currentStyle.return_value = "style"
    style_manager.style.return_value.xmlData.return_value = qml_data
    uploaded_qml = []

    def update_qml(qml, ngw_layer_resource):
        del ngw_layer_resource
        uploaded_qml.append(Path(qml).read_text())

    job = QGISResourceJob()
    with patch.object(job, "updateQMLStyle", side_effect=update_qml):
        with patch.object(
            job,
            "_process_qml_for_upload",
            return_value="processed qml",
        ) as process_qml:
            job.updateStyle(layer, Mock())

    process_qml.assert_called_once_with(qml_data, layer)
    assert uploaded_qml == ["processed qml"]
