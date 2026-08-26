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

import functools
import re
import uuid
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
)

from qgis.core import QgsFeedback
from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSize,
    Qt,
    QThread,
    QVariant,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPalette

from nextgis_connect.features.search.domain.query import (
    NgwSearchQueryBuilder,
    SearchQueryParser,
)
from nextgis_connect.features.synchronization.infrastructure.storage.cache_maintenance_service import (
    CacheMaintenanceService,
)
from nextgis_connect.legacy.detached_editing.container.container_factory import (
    DetachedContainerFactory,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.ngw.core import (
    NGWGroupResource,
    NGWResource,
    NGWVectorLayer,
)
from nextgis_connect.legacy.ngw.core.ngw_qgis_style import NGWQGISVectorStyle
from nextgis_connect.legacy.ngw.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.legacy.ngw.core.ngw_webmap import NGWWebMap
from nextgis_connect.legacy.ngw.qgis.ngw_resource_model_4qgis import (
    MapForLayerCreater,
    NGWCreateWMSService,
    NGWUpdateRasterLayer,
    NGWUpdateVectorLayer,
    QGISProjectUploader,
    QGISResourcesUploader,
    QGISStyleAdder,
    QGISStyleUpdater,
    ResourcesDownloader,
)
from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.legacy.ngw.qt.qt_ngw_resource_model_job import (
    NGWCreateMapForStyle,
    NGWCreateOgcfService,
    NGWCreateVectorLayer,
    NGWCreateWfsService,
    NGWGroupCreater,
    NGWMissingResourceUpdater,
    NGWRenameResource,
    NGWResourceBatchDelete,
    NGWResourceDelete,
    NGWResourceDeletePreviewLoader,
    NGWResourceModelJob,
    NGWResourceModelJobResult,
    NGWResourceUpdater,
    NGWRootResourcesLoader,
    NgwStylesDownloader,
    UploadedLayerResource,
)
from nextgis_connect.legacy.ngw.qt.qt_ngw_resource_model_job_error import (
    NGWResourceModelJobError,
)
from nextgis_connect.legacy.ngw_connection import NgwConnectionsManager
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis import utils
from nextgis_connect.platform.qgis.errors import (
    ErrorCode,
    NgConnectError,
    NgwConnectionError,
    NgwError,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.ui_kit.graphics import (
    LoadingIndicatorRenderer,
    NextgisDecorator,
    mix_colors,
)
from nextgis_connect.ui_kit.widgets.loading_indicator import (
    LoadingIndicatorIconAnimator,
)

from .item import QModelItem, QNGWResourceItem

__all__ = ["QNGWResourceTreeModel"]


class ResourceTreeLoadingIndicatorRenderer(LoadingIndicatorRenderer):
    PEN_WIDTH = 2.4
    TRACK_ALPHA = 210
    TRACK_FADE = 0.50

    def __init__(self) -> None:
        super().__init__(pen_width=self.PEN_WIDTH)

    def _resolved_arc_color(
        self,
        palette: QPalette,
        *,
        selected: bool,
    ) -> QColor:
        if selected:
            return palette.color(QPalette.ColorRole.HighlightedText)

        return NextgisDecorator.system_text_color(palette)

    def _resolved_track_color(
        self,
        palette: QPalette,
        *,
        selected: bool,
    ) -> QColor:
        background_color = (
            palette.color(QPalette.ColorRole.Highlight)
            if selected
            else NextgisDecorator.system_base_color(palette)
        )
        color = mix_colors(
            self._resolved_arc_color(palette, selected=selected),
            background_color,
            self.TRACK_FADE,
        )
        color.setAlpha(self.TRACK_ALPHA)

        return color


class NGWResourceModelResponse(QObject):
    delete_preview_loaded = pyqtSignal(object)
    done = pyqtSignal(QModelIndex)
    failed = pyqtSignal(object)
    finished = pyqtSignal()
    select = pyqtSignal(list)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.job_id = None
        self.job_uuid = ""
        self.__errors = {}
        self.warnings = []
        self.uploaded_layers: List[UploadedLayerResource] = []

    def errors(self):
        return self.__errors


class NGWResourcesModelJob(QObject):
    started = pyqtSignal()
    statusChanged = pyqtSignal(str)
    warningOccurred = pyqtSignal(object)
    errorOccurred = pyqtSignal(object)
    finished = pyqtSignal()

    __thread: Optional[QThread]
    __worker: NGWResourceModelJob
    __job_id: str
    __job_uuid: str
    __result: Optional[NGWResourceModelJobResult]
    __error: Optional[NGWResourceModelJobError]

    def __init__(self, parent: QObject, worker: NGWResourceModelJob):
        super().__init__(parent)
        self.__thread = None
        self.__worker = worker
        self.__job_id = self.__worker.id
        self.__job_uuid = str(uuid.uuid4())
        self.__result = None
        self.__error = None
        self.__is_finished = False

        self.__worker.started.connect(self.started.emit)
        self.__worker.dataReceived.connect(self.__rememberResult)
        self.__worker.statusChanged.connect(self.statusChanged.emit)
        self.__worker.errorOccurred.connect(self.processJobError)
        self.__worker.warningOccurred.connect(self.processJobWarnings)

        self.model_response = None

    def setResponseObject(self, response: NGWResourceModelResponse) -> None:
        self.model_response = response
        self.model_response.job_id = self.__job_id
        self.model_response.job_uuid = self.__job_uuid

    def __rememberResult(self, result: NGWResourceModelJobResult) -> None:
        self.__result = result

    def getJobId(self) -> str:
        return self.__job_id

    def getJobUuid(self) -> str:
        return self.__job_uuid

    def getResult(self) -> Optional[NGWResourceModelJobResult]:
        return self.__result

    def error(self) -> Optional[NGWResourceModelJobError]:
        return self.__error

    def processJobError(self, job_error):
        self.__error = job_error
        self.errorOccurred.emit(job_error)

    def processJobWarnings(self, job_error):
        if self.model_response:
            self.model_response.warnings.append(job_error)
        # self.warningOccurred.emit(job_error)

    def start(self):
        NgConnectInterface.instance().disable_synchronization()

        self.__thread = QThread(self)
        self.__worker.moveToThread(self.__thread)
        self.__worker.finished.connect(self.finishProcess)
        self.__thread.started.connect(self.__worker.run)

        self.__thread.start()

    def cancel(self) -> None:
        self.__worker.cancel()

    def cancel_and_wait(self) -> None:
        self.cancel()
        if self.__thread is None:
            return

        self.__thread.quit()
        self.__thread.wait()
        self.__finish(emit_finished=False)

    def finishProcess(self):
        self.__finish(emit_finished=True)

    def __finish(self, *, emit_finished: bool) -> None:
        if self.__is_finished:
            return

        if self.__thread is None:
            return

        self.__is_finished = True
        self.__safe_worker_disconnect()

        self.__thread.quit()
        self.__thread.wait()
        self.__thread = None

        if emit_finished:
            self.finished.emit()
        NgConnectInterface.instance().enable_synchronization()

    def __safe_worker_disconnect(self) -> None:
        for signal in (
            self.__worker.started,
            self.__worker.dataReceived,
            self.__worker.statusChanged,
            self.__worker.errorOccurred,
            self.__worker.warningOccurred,
            self.__worker.finished,
        ):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass


class NgwCreateVectorLayersStubs(NGWResourceModelJob):
    def __init__(
        self,
        ngw_resources: Union[NGWVectorLayer, List[NGWVectorLayer]],
    ) -> None:
        super().__init__()
        self._feedback = QgsFeedback()
        if isinstance(ngw_resources, list):
            self.ngw_resources = ngw_resources
        else:
            self.ngw_resources = [ngw_resources]
            self.result.main_resource_id = ngw_resources.resource_id

    def _do(self):
        connections_manager = NgwConnectionsManager()

        storage_service = DetachedStorageServiceFactory.create()

        detached_factory = DetachedContainerFactory()

        total = str(len(self.ngw_resources))
        for i, ngw_resource in enumerate(self.ngw_resources):
            if self._feedback.isCanceled():
                raise NgConnectError("Request was canceled")

            name = ngw_resource.display_name
            progress = "" if total == "1" else f"\n({i + 1}/{total})"
            self.statusChanged.emit(
                self.tr('Processing layer "{name}"').format(name=name)
                + progress
            )

            connection = connections_manager.connection(
                ngw_resource.connection_id
            )
            assert connection is not None

            # TODO: optimizations. e.g. fetch common dir for resources
            ngw_resource.update(skip_children=True)

            gpkg_path = storage_service.container_path(
                connection.domain_uuid, ngw_resource.resource_id
            )
            detached_factory.create_initial_container(ngw_resource, gpkg_path)
            storage_service.register_detached_container(
                connection.domain_uuid,
                ngw_resource.resource_id,
                connection_id=connection.id,
                container_path=gpkg_path,
            )


class NgwSearch(NGWResourceModelJob):
    CURRENT_USER_ALIAS: ClassVar[str] = "me"

    def __init__(
        self,
        search_string: str,
        populated_resources: Set[int],
    ) -> None:
        super().__init__()
        self.result.found_resources = []
        self.search_string = search_string.strip()
        self.populated_resources = populated_resources
        self.users_keyname = {}
        self.users_username = {}
        self.current_user_id: Optional[int] = None
        self.parents = []
        self._feedback = QgsFeedback()
        self.__query_parser = SearchQueryParser()
        self.__query_builder = NgwSearchQueryBuilder(self)

    def _do(self):
        connections_manager = NgwConnectionsManager()
        connection_id = connections_manager.current_connection_id
        assert connection_id is not None
        ngw_connection = QgsNgwConnection(connection_id)

        resources_factory = NGWResourceFactory(ngw_connection)

        try:
            for query in self.__queries():
                self.__raise_if_canceled()
                logger.debug(f"Search for {query}")
                search_url = (
                    f"/api/resource/search/?{query}&serialization=resource"
                )
                query_result = ngw_connection.get(
                    search_url,
                    feedback=self._feedback,
                )
                self.__raise_if_canceled()
                self.__process_results(resources_factory, query_result)

            assert self.result.found_resources is not None
            logger.debug(
                f"<b>✓ Found</b> {len(self.result.found_resources)} resources: {self.result.found_resources}"
            )

            if len(self.result.found_resources) == 0:
                self.result.found_resources.append(-1)

            self.__fetch_parents(resources_factory)
        except Exception:
            if self.__is_canceled():
                self.result.found_resources = []

            self.result.added_resources = []
            raise

    def __is_canceled(self) -> bool:
        return self._feedback is not None and self._feedback.isCanceled()

    def __raise_if_canceled(self) -> None:
        if not self.__is_canceled():
            return

        raise NgConnectError("Request was canceled")

    def __process_results(
        self, factory: NGWResourceFactory, resources: List[Dict[str, Any]]
    ) -> None:
        self.result.found_resources.extend(
            resource_json["resource"]["id"] for resource_json in resources
        )
        for resource_json in resources:
            parent = resource_json["resource"].get("parent")
            parent_id = 0
            if parent is not None:
                parent_id = parent["id"]
            self.parents.append(parent_id)

    def __queries(self) -> List[str]:
        if self.__has_mixed_boolean_operators():
            logger.warning("only one operator type is supported at a time")
        parsed_search = self.__query_parser.parse(self.search_string)
        if parsed_search.is_fallback and self.search_string.startswith("@"):
            logger.debug("Wrong syntax. Fallback to display_name query")

        return self.__query_builder.build(parsed_search)

    def __has_mixed_boolean_operators(self) -> bool:
        lower_search_string = self.search_string.lower()
        and_operator_count = lower_search_string.count(" and ")
        or_operator_count = lower_search_string.count(" or ")
        return and_operator_count > 0 and or_operator_count > 0

    def __fetch_users(self) -> None:
        if len(self.users_keyname) > 0:
            return

        self.__raise_if_canceled()

        connections_manager = NgwConnectionsManager()
        connection_id = connections_manager.current_connection_id
        try:
            assert connection_id is not None
            ngw_connection = QgsNgwConnection(connection_id)
            result = ngw_connection.get(
                "api/component/auth/user/?brief=true",
                feedback=self._feedback,
            )
            self.__raise_if_canceled()
            for user in result:
                self.users_keyname[user["keyname"]] = user["id"]
                self.users_username[user["display_name"]] = user["id"]
        except Exception:
            if self.__is_canceled():
                raise

            logger.exception("Can't fetch users")

    def resolve_equal(self, values: List[str]) -> List[int]:
        user_ids = set()

        non_alias_values = [
            value
            for value in values
            if not self.__is_current_user_alias(value)
        ]
        if len(non_alias_values) > 0:
            self.__fetch_users()

        missing_values = []
        for value in values:
            user_id = self.__user_id_for_owner_value(value)
            if user_id is None:
                missing_values.append(value)
                continue

            user_ids.add(user_id)

        if len(missing_values) > 0:
            self.__raise_user_not_found(missing_values)

        return sorted(user_ids)

    def resolve_like(self, operator: str, value: str) -> List[int]:
        if self.__is_current_user_alias(value):
            current_user_id = self.__fetch_current_user_id()
            if current_user_id is None:
                self.__raise_user_not_found([value])

            return [current_user_id]

        self.__fetch_users()

        user_ids = set()
        regex_pattern = self.__like_value_regex_pattern(value)
        regex_flags = re.IGNORECASE if operator == "__ilike" else 0
        regex = re.compile(f"^{regex_pattern}$", regex_flags)
        user_ids.update(
            user_id
            for key, user_id in self.users_keyname.items()
            if regex.match(key)
        )
        user_ids.update(
            user_id
            for key, user_id in self.users_username.items()
            if regex.match(key)
        )

        if len(user_ids) == 0:
            self.__raise_user_not_found([value])

        return sorted(user_ids)

    def __user_id_for_owner_value(self, value: str) -> Optional[int]:
        if self.__is_current_user_alias(value):
            return self.__fetch_current_user_id()

        return self.users_keyname.get(
            value,
            self.users_username.get(value),
        )

    def __is_current_user_alias(self, value: str) -> bool:
        return value.strip().casefold() == self.CURRENT_USER_ALIAS

    def __fetch_current_user_id(self) -> Optional[int]:
        if self.current_user_id is not None:
            return self.current_user_id

        self.__raise_if_canceled()

        connections_manager = NgwConnectionsManager()
        connection_id = connections_manager.current_connection_id
        try:
            assert connection_id is not None
            ngw_connection = QgsNgwConnection(connection_id)
            result = ngw_connection.get(
                "api/component/auth/current_user",
                feedback=self._feedback,
            )
            self.__raise_if_canceled()
            if not isinstance(result, dict):
                return None

            user_id = result.get("id")
            if isinstance(user_id, int) and not isinstance(user_id, bool):
                self.current_user_id = user_id
                return self.current_user_id

            if isinstance(user_id, str) and user_id.isdecimal():
                self.current_user_id = int(user_id)
                return self.current_user_id
        except Exception:
            if self.__is_canceled():
                raise

            logger.exception("Can't fetch current user")

        return None

    def __like_value_regex_pattern(self, value: str) -> str:
        pattern = []
        for character in value:
            if character == "%":
                pattern.append(".*")
            elif character == "_":
                pattern.append(".")
            else:
                pattern.append(re.escape(character))

        return "".join(pattern)

    def __raise_user_not_found(self, values: List[str]) -> None:
        raise NgConnectError(
            self.tr("User not found: {user}").format(
                user=", ".join(sorted(values)),
            )
        )

    def __fetch_parents(self, resources_factory: NGWResourceFactory) -> None:
        logger.debug("◴ Fetching intermediate resources")

        for parent_id in self.parents:
            self.__raise_if_canceled()
            if parent_id in self.populated_resources:
                continue
            self.__fetch_children(resources_factory, parent_id)

        sorted_added_resources = []

        # Add toppest items
        for resource in self.result.added_resources:
            has_parent_ln_list = False
            for other_resource in self.result.added_resources:
                if other_resource.resource_id == resource.parent_id:
                    has_parent_ln_list = True
                    break
            if not has_parent_ln_list:
                sorted_added_resources.append(resource)

        while len(sorted_added_resources) != len(self.result.added_resources):
            for parent_resource in sorted_added_resources:
                for other_resource in self.result.added_resources:
                    if parent_resource.resource_id == other_resource.parent_id:
                        sorted_added_resources.append(other_resource)

        self.result.added_resources = sorted_added_resources

        logger.debug("✓ All intermediate resources are fetched")

    def __fetch_children(
        self, resources_factory: NGWResourceFactory, resource_id: int
    ) -> None:
        self.__raise_if_canceled()
        children_json = NGWResource.receive_resource_children(
            resources_factory.connection,
            resource_id,
            feedback=self._feedback,
        )
        self.__raise_if_canceled()

        children: List[NGWResource] = []
        for child_json in children_json:
            children.append(resources_factory.get_resource_by_json(child_json))

        self.populated_resources.add(resource_id)

        if len(children) == 0:
            logger.error(f"Empty children list for resource {resource_id}")
            return

        self.result.added_resources = children + self.result.added_resources
        grandparent_id = children[0].grandparent_id
        if (
            grandparent_id is not None
            and grandparent_id not in self.populated_resources
        ):
            self.__fetch_children(resources_factory, grandparent_id)


class QNGWResourceTreeModelBase(QAbstractItemModel):
    _LOCKED_ITEM_TEXT_FADE: ClassVar[float] = 0.32

    jobStarted = pyqtSignal(str)
    jobStatusChanged = pyqtSignal(str, str)
    errorOccurred = pyqtSignal(str, str, Exception)
    warningOccurred = pyqtSignal(str, str, Exception)
    jobFinished = pyqtSignal(str, str)
    indexesLocked = pyqtSignal()
    indexesUnlocked = pyqtSignal()
    fetchErrorReadyForRetry = pyqtSignal(QModelIndex)

    found_resources_changed = pyqtSignal(list)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._ngw_connection = None

        self.jobs = []
        self.root_item = QModelItem()
        self.ngw_version = None
        self.support_status = None
        self._version_check_feedback: Optional[QgsFeedback] = None

        self._dangling_resources: Dict[int, NGWResource] = {}
        self.__not_permitted_resources = set()

        self._found_resources_id = []

        self.__indexes_locked_by_jobs = {}
        self.__indexes_locked_by_job_errors = {}
        self.__loading_icon = LoadingIndicatorIconAnimator(
            QSize(16, 16),
            renderer=ResourceTreeLoadingIndicatorRenderer(),
            parent=self,
        )
        self.__loading_icon.frame_changed.connect(
            self.__emit_locked_indexes_decoration_changed
        )

    def resetModel(self, ngw_connection: Optional[QgsNgwConnection]):
        self.__loading_icon.stop()
        self.beginResetModel()

        self._ngw_connection = ngw_connection
        if ngw_connection is not None:
            self._ngw_connection.invalidate_cached_ngw_components()
            self._ngw_connection.setParent(self)

        self.ngw_version = None
        self.support_status = None

        self.__cleanModel()
        self.root_item = QModelItem()

        self.jobs = []
        self.__indexes_locked_by_jobs = {}
        self.__indexes_locked_by_job_errors = {}
        self._dangling_resources = {}
        self.__not_permitted_resources = set()

        request_error = None
        # Get NGW version.
        if ngw_connection is not None:
            self._version_check_feedback = QgsFeedback()
            try:
                self.ngw_version = self._ngw_connection.get_version(
                    feedback=self._version_check_feedback
                )
                self.support_status = utils.is_version_supported(
                    self.ngw_version
                )
            except NgwError as error:
                if error.code == ErrorCode.NotFound:
                    request_error = NgwConnectionError(
                        code=ErrorCode.InvalidConnection
                    )
                    request_error.__cause__ = error
                else:
                    request_error = error

                self.ngw_version = None
                self.support_status = None
            except Exception as error:
                request_error = error
                self.ngw_version = None
                self.support_status = None
            finally:
                self._version_check_feedback = None

        self.endResetModel()

        if request_error is not None:
            self.errorOccurred.emit("", "", request_error)

    def cleanModel(self):
        self.__cleanModel()

    def __cleanModel(self):
        c = self.root_item.childCount()
        self.beginRemoveRows(QModelIndex(), 0, c - 1)
        for i in range(c - 1, -1, -1):
            self.root_item.removeChild(self.root_item.child(i))
        self.endRemoveRows()

    def item(self, index: QModelIndex) -> QModelItem:
        return (
            index.internalPointer()
            if index and index.isValid()
            else self.root_item
        )

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = QModelIndex(),  # noqa: B008
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_item = self.item(parent)
        child_item = parent_item.child(row)
        assert child_item is not None
        return self.createIndex(row, column, child_item)

    def parent(self, child: QModelIndex) -> QModelIndex:
        assert child.model() == self if child.isValid() else True

        item = self.item(child)

        if item is self.root_item or item.parent() is self.root_item:
            return QModelIndex()

        parent_item = item.parent()
        assert parent_item is not None

        return self.createIndex(
            parent_item.parent().indexOfChild(parent_item), 0, parent_item
        )

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        parent_item = self.item(parent)
        return parent_item.childCount()

    def canFetchMore(self, parent: QModelIndex) -> bool:
        if (
            not self.is_ngw_version_supported
            or self._isIndexLockedByJob(parent)
            or self._isIndexLockedByJobError(parent)
        ):
            return False

        item = self.item(parent)

        if item is self.root_item:
            if self._ngw_connection is None:
                return False
            # We expect only one root resource group
            return item.childCount() == 0

        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)
        if (
            ngw_resource.common.children
            and ngw_resource.children_count is not None
        ):
            return ngw_resource.children_count > item.childCount()

        return ngw_resource.common.children and item.childCount() == 0

    def fetchMore(self, parent: QModelIndex) -> None:
        if not self.canFetchMore(parent):
            return

        parent_item = self.item(parent)
        assert isinstance(parent_item, QModelItem)
        if parent_item is self.root_item:
            worker = NGWRootResourcesLoader(self._ngw_connection)
            logger.debug("↓ Fetch root resource")
        else:
            ngw_resource = parent_item.data(QNGWResourceItem.NGWResourceRole)
            worker = NGWResourceUpdater(ngw_resource, [])

        self._startJob(worker, parent)

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> QVariant:
        item = self.item(index)
        resource_id = item.data(QNGWResourceItem.NGWResourceIdRole)

        if (
            role == Qt.ItemDataRole.DecorationRole
            and index.isValid()
            and item.locked
        ):
            return self.__loading_icon.current_icon()

        if (
            role == Qt.ItemDataRole.ForegroundRole
            and index.isValid()
            and item.locked
        ):
            return self.__locked_item_foreground()

        data = item.data(role)

        if (
            role == Qt.ItemDataRole.FontRole
            and resource_id in self._found_resources_id
        ):
            font: QFont = QFont()
            font.setBold(True)
            return font

        return data

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: B008
        parent_item = self.item(parent)
        if not isinstance(parent_item, QNGWResourceItem):
            return parent_item.childCount() > 0

        ngw_resource = cast(
            NGWResource, parent_item.data(QNGWResourceItem.NGWResourceRole)
        )
        children = ngw_resource.common.children
        has_fetched_children = children and ngw_resource.children_count != 0
        has_loaded_children = parent_item.childCount() > 0
        return has_fetched_children or has_loaded_children

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        return self.item(index).flags()

    def __locked_item_foreground(self) -> QBrush:
        palette = NextgisDecorator.system_palette()
        color = mix_colors(
            NextgisDecorator.system_text_color(palette),
            NextgisDecorator.system_window_color(palette),
            self._LOCKED_ITEM_TEXT_FADE,
        )
        return QBrush(color)

    def _startJob(
        self,
        worker: NGWResourceModelJob,
        lock_indexes: Union[List[QModelIndex], QModelIndex, None] = None,
    ):
        job = NGWResourcesModelJob(self, worker)
        job.started.connect(self.__jobStartedProcess)
        job.statusChanged.connect(self.__jobStatusChangedProcess)
        job.finished.connect(self.__jobFinishedProcess)
        job.errorOccurred.connect(self.__jobErrorOccurredProcess)
        job.warningOccurred.connect(self.__jobWarningOccurredProcess)

        self.jobs.append(job)

        indexes_for_lock: List[QModelIndex] = []
        if isinstance(lock_indexes, QModelIndex):
            indexes_for_lock = [lock_indexes]
        elif lock_indexes is not None:
            indexes_for_lock = lock_indexes

        self._lockIndexByJob(indexes_for_lock, job)

        job.start()

        return job

    def cancel_job(self, job_id: str) -> bool:
        if (
            job_id == "NGWRootResourcesLoader"
            and self._version_check_feedback is not None
        ):
            self._version_check_feedback.cancel()
            return True

        for job in list(self.jobs):
            if job.getJobId() != job_id:
                continue

            job.cancel()
            return True

        return False

    def shutdown_jobs(self) -> None:
        if self._version_check_feedback is not None:
            self._version_check_feedback.cancel()
            self._version_check_feedback = None

        for job in list(self.jobs):
            job.cancel_and_wait()
            self._unlockIndexesByJob(job)
            if job in self.jobs:
                self.jobs.remove(job)
            job.deleteLater()

        self.__sync_loading_indicator_animation()

    def __jobStartedProcess(self):
        job = cast(NGWResourcesModelJob, self.sender())
        self.jobStarted.emit(job.getJobId())

    def __jobStatusChangedProcess(self, new_status):
        job = cast(NGWResourcesModelJob, self.sender())
        self.jobStatusChanged.emit(job.getJobId(), new_status)

    def __jobFinishedProcess(self):
        job = cast(NGWResourcesModelJob, self.sender())

        self.processJobResult(job)
        self._unlockIndexesByJob(job)

        self.jobFinished.emit(job.getJobId(), job.getJobUuid())
        self.jobs.remove(job)
        job.deleteLater()

    def __jobErrorOccurredProcess(self, error):
        job = cast(NGWResourcesModelJob, self.sender())
        self.__add_fetch_retry_action(job, error)
        self.errorOccurred.emit(job.getJobId(), job.getJobUuid(), error)

    def __add_fetch_retry_action(
        self,
        job: NGWResourcesModelJob,
        error: Exception,
    ) -> None:
        if (
            job.getJobId() != "NGWResourceUpdater"
            or not isinstance(error, NgConnectError)
            or error.try_again is not None
        ):
            return

        locked_indexes = self.__indexes_locked_by_jobs.get(job, [])
        persistent_indexes = tuple(
            QPersistentModelIndex(index)
            for index in locked_indexes
            if index.isValid()
        )
        if len(persistent_indexes) == 0:
            return

        error.try_again = lambda: self.__retry_fetch(persistent_indexes)

    def __jobWarningOccurredProcess(self, error):
        job = cast(NGWResourcesModelJob, self.sender())
        self.warningOccurred.emit(job.getJobId(), job.getJobUuid(), error)

    def addNGWResourceToTree(self, parent: QModelIndex, ngw_resource):
        parent_item = self.item(parent)
        parent_resource = parent_item.data(QNGWResourceItem.NGWResourceRole)

        new_item = QNGWResourceItem(ngw_resource)
        i = -1
        for i in range(parent_item.childCount()):
            item = parent_item.child(i)
            if new_item.more_priority(item):
                break
        else:
            i += 1

        self.beginInsertRows(parent, i, i)
        parent_item.insertChild(i, new_item)
        if (
            isinstance(parent_resource, NGWResource)
            and not parent_resource.common.children
        ):
            parent_resource.common.children = True
        self.endInsertRows()

        return self.index(i, 0, parent)

    def _lockIndexByJob(self, indexes: List[QModelIndex], job):
        if job not in self.__indexes_locked_by_jobs:
            self.__indexes_locked_by_jobs[job] = []
        self.__indexes_locked_by_jobs[job].extend(indexes)

        for index in indexes:
            item = self.item(index)
            item.lock()
            self.dataChanged.emit(index, index)

        self.__sync_loading_indicator_animation()
        self.indexesLocked.emit()

    def _unlockIndexesByJob(self, job):
        indexes = self.__indexes_locked_by_jobs.get(job, [])
        self.__indexes_locked_by_jobs[job] = []
        failed_fetch_indexes: List[QModelIndex] = []

        for index in indexes:
            item = self.item(index)
            item.unlock()
            if job.error() is not None:
                self.__indexes_locked_by_job_errors[index] = job.error()
                if job.getJobId() == "NGWResourceUpdater":
                    failed_fetch_indexes.append(index)

            self.dataChanged.emit(index, index)

        self.__sync_loading_indicator_animation()
        self.indexesUnlocked.emit()

        for index in failed_fetch_indexes:
            self.fetchErrorReadyForRetry.emit(index)
            self.clear_fetch_error(index)
            self.__emit_has_children_changed(index)

    def _isIndexLockedByJob(self, index):
        for indexes in self.__indexes_locked_by_jobs.values():
            if index in indexes:
                return True
        return False

    def _isIndexLockedByJobError(self, index):
        return index in self.__indexes_locked_by_job_errors

    def clear_fetch_error(self, index: QModelIndex) -> bool:
        """Allow fetching an index again after a failed request.

        :param index: Resource group index to unlock.
        :return: ``True`` if a failed request was registered for the index.
        """
        return self.__indexes_locked_by_job_errors.pop(index, None) is not None

    def refresh_lazy_children_state(self, index: QModelIndex) -> None:
        if not index.isValid() or not self.hasChildren(index):
            return

        self.__emit_has_children_changed(index)

    def __emit_has_children_changed(self, index: QModelIndex) -> None:
        if not index.isValid():
            return

        self.dataChanged.emit(index, index)

    def __retry_fetch(
        self,
        persistent_indexes: Tuple[QPersistentModelIndex, ...],
    ) -> None:
        for persistent_index in persistent_indexes:
            if not persistent_index.isValid():
                continue

            index = QModelIndex(persistent_index)
            self.clear_fetch_error(index)
            if self.canFetchMore(index):
                self.fetchMore(index)

    def __locked_indexes(self) -> List[QModelIndex]:
        result = []

        for indexes in self.__indexes_locked_by_jobs.values():
            result.extend(index for index in indexes if index.isValid())

        return result

    def __sync_loading_indicator_animation(self) -> None:
        if len(self.__locked_indexes()) > 0:
            self.__loading_icon.start()
            return

        self.__loading_icon.stop()

    def __emit_locked_indexes_decoration_changed(self) -> None:
        for index in self.__locked_indexes():
            self.dataChanged.emit(index, index)

    def index_from_id(self, ngw_resource_id, parent=None):
        if parent is None:
            parent = self.index(0, 0, QModelIndex())
        item = parent.internalPointer()

        if (
            isinstance(item, QNGWResourceItem)
            and item.ngw_resource_id() == ngw_resource_id
        ):
            return parent

        for i in range(item.childCount()):
            index = self.index_from_id(
                ngw_resource_id, self.index(i, 0, parent)
            )

            if index is not None:
                return index

        return None

    def resource(
        self, identifier: Union[int, QModelIndex, None]
    ) -> Optional[NGWResource]:
        if identifier is None:
            return None

        index = (
            identifier
            if isinstance(identifier, QModelIndex)
            else self.index_from_id(identifier)
        )
        if index is not None and index.isValid():
            return index.data(QNGWResourceItem.NGWResourceRole)

        return self._dangling_resources.get(identifier)

    def children_resources(
        self, parent_identifier: Union[int, QModelIndex]
    ) -> List[NGWResource]:
        parent_index = (
            parent_identifier
            if isinstance(parent_identifier, QModelIndex)
            else self.index_from_id(parent_identifier)
        )

        if parent_index is not None and parent_index.isValid():
            result = []
            for row in range(self.rowCount(parent_index)):
                child_index = self.index(row, 0, parent_index)
                result.append(
                    child_index.data(QNGWResourceItem.NGWResourceRole)
                )
            return result

        return [
            resource
            for resource in self._dangling_resources.values()
            if resource.parent_id == parent_identifier
        ]

    def is_forbidden(self, resource_id: int) -> bool:
        return resource_id in self.__not_permitted_resources

    def processJobResult(self, job: NGWResourcesModelJob):
        job_result = job.getResult()

        if job_result is None:
            # TODO Exception
            return

        if job.error() is not None:
            return

        if job.model_response is not None:
            job.model_response.uploaded_layers = list(
                job_result.uploaded_layer_resources
            )

        if (
            job_result.resource_delete_preview is not None
            and job.model_response is not None
        ):
            job.model_response.delete_preview_loaded.emit(
                job_result.resource_delete_preview
            )
            return

        if (
            job_result.is_empty()
            and job.model_response is not None
            and len(job.model_response.warnings) > 0
        ):
            job.model_response.done.emit(QModelIndex())
            return

        indexes = {}
        added_resources_id = []
        for ngw_resource in job_result.added_resources:
            if ngw_resource.common.parent is None:
                resource_id = QModelIndex()
                new_index = self.addNGWResourceToTree(
                    resource_id, ngw_resource
                )
            else:
                parent_id = ngw_resource.parent_id
                if parent_id not in indexes:
                    indexes[parent_id] = self.index_from_id(parent_id)
                resource_id = indexes[parent_id]

                item = resource_id.internalPointer()
                current_ids = [
                    item.child(i).ngw_resource_id()
                    for i in range(item.childCount())
                    if isinstance(item.child(i), QNGWResourceItem)
                ]
                if ngw_resource.resource_id not in current_ids:
                    new_index = self.addNGWResourceToTree(
                        resource_id, ngw_resource
                    )
                else:
                    continue

            added_resources_id.append(ngw_resource.resource_id)

            if job_result.main_resource_id == ngw_resource.resource_id:
                if job.model_response is not None:
                    job.model_response.done.emit(new_index)

        if len(added_resources_id) > 0 and job.model_response is not None:
            indexes_for_select = []

            for resource_id in added_resources_id:
                index = self.index_from_id(resource_id)
                parent = index.parent()
                parent_in_list = False
                while parent.isValid():
                    parent_id = parent.data(QNGWResourceItem.NGWResourceIdRole)
                    if parent_id in added_resources_id:
                        parent_in_list = True
                        break
                    parent = parent.parent()

                if parent_in_list:
                    continue

                indexes_for_select.append(index)

            job.model_response.select.emit(indexes_for_select)

        if len(indexes) == 0 and job.getJobId() == NGWResourceUpdater.__name__:
            ngw_index = self.index_from_id(job_result.main_resource_id)
            self.data(
                ngw_index, QNGWResourceItem.NGWResourceRole
            ).set_children_count(0)
            self.__emit_has_children_changed(ngw_index)
        elif len(indexes) > 0 and job_result.main_resource_id == -1:
            job.model_response.done.emit(QModelIndex())

        for ngw_resource in job_result.edited_resources:
            if ngw_resource.common.parent is None:
                self.cleanModel()  # remove root item
                resource_id = QModelIndex()
            else:
                resource_id = self.index_from_id(
                    ngw_resource.parent_id,
                )
                item = resource_id.internalPointer()

                for i in range(item.childCount()):
                    if (
                        item.child(i).ngw_resource_id()
                        == ngw_resource.resource_id
                    ):
                        self.beginRemoveRows(resource_id, i, i)
                        item.removeChild(item.child(i))
                        self.endRemoveRows()
                        break
                else:
                    # TODO exception: not find deleted resource in corrent tree
                    return

            new_index = self.addNGWResourceToTree(resource_id, ngw_resource)

            if job.model_response is not None:
                job.model_response.done.emit(new_index)

        deleted_resource_ids = {
            ngw_resource.resource_id
            for ngw_resource in job_result.deleted_resources
        }
        for ngw_resource in job_result.deleted_resources:
            self._clear_deleted_resource_cache(ngw_resource)

            if ngw_resource.parent_id in deleted_resource_ids:
                continue

            resource_id = self.index_from_id(
                ngw_resource.parent_id,
            )
            item = resource_id.internalPointer()

            for i in range(item.childCount()):
                if item.child(i).ngw_resource_id() == ngw_resource.resource_id:
                    self.beginRemoveRows(resource_id, i, i)
                    item.removeChild(item.child(i))
                    self.endRemoveRows()
                    break
            else:
                # TODO exception: not find deleted resource in corrent tree
                return

            ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)
            ngw_resource.update()

            if job.model_response is not None:
                job.model_response.done.emit(resource_id)

        for ngw_resource in job_result.dangling_resources:
            self._dangling_resources[ngw_resource.resource_id] = ngw_resource

        if job_result.found_resources is not None:
            self.found_resources_changed.emit(job_result.found_resources)
            self._found_resources_id = job_result.found_resources

        self.__not_permitted_resources.update(
            job_result.not_permitted_resources
        )

    def _clear_deleted_resource_cache(self, ngw_resource: NGWResource) -> None:
        connection = NgwConnectionsManager().connection(
            ngw_resource.connection_id
        )
        if connection is None:
            return

        is_cleared = CacheMaintenanceService().clear_resource_cache(
            connection,
            ngw_resource.resource_id,
        )
        if is_cleared:
            return

        logger.warning(
            "Could not clear cache for deleted resource id=%s",
            ngw_resource.resource_id,
        )

    @property
    def is_ngw_version_supported(self) -> bool:
        if self.support_status is None:
            return False

        return self.support_status == utils.SupportStatus.SUPPORTED


