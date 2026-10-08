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

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, cast

from qgis.core import QgsFeedback, QgsMapLayer
from qgis.PyQt.QtCore import QCoreApplication, QObject, pyqtSignal

from nextgis_connect.legacy.ngw.core.ngw_error import NGWError
from nextgis_connect.legacy.ngw.core.ngw_group_resource import NGWGroupResource
from nextgis_connect.legacy.ngw.core.ngw_qgis_style import NGWQGISStyle
from nextgis_connect.legacy.ngw.core.ngw_raster_layer import NGWRasterLayer
from nextgis_connect.legacy.ngw.core.ngw_resource import (
    API_LAYER_EXTENT,
    NGWResource,
    NGWResourceDeletePreview,
)
from nextgis_connect.legacy.ngw.core.ngw_resource_creator import (
    ResourceCreator,
)
from nextgis_connect.legacy.ngw.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.legacy.ngw.core.ngw_vector_layer import NGWVectorLayer
from nextgis_connect.legacy.ngw.core.ngw_webmap import (
    NGWWebMap,
    NGWWebMapLayer,
    NGWWebMapRoot,
)
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    NgwServerFeature,
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw.resources.utils import generate_unique_name
from nextgis_connect.legacy.settings import NgConnectSettings
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.errors import NgConnectError
from nextgis_connect.platform.qgis.extent_calculator import ExtentCalculator

from .qt_ngw_resource_model_job_error import (
    JobError,
    JobNGWError,
    JobServerRequestError,
    NGWResourceModelJobError,
)


@dataclass(frozen=True)
class UploadedLayerResource:
    qgs_map_layer: QgsMapLayer
    ngw_resource: Union[NGWVectorLayer, NGWRasterLayer]


class NGWResourceModelJobResult:
    added_resources: List[NGWResource]
    deleted_resources: List[NGWResource]
    edited_resources: List[NGWResource]
    dangling_resources: List[NGWResource]
    found_resources: Optional[List[int]]
    not_permitted_resources: List[int]
    resource_delete_preview: Optional[NGWResourceDeletePreview]
    uploaded_layer_resources: List[UploadedLayerResource]
    main_resource_id: int

    def __init__(self):
        self.added_resources = []
        self.deleted_resources = []
        self.edited_resources = []
        self.dangling_resources = []
        self.found_resources = None
        self.not_permitted_resources = []
        self.resource_delete_preview = None
        self.uploaded_layer_resources = []

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

    def putUploadedLayerResource(
        self,
        qgs_map_layer: QgsMapLayer,
        ngw_resource: Union[NGWVectorLayer, NGWRasterLayer],
    ) -> None:
        self.uploaded_layer_resources.append(
            UploadedLayerResource(qgs_map_layer, ngw_resource)
        )

    def clear(self) -> None:
        self.added_resources = []
        self.deleted_resources = []
        self.edited_resources = []
        self.dangling_resources = []
        self.found_resources = None
        self.not_permitted_resources = []
        self.resource_delete_preview = None
        self.uploaded_layer_resources = []
        self.main_resource_id = -1

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
        self._feedback: Optional[QgsFeedback] = None

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

    def webmap_extent_from_ngw_resource(
        self,
        ngw_resource: NGWResource,
    ) -> Optional[Dict[str, float]]:
        try:
            response = ngw_resource.connection.get(
                API_LAYER_EXTENT(ngw_resource.resource_id)
            )
        except Exception:
            logger.exception(
                f"Could not fetch extent for NGW resource "
                f"{ngw_resource.resource_id}"
            )
            return None

        extent = ExtentCalculator.from_ngw_extent_dict(response)
        if extent is None:
            return None

        try:
            return ExtentCalculator.to_webmap_extent(extent)
        except ValueError:
            logger.exception(
                f"Could not convert extent for NGW resource "
                f"{ngw_resource.resource_id}"
            )
            return None

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

    def putUploadedLayerResourceToResult(
        self,
        qgs_map_layer: QgsMapLayer,
        ngw_resource: Union[NGWVectorLayer, NGWRasterLayer],
    ) -> None:
        self.result.putUploadedLayerResource(qgs_map_layer, ngw_resource)

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
                # fmt: off
                self.errorOccurred.emit(
                    JobServerRequestError(
                        QCoreApplication.translate(
                            "NGWResourceModelJob", "Bad http comunication."
                        )
                        + str(error),
                        error.url,
                        error.user_msg,
                        error.need_reconnect,
                    )
                )
                # fmt: on

            elif error.type == NGWError.TypeNGWUnexpectedAnswer:
                # fmt: off
                self.errorOccurred.emit(
                    JobNGWError(
                        QCoreApplication.translate(
                            "NGWResourceModelJob", "Can't parse server answer"
                        ),
                        error.url,
                    )
                )
                # fmt: on

            else:
                # fmt: off
                self.errorOccurred.emit(
                    JobServerRequestError(
                        QCoreApplication.translate(
                            "NGWResourceModelJob",
                            "Something wrong with request to server"
                        ),
                        error.url,
                    )
                )
                # fmt: on

        except (NGWResourceModelJobError, NgConnectError) as error:
            self.errorOccurred.emit(error)

        except Exception as error:
            error = NgConnectError(str(error))
            error.__cause__ = error
            self.errorOccurred.emit(error)

        self.dataReceived.emit(self.result)
        self.finished.emit()

    def cancel(self) -> None:
        if self._feedback is None:
            return

        self._feedback.cancel()

    def _is_canceled(self) -> bool:
        return self._feedback is not None and self._feedback.isCanceled()

    def _raise_if_canceled(self) -> None:
        if not self._is_canceled():
            return

        raise NgConnectError("Request was canceled")

    def _do(self):
        pass


