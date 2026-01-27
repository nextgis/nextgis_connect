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

from copy import deepcopy
from typing import Any, Dict, List, Optional, Union, cast

from qgis.PyQt.QtCore import QObject, pyqtSignal

from nextgis_connect.exceptions import NgConnectError
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core.ngw_error import NGWError
from nextgis_connect.ngw_api.core.ngw_group_resource import NGWGroupResource
from nextgis_connect.ngw_api.core.ngw_qgis_style import NGWQGISStyle
from nextgis_connect.ngw_api.core.ngw_raster_layer import NGWRasterLayer
from nextgis_connect.ngw_api.core.ngw_resource import NGWResource
from nextgis_connect.ngw_api.core.ngw_resource_creator import ResourceCreator
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.ngw_api.core.ngw_webmap import (
    NGWWebMap,
    NGWWebMapLayer,
    NGWWebMapRoot,
)
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.resources.utils import generate_unique_name
from nextgis_connect.settings import NgConnectSettings

from .qt_ngw_resource_model_job_error import (
    JobNGWError,
    JobServerRequestError,
    NGWResourceModelJobError,
)


class NGWResourceModelJobResult:
    added_resources: List[NGWResource]
    deleted_resources: List[NGWResource]
    edited_resources: List[NGWResource]
    dangling_resources: List[NGWResource]
    found_resources: Optional[List[int]]
    not_permitted_resources: List[int]
    main_resource_id: int

    def __init__(self):
        self.added_resources = []
        self.deleted_resources = []
        self.edited_resources = []
        self.dangling_resources = []
        self.found_resources = None
        self.not_permitted_resources = []

        self.main_resource_id = -1

    def putAddedResource(
        self, ngw_resource: NGWResource, is_main: bool = False
    ) -> None:
        self.added_resources.append(ngw_resource)
        if is_main:
            self.main_resource_id = ngw_resource.resource_id

    def putEditedResource(
        self, ngw_resource: NGWResource, is_main: bool = False
    ) -> None:
        self.edited_resources.append(ngw_resource)
        if is_main:
            self.main_resource_id = ngw_resource.resource_id

    def putDeletedResource(self, ngw_resource: NGWResource) -> None:
        self.deleted_resources.append(ngw_resource)

    def is_empty(self):
        return (
            len(self.added_resources) == 0
            and len(self.edited_resources) == 0
            and len(self.deleted_resources) == 0
        )


class NGWResourceModelJob(QObject):
    started = pyqtSignal()
    statusChanged = pyqtSignal(str)
    warningOccurred = pyqtSignal(object)
    errorOccurred = pyqtSignal(object)
    dataReceived = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.id = self.__class__.__name__

        self.result = NGWResourceModelJobResult()

    def unique_resource_name(
        self, resource_name: str, ngw_group: NGWGroupResource
    ) -> str:
        children_names = [
            children.display_name for children in ngw_group.get_children()
        ]
        unique_resource_name = generate_unique_name(
            resource_name, children_names
        )
        return unique_resource_name

    def getResourcesChain2Root(self, ngw_resource):
        ngw_resource.update()
        chain = [ngw_resource]
        parent = ngw_resource.get_parent()
        while parent is not None:
            parent.update()
            chain.insert(0, parent)
            parent = parent.get_parent()

        return chain

    def putAddedResourceToResult(
        self, ngw_resource: NGWResource, is_main: bool = False
    ):
        self.result.putAddedResource(ngw_resource, is_main)

    def putEditedResourceToResult(
        self, ngw_resource: NGWResource, is_main: bool = False
    ):
        self.result.putEditedResource(ngw_resource, is_main)

    def putDeletedResourceToResult(self, ngw_resource: NGWResource):
        self.result.putDeletedResource(ngw_resource)

    def run(self):
        if NgConnectSettings().is_developer_mode:
            try:
                import debugpy  # noqa: T100
            except ImportError:
                logger.warning(
                    "To support threads debugging you need to install debugpy"
                )
            else:
                if debugpy.is_client_connected():
                    debugpy.debug_this_thread()

        self.started.emit()
        try:
            self._do()
        except NGWError as error:
            if error.type == NGWError.TypeRequestError:
                self.errorOccurred.emit(
                    JobServerRequestError(
                        self.tr("Bad http comunication.") + str(error),
                        error.url,
                        error.user_msg,
                        error.need_reconnect,
                    )
                )

            elif error.type == NGWError.TypeNGWUnexpectedAnswer:
                self.errorOccurred.emit(
                    JobNGWError(
                        self.tr("Can't parse server answer"), error.url
                    )
                )

            else:
                self.errorOccurred.emit(
                    JobServerRequestError(
                        self.tr("Something wrong with request to server"),
                        error.url,
                    )
                )

        except (NGWResourceModelJobError, NgConnectError) as error:
            self.errorOccurred.emit(error)

        except Exception as error:
            error = NgConnectError(str(error))
            error.__cause__ = error
            self.errorOccurred.emit(error)

        self.dataReceived.emit(self.result)
        self.finished.emit()

    def _do(self):
        pass


