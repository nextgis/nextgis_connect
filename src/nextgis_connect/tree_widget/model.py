import functools
import itertools
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
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
from urllib.parse import quote_plus

from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    QObject,
    Qt,
    QThread,
    QVariant,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QFont

from nextgis_connect import utils
from nextgis_connect.compat import parse_version
from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.exceptions import ErrorCode, NgwConnectionError, NgwError
from nextgis_connect.logging import logger
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.ngw_api.core import (
    NGWGroupResource,
    NGWResource,
    NGWVectorLayer,
)
from nextgis_connect.ngw_api.core.ngw_qgis_style import NGWQGISVectorStyle
from nextgis_connect.ngw_api.core.ngw_resource_factory import (
    NGWResourceFactory,
)
from nextgis_connect.ngw_api.core.ngw_webmap import NGWWebMap
from nextgis_connect.ngw_api.qgis.ngw_resource_model_4qgis import (
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
from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import QgsNgwConnection
from nextgis_connect.ngw_api.qt.qt_ngw_resource_model_job import (
    NGWCreateMapForStyle,
    NGWCreateOgcfService,
    NGWCreateVectorLayer,
    NGWCreateWfsService,
    NGWGroupCreater,
    NGWMissingResourceUpdater,
    NGWRenameResource,
    NGWResourceDelete,
    NGWResourceModelJob,
    NGWResourceModelJobResult,
    NGWResourceUpdater,
    NGWRootResourcesLoader,
    NgwStylesDownloader,
)
from nextgis_connect.ngw_api.qt.qt_ngw_resource_model_job_error import (
    NGWResourceModelJobError,
)
from nextgis_connect.ngw_connection import NgwConnectionsManager
from nextgis_connect.settings.ng_connect_cache_manager import (
    NgConnectCacheManager,
)

from .item import QModelItem, QNGWResourceItem

__all__ = ["QNGWResourceTreeModel"]


class NGWResourceModelResponse(QObject):
    done = pyqtSignal(QModelIndex)
    select = pyqtSignal(list)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.job_id = None
        self.job_uuid = ""
        self.__errors = {}
        self.warnings = []

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

    def finishProcess(self):
        if self.__thread is None:
            return

        self.__worker.started.disconnect()
        self.__worker.dataReceived.disconnect()
        self.__worker.statusChanged.disconnect()
        self.__worker.errorOccurred.disconnect()
        self.__worker.warningOccurred.disconnect()
        self.__worker.finished.disconnect()

        self.__thread.quit()
        self.__thread.wait()

        self.finished.emit()

        NgConnectInterface.instance().enable_synchronization()


class NgwCreateVectorLayersStubs(NGWResourceModelJob):
    def __init__(
        self,
        ngw_resources: Union[NGWVectorLayer, List[NGWVectorLayer]],
    ) -> None:
        super().__init__()
        if isinstance(ngw_resources, list):
            self.ngw_resources = ngw_resources
        else:
            self.ngw_resources = [ngw_resources]
            self.result.main_resource_id = ngw_resources.resource_id

    def _do(self):
        connections_manager = NgwConnectionsManager()

        cache_manager = NgConnectCacheManager()
        cache_directory = Path(cache_manager.cache_directory)

        detached_factory = DetachedLayerFactory()

        total = str(len(self.ngw_resources))
        for i, ngw_resource in enumerate(self.ngw_resources):
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

            instance_subdir = connection.domain_uuid
            instance_cache_path = cache_directory / instance_subdir
            instance_cache_path.mkdir(parents=True, exist_ok=True)
            gpkg_path = (
                instance_cache_path / f"{ngw_resource.resource_id}.gpkg"
            )
            detached_factory.create_initial_container(ngw_resource, gpkg_path)


class NgwSearch(NGWResourceModelJob):
    @dataclass
    class Tag:
        name: str
        query_name: str
        old_query_name: str
        in_supported: bool = True
        visible: bool = True

    INT_TAGS: ClassVar[List[Tag]] = [
        Tag("id", "id", "id"),
        Tag("parent", "parent", "parent_id"),
        Tag("root", "root", "parent_id__recursive", in_supported=False),
        Tag("owner", "owner_user", "owner_user_id"),
    ]

    STR_TAGS: ClassVar[List[Tag]] = [
        Tag("type", "cls", "cls"),
        Tag("name", "display_name", "display_name"),
        Tag("keyname", "keyname", "keyname"),
        Tag("owner", "owner", "owner_user_id"),
    ]

    def __init__(
        self,
        search_string: str,
        populated_resources: Set[int],
        is_new_api: bool = False,
    ) -> None:
        super().__init__()
        self.result.found_resources = []
        self.search_string = search_string.strip()
        self.populated_resources = populated_resources
        self.is_new_api = is_new_api
        self.users_keyname = {}
        self.users_username = {}
        self.parents = []

    def _do(self):
        connections_manager = NgwConnectionsManager()
        connection_id = connections_manager.current_connection_id
        assert connection_id is not None
        ngw_connection = QgsNgwConnection(connection_id)

        resources_factory = NGWResourceFactory(ngw_connection)

        for query in self.__queries():
            logger.debug(f"Search for {query}")
            search_url = (
                f"/api/resource/search/?{query}&serialization=resource"
            )
            query_result = ngw_connection.get(search_url)
            self.__process_results(resources_factory, query_result)

        assert self.result.found_resources is not None
        logger.debug(
            f"<b>✓ Found</b> {len(self.result.found_resources)} resources: {self.result.found_resources}"
        )

        if len(self.result.found_resources) == 0:
            self.result.found_resources.append(-1)

        try:
            self.__fetch_parents(resources_factory)
        except Exception:
            self.result.added_resources = []
            raise

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
        if not self.search_string.startswith("@"):
            return [self.__default_query()]

        lower_search_string = self.search_string.lower()
        and_operator_count = lower_search_string.count(" and ")
        or_operator_count = lower_search_string.count(" or ")

        if and_operator_count + or_operator_count not in (
            and_operator_count,
            or_operator_count,
        ):
            logger.warning("only one operator type is supported at a time")
            return [self.__default_query()]

        result = list(
            itertools.chain.from_iterable(
                self.__parallel_queries(search_substring)
                for search_substring in re.split(
                    r"(?i)\sor\s", self.search_string
                )
            )
        )

        if len(result) == 0:
            logger.debug("Wrong syntax. Fallback to display_name query")
            return [self.__default_query()]

        return result

    def __parallel_queries(self, search_string: str) -> List[str]:
        groups = [
            self.__tag_queries(search_substring)
            for search_substring in re.split(r"(?i)\sand\s", search_string)
        ]
        return ["&".join(combo) for combo in itertools.product(*groups)]

    def __tag_queries(self, search_string: str) -> List[str]:
        for tag in self.INT_TAGS:
            queries = self.__int_queries(search_string, tag)
            if len(queries) != 0:
                return queries

        for tag in self.STR_TAGS:
            queries = self.__str_queries(search_string, tag)
            if len(queries) != 0:
                return queries

        if self.is_new_api:
            queries = self.__metadata_queries(search_string)
            if len(queries) != 0:
                return queries

        logger.warning(
            self.tr("Unknown search tag. Possible values: ")
            + ", ".join(
                f"@{tag.name}" for tag in (*self.INT_TAGS, *self.STR_TAGS)
            )
            + ", @metadata"
            if self.is_new_api
            else ""
        )

        return []

    def __default_query(self) -> str:
        if self.search_string.startswith('"') and self.search_string.endswith(
            '"'
        ):
            search_string = quote_plus(self.search_string[1:-1])
            operator = "__eq" if not self.is_new_api else ""
            return f"display_name{operator}={search_string}"
        else:
            search_string = quote_plus(f"%{self.search_string}%")
            return f"display_name__ilike={search_string}"

    def __int_queries(self, search_string: str, tag: Tag) -> List[str]:
        tag_name = re.escape(tag.name)
        pattern = (
            rf"^@{tag_name}\s*=\s*(\d+)$"
            rf"|^@{tag_name}\s+IN\s*\(([\d,\s]+)\)$"
        )
        matches = re.findall(pattern, search_string, flags=re.IGNORECASE)
        if not matches:
            return []

        values = []
        for match in matches:
            if match[0]:
                values.append(int(match[0]))
            elif match[1]:
                values.extend(map(int, match[1].split(",")))

        logger.debug(f"Found {tag.name} queries: {values}")

        if not self.is_new_api:
            return list(
                map(lambda value: f"{tag.old_query_name}={value}", values)
            )
        else:
            values_count = len(values)
            if values_count == 0:
                return []
            elif values_count == 1:
                return [f"{tag.query_name}={values[0]}"]
            else:
                joined_values = ",".join(map(str, values))
                if tag.in_supported:
                    return [f"{tag.query_name}__in={joined_values}"]
                else:
                    return list(
                        map(lambda value: f"{tag.query_name}={value}", values)
                    )

    def __str_queries(self, search_string: str, tag: Tag) -> List[str]:
        tag_name = re.escape(tag.name)
        pattern = (
            rf"^@{tag_name}\s*=\s*(['\"])(.*?)\1$"
            rf"|^@{tag_name}\s+ILIKE\s+(['\"])(.*?)\3$"
            rf"|^@{tag_name}\s+IN\s*\((.*?)\)$"
        )

        matches = re.findall(pattern, search_string, flags=re.IGNORECASE)
        if not matches:
            return []

        operator = "__eq"
        values = []
        for match in matches:
            if match[1]:  # '='
                values.append(match[1])
            elif match[3]:  # 'ILIKE'
                operator = "__ilike"
                values.append(match[3])
            elif match[4]:  # IN
                matches = re.findall(r"\"(.*?)\"|'(.*?)'", match[4])
                values.extend(
                    match for pair in matches for match in pair if match
                )

        if tag_name == "owner":
            values = self.__extract_user_ids(operator, values)
            operator = "__eq"

        logger.debug(f"Found {tag.name} queries: {values}")

        if not self.is_new_api:
            return list(
                map(
                    lambda value: f"{tag.old_query_name}{operator}={quote_plus(str(value))}",
                    values,
                )
            )
        else:
            operator = "" if operator == "__eq" else operator

            values_count = len(values)
            if values_count == 0:
                return []
            elif values_count == 1:
                return [
                    f"{tag.query_name}{operator}={quote_plus(str(values[0]))}"
                ]
            else:
                joined_values = ",".join(
                    map(lambda value: quote_plus(str(value)), values)
                )
                return [f"{tag.query_name}__in={joined_values}"]

    def __metadata_queries(self, search_string: str) -> List[str]:
        pattern = r'@metadata\["([^"]+)"\]\s*=\s*(?:"([^"]+)"|([^"]\S*))'
        match = re.match(pattern, search_string)
        if not match:
            return []

        key = quote_plus(match.group(1))
        value: str = (
            match.group(2) if match.group(2) is not None else match.group(3)
        )
        ilike_value = quote_plus(f"%{value}%")

        queries = [f"resmeta__ilike[{key}]={ilike_value}"]
        if value.isnumeric():
            queries.append(f"resmeta__json[{key}]={value}")
        elif value.lower() in ("true", "false"):
            queries.append(f"resmeta__json[{key}]={value.lower()}")
        else:
            try:
                float_value = float(value)
                queries.append(f"resmeta__json[{key}]={float_value}")
            except ValueError:
                pass

        return queries

    def __fetch_users(self) -> None:
        if len(self.users_keyname) > 0:
            return

        connections_manager = NgwConnectionsManager()
        connection_id = connections_manager.current_connection_id
        try:
            assert connection_id is not None
            ngw_connection = QgsNgwConnection(connection_id)
            result = ngw_connection.get("api/component/auth/user/")
            for user in result:
                self.users_keyname[user["keyname"]] = user["id"]
                self.users_username[user["display_name"]] = user["id"]
        except Exception:
            logger.exception("Can't fetch users")

    def __extract_user_ids(
        self, operator: str, values: List[str]
    ) -> List[int]:
        self.__fetch_users()

        ids = set()

        if operator == "__eq":
            ids.update(
                map(
                    lambda value: self.users_keyname.get(
                        value, self.users_username.get(value, -1)
                    ),
                    values,
                )
            )

        elif operator == "__ilike":
            regex_pattern = values[0].replace("%", ".*").replace("_", ".")
            regex = re.compile(f"^{regex_pattern}$", re.IGNORECASE)
            ids.update(
                value
                for key, value in self.users_keyname.items()
                if regex.match(key)
            )
            ids.update(
                value
                for key, value in self.users_username.items()
                if regex.match(key)
            )

        return list(ids)

    def __fetch_parents(self, resources_factory: NGWResourceFactory) -> None:
        logger.debug("◴ Fetching intermediate resources")

        for parent_id in self.parents:
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
        children_json = NGWResource.receive_resource_children(
            resources_factory.connection, resource_id
        )

        children: List[NGWResource] = []
        for child_json in children_json:
            children.append(resources_factory.get_resource_by_json(child_json))

        self.populated_resources.add(resource_id)

        if len(children) == 0:
            logger.error(f"Empty children list for resource {resource_id}")
            return

        self.result.added_resources = children + self.result.added_resources
        grandparent_id = children[0].grandparent_id
        if grandparent_id not in self.populated_resources:
            self.__fetch_children(resources_factory, grandparent_id)


class QNGWResourceTreeModelBase(QAbstractItemModel):
    jobStarted = pyqtSignal(str)
    jobStatusChanged = pyqtSignal(str, str)
    errorOccurred = pyqtSignal(str, str, Exception)
    warningOccurred = pyqtSignal(str, str, Exception)
    jobFinished = pyqtSignal(str, str)
    indexesLocked = pyqtSignal()
    indexesUnlocked = pyqtSignal()

    found_resources_changed = pyqtSignal(list)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._ngw_connection = None

        self.jobs = []
        self.root_item = QModelItem()
        self.ngw_version = None
        self.support_status = None

        self._dangling_resources: Dict[int, NGWResource] = {}
        self.__not_permitted_resources = set()

        self._found_resources_id = []

        self.__indexes_locked_by_jobs = {}
        self.__indexes_locked_by_job_errors = {}

    def resetModel(self, ngw_connection: Optional[QgsNgwConnection]):
        self.beginResetModel()

        self._ngw_connection = ngw_connection
        if ngw_connection is not None:
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
            try:
                self.ngw_version = self._ngw_connection.get_version()
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

        self.endResetModel()

        if request_error is not None:
            self.errorOccurred.emit(None, None, request_error)

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
        has_created_children = not children and parent_item.childCount() > 0
        return has_fetched_children or has_created_children

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        return self.item(index).flags()

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
        self.errorOccurred.emit(job.getJobId(), job.getJobUuid(), error)

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

        self.indexesLocked.emit()

    def _unlockIndexesByJob(self, job):
        indexes = self.__indexes_locked_by_jobs.get(job, [])
        self.__indexes_locked_by_jobs[job] = []

        for index in indexes:
            item = self.item(index)
            item.unlock()
            if job.error() is not None:
                self.__indexes_locked_by_job_errors[index] = job.error()

            self.dataChanged.emit(index, index)

        self.indexesUnlocked.emit()

    def _isIndexLockedByJob(self, index):
        for indexes in self.__indexes_locked_by_jobs.values():
            if index in indexes:
                return True
        return False

    def _isIndexLockedByJobError(self, index):
        return index in self.__indexes_locked_by_job_errors

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
            # Qt API has no signal like 'hasChildrenChanged'. This is a workaround
            self.beginInsertRows(ngw_index, 0, 0)
            self.endInsertRows()
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

        for ngw_resource in job_result.deleted_resources:
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
    def deleteResource(self, index):
        item = index.internalPointer()
        ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(NGWResourceDelete(ngw_resource))

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
    def uploadProjectResources(self, ngw_group_name, ngw_current_index, iface):
        if not ngw_current_index.isValid():
            ngw_current_index = self.index(0, 0, ngw_current_index)

        ngw_group_index = self._nearest_ngw_group_resource_parent(
            ngw_current_index
        )
        group_item = ngw_group_index.internalPointer()
        ngw_resource = group_item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(
            QGISProjectUploader(
                ngw_group_name, ngw_resource, iface, self.ngw_version
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
        has_new_search_api = self.ngw_version is not None and parse_version(
            self.ngw_version
        ) >= parse_version("5.0.0.dev13")
        worker = NgwSearch(
            search_string,
            self.__collect_populated_resources(),
            has_new_search_api,
        )
        return self._startJob(worker)

    def reset_search(self) -> None:
        self.found_resources_changed.emit([])
        self._found_resources_id = []

    @modelRequest
    def download_vector_layers_if_needed(
        self, indexes: Union[QModelIndex, List[QModelIndex]]
    ):
        cache_manager = NgConnectCacheManager()
        connections_manager = NgwConnectionsManager()

        def collect_indexes(
            index: QModelIndex,
        ) -> Tuple[List[QModelIndex], List[QModelIndex]]:
            ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
            connection = connections_manager.connection(
                ngw_resource.connection_id
            )
            assert connection is not None
            instance_subdir = connection.domain_uuid

            if isinstance(ngw_resource, NGWVectorLayer):
                if cache_manager.exists(
                    f"{instance_subdir}/{ngw_resource.resource_id}.gpkg"
                ):
                    return [index], []
                return [index], [index]

            if isinstance(ngw_resource, NGWQGISVectorStyle):
                parent = index.parent()
                parent_resource = parent.data(QNGWResourceItem.NGWResourceRole)
                if not isinstance(parent_resource, NGWVectorLayer):
                    return [], []

                if cache_manager.exists(
                    f"{instance_subdir}/{parent_resource.resource_id}.gpkg"
                ):
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
                instance_subdir = connection.domain_uuid

                if cache_manager.exists(
                    f"{instance_subdir}/{ngw_resource.resource_id}.gpkg"
                ):
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
