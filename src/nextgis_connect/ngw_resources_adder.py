from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple, Union, cast

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsEditorWidgetSetup,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsLayerTreeRegistryBridge,
    QgsMapLayer,
    QgsMapLayerStyle,
    QgsMapLayerStyleManager,
    QgsProject,
    QgsRasterLayer,
    QgsReferencedRectangle,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QEventLoop, QModelIndex, QObject, QTimer
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.utils import iface

from nextgis_connect.detached_editing.utils import detached_layer_uri
from nextgis_connect.dialog_choose_style import NGWLayerStyleChooserDialog
from nextgis_connect.exceptions import ErrorCode, NgConnectError, NgwError
from nextgis_connect.logging import logger
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_api.core import (
    NGWBaseMap,
    NGWGroupResource,
    NGWOgcfService,
    NGWPostgisLayer,
    NGWQGISStyle,
    NGWRasterLayer,
    NGWResource,
    NGWVectorLayer,
    NGWWebMap,
    NGWWfsService,
    NGWWmsConnection,
    NGWWmsLayer,
    NGWWmsService,
)
from nextgis_connect.ngw_api.core.ngw_abstract_vector_resource import (
    NGWAbstractVectorResource,
)
from nextgis_connect.ngw_api.core.ngw_postgis_layer import NGWPostgisConnection
from nextgis_connect.ngw_api.core.ngw_tms_resources import (
    NGWTmsConnection,
    NGWTmsLayer,
)
from nextgis_connect.ngw_api.core.ngw_webmap import (
    NGWWebMapGroup,
    NGWWebMapLayer,
)
from nextgis_connect.ngw_connection import NgwConnectionsManager
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)
from nextgis_connect.tasks.ng_connect_task import NgConnectTask
from nextgis_connect.tree_widget.item import QNGWResourceItem
from nextgis_connect.tree_widget.model import QNGWResourceTreeModel

if TYPE_CHECKING:
    assert isinstance(iface, QgisInterface)

LayerObjectId = int
InsertionId = Union[QModelIndex, LayerObjectId]
LayerParams = Tuple[str, str, str]

InsertionPoint = QgsLayerTreeRegistryBridge.InsertionPoint

TmsLayerResources = (NGWTmsLayer, NGWTmsConnection, NGWBaseMap)
ServiceLayerResources = (NGWPostgisLayer, NGWWmsLayer)

VectorResources = (NGWVectorLayer, NGWPostgisLayer)
RasterResources = (NGWRasterLayer, *TmsLayerResources, NGWWmsLayer)

VectorServices = (NGWWfsService, NGWOgcfService)
ServiceResources = (*VectorServices, NGWWmsService)
ConnectionResources = (NGWWmsConnection,)

VectorProviders = ("ogr", "wfs", "oapif", "postgres")


class LayerCreatorTask(NgConnectTask):
    __layers_params: Dict[InsertionId, LayerParams]
    __layers: Dict[InsertionId, QgsMapLayer]

    def __init__(self, layers_params: Dict[InsertionId, LayerParams]) -> None:
        super().__init__()
        self.__layers_params = layers_params
        self.__layers = {}

    @property
    def layers(self) -> Dict[InsertionId, QgsMapLayer]:
        return self.__layers

    def run(self) -> bool:
        super().run()

        main_thread = QgsApplication.instance().thread()

        count = len(self.__layers_params)

        for i, (insertion_id, layer_params) in enumerate(
            self.__layers_params.items()
        ):
            provider = layer_params[-1]
            layer_name = layer_params[1]
            counter = f"[{i + 1}/{count}] " if count > 1 else ""

            logger.debug(f'{counter}Creating {provider} layer "{layer_name}"')

            if provider.lower() in VectorProviders:
                layer = QgsVectorLayer(*layer_params)
            else:
                layer = QgsRasterLayer(*layer_params)

            layer.setParent(None)
            layer.moveToThread(main_thread)

            if not layer.isValid():
                error = layer.error().summary()
                logger.warning(f'Layer "{layer_name}" is not valid: {error}')

            self.__layers[insertion_id] = layer

        return True


