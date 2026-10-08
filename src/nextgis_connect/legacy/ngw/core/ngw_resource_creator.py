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

import configparser
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from qgis.core import QgsApplication, QgsFeedback, QgsMapLayer

from nextgis_connect.legacy.ngw.qgis.layer_source_sanitizer import (
    QgisLayerSourceSanitizer,
)
from nextgis_connect.legacy.settings import NgConnectSettings

from .ngw_group_resource import NGWGroupResource
from .ngw_ogcf_service import NGWOgcfService
from .ngw_qgis_style import NGWQGISVectorStyle
from .ngw_raster_layer import NGWRasterLayer
from .ngw_resource import NGWResource
from .ngw_tileset import NGWTileset
from .ngw_vector_layer import NGWVectorLayer
from .ngw_wfs_service import NGWWfsService


class ResourceCreator:
    @staticmethod
    def resource_created_by_metadata() -> Dict[str, str]:
        if not NgConnectSettings().add_resource_creation_metadata:
            return {}

        return {
            "created_by": (
                f"NextGIS-Connect/{ResourceCreator._plugin_version()}"
            )
        }

    @staticmethod
    def resource_creation_metadata(layer: QgsMapLayer) -> Dict[str, str]:
        metadata = ResourceCreator.resource_created_by_metadata()
        if len(metadata) == 0:
            return metadata

        source = QgisLayerSourceSanitizer().sanitize(layer)
        if source is not None:
            metadata["source"] = source
        return metadata

    @staticmethod
    def _add_metadata(
        params: Dict[str, Any],
        metadata: Optional[Dict[str, str]],
    ) -> None:
        if metadata is None or len(metadata) == 0:
            return

        params["resmeta"] = {"items": metadata}

    @staticmethod
    def _plugin_version() -> str:
        metadata_path = Path(__file__).resolve().parents[3] / "metadata.txt"
        metadata = configparser.ConfigParser()
        metadata.read(str(metadata_path), encoding="utf-8")
        return metadata.get("general", "version")

    @staticmethod
    def create_group(
        parent_ngw_resource,
        new_group_name,
        feedback: Optional[QgsFeedback] = None,
    ):
        connection = parent_ngw_resource.res_factory.connection
        url = parent_ngw_resource.get_api_collection_url()

        params = dict(
            resource=dict(
                cls=NGWGroupResource.type_id,
                parent=dict(id=parent_ngw_resource.resource_id),
                display_name=new_group_name,
            )
        )

        result = connection.post(url, params=params, feedback=feedback)

        ngw_resource = NGWGroupResource(
            parent_ngw_resource.res_factory,
            NGWResource.receive_resource_obj(
                connection,
                result["id"],
                feedback=feedback,
            ),
        )
        parent_ngw_resource.common.children = True

        return ngw_resource

    @staticmethod
    def create_empty_vector_layer(
        parent_ngw_resource,
        vector_layer: Dict[str, Any],
    ) -> NGWVectorLayer:
        connection = parent_ngw_resource.res_factory.connection

        url = parent_ngw_resource.get_api_collection_url()
        result = connection.post(url, params=vector_layer, is_lunkwill=True)

        ngw_resource = NGWResource.receive_resource_obj(
            connection, result["id"]
        )

        parent_ngw_resource.common.children = True
        return NGWVectorLayer(parent_ngw_resource.res_factory, ngw_resource)

    @staticmethod
    def create_default_vector_style(
        ngw_vector_layer: NGWVectorLayer,
        feedback: Optional[QgsFeedback] = None,
    ) -> NGWQGISVectorStyle:
        connection = ngw_vector_layer.res_factory.connection
        # fmt: off
        display_name = QgsApplication.translate(
            "ResourceCreator",
            "Default style"
        )
        # fmt: on
        url = ngw_vector_layer.get_api_collection_url()
        params = dict(
            resource=dict(
                cls=NGWQGISVectorStyle.type_id,
                parent=dict(id=ngw_vector_layer.resource_id),
                display_name=display_name,
            ),
        )

        result = connection.post(url, params=params, feedback=feedback)
        ngw_resource = NGWResource.receive_resource_obj(
            connection,
            result["id"],
            feedback=feedback,
        )
        ngw_vector_layer.common.children = True
        return NGWQGISVectorStyle(
            ngw_vector_layer.res_factory,
            ngw_resource,
        )

    @staticmethod
    def create_vector_layer(
        parent_ngw_resource,
        filename,
        layer_name,
        old_fid_name,
        upload_callback,
        create_callback,
        metadata: Optional[Dict[str, str]] = None,
        feedback: Optional[QgsFeedback] = None,
    ) -> NGWVectorLayer:
        connection = parent_ngw_resource.res_factory.connection

        # Use tus uploading for files by default.
        # vector_file_desc = connection.upload_file(filename, upload_callback)
        vector_file_desc = connection.tus_upload_file(
            filename, upload_callback, feedback=feedback
        )
        fid_fields = ["ngw_id", "id"]
        if old_fid_name is not None:
            fid_fields.append(old_fid_name)

        url = parent_ngw_resource.get_api_collection_url()
        params = dict(
            resource=dict(
                cls=NGWVectorLayer.type_id,
                parent=dict(id=parent_ngw_resource.resource_id),
                display_name=layer_name,
            ),
            vector_layer=dict(
                srs=dict(id=3857),
                source=vector_file_desc,
                fix_errors="LOSSY",
                skip_errors=True,
                fid_source="AUTO",
                fid_field=",".join(fid_fields),
            ),
        )
        ResourceCreator._add_metadata(params, metadata)
        create_callback()  # show "Create" status

        # Use "lunkwill" layer creation request (specific type of long request) by default.
        # result = connection.post(url, params=params)
        result = connection.post(
            url, params=params, is_lunkwill=True, feedback=feedback
        )

        ngw_resource = NGWResource.receive_resource_obj(
            connection,
            result["id"],
            feedback=feedback,
        )

        parent_ngw_resource.common.children = True

        return NGWVectorLayer(parent_ngw_resource.res_factory, ngw_resource)

    @staticmethod
    def create_raster_layer(
        parent_ngw_resource,
        filename,
        layer_name,
        upload_as_cog,
        upload_callback,
        create_callback,
        metadata: Optional[Dict[str, str]] = None,
        feedback: Optional[QgsFeedback] = None,
    ):
        connection = parent_ngw_resource.res_factory.connection

        # Use tus uploading for files by default.
        # raster_file_desc = connection.upload_file(filename, upload_callback)
        raster_file_desc = connection.tus_upload_file(
            filename, upload_callback, feedback=feedback
        )

        url = parent_ngw_resource.get_api_collection_url()
        params = dict(
            resource=dict(
                cls=NGWRasterLayer.type_id,
                parent=dict(id=parent_ngw_resource.resource_id),
                display_name=layer_name,
            ),
            raster_layer=dict(
                srs=dict(id=3857), source=raster_file_desc, cog=upload_as_cog
            ),
        )
        ResourceCreator._add_metadata(params, metadata)

        create_callback()  # show "Create" status

        # Use "lunkwill" layer creation request (specific type of long request) by default.
        # result = connection.post(url, params=params)
        result = connection.post(
            url, params=params, is_lunkwill=True, feedback=feedback
        )

        ngw_resource = NGWResource.receive_resource_obj(
            connection,
            result["id"],
            feedback=feedback,
        )
        parent_ngw_resource.common.children = True

        return NGWRasterLayer(parent_ngw_resource.res_factory, ngw_resource)

    @staticmethod
    def create_tileset(
        parent_ngw_resource,
        filename,
        layer_name,
        upload_callback,
        create_callback,
        metadata: Optional[Dict[str, str]] = None,
        feedback: Optional[QgsFeedback] = None,
    ) -> NGWTileset:
        connection = parent_ngw_resource.res_factory.connection

        tileset_file_desc = connection.tus_upload_file(
            filename,
            upload_callback,
            feedback=feedback,
        )

        url = parent_ngw_resource.get_api_collection_url()
        params = dict(
            resource=dict(
                cls=NGWTileset.type_id,
                parent=dict(id=parent_ngw_resource.resource_id),
                display_name=layer_name,
            ),
            tileset=dict(
                srs=dict(id=3857),
                source=tileset_file_desc,
            ),
        )
        ResourceCreator._add_metadata(params, metadata)

        create_callback()

        result = connection.post(
            url,
            params=params,
            is_lunkwill=True,
            feedback=feedback,
        )

        ngw_resource = NGWResource.receive_resource_obj(
            connection,
            result["id"],
            feedback=feedback,
        )
        parent_ngw_resource.common.children = True

        return NGWTileset(parent_ngw_resource.res_factory, ngw_resource)

    @staticmethod
    def create_wfs_or_ogcf_service(
        service_type: str,
        service_name: str,
        ngw_group_resource: NGWGroupResource,
        ngw_layers: Iterable[NGWVectorLayer],
        max_features: int = 1000,
    ):
        assert service_type in ("WFS", "OGC API - Features")

        connection = ngw_group_resource.res_factory.connection
        url = ngw_group_resource.get_api_collection_url()

        params_layers = []
        for ngw_layer in ngw_layers:
            params_layer = dict(
                display_name=ngw_layer.display_name,
                keyname=f"ngw_id_{ngw_layer.resource_id:d}",
                resource_id=ngw_layer.resource_id,
                maxfeatures=max_features,
            )
            params_layers.append(params_layer)

        ngw_type = NGWWfsService if service_type == "WFS" else NGWOgcfService

        params: Dict[str, Any] = dict(
            resource=dict(
                cls=ngw_type.type_id,
                display_name=service_name,
                parent=dict(id=ngw_group_resource.resource_id),
            )
        )
        params_key = "layers" if service_type == "WFS" else "collections"
        params[ngw_type.type_id] = {params_key: params_layers}

        result = connection.post(url, params=params)

        ngw_resource = ngw_type(
            ngw_group_resource.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )
        ngw_group_resource.common.children = True

        return ngw_resource

    @staticmethod
    def create_lookup_table(
        name: str,
        items: Dict[str, str],
        parent_group_resource: NGWGroupResource,
        metadata: Optional[Dict[str, str]] = None,
    ) -> NGWResource:
        connection = parent_group_resource.res_factory.connection
        url = parent_group_resource.get_api_collection_url()

        params = dict(
            resource=dict(
                cls="lookup_table",
                display_name=name,
                parent=dict(id=parent_group_resource.resource_id),
            ),
            lookup_table=dict(items=items),
        )
        ResourceCreator._add_metadata(params, metadata)

        result = connection.post(url, params=params)

        ngw_resource = NGWResource(
            parent_group_resource.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )
        parent_group_resource.common.children = True

        return ngw_resource
