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

from .ngw_attachment import NGWAttachment
from .ngw_base_map import NGWBaseMap
from .ngw_error import NGWError
from .ngw_group_resource import NGWGroupResource
from .ngw_mapserver_style import NGWMapServerStyle
from .ngw_ogcf_service import NGWOgcfService
from .ngw_point_cloud_layer import NGWPointCloudLayer
from .ngw_postgis_layer import NGWPostgisLayer
from .ngw_qgis_style import (
    NGWQGISRasterStyle,
    NGWQGISStyle,
    NGWQGISVectorStyle,
)
from .ngw_raster_layer import NGWRasterLayer
from .ngw_raster_mosaic import NGWRasterMosaic
from .ngw_raster_style import NGWRasterStyle
from .ngw_resource import NGWResource
from .ngw_tileset import NGWTileset
from .ngw_tms_resources import NGWTmsConnection, NGWTmsLayer
from .ngw_vector_layer import NGWVectorLayer
from .ngw_webmap import NGWWebMap
from .ngw_wfs_connection import NGWWfsConnection
from .ngw_wfs_layer import NGWWfsLayer
from .ngw_wfs_service import NGWWfsService
from .ngw_wms_connection import NGWWmsConnection
from .ngw_wms_layer import NGWWmsLayer
from .ngw_wms_service import NGWWmsService

__all__ = [
    "NGWAttachment",
    "NGWBaseMap",
    "NGWError",
    "NGWGroupResource",
    "NGWMapServerStyle",
    "NGWOgcfService",
    "NGWPointCloudLayer",
    "NGWPostgisLayer",
    "NGWQGISRasterStyle",
    "NGWQGISStyle",
    "NGWQGISVectorStyle",
    "NGWRasterLayer",
    "NGWRasterMosaic",
    "NGWRasterStyle",
    "NGWResource",
    "NGWTileset",
    "NGWTmsConnection",
    "NGWTmsLayer",
    "NGWVectorLayer",
    "NGWWebMap",
    "NGWWfsConnection",
    "NGWWfsLayer",
    "NGWWfsService",
    "NGWWmsConnection",
    "NGWWmsLayer",
    "NGWWmsService",
]
