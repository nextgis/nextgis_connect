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

from typing import Dict, Optional, Type

from qgis.core import QgsFeedback

from nextgis_connect.legacy.ngw.core.ngw_tms_resources import (
    NGWTmsConnection,
    NGWTmsLayer,
)
from nextgis_connect.legacy.ngw.core.ngw_wfs_connection import NGWWfsConnection
from nextgis_connect.legacy.ngw.core.ngw_wfs_layer import NGWWfsLayer
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.platform.logging import logger

from .ngw_base_map import NGWBaseMap
from .ngw_eeko_storage import NGWEekoStorage
from .ngw_group_resource import NGWGroupResource
from .ngw_mapserver_style import NGWMapServerStyle
from .ngw_ogcf_service import NGWOgcfService
from .ngw_point_cloud_layer import NGWPointCloudLayer
from .ngw_postgis_layer import NGWPostgisConnection, NGWPostgisLayer
from .ngw_qgis_style import NGWQGISRasterStyle, NGWQGISVectorStyle
from .ngw_raster_layer import NGWRasterLayer
from .ngw_raster_mosaic import NGWRasterMosaic
from .ngw_raster_style import NGWRasterStyle
from .ngw_resource import NGWResource
from .ngw_tileset import NGWTileset
from .ngw_vector_layer import NGWVectorLayer
from .ngw_webmap import NGWWebMap
from .ngw_wfs_service import NGWWfsService
from .ngw_wms_connection import NGWWmsConnection
from .ngw_wms_layer import NGWWmsLayer
from .ngw_wms_service import NGWWmsService

API_NGW_VERSION = "/api/component/pyramid/pkg_version"


class NGWResourceFactory:
    __res_types_register: Dict[str, Type[NGWResource]]
    __default_type: str
    __conn: QgsNgwConnection

    def __init__(self, ngw_connection: QgsNgwConnection):
        self.__res_types_register = {
            NGWResource.type_id: NGWResource,
            NGWWfsService.type_id: NGWWfsService,
            NGWWfsLayer.type_id: NGWWfsLayer,
            NGWWfsConnection.type_id: NGWWfsConnection,
            NGWOgcfService.type_id: NGWOgcfService,
            NGWWmsService.type_id: NGWWmsService,
            NGWGroupResource.type_id: NGWGroupResource,
            NGWVectorLayer.type_id: NGWVectorLayer,
            NGWMapServerStyle.type_id: NGWMapServerStyle,
            NGWQGISVectorStyle.type_id: NGWQGISVectorStyle,
            NGWQGISRasterStyle.type_id: NGWQGISRasterStyle,
            NGWRasterLayer.type_id: NGWRasterLayer,
            NGWWebMap.type_id: NGWWebMap,
            NGWRasterStyle.type_id: NGWRasterStyle,
            NGWWmsConnection.type_id: NGWWmsConnection,
            NGWWmsLayer.type_id: NGWWmsLayer,
            NGWBaseMap.type_id: NGWBaseMap,
            NGWPostgisConnection.type_id: NGWPostgisConnection,
            NGWPostgisLayer.type_id: NGWPostgisLayer,
            NGWPointCloudLayer.type_id: NGWPointCloudLayer,
            NGWTmsConnection.type_id: NGWTmsConnection,
            NGWTmsLayer.type_id: NGWTmsLayer,
            NGWTileset.type_id: NGWTileset,
            NGWEekoStorage.type_id: NGWEekoStorage,
            NGWRasterMosaic.type_id: NGWRasterMosaic,
            # Aliases
            "demo_project": NGWGroupResource,
            "gpdobj_group": NGWGroupResource,
            "gpdobj_pi_dm": NGWGroupResource,
            "gpdobj_pir_obj": NGWGroupResource,
            "gpdobj_pir_oip": NGWGroupResource,
            "gpdobj_pir_dm": NGWGroupResource,
            "gpdobj_dm_section": NGWGroupResource,
            "gpdobj_dm_group": NGWGroupResource,
            "gpdobj_storage": NGWEekoStorage,
            "gpdobj_oper_dm": NGWGroupResource,
        }
        self.__default_type = NGWResource.type_id
        self.__conn = ngw_connection

    @property
    def connection(self) -> QgsNgwConnection:
        return self.__conn

    def get_resource(
        self,
        resource_id: int,
        *,
        feedback: Optional[QgsFeedback] = None,
    ) -> NGWResource:
        logger.debug(f"↓ Fetch resource with id={resource_id}")
        res_json = NGWResource.receive_resource_obj(
            self.__conn,
            resource_id,
            feedback=feedback,
        )
        return self.get_resource_by_json(res_json)

    def get_resource_by_json(self, res_json) -> NGWResource:
        resource_type: Type[NGWResource]
        if res_json["resource"]["cls"] in self.__res_types_register:
            resource_type = self.__res_types_register[
                res_json["resource"]["cls"]
            ]
        else:
            resource_type = self.__res_types_register[self.__default_type]
        return resource_type(self, res_json)

    def get_root_resource(
        self,
        *,
        feedback: Optional[QgsFeedback] = None,
    ) -> NGWResource:
        return self.get_resource(0, feedback=feedback)

    def get_ngw_verson(self):
        return self.__conn.get_ngw_components()