def modelRequest(
    method: Callable[..., Optional[NGWResourcesModelJob]],
) -> Callable[..., Optional[NGWResourceModelResponse]]:
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        job = method(self, *args, **kwargs)
        if job is None:
            return None
        response = NGWResourceModelResponse(self)
        job.setResponseObject(response)
        job.errorOccurred.connect(response.failed.emit)
        job.finished.connect(response.finished.emit)
        return response

    return wrapper


class QNGWResourceTreeModel(QNGWResourceTreeModelBase):
    connection_id_changed = pyqtSignal(str)

    @property
    def connection_id(self) -> Optional[str]:
        if self._ngw_connection is None:
            return None
        return self._ngw_connection.connection_id

    @property
    def is_connected(self) -> bool:
        return self.ngw_version is not None

    def resetModel(self, ngw_connection: Optional[QgsNgwConnection]):
        self.reset_search()
        self.connection_id_changed.emit(
            ngw_connection.connection_id if ngw_connection is not None else ""
        )
        super().resetModel(ngw_connection)

    def _nearest_ngw_group_resource_parent(self, index):
        checking_index = index

        item = checking_index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        while not isinstance(ngw_resource, NGWGroupResource):
            checking_index = self.parent(checking_index)
            checking_item = checking_index.internalPointer()
            ngw_resource = checking_item.data(QNGWResourceItem.NGWResourceRole)

        return checking_index

    @modelRequest
    def tryCreateNGWGroup(self, new_group_name, parent_index):
        if not parent_index.isValid():
            parent_index = self.index(0, 0, parent_index)

        parent_index = self._nearest_ngw_group_resource_parent(parent_index)

        parent_item = parent_index.internalPointer()
        ngw_resource_parent = parent_item.data(parent_item.NGWResourceRole)

        return self._startJob(
            NGWGroupCreater(new_group_name, ngw_resource_parent)
        )

    @modelRequest
    def loadDeletePreview(self, indexes: List[QModelIndex]):
        resources = [
            index.data(QNGWResourceItem.NGWResourceRole)
            for index in self._extract_deletion_root_indexes(indexes)
        ]

        return self._startJob(NGWResourceDeletePreviewLoader(resources))

    @modelRequest
    def deleteResource(self, index):
        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(NGWResourceDelete(ngw_resource))

    @modelRequest
    def deleteResources(self, indexes: List[QModelIndex]):
        resources = [
            index.data(QNGWResourceItem.NGWResourceRole)
            for index in self._extract_deletion_root_indexes(indexes)
        ]

        return self._startJob(NGWResourceBatchDelete(resources))

    def _extract_deletion_root_indexes(
        self, indexes: List[QModelIndex]
    ) -> List[QModelIndex]:
        resource_ids = {
            index.data(QNGWResourceItem.NGWResourceIdRole)
            for index in indexes
            if index.isValid() and index.parent().isValid()
        }
        root_indexes = []
        used_resource_ids = set()

        for index in indexes:
            if not index.isValid():
                continue

            if not index.parent().isValid():
                continue

            resource_id = index.data(QNGWResourceItem.NGWResourceIdRole)
            if resource_id in used_resource_ids:
                continue

            if self._has_selected_parent(index, resource_ids):
                continue

            root_indexes.append(index)
            used_resource_ids.add(resource_id)

        return root_indexes

    def _has_selected_parent(
        self, index: QModelIndex, resource_ids: Set[int]
    ) -> bool:
        parent = index.parent()
        while parent.isValid():
            parent_id = parent.data(QNGWResourceItem.NGWResourceIdRole)
            if parent_id != 0 and parent_id in resource_ids:
                return True

            parent = parent.parent()

        return False

    @modelRequest
    def createWfsOrOgcfForVector(
        self, service_type: str, index: QModelIndex, max_features: int
    ):
        assert service_type in ("WFS", "OGC API - Features")
        if not index.isValid():
            index = self.index(0, 0, index)

        parent_index = self._nearest_ngw_group_resource_parent(index)

        parent_item = parent_index.internalPointer()
        ngw_parent_resource = parent_item.data(
            QNGWResourceItem.NGWResourceRole
        )

        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        job_type = (
            NGWCreateWfsService
            if service_type == "WFS"
            else NGWCreateOgcfService
        )

        return self._startJob(
            job_type(ngw_resource, ngw_parent_resource, max_features)
        )

    @modelRequest
    def createVectorLayer(
        self,
        parent_index: QModelIndex,
        vector_layer: Dict[str, Any],
    ):
        if not parent_index.isValid():
            parent_index = self.index(0, 0, parent_index)

        parent_index = self._nearest_ngw_group_resource_parent(parent_index)

        parent_item = parent_index.internalPointer()
        parent_resource = parent_item.data(parent_item.NGWResourceRole)

        return self._startJob(
            NGWCreateVectorLayer(parent_resource, vector_layer)
        )

    @modelRequest
    def createMapForStyle(self, index):
        if not index.isValid():
            index = self.index(0, 0, index)

        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(NGWCreateMapForStyle(ngw_resource))

    @modelRequest
    def renameResource(self, index, new_name):
        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(NGWRenameResource(ngw_resource, new_name))

    @modelRequest
    def uploadResourcesList(
        self, qgs_layer_tree_nodes, ngw_current_index, iface
    ):
        if not ngw_current_index.isValid():
            ngw_current_index = self.index(0, 0, ngw_current_index)

        ngw_group_index = self._nearest_ngw_group_resource_parent(
            ngw_current_index
        )
        group_item = ngw_group_index.internalPointer()
        ngw_group = group_item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(
            QGISResourcesUploader(
                qgs_layer_tree_nodes, ngw_group, iface, self.ngw_version
            )
        )

    @modelRequest
    def updateQGISStyle(self, qgs_map_layer, index):
        if not index.isValid():
            index = self.index(0, 0, index)

        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(QGISStyleUpdater(qgs_map_layer, ngw_resource))

    @modelRequest
    def addQGISStyle(self, qgs_map_layer, index):
        if not index.isValid():
            index = self.index(0, 0, index)

        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(QGISStyleAdder(qgs_map_layer, ngw_resource))

    @modelRequest
    def uploadProjectResources(
        self, ngw_group_name, ngw_current_index, iface, create_webmap=True
    ):
        if not ngw_current_index.isValid():
            ngw_current_index = self.index(0, 0, ngw_current_index)

        ngw_group_index = self._nearest_ngw_group_resource_parent(
            ngw_current_index
        )
        group_item = ngw_group_index.internalPointer()
        ngw_resource = group_item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(
            QGISProjectUploader(
                ngw_group_name,
                ngw_resource,
                iface,
                self.ngw_version,
                create_webmap=create_webmap,
            )
        )

    @modelRequest
    def createMapForLayer(self, index, ngw_style_id):
        if not index.isValid():
            index = self.index(0, 0, index)

        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(MapForLayerCreater(ngw_resource, ngw_style_id))

    @modelRequest
    def createWMSService(self, index, ngw_resource_style_id):
        if not index.isValid():
            index = self.index(0, 0, index)

        parent_index = self._nearest_ngw_group_resource_parent(index)

        parent_item = parent_index.internalPointer()
        ngw_parent_resource = parent_item.data(
            QNGWResourceItem.NGWResourceRole
        )

        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(
            NGWCreateWMSService(
                ngw_resource, ngw_parent_resource, ngw_resource_style_id
            )
        )

    @modelRequest
    def updateNGWVectorLayer(self, index, qgs_layer):
        if not index.isValid():
            index = self.index(0, 0, index)

        item = index.internalPointer()
        ngw_vector_layer = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(
            NGWUpdateVectorLayer(ngw_vector_layer, qgs_layer),
        )

    @modelRequest
    def updateNGWRasterLayer(self, index, qgs_layer):
        if not index.isValid():
            index = self.index(0, 0, index)

        item = index.internalPointer()
        ngw_raster_layer = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(
            NGWUpdateRasterLayer(ngw_raster_layer, qgs_layer),
        )

    @modelRequest
    def fetch_not_expanded(
        self, resources_id: List[int]
    ) -> Optional[NGWResourcesModelJob]:
        indexes_for_fetch: List[QModelIndex] = [
            self.index_from_id(resource_id) for resource_id in resources_id
        ]
        indexes_for_fetch = [
            index for index in indexes_for_fetch if index is not None
        ]
        ids_for_fetch = [
            resource_id
            for resource_id in resources_id
            if resource_id in self._dangling_resources
        ]

        if len(indexes_for_fetch) == 0 and len(ids_for_fetch) == 0:
            return None

        resources: List[NGWResource] = [
            cast(NGWResource, self.resource(index))
            for index in indexes_for_fetch
        ]
        dangling_resources: List[NGWResource] = [
            cast(NGWResource, self.resource(index)) for index in ids_for_fetch
        ]

        worker = NGWMissingResourceUpdater(
            resources, dangling_resources, recursive=True
        )
        return self._startJob(worker, lock_indexes=indexes_for_fetch)

    @modelRequest
    def fetch_missing(
        self, resources_id: List[int]
    ) -> Optional[NGWResourcesModelJob]:
        def is_not_downloaded(resource_id: int) -> bool:
            resource = self.resource(resource_id)
            return resource is None and not self.is_forbidden(resource_id)

        not_donloaded_resources_id = set(
            resource_id
            for resource_id in resources_id
            if is_not_downloaded(resource_id)
        )
        if len(not_donloaded_resources_id) == 0:
            return None

        worker = ResourcesDownloader(
            self._ngw_connection.connection_id, not_donloaded_resources_id
        )
        return self._startJob(worker)

    @modelRequest
    def search(self, search_string) -> Optional[NGWResourcesModelJob]:
        worker = NgwSearch(
            search_string,
            self.__collect_populated_resources(),
        )
        return self._startJob(worker)

    def reset_search(self) -> None:
        self.found_resources_changed.emit([])
        self._found_resources_id = []

    @modelRequest
    def download_vector_layers_if_needed(
        self, indexes: Union[QModelIndex, List[QModelIndex]]
    ):
        storage_service = DetachedStorageServiceFactory.create()
        connections_manager = NgwConnectionsManager()

        def collect_indexes(
            index: QModelIndex,
        ) -> Tuple[List[QModelIndex], List[QModelIndex]]:
            ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
            connection = connections_manager.connection(
                ngw_resource.connection_id
            )
            assert connection is not None

            if isinstance(ngw_resource, NGWVectorLayer):
                container_path = storage_service.container_path(
                    connection.domain_uuid, ngw_resource.resource_id
                )
                if container_path.exists():
                    return [index], []
                return [index], [index]

            if isinstance(ngw_resource, NGWQGISVectorStyle):
                parent = index.parent()
                parent_resource = parent.data(QNGWResourceItem.NGWResourceRole)
                if not isinstance(parent_resource, NGWVectorLayer):
                    return [], []

                container_path = storage_service.container_path(
                    connection.domain_uuid, parent_resource.resource_id
                )
                if container_path.exists():
                    return [parent, index], []
                return [parent, index], [parent]

            if not isinstance(ngw_resource, NGWGroupResource):
                return [], []

            indexes_for_lock: List[QModelIndex] = []
            indexes_for_fetch: List[QModelIndex] = []
            for row in range(self.rowCount(index)):
                child_index = self.index(row, 0, index)
                lock_indexes, fetch_indexes = collect_indexes(child_index)
                indexes_for_lock.extend(lock_indexes)
                indexes_for_fetch.extend(fetch_indexes)

            if len(indexes_for_lock) > 0:
                indexes_for_lock.append(index)

            return indexes_for_lock, indexes_for_fetch

        def collect_not_downloaded_webmap_layers(webmap: NGWWebMap):
            result = []
            for resource_id in webmap.all_resources_id:
                ngw_resource = self.resource(resource_id)
                if not isinstance(ngw_resource, NGWVectorLayer):
                    continue

                connection = connections_manager.connection(
                    ngw_resource.connection_id
                )
                assert connection is not None
                container_path = storage_service.container_path(
                    connection.domain_uuid, ngw_resource.resource_id
                )
                if container_path.exists():
                    continue

                result.append(ngw_resource)

            return result

        if isinstance(indexes, QModelIndex):
            indexes = [indexes]

        indexes_for_lock: List[QModelIndex] = []
        indexes_for_fetch: List[QModelIndex] = []
        for index in indexes:
            lock_indexes, fetch_indexes = collect_indexes(index)
            indexes_for_lock.extend(lock_indexes)
            indexes_for_fetch.extend(fetch_indexes)

        vector_layers: List[NGWVectorLayer] = [
            index.data(QNGWResourceItem.NGWResourceRole)
            for index in set(indexes_for_fetch)
        ]

        for index in indexes:
            webmap = index.data(QNGWResourceItem.NGWResourceRole)
            if not isinstance(webmap, NGWWebMap):
                continue
            vector_layers.extend(collect_not_downloaded_webmap_layers(webmap))

        if len(vector_layers) == 0:
            return None

        worker = NgwCreateVectorLayersStubs(vector_layers)
        return self._startJob(worker, lock_indexes=list(set(indexes_for_lock)))

    @modelRequest
    def fetch_missing_styles(
        self, resources_id: List[int]
    ) -> Optional[NGWResourcesModelJob]:
        if len(resources_id) == 0:
            return None

        indexes_for_lock: List[QModelIndex] = [
            self.index_from_id(resource_id) for resource_id in resources_id
        ]
        indexes_for_lock = [
            index for index in indexes_for_lock if index is not None
        ]

        resources = [
            self.resource(resource_id) for resource_id in resources_id
        ]

        worker = NgwStylesDownloader(resources)  # type: ignore
        return self._startJob(worker, lock_indexes=list(set(indexes_for_lock)))

    def __collect_populated_resources(
        self,
        parent: QModelIndex = QModelIndex(),  # noqa: B008
    ) -> Set[int]:
        result = set()

        if not self.canFetchMore(parent):
            result.add(parent.data(QNGWResourceItem.NGWResourceIdRole))

        for row in range(self.rowCount(parent)):
            child_index = self.index(row, 0, parent)
            result.update(self.__collect_populated_resources(child_index))

        return result
