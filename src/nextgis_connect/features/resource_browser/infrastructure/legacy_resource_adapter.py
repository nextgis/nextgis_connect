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

from typing import Optional, Union

from qgis.PyQt.QtCore import QModelIndex

from nextgis_connect.legacy.ngw.core import (
    NGWBaseMap,
    NGWOgcfService,
    NGWPointCloudLayer,
    NGWPostgisLayer,
    NGWQGISStyle,
    NGWRasterLayer,
    NGWResource,
    NGWTileset,
    NGWVectorLayer,
    NGWWebMap,
    NGWWfsLayer,
    NGWWfsService,
    NGWWmsConnection,
    NGWWmsLayer,
    NGWWmsService,
)
from nextgis_connect.legacy.ngw.core.ngw_tms_resources import (
    NGWTmsConnection,
    NGWTmsLayer,
)
from nextgis_connect.legacy.tree_widget.item import QNGWResourceItem

TMS_LAYER_RESOURCE_TYPES = (
    NGWTmsLayer,
    NGWTmsConnection,
    NGWBaseMap,
    NGWTileset,
)
SERVICE_LAYER_RESOURCE_TYPES = (NGWPostgisLayer, NGWWmsLayer, NGWWfsLayer)
VECTOR_RESOURCE_TYPES = (NGWWfsLayer, NGWPostgisLayer)
RASTER_RESOURCE_TYPES = (
    NGWRasterLayer,
    *TMS_LAYER_RESOURCE_TYPES,
    NGWWmsLayer,
)
POINT_CLOUD_RESOURCE_TYPES = (NGWPointCloudLayer,)
VECTOR_SERVICE_TYPES = (NGWWfsService, NGWOgcfService)
SERVICE_RESOURCE_TYPES = (*VECTOR_SERVICE_TYPES, NGWWmsService)
CONNECTION_RESOURCE_TYPES = (NGWWmsConnection,)


def resource_from_index(index: QModelIndex) -> Optional[NGWResource]:
    """Return the legacy resource stored by a model index."""
    resource = index.data(QNGWResourceItem.NGWResourceRole)
    return resource if isinstance(resource, NGWResource) else None


def is_style(
    resource: Union[Optional[NGWResource], QModelIndex],
) -> bool:
    if isinstance(resource, QModelIndex):
        resource = resource_from_index(resource)
    return isinstance(resource, NGWQGISStyle)


def is_layer(
    resource: Union[Optional[NGWResource], QModelIndex],
) -> bool:
    if isinstance(resource, QModelIndex):
        resource = resource_from_index(resource)
    return isinstance(
        resource,
        (
            NGWVectorLayer,
            *VECTOR_RESOURCE_TYPES,
            *RASTER_RESOURCE_TYPES,
            *POINT_CLOUD_RESOURCE_TYPES,
        ),
    )


def is_webmap(
    resource: Union[Optional[NGWResource], QModelIndex],
) -> bool:
    if isinstance(resource, QModelIndex):
        resource = resource_from_index(resource)
    return isinstance(resource, NGWWebMap)


def is_service(
    resource: Union[Optional[NGWResource], QModelIndex],
) -> bool:
    if isinstance(resource, QModelIndex):
        resource = resource_from_index(resource)
    return isinstance(
        resource,
        (*VECTOR_SERVICE_TYPES, NGWWmsService, NGWWmsConnection),
    )