def is_layer(resource: Union[Optional[NGWResource], QModelIndex]) -> bool:
    if resource is None:
        return False

    if isinstance(resource, QModelIndex):
        resource = resource.data(QNGWResourceItem.NGWResourceRole)

    return isinstance(resource, (*VectorResources, *RasterResources))


def is_style(resource: Union[Optional[NGWResource], QModelIndex]) -> bool:
    if resource is None:
        return False

    if isinstance(resource, QModelIndex):
        resource = resource.data(QNGWResourceItem.NGWResourceRole)

    return isinstance(resource, NGWQGISStyle)


def is_webmap(resource: Union[Optional[NGWResource], QModelIndex]) -> bool:
    if resource is None:
        return False

    if isinstance(resource, QModelIndex):
        resource = resource.data(QNGWResourceItem.NGWResourceRole)

    return isinstance(resource, NGWWebMap)


def is_service(
    resource: Union[Optional[NGWResource], QModelIndex],
) -> bool:
    if resource is None:
        return False

    if isinstance(resource, QModelIndex):
        resource = resource.data(QNGWResourceItem.NGWResourceRole)

    return isinstance(
        resource, (*VectorServices, NGWWmsService, NGWWmsConnection)
    )


class NgwResourcesAdder(QObject):
    __project: QgsProject

    __model: QNGWResourceTreeModel
    __indices: List[QModelIndex]

    __is_mass_adding: bool

    __layers_params: Dict[InsertionId, LayerParams]
    __layers: Dict[InsertionId, QgsMapLayer]
    __default_styles: Dict[QModelIndex, int]
    __skip_wfs_with_z: Optional[bool]
    __skipped_resources: Set[InsertionId]
    __insertion_stack: List[InsertionPoint]

    def __init__(
        self,
        model: QNGWResourceTreeModel,
        indices: Union[QModelIndex, List[QModelIndex]],
        insertion_point: InsertionPoint,
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
        self.__insertion_stack.append(insertion_point)

        self.__is_mass_adding = False
        self.__layers = {}
        self.__layers_params = {}
        self.__default_styles = {}
        self.__skip_wfs_with_z = None
        self.__skipped_resources = set()
        self.__insertion_stack = []

    def missing_resources(self) -> Tuple[bool, List[int]]:
        """Extract resources needed for layers to add to QGIS"""
        result = []

        try:
            for index in self.__indices:
                if is_style(index):
                    index = index.parent()
                result.extend(self.__missing_resources(index))
        except Exception as error:
            message = self.tr("An error occured while fetching resources")
            ng_error = NgwError(user_message=message)
            ng_error.__cause__ = error
            NgConnectInterface.instance().show_error(ng_error)
            return False, []

        result = list(set(result))
        if len(result) > 0:
            logger.debug(
                f"{len(result)} additional resources will be downloaded"
            )

        return (True, result)

    def missing_styles(self) -> Tuple[bool, List[int]]:
        result = []
        try:
            for index in self.__indices:
                if is_style(index):
                    index = index.parent()
                result.extend(self.__missing_styles(index))

        except Exception as error:
            message = self.tr("An error occured while fetching styles")
            ng_error = NgwError(user_message=message)
            ng_error.__cause__ = error
            NgConnectInterface.instance().show_error(ng_error)
            return False, []

        result = list(set(result))
        if len(result) > 0:
            logger.debug(f"{len(result)} styles will be downloaded")

        return (True, result)

    def run(self) -> bool:
        indices = self.__indices

        added_layers = 0

        try:
            self.__collect_layers_params()
            self.__create_layers()

            for index in indices:
                self.__add_resource(index)

            added_layers = len(self.__layers)

        except Exception as error:
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

            NgConnectInterface.instance().show_error(ng_error)
            return False

        finally:
            self.__insertion_stack.clear()
            self.__layers_params.clear()
            self.__layers.clear()

        if added_layers == 0:
            layer_label = "No layers"
        elif added_layers > 1:
            layer_label = f"{added_layers} layers"
        else:
            layer_label = "Layer"

        logger.debug(f"{layer_label} has been added to the map")

        return True

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
        layer.styleManager().setCurrentStyle(style_resource.display_name)

    def __add_group(self, group_index: QModelIndex) -> None:
        group_resource: NGWGroupResource = group_index.data(
            QNGWResourceItem.NGWResourceRole
        )

        self.__insert_group(group_resource.display_name)

        # Add children
        for row in range(self.__model.rowCount(group_index)):
            child_index = self.__model.index(row, 0, group_index)
            self.__add_resource(child_index)

        self.__insertion_stack.pop()

    def __add_layer(
        self, layer_index: QModelIndex
    ) -> Optional[QgsLayerTreeLayer]:
        ngw_resource = layer_index.data(QNGWResourceItem.NGWResourceRole)
        if is_style(ngw_resource):
            ngw_resource = self.__model.resource(layer_index.parent())
        assert ngw_resource is not None

        if (
            layer_index in self.__skipped_resources
            or ngw_resource.resource_id in self.__skipped_resources
        ):
            return

        insertion_point = self.__insertion_stack[-1]

        if layer_index not in self.__layers:
            logger.debug(
                f"Layer {ngw_resource.resource_id} was not added to QGIS"
            )
            raise RuntimeError

        layer = self.__layers[layer_index]

        layer.setName(ngw_resource.display_name)

        self.__add_all_styles_to_layer(ngw_resource, layer)
        if isinstance(ngw_resource, NGWAbstractVectorResource):
            assert isinstance(layer, QgsVectorLayer)
            self.__add_fields_aliases(ngw_resource, layer)
            self.__add_lookup_tables(ngw_resource, layer)
            self.__set_display_field(ngw_resource, layer)

        layer.setCustomProperty(
            "ngw_connection_id", ngw_resource.connection_id
        )
        layer.setCustomProperty("ngw_resource_id", ngw_resource.resource_id)

        layer_node = insertion_point.group.insertLayer(
            insertion_point.position, layer
        )
        assert layer_node is not None
        layer_node.setExpanded(not self.__is_mass_adding)
        insertion_point.position += 1

        return layer_node

    def __add_service(self, service_index: QModelIndex) -> None:
        if service_index in self.__skipped_resources:
            return

        service_resource: Union[
            NGWWfsService, NGWOgcfService, NGWWmsService
        ] = service_index.data(QNGWResourceItem.NGWResourceRole)

        self.__insert_group(service_resource.display_name)

        # Add children
        for layer in service_resource.layers:
            if id(layer) in self.__skipped_resources:
                continue

            self.__add_service_layer(service_resource, layer)

        self.__insertion_stack.pop()

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

        layer.setCustomProperty(
            "ngw_connection_id", ngw_resource.connection_id
        )
        layer.setCustomProperty("ngw_resource_id", ngw_resource.resource_id)

        layer_node = insertion_point.group.insertLayer(
            insertion_point.position, layer
        )
        assert layer_node is not None
        layer_node.setExpanded(False)
        insertion_point.position += 1

    def __add_webmap(self, webmap_index: QModelIndex) -> None:
        webmap_resource: NGWWebMap = webmap_index.data(
            QNGWResourceItem.NGWResourceRole
        )

        # Set project CRS if no layers added previously
        if not self.__is_mass_adding and self.__project.count() == 0:
            self.__project.setCrs(
                QgsCoordinateReferenceSystem.fromEpsgId(3857)
            )

        # Add webmap to tree
        qgs_group = self.__insert_group(webmap_resource.display_name)

        for child in webmap_resource.root.children:
            if isinstance(child, NGWWebMapGroup):
                self.__add_webmap_group(webmap_resource, child)
            elif isinstance(child, NGWWebMapLayer):
                self.__add_webmap_layer(webmap_resource, child)

        self.__add_webmap_basemaps(webmap_resource)

        qgs_group.setExpanded(True)

        self.__insertion_stack.pop()

        # Set extent
        self.__set_webmap_extent(webmap_resource)

    def __add_webmap_group(
        self, webmap: NGWWebMap, webmap_group: NGWWebMapGroup
    ) -> None:
        # Create group in layers tree
        qgs_group = self.__insert_group(webmap_group.display_name)

        for child in webmap_group.children:
            if isinstance(child, NGWWebMapGroup):
                self.__add_webmap_group(webmap, child)
            elif isinstance(child, NGWWebMapLayer):
                self.__add_webmap_layer(webmap, child)

        qgs_group.setExpanded(webmap_group.expanded)
        qgs_group.setIsMutuallyExclusive(webmap_group.exclusive)

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
            self.__replace_default_style(style_resource, layer)  # type: ignore
            layer_resource_id = webmap_layer.style_parent_id
        else:
            layer_resource_id = webmap_layer.layer_style_id

        layer.setCustomProperty("ngw_connection_id", webmap.connection_id)
        layer.setCustomProperty("ngw_resource_id", layer_resource_id)

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
            if basemap.resource_id in self.__skipped_resources:
                continue

            basemap_layer = self.__layers[id(basemap)]
            basemap_layer.setName(basemap.display_name)

            basemap_layer.setCustomProperty(
                "ngw_connection_id", webmap.connection_id
            )
            basemap_layer.setCustomProperty(
                "ngw_resource_id", basemap.resource_id
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

        self.__insertion_stack.pop()

    def __set_webmap_extent(self, webmap: NGWWebMap) -> None:
        extent = webmap.extent
        if extent is None:
            return

        QTimer.singleShot(0, lambda: self.__update_extent(extent))

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

    def __missing_resources(self, index: QModelIndex) -> List[int]:
        resource: NGWResource = index.data(QNGWResourceItem.NGWResourceRole)

        result = []
        if isinstance(resource, NGWGroupResource):
            result = self.__missing_resources_from_group(index)
        elif is_layer(resource):
            result = self.__missing_resources_from_layer(index)
        elif isinstance(resource, NGWWebMap):
            result = self.__missing_resources_from_webmap(index)
        elif isinstance(resource, VectorServices):
            result = self.__missing_resources_from_vector_service(index)

        return result

    def __missing_resources_from_group(
        self, group_index: QModelIndex
    ) -> List[int]:
        resource: NGWResource = group_index.data(
            QNGWResourceItem.NGWResourceRole
        )

        result = []
        if self.__model.canFetchMore(group_index):
            result.append(resource.resource_id)
        else:
            for row in range(self.__model.rowCount(group_index)):
                child_index = self.__model.index(row, 0, group_index)
                result.extend(self.__missing_resources(child_index))

        return result

    def __missing_resources_from_webmap(self, index: QModelIndex) -> List[int]:
        webmap: NGWWebMap = index.data(QNGWResourceItem.NGWResourceRole)

        result = []

        for resource_id in webmap.all_resources_id:
            if self.__is_downloaded(resource_id):
                resource = self.__model.resource(resource_id)
                assert resource is not None
                if not is_layer(resource):
                    continue

                # Download lookup tables
                result.extend(
                    self.__missing_lookup_tables_from_layer(resource)
                )

                # Download services
                result.extend(self.__missing_services_from_layer(resource))

            else:
                result.append(resource_id)

        return result

    def __missing_resources_from_vector_service(
        self, index: QModelIndex
    ) -> List[int]:
        service: Union[NGWWfsService, NGWOgcfService] = index.data(
            QNGWResourceItem.NGWResourceRole
        )

        result = []
        for layer in service.layers:
            index = self.__model.index_from_id(layer.resource_id)
            resource = self.__model.resource(layer.resource_id)

            if self.__model.is_forbidden(layer.resource_id):
                continue
            elif resource is None:
                result.append(layer.resource_id)
            elif index is not None and index.isValid():
                result.extend(self.__missing_resources_from_layer(index))
            else:
                # is dangling
                styles = self.__model.children_resources(layer.resource_id)
                if resource.common.children and len(styles) == 0:
                    result.append(layer.resource_id)
                result.extend(
                    self.__missing_lookup_tables_from_layer(resource)
                )

        return result

    def __missing_resources_from_layer(self, index: QModelIndex) -> List[int]:
        resource: NGWResource = index.data(QNGWResourceItem.NGWResourceRole)

        result = []

        # Download styles
        if self.__model.canFetchMore(index):
            result.append(resource.resource_id)

        # Download lookup tables
        result.extend(self.__missing_lookup_tables_from_layer(index))

        # Download services
        result.extend(self.__missing_services_from_layer(index))

        return result

    def __missing_lookup_tables_from_layer(
        self, resource: Union[QModelIndex, NGWResource]
    ) -> List[int]:
        if isinstance(resource, QModelIndex):
            resource = resource.data(QNGWResourceItem.NGWResourceRole)

        if not isinstance(resource, NGWAbstractVectorResource):
            return []

        result = []
        for field in resource.fields:
            table_id = field.lookup_table
            if table_id is None or self.__is_downloaded(table_id):
                continue
            result.append(table_id)

        return result

    def __missing_services_from_layer(
        self, resource: Union[QModelIndex, NGWResource]
    ) -> List[int]:
        if isinstance(resource, QModelIndex):
            resource = resource.data(QNGWResourceItem.NGWResourceRole)

        if not isinstance(resource, (NGWPostgisLayer, NGWWmsLayer)):
            return []

        result = []
        if not self.__is_downloaded(resource.service_resource_id):
            result.append(resource.service_resource_id)
        return result

    def __is_downloaded(self, resource_id: int) -> bool:
        resource = self.__model.resource(resource_id)
        return resource is not None or self.__model.is_forbidden(resource_id)

    def __missing_styles(self, index: QModelIndex) -> List[int]:
        resource: NGWResource = index.data(QNGWResourceItem.NGWResourceRole)

        result = []

        if (
            isinstance(resource, NGWQGISStyle)
            and not resource.is_qml_populated
        ):
            result.append(resource.resource_id)

        elif isinstance(resource, NGWWebMap):
            for resource_id in resource.all_resources_id:
                child = self.__model.resource(resource_id)
                if (
                    not isinstance(child, NGWQGISStyle)
                    or child.is_qml_populated
                ):
                    continue

                result.append(child.resource_id)

        elif isinstance(resource, VectorServices):
            for layer in resource.layers:
                for child in self.__model.children_resources(
                    layer.resource_id
                ):
                    if (
                        not isinstance(child, NGWQGISStyle)
                        or child.is_qml_populated
                    ):
                        continue

                    result.append(child.resource_id)

        else:
            for row in range(self.__model.rowCount(index)):
                child_index = self.__model.index(row, 0, index)
                result.extend(self.__missing_styles(child_index))

        return result

    def __collect_layers_params(self) -> None:
        for index in self.__indices:
            self.__collect_params_for_index(index)

        self.__layers_params = {
            insertion_id: params
            for insertion_id, params in self.__layers_params.items()
            if params[-1] != ""
        }

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
                self.__collect_params_for_index(child_index)

    def __collect_params_for_layer_index(self, index: QModelIndex) -> None:
        resource: NGWVectorLayer = index.data(QNGWResourceItem.NGWResourceRole)
        params = self.__collect_params_for_layer_resource(resource)

        if not self.__is_mass_adding and self.__model.rowCount(index) > 1:
            dialog = NGWLayerStyleChooserDialog(
                self.tr("Select style"), index, self.__model
            )
            result = dialog.exec()
            if result == NGWLayerStyleChooserDialog.DialogCode.Accepted:
                selected_index = dialog.selectedStyleIndex()
                if selected_index is not None and selected_index.isValid():
                    default_style = selected_index.data(
                        QNGWResourceItem.NGWResourceRole
                    )
                    self.__default_styles[index] = default_style.resource_id

        self.__layers_params[index] = params

    def __collect_params_for_style_index(self, index: QModelIndex) -> None:
        resource: NGWVectorLayer = index.parent().data(
            QNGWResourceItem.NGWResourceRole
        )
        params = self.__collect_params_for_layer_resource(resource)

        self.__layers_params[index] = params

    def __collect_params_for_layer_resource(
        self, resource: NGWResource
    ) -> LayerParams:
        if isinstance(resource, NGWVectorLayer):
            return self.__collect_params_for_detached_layer(resource)
        if isinstance(resource, NGWPostgisLayer):
            return self.__collect_params_for_postgis_layer(resource)
        if isinstance(resource, NGWWmsLayer):
            return self.__collect_params_for_wms_layer(resource)
        if isinstance(resource, NGWRasterLayer):
            return self.__collect_params_for_cog_raster_layer(resource)
        if isinstance(resource, TmsLayerResources):
            return resource.layer_params

        raise NgConnectError(f"Unsupported type: {resource.common.cls}")

    def __collect_params_for_webmap(self, index: QModelIndex) -> None:
        webmap: NGWWebMap = index.data(QNGWResourceItem.NGWResourceRole)

        for child in webmap.root.children:
            if isinstance(child, NGWWebMapGroup):
                self.__collect_params_for_webmap_group(child)
            elif isinstance(child, NGWWebMapLayer):
                self.__collect_params_for_webmap_layer(child)

        self.__collect_params_for_webmap_basemaps(webmap)

    def __collect_params_for_webmap_layer(
        self, webmap_layer: NGWWebMapLayer
    ) -> None:
        layer_resource = self.__model.resource(webmap_layer.style_parent_id)
        style_resource = self.__model.resource(webmap_layer.layer_style_id)

        if is_layer(layer_resource):
            assert layer_resource is not None
            params = self.__collect_params_for_layer_resource(layer_resource)

        elif is_layer(style_resource):
            assert style_resource is not None
            params = self.__collect_params_for_layer_resource(style_resource)

        else:
            raise NgConnectError

        self.__layers_params[id(webmap_layer)] = params

    def __collect_params_for_webmap_group(
        self, webmap_group: NGWWebMapGroup
    ) -> None:
        for child in webmap_group.children:
            if isinstance(child, NGWWebMapGroup):
                self.__collect_params_for_webmap_group(child)
            elif isinstance(child, NGWWebMapLayer):
                self.__collect_params_for_webmap_layer(child)

    def __collect_params_for_webmap_basemaps(self, webmap: NGWWebMap) -> None:
        for basemap in webmap.basemaps:
            basemap_resource = self.__model.resource(basemap.resource_id)
            if basemap_resource is None:
                message = f"Can't find basemap (id={basemap.resource_id})"
                raise NgConnectError(
                    code=ErrorCode.AddingError, log_message=message
                )

            self.__layers_params[id(basemap)] = (
                self.__collect_params_for_layer_resource(basemap_resource)
            )

    def __collect_params_for_service(self, index: QModelIndex) -> None:
        resource = index.data(QNGWResourceItem.NGWResourceRole)

        self.__check_wfs_service(index)

        if index in self.__skipped_resources:
            return

        for layer in resource.layers:
            if id(layer) in self.__skipped_resources:
                continue

            self.__layers_params[id(layer)] = resource.params_for_layer(layer)

    def __collect_params_for_detached_layer(
        self, vector_layer: NGWVectorLayer
    ) -> LayerParams:
        connections_manager = NgwConnectionsManager()
        connection = connections_manager.connection(vector_layer.connection_id)
        assert connection is not None

        cache_manager = NgConnectCacheManager()
        connection_path = (
            Path(cache_manager.cache_directory) / connection.domain_uuid
        )

        uri = detached_layer_uri(
            connection_path / f"{vector_layer.resource_id}.gpkg"
        )

        return (uri, vector_layer.display_name, "ogr")

    def __collect_params_for_postgis_layer(
        self, postgis_layer: NGWPostgisLayer
    ) -> LayerParams:
        postgis_connection = cast(
            NGWPostgisConnection,
            self.__model.resource(postgis_layer.service_resource_id),
        )
        if postgis_connection is None:
            message = (
                f"Connecton for PostGIS layer {postgis_layer.display_name}"
                " is not accessible"
            )
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        return postgis_layer.layer_params(postgis_connection)

    def __collect_params_for_wms_layer(
        self, wms_layer: NGWWmsLayer
    ) -> LayerParams:
        wms_connection = cast(
            NGWWmsConnection,
            self.__model.resource(wms_layer.service_resource_id),
        )
        if wms_connection is None:
            message = (
                f"Connecton for WMS layer {wms_layer.display_name}"
                " is not accessible"
            )
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        return wms_layer.layer_params(wms_connection)

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
            logger.warning(f'Layer "{raster_layer.display_name}" was skipped')
            self.__skipped_resources.add(raster_layer.resource_id)
            return ("", "", "")

        return raster_layer.layer_params

    def __create_layers(self) -> None:
        if len(self.__layers_params) == 0:
            return

        task = LayerCreatorTask(self.__layers_params)

        event_loop = QEventLoop()
        task.taskCompleted.connect(event_loop.exit)
        task.taskTerminated.connect(event_loop.exit)
        NgConnectInterface.instance().task_manager.addTask(task)
        event_loop.exec()

        self.__layers = task.layers

        if all(not layer.isValid() for layer in self.__layers.values()):
            message = "All layers is invalid"
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        QgsProject.instance().addMapLayers(
            self.__layers.values(), addToLegend=False
        )

    def __add_fields_aliases(
        self,
        ngw_vector_layer: NGWAbstractVectorResource,
        qgs_vector_layer: QgsVectorLayer,
    ) -> None:
        qgs_fields = qgs_vector_layer.fields()
        for ngw_field in ngw_vector_layer.fields:
            if ngw_field.display_name is None:
                continue

            qgs_vector_layer.setFieldAlias(
                qgs_fields.indexFromName(ngw_field.keyname),
                ngw_field.display_name,
            )

    def __add_lookup_tables(
        self,
        ngw_vector_layer: NGWAbstractVectorResource,
        qgs_vector_layer: QgsVectorLayer,
    ) -> None:
        qgs_fields = qgs_vector_layer.fields()

        lookup_tables: Dict[int, List[Dict[str, str]]] = {}

        for ngw_field in ngw_vector_layer.fields:
            if ngw_field.lookup_table is None:
                continue

            lookup_table_id = ngw_field.lookup_table

            if lookup_table_id not in lookup_tables:
                lookup_table = self.__model.resource(ngw_field.lookup_table)
                lookup_tables[lookup_table_id] = [
                    {description: value}
                    for value, description in lookup_table._json[
                        "lookup_table"
                    ]["items"].items()
                ]

            setup = QgsEditorWidgetSetup(
                "ValueMap", {"map": lookup_tables[lookup_table_id]}
            )
            field_index = qgs_fields.indexFromName(ngw_field.keyname)
            qgs_vector_layer.setEditorWidgetSetup(field_index, setup)

    def __extract_styles(
        self, layer_index: Union[QModelIndex, NGWResource]
    ) -> List[NGWQGISStyle]:
        styles: List[NGWQGISStyle] = []
        if isinstance(layer_index, QModelIndex):
            for row in range(self.__model.rowCount(layer_index)):
                style_index = self.__model.index(row, 0, layer_index)
                style_resource = style_index.data(
                    QNGWResourceItem.NGWResourceRole
                )
                if isinstance(style_resource, NGWQGISStyle):
                    styles.append(style_resource)
        else:
            styles = [
                style
                for style in self.__model.children_resources(
                    layer_index.resource_id
                )
                if isinstance(style, NGWQGISStyle)
            ]

        return styles

    def __add_all_styles_to_layer(
        self,
        layer_index: Union[QModelIndex, NGWResource],
        qgs_layer: QgsMapLayer,
    ) -> None:
        styles = self.__extract_styles(layer_index)

        if len(styles) == 0:
            return

        styles.sort(key=lambda resource: resource.display_name)

        style_manager = qgs_layer.styleManager()
        assert style_manager is not None

        TEMP_NAME = "_TODELETE"
        style_manager.renameStyle(style_manager.currentStyle(), TEMP_NAME)

        # Add styles
        for style_resource in styles:
            style_resource = cast(NGWQGISStyle, style_resource)
            self.__add_style_to_layer(style_manager, style_resource)

        # Remove default style
        style_manager.removeStyle(TEMP_NAME)

        # Set default style
        styles_name = style_manager.styles()
        name_to_find = qgs_layer.name()
        if layer_index in self.__default_styles:
            resource = self.__model.resource(
                self.__default_styles[layer_index]
            )
            assert resource is not None
            name_to_find = resource.display_name

        default_style_index = (
            0
            if name_to_find not in styles_name
            else styles_name.index(name_to_find)
        )

        style_manager.setCurrentStyle(styles_name[default_style_index])

    def __replace_default_style(
        self, style_resource: NGWQGISStyle, qgs_layer: QgsMapLayer
    ):
        style_manager = qgs_layer.styleManager()
        assert style_manager is not None

        TEMP_NAME = "_TODELETE"
        style_manager.renameStyle(style_manager.currentStyle(), TEMP_NAME)

        self.__add_style_to_layer(style_manager, style_resource)

        # Remove default style
        style_manager.removeStyle(TEMP_NAME)

    def __add_style_to_layer(
        self,
        style_manager: QgsMapLayerStyleManager,
        style_resource: NGWQGISStyle,
    ):
        if not style_resource.is_qml_populated:
            message = (
                f'QML for style "{style_resource.display_name}"'
                " is not downloaded"
            )
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        style = QgsMapLayerStyle(style_resource.qml)
        if not style.isValid():
            message = (
                f'Unable apply style "{style_resource.display_name}"'
                " to the layer"
            )
            raise NgConnectError(
                code=ErrorCode.AddingError, log_message=message
            )

        style_manager.addStyle(style_resource.display_name, style)

    def __set_display_field(
        self,
        ngw_vector_layer: NGWAbstractVectorResource,
        qgs_vector_layer: QgsVectorLayer,
    ) -> None:
        for field in ngw_vector_layer.fields:
            if field.is_label:
                qgs_vector_layer.setDisplayExpression(f'"{field.keyname}"')
                break

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

        if self.__skip_wfs_with_z is None:
            message_box = QMessageBox()
            message_box.setWindowTitle(self.tr("Warning"))
            message_box.setText(
                self.tr(
                    "You are trying to add a WFS service containing a layer"
                    " with Z dimension. WFS in QGIS doesn't fully support"
                    " editing such geometries. You won't be able to edit and"
                    " create new features. You will only be able to delete"
                    " features.\nTo fix this, change geometry type of your"
                    " layer(s) and recreate WFS service."
                )
            )
            message_box.setIcon(QMessageBox.Icon.Warning)
            message_box.setStandardButtons(
                QMessageBox.StandardButtons()
                | QMessageBox.StandardButton.Ignore
                | QMessageBox.StandardButton.Cancel
            )
            message_box.button(QMessageBox.StandardButton.Ignore).setText(
                self.tr("Add anyway")
            )
            message_box.button(QMessageBox.StandardButton.Cancel).setText(
                self.tr("Skip")
            )
            result = message_box.exec()

            self.__skip_wfs_with_z = (
                result == QMessageBox.StandardButton.Cancel
            )

        if not self.__skip_wfs_with_z:
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

    @staticmethod
    def __update_extent(extent: QgsReferencedRectangle) -> None:
        iface.mapCanvas().setReferencedExtent(extent)
        iface.mapCanvas().refresh()
