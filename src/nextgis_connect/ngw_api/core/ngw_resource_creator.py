"""
/***************************************************************************
    NextGIS WEB API
                              -------------------
        begin                : 2014-11-19
        git sha              : $Format:%H$
        copyright            : (C) 2014 by NextGIS
        email                : info@nextgis.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from typing import Any, Dict, Iterable

from nextgis_connect.settings import NgConnectSettings

from .ngw_group_resource import NGWGroupResource
from .ngw_ogcf_service import NGWOgcfService
from .ngw_raster_layer import NGWRasterLayer
from .ngw_resource import NGWResource
from .ngw_vector_layer import NGWVectorLayer
from .ngw_wfs_service import NGWWfsService


class ResourceCreator:
    @staticmethod
    def create_group(parent_ngw_resource, new_group_name):
        connection = parent_ngw_resource.res_factory.connection
        url = parent_ngw_resource.get_api_collection_url()

        params = dict(
            resource=dict(
                cls=NGWGroupResource.type_id,
                parent=dict(id=parent_ngw_resource.resource_id),
                display_name=new_group_name,
            )
        )

        result = connection.post(url, params=params)

        ngw_resource = NGWGroupResource(
            parent_ngw_resource.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
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
    def create_vector_layer(
        parent_ngw_resource,
        filename,
        layer_name,
        old_fid_name,
        upload_callback,
        create_callback,
    ) -> NGWVectorLayer:
        connection = parent_ngw_resource.res_factory.connection

        # Use tus uploading for files by default.
        # vector_file_desc = connection.upload_file(filename, upload_callback)
        vector_file_desc = connection.tus_upload_file(
            filename, upload_callback
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
        if NgConnectSettings().upload_vector_with_versioning:
            params["feature_layer"] = dict(versioning=dict(enabled=True))

        create_callback()  # show "Create" status

        # Use "lunkwill" layer creation request (specific type of long request) by default.
        # result = connection.post(url, params=params)
        result = connection.post(url, params=params, is_lunkwill=True)

        ngw_resource = NGWResource.receive_resource_obj(
            connection, result["id"]
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
    ):
        connection = parent_ngw_resource.res_factory.connection

        # Use tus uploading for files by default.
        # raster_file_desc = connection.upload_file(filename, upload_callback)
        raster_file_desc = connection.tus_upload_file(
            filename, upload_callback
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

        create_callback()  # show "Create" status

        # Use "lunkwill" layer creation request (specific type of long request) by default.
        # result = connection.post(url, params=params)
        result = connection.post(url, params=params, is_lunkwill=True)

        ngw_resource = NGWResource.receive_resource_obj(
            connection, result["id"]
        )
        parent_ngw_resource.common.children = True

        return NGWRasterLayer(parent_ngw_resource.res_factory, ngw_resource)

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
                keyname="ngw_id_%d" % ngw_layer.resource_id,
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

        result = connection.post(url, params=params)

        ngw_resource = NGWResource(
            parent_group_resource.res_factory,
            NGWResource.receive_resource_obj(connection, result["id"]),
        )
        parent_group_resource.common.children = True

        return ngw_resource
