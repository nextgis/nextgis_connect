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

from typing import List, Optional, Tuple

from qgis.core import QgsMapLayer, QgsPathResolver, QgsVectorLayer

from nextgis_connect.features.qml_processing.primary_key import (
    PrimaryKeyQmlHandler,
)
from nextgis_connect.features.qml_processing.processor import (
    QmlDocumentHandler,
)
from nextgis_connect.features.qml_processing.svg_embedding import (
    SvgEmbeddingQmlHandler,
)
from nextgis_connect.platform.qgis.compat import FieldType


def qml_handlers_for_layer(
    layer: QgsMapLayer,
    *,
    embed_svg_images: bool = False,
    path_resolver: Optional[QgsPathResolver] = None,
) -> Tuple[QmlDocumentHandler, ...]:
    """Return the QML transformations applicable to a layer upload.

    Callers select handlers from settings or known server capabilities before
    constructing :class:`QmlProcessor`.
    """
    handlers: List[QmlDocumentHandler] = []
    if embed_svg_images:
        handlers.append(
            SvgEmbeddingQmlHandler(path_resolver or QgsPathResolver())
        )

    if isinstance(layer, QgsVectorLayer) and layer.providerType() == "ogr":
        primary_key_attributes = layer.primaryKeyAttributes()
        if primary_key_attributes:
            primary_key_field = layer.fields()[primary_key_attributes[0]]
            if primary_key_field.type() in (
                FieldType.Int,
                FieldType.LongLong,
            ):
                handlers.append(PrimaryKeyQmlHandler(primary_key_field.name()))

    return tuple(handlers)