class NGWRootResourcesLoader(NGWResourceModelJob):
    ngw_connection: QgsNgwConnection

    def __init__(self, ngw_connection: QgsNgwConnection):
        super().__init__()
        self.ngw_connection = ngw_connection
        self._feedback = QgsFeedback()

    def _do(self):
        rsc_factory = NGWResourceFactory(self.ngw_connection)

        ngw_root_resource = rsc_factory.get_root_resource(
            feedback=self._feedback
        )
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
        self._feedback = QgsFeedback()
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
        try:
            self._raise_if_canceled()
            for ngw_resource in self.ngw_resources:
                self.__get_children(ngw_resource)

            for ngw_resource in self.dangling_resources:
                self.__get_children(ngw_resource, dangling=True)
            self._raise_if_canceled()
        except Exception:
            if self._is_canceled():
                self.result.clear()
            raise

    def __get_children(
        self, ngw_resource: NGWResource, dangling: bool = False
    ):
        self._raise_if_canceled()
        ngw_resource_children = ngw_resource.get_children(
            feedback=self._feedback
        )
        self._raise_if_canceled()
        for ngw_resource_child in ngw_resource_children:
            self._raise_if_canceled()
            if dangling:
                self.result.dangling_resources.append(ngw_resource_child)
            else:
                self.putAddedResourceToResult(ngw_resource_child)

            if self.recursive and isinstance(
                ngw_resource_child, NGWGroupResource
            ):
                self.__get_children(ngw_resource_child, dangling=dangling)
        self._raise_if_canceled()


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


class NGWResourceBatchDelete(NGWResourceModelJob):
    def __init__(self, ngw_resources: List[NGWResource]) -> None:
        super().__init__()
        self.ngw_resources = ngw_resources

    def _do(self) -> None:
        deleted_resources = NGWResource.delete_resources(self.ngw_resources)
        for ngw_resource in deleted_resources:
            self.putDeletedResourceToResult(ngw_resource)


class NGWResourceDeletePreviewLoader(NGWResourceModelJob):
    def __init__(self, ngw_resources: List[NGWResource]) -> None:
        super().__init__()
        self._feedback = QgsFeedback()
        self.ngw_resources = ngw_resources

    def _do(self) -> None:
        self.result.resource_delete_preview = (
            NGWResource.simulate_delete_resources(
                self.ngw_resources,
                feedback=self._feedback,
            )
        )


class NGWCreateVectorLayer(NGWResourceModelJob):
    _NO_GEOMETRY_TYPES = frozenset(
        {
            "NONE",
            "NOGEOMETRY",
            "NO_GEOMETRY",
            "NO GEOMETRY",
        }
    )

    def __init__(
        self,
        parent_resource: NGWGroupResource,
        vector_layer: Dict[str, Any],
    ):
        super().__init__()
        self.parent_resource = parent_resource
        self.vector_layer = vector_layer

    def _do(self):
        self._ensure_no_geometry_versioning_supported()

        vector_resource = ResourceCreator.create_empty_vector_layer(
            self.parent_resource, self.vector_layer
        )
        style_resource = ResourceCreator.create_default_vector_style(
            vector_resource
        )

        self.putAddedResourceToResult(vector_resource, is_main=True)
        self.putAddedResourceToResult(style_resource)
        self.parent_resource.update()

    def _ensure_no_geometry_versioning_supported(self) -> None:
        if not self._is_no_geometry_versioning_requested():
            return

        required_feature = NgwServerFeature.NO_GEOMETRY_LAYER_VERSIONING
        if self.parent_resource.connection.has_support_for_feature(
            required_feature
        ):
            return

        required_version = required_feature.required_version
        raise JobError(
            "Vector layer without geometry and with feature versioning "
            f"requires NextGIS Web {required_version} or newer"
        )

    def _is_no_geometry_versioning_requested(self) -> bool:
        vector_layer = self.vector_layer.get(NGWVectorLayer.type_id, {})
        geometry_type = str(vector_layer.get("geometry_type", "")).upper()
        if geometry_type not in self._NO_GEOMETRY_TYPES:
            return False

        feature_layer = self.vector_layer.get("feature_layer", {})
        versioning = feature_layer.get("versioning", {})
        return versioning.get("enabled") is True


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
            bbox=self.webmap_extent_from_ngw_resource(ngw_layer),
        )

        self.putAddedResourceToResult(ngw_resource, is_main=True)


class NGWMoveResource(NGWResourceModelJob):
    def __init__(self, resource: NGWResource, parent: NGWResource) -> None:
        super().__init__()
        self.resource = deepcopy(resource)
        self.parent_resource = deepcopy(parent)

    def _do(self):
        self.resource.move_to(self.parent_resource)
        self.putEditedResourceToResult(self.resource, is_main=True)


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
        self._feedback = QgsFeedback()
        if isinstance(ngw_resources, list):
            self.ngw_resources = ngw_resources
        else:
            self.ngw_resources = [ngw_resources]
            self.result.main_resource_id = ngw_resources.resource_id

    def _do(self):
        total = len(self.ngw_resources)

        for i, style_resource in enumerate(self.ngw_resources):
            if self._feedback.isCanceled():
                raise NgConnectError("Request was canceled")

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