class NGWRootResourcesLoader(NGWResourceModelJob):
    ngw_connection: QgsNgwConnection

    def __init__(self, ngw_connection: QgsNgwConnection):
        super().__init__()
        self.ngw_connection = ngw_connection

    def _do(self):
        rsc_factory = NGWResourceFactory(self.ngw_connection)

        ngw_root_resource = rsc_factory.get_root_resource()
        self.putAddedResourceToResult(ngw_root_resource, is_main=True)


class NGWResourceUpdater(NGWResourceModelJob):
    def __init__(
        self,
        ngw_resources: Union[NGWResource, List[NGWResource]],
        dangling_resources: Union[NGWResource, List[NGWResource]],
        *,
        recursive: bool = False,
    ) -> None:
        super().__init__()
        ngw_resources = deepcopy(ngw_resources)
        if isinstance(ngw_resources, list):
            self.ngw_resources = ngw_resources
        else:
            self.ngw_resources = [ngw_resources]
            self.result.main_resource_id = ngw_resources.resource_id

        if isinstance(dangling_resources, list):
            self.dangling_resources = dangling_resources
        else:
            self.dangling_resources = [dangling_resources]
            if self.result.main_resource_id is None:
                self.result.main_resource_id = dangling_resources.resource_id

        self.recursive = recursive

    def _do(self):
        for ngw_resource in self.ngw_resources:
            self.__get_children(ngw_resource)

        for ngw_resource in self.dangling_resources:
            self.__get_children(ngw_resource, dangling=True)

    def __get_children(
        self, ngw_resource: NGWResource, dangling: bool = False
    ):
        ngw_resource_children = ngw_resource.get_children()
        for ngw_resource_child in ngw_resource_children:
            if dangling:
                self.result.dangling_resources.append(ngw_resource_child)
            else:
                self.putAddedResourceToResult(ngw_resource_child)

            if self.recursive and isinstance(
                ngw_resource_child, NGWGroupResource
            ):
                self.__get_children(ngw_resource_child, dangling=dangling)


class NGWGroupCreater(NGWResourceModelJob):
    new_group_name: str

    def __init__(self, new_group_name, ngw_resource_parent):
        super().__init__()
        self.new_group_name = new_group_name
        self.ngw_resource_parent = ngw_resource_parent

    def _do(self):
        new_group_name = self.unique_resource_name(
            self.new_group_name, self.ngw_resource_parent
        )

        ngw_group_resource = ResourceCreator.create_group(
            self.ngw_resource_parent, new_group_name
        )

        self.putAddedResourceToResult(ngw_group_resource, is_main=True)
        self.ngw_resource_parent.update()


class NGWResourceDelete(NGWResourceModelJob):
    def __init__(self, ngw_resource):
        NGWResourceModelJob.__init__(self)
        self.ngw_resource = ngw_resource

    def _do(self):
        NGWResource.delete_resource(self.ngw_resource)

        self.putDeletedResourceToResult(self.ngw_resource)


class NGWCreateVectorLayer(NGWResourceModelJob):
    def __init__(
        self,
        parent_resource: NGWGroupResource,
        vector_layer: Dict[str, Any],
    ):
        super().__init__()
        self.parent_resource = parent_resource
        self.vector_layer = vector_layer

    def _do(self):
        vector_resource = ResourceCreator.create_empty_vector_layer(
            self.parent_resource, self.vector_layer
        )

        self.putAddedResourceToResult(vector_resource, is_main=True)
        self.parent_resource.update()


