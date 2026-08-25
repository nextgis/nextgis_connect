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

from pathlib import Path
from unittest import mock

from qgis.gui import QgsFileWidget
from qgis.PyQt.QtGui import QColor, QPixmap

from nextgis_connect.legacy.ngw.core.ngw_feature import NGWFeature
from nextgis_connect.legacy.ngw.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.legacy.ngw.qgis.ngw_resource_model_4qgis import (
    QGISResourceJob,
)


def test_import_attachments_declares_png_mime_type(
    qgis_app,
    tmp_path: Path,
) -> None:
    del qgis_app

    image_path = tmp_path / "photo.png"
    pixmap = QPixmap(1, 1)
    pixmap.fill(QColor("#ff0000"))
    assert pixmap.save(str(image_path))

    connection = mock.Mock()
    uploaded_file = {
        "id": "file-upload",
        "name": "photo.png",
        "mime_type": "image/png",
        "size": image_path.stat().st_size,
    }
    connection.upload_file.return_value = uploaded_file
    connection.post.return_value = {"id": 1}

    ngw_resource = mock.Mock()
    ngw_resource.type_id = NGWVectorLayer.type_id
    ngw_resource.resource_id = 9
    ngw_resource.res_factory.connection = connection
    ngw_resource.get_features.return_value = [
        NGWFeature({"id": 1}, ngw_resource)
    ]

    editor_widget = mock.Mock()
    editor_widget.type.return_value = "ExternalResource"
    editor_widget.config.return_value = {
        "StorageType": False,
        "StorageMode": QgsFileWidget.StorageMode.GetFile,
        "RelativeStorage": None,
    }
    qgs_vector_layer = mock.Mock()
    qgs_vector_layer.attributeList.return_value = [0]
    qgs_vector_layer.editorWidgetSetup.return_value = editor_widget
    qgs_feature = mock.Mock()
    qgs_feature.attributes.return_value = [str(image_path)]
    qgs_vector_layer.getFeatures.return_value = [qgs_feature]

    QGISResourceJob().importAttachments(qgs_vector_layer, ngw_resource)

    assert connection.upload_file.call_args.args[0] == str(image_path)
    assert connection.upload_file.call_args.kwargs["mime_type"] == "image/png"
    connection.post.assert_called_once_with(
        "/api/resource/9/feature/1/attachment/",
        json={
            "name": "photo.png",
            "file_upload": uploaded_file,
            "mime_type": "image/png",
        },
    )
