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

import urllib.parse
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple, Union, cast

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeRegistryBridge,
    QgsMapLayer,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QModelIndex, QObject
from qgis.PyQt.QtGui import QColor
from qgis.utils import iface

from nextgis_connect.features.resource_browser.application import (
    ResourceAddingErrorContext,
    ResourceBatchImportInteraction,
    ResourceImportCancelledError,
)
from nextgis_connect.features.resource_browser.domain import (
    ResourceBatchImportResult,
    ResourceBatchImportStatus,
    ResourceImportWarning,
)
from nextgis_connect.features.resource_browser.infrastructure.legacy_resource_adapter import (
    SERVICE_LAYER_RESOURCE_TYPES,
    TMS_LAYER_RESOURCE_TYPES,
    is_layer,
    is_service,
    is_style,
    is_webmap,
)
from nextgis_connect.features.resource_browser.infrastructure.qgis_resource_batch_extent import (
    QgisResourceBatchExtentCoordinator,
    ResourceExtentSubjectFactory,
)
from nextgis_connect.features.resource_browser.infrastructure.qgis_resource_batch_layer import (
    BatchLayerId,
    QgisBatchLayerFactory,
    QgisLayerCreationParameters,
)
from nextgis_connect.features.resource_browser.infrastructure.qgis_resource_batch_layer_metadata import (
    QgisVectorLayerMetadataApplicator,
)
from nextgis_connect.features.resource_browser.infrastructure.qgis_resource_batch_style import (
    QgisResourceBatchStyleApplicator,
)
from nextgis_connect.features.resource_browser.infrastructure.resource_dependency_analyzer import (
    ResourceDependencyAnalyzer,
)
from nextgis_connect.legacy.detached_editing.container.cache_lifecycle import (
    CachedDetachedContainerLifecycle,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.utils import (
    detached_layer_uri,
)
from nextgis_connect.legacy.ngw.core import (
    NGWGroupResource,
    NGWOgcfService,
    NGWPostgisLayer,
    NGWRasterLayer,
    NGWRasterMosaic,
    NGWResource,
    NGWVectorLayer,
    NGWWebMap,
    NGWWfsLayer,
    NGWWfsService,
    NGWWmsLayer,
    NGWWmsService,
)
from nextgis_connect.legacy.ngw.core.ngw_abstract_vector_resource import (
    NGWAbstractVectorResource,
)
from nextgis_connect.legacy.ngw.core.ngw_resource import RESOURCE_URL
from nextgis_connect.legacy.ngw.core.ngw_webmap import (
    NGWWebMapGroup,
    NGWWebMapLayer,
)
from nextgis_connect.legacy.ngw_connection import NgwConnectionsManager
from nextgis_connect.legacy.tree_widget.item import QNGWResourceItem
from nextgis_connect.legacy.tree_widget.model import QNGWResourceTreeModel
from nextgis_connect.platform.logging import escape_html, logger
from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgConnectError,
    NgConnectWarning,
    NgwError,
    ResourcePermissionError,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface

if TYPE_CHECKING:
    assert isinstance(iface, QgisInterface)

InsertionId = BatchLayerId
LayerParams = Tuple[str, str, str]

InsertionPoint = QgsLayerTreeRegistryBridge.InsertionPoint


class QgisResourceBatchImporter(QObject):
    __project: QgsProject

    __model: QNGWResourceTreeModel
    __indices: List[QModelIndex]

    __is_mass_adding: bool

    __layers_params: Dict[InsertionId, QgisLayerCreationParameters]
    __layers: Dict[InsertionId, QgsMapLayer]
    __default_styles: Dict[QModelIndex, int]
    __skipped_resources: Set[InsertionId]
    __insertion_stack: List[InsertionPoint]
    __warnings: List[NgConnectWarning]
    __extent_coordinator: QgisResourceBatchExtentCoordinator
    __adding_error_contexts: Dict[InsertionId, ResourceAddingErrorContext]
    __last_status: ResourceBatchImportStatus
    __vector_layer_metadata_applicator: QgisVectorLayerMetadataApplicator
    __interaction: ResourceBatchImportInteraction
    __dependency_analyzer: ResourceDependencyAnalyzer
    __style_applicator: QgisResourceBatchStyleApplicator
    __layer_factory: Optional[QgisBatchLayerFactory]
    __cancel_requested: bool

    def __init__(
        self,
        model: QNGWResourceTreeModel,
        indices: Union[QModelIndex, List[QModelIndex]],
        insertion_point: InsertionPoint,
        interaction: ResourceBatchImportInteraction,
    ) -> None:
        super().__init__(model)
        self.__project = cast(QgsProject, QgsProject.instance())

        self.__model = model
        self.__indices = indices if isinstance(indices, list) else [indices]
        self.__process_indexes_list()
        self.__is_mass_adding = len(self.__indices) > 1 or (
            len(self.__indices) == 1
            and not (
                is_layer(self.__indices[0]) or is_style(self.__indices[0])
            )
        )

        self.__layers = {}
        self.__layers_params = {}
        self.__default_styles = {}
        self.__skipped_resources = set()
        self.__insertion_stack = []
        self.__insertion_stack.append(insertion_point)
        self.__warnings = []
        self.__extent_coordinator = QgisResourceBatchExtentCoordinator(
            model,
            iface.mapCanvas() if iface is not None else None,
            self.__project,
        )
        self.__adding_error_contexts = {}
        self.__last_status = ResourceBatchImportStatus.FAILED
        self.__vector_layer_metadata_applicator = (
            QgisVectorLayerMetadataApplicator(model)
        )
        self.__interaction = interaction
        self.__dependency_analyzer = ResourceDependencyAnalyzer(model)
        self.__style_applicator = QgisResourceBatchStyleApplicator(model)
        self.__layer_factory = None
        self.__cancel_requested = False

    def cancel(self) -> None:
        """Request cancellation of layer preparation before project commit."""
        self.__cancel_requested = True
        if self.__layer_factory is not None:
            self.__layer_factory.cancel()

    def __raise_if_cancelled(self) -> None:
        if self.__cancel_requested:
            raise ResourceImportCancelledError

    def missing_resources(self) -> Tuple[bool, List[int]]:
        """Extract resources needed for layers to add to QGIS"""
        try:
            resource_ids = self.__dependency_analyzer.missing_resource_ids(
                self.__indices
            )
        except Exception as error:
            message = self.tr("An error occurred while fetching resources")
            ng_error = NgwError(user_message=message)
            ng_error.__cause__ = error
            NgConnectInterface.instance().notifier.display_exception(ng_error)
            return False, []

        result = list(resource_ids)
        if len(result) > 0:
            logger.debug(
                f"{len(result)} additional resources will be downloaded"
            )

        return (True, result)

    def missing_styles(self) -> Tuple[bool, List[int]]:
        try:
            style_ids = self.__dependency_analyzer.missing_style_ids(
                self.__indices
            )

        except Exception as error:
            message = self.tr("An error occurred while fetching styles")
            ng_error = NgwError(user_message=message)
            ng_error.__cause__ = error
            NgConnectInterface.instance().notifier.display_exception(ng_error)
            return False, []

        result = list(style_ids)
        if len(result) > 0:
            logger.debug(f"{len(result)} styles will be downloaded")

        return (True, result)

    @property
    def warnings(self) -> List[NgConnectWarning]:
        return self.__warnings

    def execute(self) -> ResourceBatchImportResult:
        """Run the import and return a structured application result."""
        existing_layer_ids = set(self.__project.mapLayers())
        self._run()
        added_layer_ids = tuple(
            layer_id
            for layer_id in self.__project.mapLayers()
            if layer_id not in existing_layer_ids
        )
        warnings = tuple(
            ResourceImportWarning(warning.user_message, warning.detail)
            for warning in self.__warnings
        )
        return ResourceBatchImportResult(
            self.__last_status,
            added_layer_ids,
            warnings,
        )

    def _run(self) -> None:
        indices = self.__indices

        added_layers = 0

        try:
            self.__raise_if_cancelled()
            self.__collect_layers_params()
            self.__raise_if_cancelled()
            self.__create_layers()
            self.__raise_if_cancelled()

            for index in indices:
                self.__raise_if_cancelled()
                self.__add_resource_with_error_handling(index)

            added_layers = len(self.__layers)
            self.__extent_coordinator.apply()

        except ResourceImportCancelledError:
            self.__last_status = ResourceBatchImportStatus.CANCELLED
            return

        except NgwError as error:
            self.__last_status = ResourceBatchImportStatus.FAILED
            NgConnectInterface.instance().notifier.display_exception(error)
            return

        except Exception as error:
            self.__last_status = ResourceBatchImportStatus.FAILED
            if self.__is_mass_adding:
                user_message = self.tr("Resources can't be added to the map")

            else:
                ngw_resource: NGWResource = indices[0].data(
                    QNGWResourceItem.NGWResourceRole
                )
                user_message = self.tr(
                    'Resource "{}" can\'t be added to the map'
                ).format(ngw_resource.display_name)

            ng_error = NgwError(user_message=user_message)
            ng_error.__cause__ = error

            NgConnectInterface.instance().notifier.display_exception(ng_error)
            return

        finally:
            self.__insertion_stack.clear()
            self.__layers_params.clear()
            self.__layers.clear()
            self.__adding_error_contexts.clear()
            self.__extent_coordinator.clear()

        if added_layers == 0:
            layer_label = "No layers"
        elif added_layers > 1:
            layer_label = f"{added_layers} layers"
        else:
            layer_label = "Layer"

        logger.debug(f"{layer_label} has been added to the map")

        self.__last_status = ResourceBatchImportStatus.SUCCEEDED

    def __add_resource_with_error_handling(self, index: QModelIndex) -> None:
        try:
            self.__add_resource(index)
        except ResourceImportCancelledError:
            raise
        except Exception as error:
            context = self.__adding_error_context_from_index(index)
            if self.__skip_after_adding_error(error, context):
                return
            raise

    def __add_resource(self, index: QModelIndex) -> None:
        ngw_resource: NGWResource = index.data(
            QNGWResourceItem.NGWResourceRole
        )

        if isinstance(ngw_resource, NGWGroupResource):
            self.__add_group(index)
        elif is_webmap(ngw_resource):
            self.__add_webmap(index)
        elif is_service(ngw_resource):
            self.__add_service(index)
        elif is_layer(ngw_resource):
            self.__add_layer(index)
        elif is_style(index):
            self.__add_layer_from_style(index)

    def __add_layer_from_style(self, index: QModelIndex) -> None:
        layer_node = self.__add_layer(index)
        if layer_node is None:
            return

        layer = layer_node.layer()
        style_resource: NGWResource = index.data(
            QNGWResourceItem.NGWResourceRole
        )
        layer_name = layer.name()
        style_name = style_resource.display_name
        layer.styleManager().setCurrentStyle(style_name)
        layer.setName(
            style_name
            if layer_name in style_name
            else f"{layer_name} — {style_name}"
        )

    def __add_group(self, group_index: QModelIndex) -> None:
        group_resource: NGWGroupResource = group_index.data(
            QNGWResourceItem.NGWResourceRole
        )

        self.__insert_group(group_resource.display_name)

        # Add children
        for row in range(self.__model.rowCount(group_index)):
            child_index = self.__model.index(row, 0, group_index)
            self.__add_resource_with_error_handling(child_index)

        self.__insertion_stack.pop()

    def __set_ngw_layer_properties(
        self, layer: QgsMapLayer, connection_id: str, resource_id: int
    ) -> None:
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(connection_id)
        assert connection is not None

        layer.setCustomProperty("ngw_connection_id", connection_id)
        layer.setCustomProperty("ngw_instance_id", connection.domain_uuid)
        layer.setCustomProperty("ngw_resource_id", resource_id)

    def __add_layer(self, index: QModelIndex) -> Optional[QgsLayerTreeLayer]:
        ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
        layer_resource = (
            self.__model.resource(index.parent())
            if is_style(ngw_resource)
            else ngw_resource
        )
        assert isinstance(layer_resource, NGWResource)

        if (
            index in self.__skipped_resources
            or ngw_resource.resource_id in self.__skipped_resources
            or layer_resource.resource_id in self.__skipped_resources
        ):
            return

        insertion_point = self.__insertion_stack[-1]

        if index not in self.__layers:
            logger.debug(
                f"Layer {layer_resource.resource_id} was not added to QGIS"
            )
            raise RuntimeError

        layer = self.__layers[index]

        layer.setName(layer_resource.display_name)

        # TODO: it's not obvious that default style attached to style_index
        self.__style_applicator.apply_all(
            index,
            layer,
            self.__default_styles.get(index),
        )
        if isinstance(layer_resource, NGWAbstractVectorResource):
            assert isinstance(layer, QgsVectorLayer)
            self.__vector_layer_metadata_applicator.apply(
                layer_resource,
                layer,
            )

        self.__set_ngw_layer_properties(
            layer,
            layer_resource.connection_id,
            layer_resource.resource_id,
        )

        layer_node = insertion_point.group.insertLayer(
            insertion_point.position, layer
        )
        assert layer_node is not None
        layer_node.setExpanded(not self.__is_mass_adding)
        insertion_point.position += 1
        self.__extent_coordinator.add(
            ResourceExtentSubjectFactory.from_layer(layer_resource, layer)
        )

        return layer_node

    def __add_service(self, service_index: QModelIndex) -> None:
        if service_index in self.__skipped_resources:
            return

        service_resource: Union[
            NGWWfsService, NGWOgcfService, NGWWmsService
        ] = service_index.data(QNGWResourceItem.NGWResourceRole)

        layers = [
            layer
            for layer in service_resource.layers
            if id(layer) not in self.__skipped_resources
        ]
        if len(layers) == 0:
            return

        if len(layers) == 1:
            self.__add_service_layer_with_error_handling(
                service_resource, layers[0]
            )
            return

        self.__insert_group(service_resource.display_name)

        # Add children
        for layer in layers:
            self.__add_service_layer_with_error_handling(
                service_resource, layer
            )

        self.__insertion_stack.pop()

    def __add_service_layer_with_error_handling(
        self, ngw_resource: NGWResource, service_layer
    ) -> None:
        try:
            self.__add_service_layer(ngw_resource, service_layer)
        except ResourceImportCancelledError:
            raise
        except Exception as error:
            context = self.__adding_error_context_for_service_layer(
                service_layer
            )
            if self.__skip_after_adding_error(error, context):
                return
            raise

    def __add_service_layer(
        self, ngw_resource: NGWResource, service_layer
    ) -> None:
        insertion_point = self.__insertion_stack[-1]

        if id(service_layer) not in self.__layers:
            message = (
                f'Layer "{service_layer.display_name}" was not added to QGIS'
            )
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        layer = self.__layers[id(service_layer)]
        layer.setName(service_layer.display_name)

        if isinstance(layer, QgsVectorLayer):
            layer_resource = self.__model.resource(service_layer.resource_id)
            assert isinstance(layer_resource, NGWAbstractVectorResource)
            self.__style_applicator.apply_all(layer_resource, layer)
            self.__vector_layer_metadata_applicator.apply(
                layer_resource,
                layer,
            )

        self.__set_ngw_layer_properties(
            layer,
            ngw_resource.connection_id,
            ngw_resource.resource_id,
        )

        layer_node = insertion_point.group.insertLayer(
            insertion_point.position, layer
        )
        assert layer_node is not None
        layer_node.setExpanded(False)
        insertion_point.position += 1
        extent_resource_id = getattr(service_layer, "resource_id", None)
        extent_resource = (
            self.__model.resource(extent_resource_id)
            if extent_resource_id is not None
            else None
        )
        if isinstance(extent_resource, NGWResource):
            self.__extent_coordinator.add(
                ResourceExtentSubjectFactory.from_layer(
                    extent_resource,
                    layer,
                )
            )

    def __add_webmap(self, webmap_index: QModelIndex) -> None:
        webmap_resource: NGWWebMap = webmap_index.data(
            QNGWResourceItem.NGWResourceRole
        )

        background_color = webmap_resource.basemap_background_color
        if background_color is not None and iface is not None:
            color = QColor(
                background_color
                if background_color.startswith("#")
                else f"#{background_color}"
            )
            if color.isValid():
                iface.mapCanvas().setCanvasColor(color)

        # Set project CRS if no layers added previously
        if not self.__is_mass_adding and self.__project.count() == 0:
            self.__project.setCrs(
                QgsCoordinateReferenceSystem.fromEpsgId(3857)
            )

        # Add webmap to tree
        qgs_group = self.__insert_group(webmap_resource.display_name)

        for child in webmap_resource.root.children:
            self.__add_webmap_item(webmap_resource, child)

        self.__add_webmap_basemaps(webmap_resource)

        qgs_group.setExpanded(True)

        self.__insertion_stack.pop()
        self.__extent_coordinator.add(
            ResourceExtentSubjectFactory.from_webmap(webmap_resource)
        )

    def __add_webmap_item(
        self,
        webmap: NGWWebMap,
        webmap_item: Union[NGWWebMapGroup, NGWWebMapLayer],
    ) -> None:
        try:
            if isinstance(webmap_item, NGWWebMapGroup):
                self.__add_webmap_group(webmap, webmap_item)
            elif isinstance(webmap_item, NGWWebMapLayer):
                self.__add_webmap_layer(webmap, webmap_item)
        except ResourceImportCancelledError:
            raise
        except Exception as error:
            context = self.__adding_error_context_for_webmap_item(
                webmap, webmap_item
            )
            if self.__skip_after_adding_error(error, context):
                return
            raise

    def __add_webmap_group(
        self, webmap: NGWWebMap, webmap_group: NGWWebMapGroup
    ) -> None:
        # Create group in layers tree
        qgs_group = self.__insert_group(webmap_group.display_name)

        for child in webmap_group.children:
            self.__add_webmap_item(webmap, child)

        qgs_group.setExpanded(webmap_group.expanded)
        qgs_group.setIsMutuallyExclusive(webmap_group.exclusive)
        qgs_group.setItemVisibilityChecked(webmap_group.is_visible)

        group_position = self.__insertion_stack.pop()

        # NGW webmap display behaviour
        if group_position.position == 0:
            parent_position = self.__insertion_stack[-1]
            parent_position.group.removeChildNode(qgs_group)
            parent_position.position -= 1

    def __add_webmap_layer(
        self, webmap: NGWWebMap, webmap_layer: NGWWebMapLayer
    ) -> None:
        if (
            webmap_layer.layer_style_id in self.__skipped_resources
            or webmap_layer.style_parent_id in self.__skipped_resources
        ):
            return

        if id(webmap_layer) not in self.__layers:
            message = (
                f'Layer "{webmap_layer.display_name}" was not added to QGIS'
            )
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        insertion_point = self.__insertion_stack[-1]

        layer = self.__layers[id(webmap_layer)]
        layer.setName(webmap_layer.display_name)

        style_resource = self.__model.resource(webmap_layer.layer_style_id)
        if is_style(style_resource):
            self.__style_applicator.replace_default(
                style_resource,
                layer,
            )  # type: ignore
            layer_resource_id = webmap_layer.style_parent_id
            assert layer_resource_id is not None
        else:
            layer_resource_id = webmap_layer.layer_style_id

        layer_resource = self.__model.resource(layer_resource_id)
        if isinstance(layer_resource, NGWAbstractVectorResource):
            assert isinstance(layer, QgsVectorLayer)
            self.__vector_layer_metadata_applicator.apply(
                layer_resource,
                layer,
            )

        self.__set_ngw_layer_properties(
            layer,
            webmap.connection_id,
            layer_resource_id,
        )

        layer_node = insertion_point.group.insertLayer(
            insertion_point.position, layer
        )
        assert layer_node is not None
        layer_node.setItemVisibilityChecked(webmap_layer.is_visible)
        layer_node.setExpanded(
            webmap_layer.legend if webmap_layer.legend is not None else False
        )
        insertion_point.position += 1

    def __add_webmap_basemaps(
        self,
        webmap: NGWWebMap,
    ) -> None:
        if len(webmap.basemaps) == 0:
            return

        basemaps_group = self.__insert_group(self.tr("Basemaps"))

        insertion_point = self.__insertion_stack[-1]

        enabled_basemap_index = 0

        for i, basemap in enumerate(webmap.basemaps):
            if (
                id(basemap) in self.__skipped_resources
                or basemap.resource_id in self.__skipped_resources
            ):
                continue

            if id(basemap) not in self.__layers:
                message = (
                    f'Basemap "{basemap.display_name}" was not added to QGIS'
                )
                error = NgConnectError(
                    code=ErrorCode.AddingError, log_message=message
                )
                context = self.__adding_error_context_for_webmap_basemap(
                    webmap, basemap
                )
                if self.__skip_after_adding_error(error, context):
                    continue
                raise error

            basemap_layer = self.__layers[id(basemap)]
            basemap_layer.setName(basemap.display_name)

            self.__set_ngw_layer_properties(
                basemap_layer,
                webmap.connection_id,
                basemap.resource_id,
            )

            if basemap.opacity is not None:
                basemap_layer.setOpacity(basemap.opacity)

            layer_node = insertion_point.group.insertLayer(
                insertion_point.position, basemap_layer
            )
            assert layer_node is not None
            layer_node.setExpanded(False)
            insertion_point.position += 1

            if basemap.enabled:
                enabled_basemap_index = i

        basemaps_group.setIsMutuallyExclusive(
            True, initialChildIndex=enabled_basemap_index
        )
        basemaps_group.setItemVisibilityChecked(
            not bool(webmap.basemap_disabled)
        )

        self.__insertion_stack.pop()

    def __insert_group(self, name: str) -> QgsLayerTreeGroup:
        insertion_point = self.__insertion_stack.pop()
        qgs_group = insertion_point.group.insertGroup(
            insertion_point.position, name
        )
        assert qgs_group is not None

        # Increment old point
        self.__insertion_stack.append(
            InsertionPoint(insertion_point.group, insertion_point.position + 1)
        )

        # Add new point for children
        self.__insertion_stack.append(InsertionPoint(qgs_group, 0))

        return qgs_group

    def __store_layer_params(
        self,
        insertion_id: InsertionId,
        params: LayerParams,
        context: ResourceAddingErrorContext,
    ) -> None:
        self.__layers_params[insertion_id] = QgisLayerCreationParameters(
            *params
        )
        self.__adding_error_contexts[insertion_id] = context

    def __adding_error_context_from_index(
        self,
        index: QModelIndex,
    ) -> ResourceAddingErrorContext:
        context = self.__adding_error_contexts.get(index)
        if context is not None:
            return context

        if index.isValid():
            resource = index.data(QNGWResourceItem.NGWResourceRole)
            if isinstance(resource, NGWResource):
                return self.__adding_error_context_for_resource(
                    resource, index
                )

        return ResourceAddingErrorContext(
            display_name=self.tr("Resource"),
            insertion_id=index,
        )

    def __adding_error_context_for_resource(
        self,
        resource: NGWResource,
        insertion_id: Optional[InsertionId] = None,
    ) -> ResourceAddingErrorContext:
        return ResourceAddingErrorContext(
            display_name=resource.display_name,
            insertion_id=insertion_id,
            resource_ids=(resource.resource_id,),
            resource_url=self.__resource_url(resource),
        )

    def __adding_error_context_for_service_layer(
        self,
        service_layer,
    ) -> ResourceAddingErrorContext:
        display_name = getattr(
            service_layer,
            "display_name",
            self.tr("Service layer"),
        )
        resource_ids = self.__normalized_resource_ids(
            getattr(service_layer, "resource_id", None)
        )
        return ResourceAddingErrorContext(
            display_name=display_name,
            insertion_id=id(service_layer),
            resource_ids=resource_ids,
        )

    def __adding_error_context_for_webmap_item(
        self,
        webmap: NGWWebMap,
        webmap_item: Union[NGWWebMapGroup, NGWWebMapLayer],
    ) -> ResourceAddingErrorContext:
        if isinstance(webmap_item, NGWWebMapLayer):
            return self.__adding_error_context_for_webmap_layer(
                webmap, webmap_item
            )

        return ResourceAddingErrorContext(
            display_name=webmap_item.display_name,
        )

    def __adding_error_context_for_webmap_layer(
        self,
        webmap: NGWWebMap,
        webmap_layer: NGWWebMapLayer,
    ) -> ResourceAddingErrorContext:
        resource_ids = self.__normalized_resource_ids(
            webmap_layer.style_parent_id,
            webmap_layer.layer_style_id,
        )
        resource_url = self.__webmap_resource_url(webmap, resource_ids)
        return ResourceAddingErrorContext(
            display_name=webmap_layer.display_name,
            insertion_id=id(webmap_layer),
            resource_ids=resource_ids,
            resource_url=resource_url,
        )

    def __adding_error_context_for_webmap_basemap(
        self,
        webmap: NGWWebMap,
        basemap,
    ) -> ResourceAddingErrorContext:
        resource_ids = self.__normalized_resource_ids(basemap.resource_id)
        return ResourceAddingErrorContext(
            display_name=basemap.display_name,
            insertion_id=id(basemap),
            resource_ids=resource_ids,
            resource_url=self.__webmap_resource_url(webmap, resource_ids),
        )

    def __raise_if_webmap_layer_forbidden(
        self,
        webmap: NGWWebMap,
        webmap_layer: NGWWebMapLayer,
    ) -> None:
        for resource_id in self.__normalized_resource_ids(
            webmap_layer.style_parent_id,
            webmap_layer.layer_style_id,
        ):
            if not self.__model.is_forbidden(resource_id):
                continue

            raise self.__resource_permission_error(
                webmap,
                webmap_layer.display_name,
                resource_id,
            )

    def __resource_permission_error(
        self,
        webmap: NGWWebMap,
        display_name: str,
        resource_id: int,
    ) -> ResourcePermissionError:
        resource_url = self.__webmap_resource_url(webmap, (resource_id,))
        user_message = self.tr(
            'Resource "{}" is not accessible because you do not have the '
            "necessary permissions"
        ).format(display_name)
        detail = self.tr("Resource ID: {resource_id}").format(
            resource_id=resource_id
        )
        return ResourcePermissionError(
            log_message=(
                f'No permissions to access resource "{display_name}" '
                f"(id={resource_id})"
            ),
            user_message=user_message,
            detail=detail,
            resource_url=resource_url,
        )

    def __skip_after_adding_error(
        self,
        error: Exception,
        context: ResourceAddingErrorContext,
    ) -> bool:
        if not self.__interaction.should_skip_after_error(
            error,
            context,
            self.__can_skip_adding_error(),
        ):
            return False

        self.__mark_skipped_adding_context(context)
        return True

    def __can_skip_adding_error(self) -> bool:
        return self.__is_mass_adding

    def __mark_skipped_adding_context(
        self,
        context: ResourceAddingErrorContext,
    ) -> None:
        if context.insertion_id is not None:
            self.__skipped_resources.add(context.insertion_id)

        for resource_id in context.resource_ids:
            self.__skipped_resources.add(resource_id)

    @staticmethod
    def __normalized_resource_ids(
        *resource_ids: Optional[int],
    ) -> Tuple[int, ...]:
        result: List[int] = []
        for resource_id in resource_ids:
            if resource_id is None or isinstance(resource_id, bool):
                continue

            try:
                normalized_resource_id = int(resource_id)
            except (TypeError, ValueError):
                continue

            if normalized_resource_id <= 0:
                continue

            if normalized_resource_id not in result:
                result.append(normalized_resource_id)

        return tuple(result)

    @staticmethod
    def __resource_url(resource: NGWResource) -> Optional[str]:
        try:
            return resource.get_absolute_url()
        except Exception:
            return None

    @staticmethod
    def __webmap_resource_url(
        webmap: NGWWebMap,
        resource_ids: Tuple[int, ...],
    ) -> Optional[str]:
        if len(resource_ids) == 0:
            return None

        try:
            server_url = webmap.res_factory.connection.server_url
        except Exception:
            return None

        return urllib.parse.urljoin(server_url, RESOURCE_URL(resource_ids[0]))

    def __collect_layers_params(self) -> None:
        for index in self.__indices:
            self.__collect_params_for_index_with_error_handling(index)

        self.__layers_params = {
            insertion_id: params
            for insertion_id, params in self.__layers_params.items()
            if not params.is_empty
        }

    def __collect_params_for_index_with_error_handling(
        self, index: QModelIndex
    ) -> None:
        try:
            self.__collect_params_for_index(index)
        except ResourceImportCancelledError:
            raise
        except Exception as error:
            context = self.__adding_error_context_from_index(index)
            if self.__skip_after_adding_error(error, context):
                return
            raise

    def __collect_params_for_index(self, index: QModelIndex) -> None:
        if is_layer(index):
            self.__collect_params_for_layer_index(index)
        elif is_style(index):
            self.__collect_params_for_style_index(index)
        elif is_webmap(index):
            self.__collect_params_for_webmap(index)
        elif is_service(index):
            self.__collect_params_for_service(index)
        else:
            for row in range(self.__model.rowCount(index)):
                child_index = self.__model.index(row, 0, index)
                self.__collect_params_for_index_with_error_handling(
                    child_index
                )

    def __collect_params_for_layer_index(self, index: QModelIndex) -> None:
        resource: NGWVectorLayer = index.data(QNGWResourceItem.NGWResourceRole)
        params = self.__collect_params_for_layer_resource(resource)

        styles = self.__style_applicator.style_resources(index)
        if not self.__is_mass_adding and len(styles) > 1:
            default_style_id = self.__interaction.select_default_style(
                self.tr("Select style"),
                index,
                self.__model,
            )
            if default_style_id is not None:
                self.__default_styles[index] = default_style_id

        self.__store_layer_params(
            index,
            params,
            self.__adding_error_context_for_resource(resource, index),
        )

    def __collect_params_for_style_index(self, index: QModelIndex) -> None:
        resource: NGWVectorLayer = index.parent().data(
            QNGWResourceItem.NGWResourceRole
        )
        params = self.__collect_params_for_layer_resource(resource)

        self.__store_layer_params(
            index,
            params,
            self.__adding_error_context_for_resource(resource, index),
        )

    def __collect_params_for_layer_resource(
        self, resource: NGWResource
    ) -> LayerParams:
        if isinstance(resource, NGWVectorLayer):
            return self.__collect_params_for_detached_layer(resource)
        if isinstance(resource, SERVICE_LAYER_RESOURCE_TYPES):
            return self.__collect_params_for_service_layer(resource)
        if isinstance(resource, NGWRasterLayer):
            return self.__collect_params_for_cog_raster_layer(resource)
        if isinstance(resource, TMS_LAYER_RESOURCE_TYPES):
            return resource.layer_params

        raise NgConnectError(
            escape_html(f"Unsupported resource: {resource!r}"),
            code=ErrorCode.AddingError,
        )

    def __collect_params_for_webmap(self, index: QModelIndex) -> None:
        webmap: NGWWebMap = index.data(QNGWResourceItem.NGWResourceRole)

        for child in webmap.root.children:
            self.__collect_params_for_webmap_item(webmap, child)

        self.__collect_params_for_webmap_basemaps(webmap)

    def __collect_params_for_webmap_item(
        self,
        webmap: NGWWebMap,
        webmap_item: Union[NGWWebMapGroup, NGWWebMapLayer],
    ) -> None:
        try:
            if isinstance(webmap_item, NGWWebMapGroup):
                self.__collect_params_for_webmap_group(webmap, webmap_item)
            elif isinstance(webmap_item, NGWWebMapLayer):
                self.__collect_params_for_webmap_layer(webmap, webmap_item)
        except ResourceImportCancelledError:
            raise
        except Exception as error:
            context = self.__adding_error_context_for_webmap_item(
                webmap, webmap_item
            )
            if self.__skip_after_adding_error(error, context):
                return
            raise

    def __collect_params_for_webmap_layer(
        self, webmap: NGWWebMap, webmap_layer: NGWWebMapLayer
    ) -> None:
        self.__raise_if_webmap_layer_forbidden(webmap, webmap_layer)

        layer_resource = self.__model.resource(webmap_layer.style_parent_id)
        style_resource = self.__model.resource(webmap_layer.layer_style_id)

        if is_layer(layer_resource):
            assert layer_resource is not None
            params = self.__collect_params_for_layer_resource(layer_resource)

        elif is_layer(style_resource):
            assert style_resource is not None
            params = self.__collect_params_for_layer_resource(style_resource)

        elif isinstance(layer_resource, NGWRasterMosaic):
            assert webmap_layer.style_parent_id is not None
            self.__skipped_resources.add(webmap_layer.style_parent_id)
            return

        else:
            error = NgConnectError(
                "Unsupported resources",
                user_message=self.tr(
                    'Layer "{}" can\'t be added to the map'
                ).format(webmap_layer.display_name),
                detail=self.tr(
                    "The linked layer or style resource is not available."
                ),
                code=ErrorCode.AddingError,
            )
            error.add_note(escape_html(f"Style parent: {layer_resource!r}"))
            error.add_note(escape_html(f"Style: {style_resource!r}"))
            raise error

        self.__store_layer_params(
            id(webmap_layer),
            params,
            self.__adding_error_context_for_webmap_layer(webmap, webmap_layer),
        )

    def __collect_params_for_webmap_group(
        self, webmap: NGWWebMap, webmap_group: NGWWebMapGroup
    ) -> None:
        for child in webmap_group.children:
            self.__collect_params_for_webmap_item(webmap, child)

    def __collect_params_for_webmap_basemaps(self, webmap: NGWWebMap) -> None:
        for basemap in webmap.basemaps:
            try:
                if self.__model.is_forbidden(basemap.resource_id):
                    raise self.__resource_permission_error(
                        webmap,
                        basemap.display_name,
                        basemap.resource_id,
                    )

                basemap_resource = self.__model.resource(basemap.resource_id)
                if basemap_resource is None:
                    message = f"Can't find basemap (id={basemap.resource_id})"
                    raise NgConnectError(
                        code=ErrorCode.AddingError, log_message=message
                    )

                self.__store_layer_params(
                    id(basemap),
                    self.__collect_params_for_layer_resource(basemap_resource),
                    self.__adding_error_context_for_webmap_basemap(
                        webmap, basemap
                    ),
                )
            except ResourceImportCancelledError:
                raise
            except Exception as error:
                context = self.__adding_error_context_for_webmap_basemap(
                    webmap, basemap
                )
                if self.__skip_after_adding_error(error, context):
                    continue
                raise

    def __collect_params_for_service(self, index: QModelIndex) -> None:
        resource = index.data(QNGWResourceItem.NGWResourceRole)

        self.__check_wfs_service(index)

        if index in self.__skipped_resources:
            return

        for layer in resource.layers:
            if id(layer) in self.__skipped_resources:
                continue

            try:
                self.__store_layer_params(
                    id(layer),
                    resource.params_for_layer(layer),
                    self.__adding_error_context_for_service_layer(layer),
                )
            except ResourceImportCancelledError:
                raise
            except Exception as error:
                context = self.__adding_error_context_for_service_layer(layer)
                if self.__skip_after_adding_error(error, context):
                    continue
                raise

    def __collect_params_for_detached_layer(
        self, vector_layer: NGWVectorLayer
    ) -> LayerParams:
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(vector_layer.connection_id)
        assert connection is not None

        detached_layer_path = (
            DetachedStorageServiceFactory.create().container_path(
                connection.domain_uuid, vector_layer.resource_id
            )
        )
        if detached_layer_path.exists():
            is_ready = CachedDetachedContainerLifecycle().reconcile(
                detached_layer_path,
                vector_layer,
                connection,
            )
            if not is_ready:
                raise NgConnectError(
                    code=ErrorCode.ContainerIsInvalid,
                    log_message=(
                        "Detached container is incompatible: "
                        f"{detached_layer_path}"
                    ),
                )

        uri = detached_layer_uri(detached_layer_path)

        return (uri, vector_layer.display_name, "ogr")

    def __collect_params_for_service_layer(
        self, service_layer: Union[NGWWmsLayer, NGWWfsLayer, NGWPostgisLayer]
    ) -> LayerParams:
        connection = self.__model.resource(service_layer.service_resource_id)
        if connection is None:
            message = (
                f"Connecton for layer {service_layer.display_name}"
                " is not accessible"
            )
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        return service_layer.layer_params(connection)  # type: ignore

    def __collect_params_for_geojson_layer(
        self, vector_layer: NGWVectorLayer
    ) -> LayerParams:
        return (
            vector_layer.get_absolute_geojson_url(),
            vector_layer.display_name,
            "ogr",
        )

    def __collect_params_for_cog_raster_layer(
        self, raster_layer: NGWRasterLayer
    ) -> LayerParams:
        if not raster_layer.is_cog:
            raise NgwError(code=ErrorCode.UnsupportedRasterType)

        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(raster_layer.connection_id)
        assert connection is not None
        if connection.method not in ("", "Basic"):
            self.__skipped_resources.add(raster_layer.resource_id)

            user_message = self.tr(
                f'Layer "{raster_layer.display_name}" was not added to the map'
            )
            detail = self.tr(
                "Currently adding raster layers is not available for OAuth"
                " connections. Please use Basic authentication."
            )
            self.__warnings.append(
                NgConnectWarning(user_message=user_message, detail=detail)
            )
            logger.warning(user_message)
            return ("", "", "")

        return raster_layer.layer_params

    def __create_layers(self) -> None:
        if len(self.__layers_params) == 0:
            return

        self.__layer_factory = QgisBatchLayerFactory(
            NgConnectInterface.instance().task_manager
        )
        try:
            self.__layers = cast(
                Dict[InsertionId, QgsMapLayer],
                self.__layer_factory.create(self.__layers_params),
            )
        finally:
            self.__layer_factory = None
        self.__raise_if_cancelled()
        self.__remove_invalid_layers_after_user_choice()
        self.__raise_if_cancelled()

        if len(self.__layers) == 0:
            return

        if all(not layer.isValid() for layer in self.__layers.values()):
            message = "All layers are invalid"
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        self.__raise_if_cancelled()
        QgsProject.instance().addMapLayers(
            self.__layers.values(), addToLegend=False
        )

    def __remove_invalid_layers_after_user_choice(self) -> None:
        for insertion_id, layer in list(self.__layers.items()):
            if layer.isValid():
                continue

            error_summary = layer.error().summary()
            layer_name = layer.name()
            context = self.__adding_error_contexts.get(
                insertion_id,
                ResourceAddingErrorContext(
                    display_name=layer_name,
                    insertion_id=insertion_id,
                ),
            )
            error = NgConnectError(
                log_message=(
                    f'Layer "{layer_name}" is not valid: {error_summary}'
                ),
                user_message=self.tr(
                    'Layer "{}" can\'t be added to the map'
                ).format(layer_name),
                detail=error_summary,
                code=ErrorCode.AddingError,
            )
            if not self.__skip_after_adding_error(error, context):
                raise error

            self.__layers.pop(insertion_id, None)
            layer.deleteLater()

    def __process_indexes_list(self) -> None:
        def has_parent_in_list(index: QModelIndex) -> bool:
            index = index.parent()
            while index.isValid():
                if index in self.__indices:
                    return True
                index = index.parent()
            return False

        i = 0
        for ngw_index in self.__indices:
            if not ngw_index.isValid() or has_parent_in_list(ngw_index):
                del self.__indices[i]
            else:
                i += 1

    def __check_wfs_service(self, index: QModelIndex):
        resource: NGWResource = index.data(QNGWResourceItem.NGWResourceRole)
        if not isinstance(resource, NGWWfsService):
            return

        has_z = False
        has_only_z = True

        for layer in resource.layers:
            layer_resource = cast(
                NGWVectorLayer, self.__model.resource(layer.resource_id)
            )
            if layer_resource.is_geom_with_z():
                has_z = True
            else:
                has_only_z = False

        if not has_z:
            return

        if not self.__interaction.should_skip_wfs_with_z():
            return

        if has_only_z:
            self.__skipped_resources.add(index)
            return

        for layer in resource.layers:
            layer_resource = cast(
                NGWVectorLayer, self.__model.resource(layer.resource_id)
            )
            if layer_resource.is_geom_with_z():
                self.__skipped_resources.add(id(layer))