class NGWCreateWfsOrOgcfService(NGWResourceModelJob):
    def __init__(
        self,
        service_type: str,
        ngw_vector_layer: NGWVectorLayer,
        ngw_group_resource: NGWGroupResource,
        max_features: int,
    ):
        super().__init__()
        assert service_type in ("WFS", "OGC API - Features")
        self.service_type = service_type
        self.ngw_vector_layer = ngw_vector_layer
        self.ngw_group_resource = ngw_group_resource
        self.ret_obj_num = max_features

    def _do(self):
        service_name: str = self.ngw_vector_layer.display_name
        service_name += f" — {self.service_type} service"
        ngw_wfs_service_name = self.unique_resource_name(
            service_name, self.ngw_group_resource
        )

        service_resource = ResourceCreator.create_wfs_or_ogcf_service(
            self.service_type,
            ngw_wfs_service_name,
            self.ngw_group_resource,
            [self.ngw_vector_layer],
            self.ret_obj_num,
        )

        self.putAddedResourceToResult(service_resource, is_main=True)


class NGWCreateWfsService(NGWCreateWfsOrOgcfService):
    def __init__(
        self,
        ngw_vector_layer: NGWVectorLayer,
        ngw_group_resource: NGWGroupResource,
        max_features: int,
    ):
        super().__init__(
            "WFS", ngw_vector_layer, ngw_group_resource, max_features
        )


class NGWCreateOgcfService(NGWCreateWfsOrOgcfService):
    def __init__(
        self,
        ngw_vector_layer: NGWVectorLayer,
        ngw_group_resource: NGWGroupResource,
        max_features: int,
    ):
        super().__init__(
            "OGC API - Features",
            ngw_vector_layer,
            ngw_group_resource,
            max_features,
        )


class NGWCreateMapForStyle(NGWResourceModelJob):
    def __init__(self, ngw_style):
        NGWResourceModelJob.__init__(self)
        self.ngw_style = ngw_style

    def _do(self):
        ngw_layer: Union[NGWVectorLayer, NGWRasterLayer] = (
            self.ngw_style.get_parent()
        )
        ngw_group = cast(NGWGroupResource, ngw_layer.get_parent())

        ngw_map_name = self.unique_resource_name(
            self.ngw_style.display_name + "-map", ngw_group
        )

        ngw_webmap_root_group = NGWWebMapRoot()
        ngw_webmap_root_group.appendChild(
            NGWWebMapLayer(
                self.ngw_style.resource_id,
                ngw_layer.display_name,
                is_visible=True,
                transparency=None,
                legend=True,
            )
        )

        ngw_resource = NGWWebMap.create_in_group(
            ngw_map_name,
            ngw_group,
            [item.toDict() for item in ngw_webmap_root_group.children],
            bbox=ngw_layer.extent(),
        )

        self.putAddedResourceToResult(ngw_resource, is_main=True)


class NGWRenameResource(NGWResourceModelJob):
    def __init__(self, ngw_resource, new_name):
        NGWResourceModelJob.__init__(self)
        self.ngw_resource = ngw_resource
        self.new_name = new_name

    def _do(self):
        self.ngw_resource.change_name(self.new_name)

        # self.putAddedResourceToResult(self.ngw_resource, is_main=True)
        self.putEditedResourceToResult(self.ngw_resource, is_main=True)


class NgwStylesDownloader(NGWResourceModelJob):
    def __init__(
        self,
        ngw_resources: Union[NGWQGISStyle, List[NGWQGISStyle]],
    ) -> None:
        super().__init__()
        if isinstance(ngw_resources, list):
            self.ngw_resources = ngw_resources
        else:
            self.ngw_resources = [ngw_resources]
            self.result.main_resource_id = ngw_resources.resource_id

    def _do(self):
        total = len(self.ngw_resources)

        for i, style_resource in enumerate(self.ngw_resources):
            name = style_resource.display_name
            progress = "" if total == "1" else f"\n({i + 1}/{total})"
            self.statusChanged.emit(
                self.tr('Downloading style "{name}"').format(name=name)
                + progress
            )

            style_resource.populate_qml()


class NGWMissingResourceUpdater(NGWResourceUpdater):
    # Empty class for blocking interface
    pass
