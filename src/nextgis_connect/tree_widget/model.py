import functools
import uuid
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union, cast

from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QCoreApplication,
    QModelIndex,
    QObject,
    QThread,
    pyqtSignal,
)

from nextgis_connect import utils
from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.logging import logger
from nextgis_connect.ngw_api.core import (
    NGWGroupResource,
    NGWResource,
    NGWVectorLayer,
)
from nextgis_connect.ngw_api.core.ngw_qgis_style import NGWQGISVectorStyle
from nextgis_connect.ngw_api.qgis.ngw_resource_model_4qgis import (
    MapForLayerCreater,
    NGWCreateWMSForVector,
    NGWUpdateVectorLayer,
    QGISProjectUploader,
    QGISResourcesUploader,
    QGISStyleAdder,
    QGISStyleUpdater,
)
from nextgis_connect.ngw_api.qt.qt_ngw_resource_model_job import (
    NGWCreateMapForStyle,
    NGWCreateOgcfService,
    NGWCreateWfsService,
    NGWGroupCreater,
    NGWRenameResource,
    NGWResourceDelete,
    NGWResourceModelJob,
    NGWResourceModelJobResult,
    NGWResourceUpdater,
    NGWRootResourcesLoader,
)
from nextgis_connect.ngw_api.qt.qt_ngw_resource_model_job_error import (
    NGWResourceModelJobError,
)
from nextgis_connect.ngw_connection import NgwConnectionsManager
from nextgis_connect.settings import NgConnectCacheManager

from .item import QModelItem, QNGWResourceItem

__all__ = ["QNGWResourceTreeModel"]


class NGWResourceModelResponse(QObject):
    done = pyqtSignal(QModelIndex)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.job_id = None
        self.job_uuid = None
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
            self.result.main_resource_id = ngw_resources.common.id

    def _do(self):
        connections_manager = NgwConnectionsManager()

        cache_manager = NgConnectCacheManager()
        cache_directory = Path(cache_manager.cache_directory)

        detached_factory = DetachedLayerFactory()

        total = str(len(self.ngw_resources))
        for i, ngw_resource in enumerate(self.ngw_resources):
            name = ngw_resource.common.display_name
            progress = "" if total == "1" else f" ({i + 1}/{total})"
            self.statusChanged.emit(
                self.tr('Adding layer "{name}"').format(name=name) + progress
            )

            connection = connections_manager.connection(
                ngw_resource.connection_id
            )
            assert connection is not None
            instance_subdir = connection.domain_uuid

            instance_cache_path = cache_directory / instance_subdir
            instance_cache_path.mkdir(parents=True, exist_ok=True)
            gpkg_path = instance_cache_path / f"{ngw_resource.common.id}.gpkg"
            detached_factory.create_container(ngw_resource, gpkg_path)


class QNGWResourceTreeModelBase(QAbstractItemModel):
    jobStarted = pyqtSignal(str)
    jobStatusChanged = pyqtSignal(str, str)
    errorOccurred = pyqtSignal(str, str, object)
    warningOccurred = pyqtSignal(str, str, object)
    jobFinished = pyqtSignal(str, str)
    indexesLocked = pyqtSignal()
    indexesUnlocked = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._ngw_connection = None

        self.jobs = []
        self.root_item = QModelItem()
        self.ngw_version = None
        self.support_status = None

        self.__indexes_locked_by_jobs = {}
        self.__indexes_locked_by_job_errors = {}

    def resetModel(self, ngw_connection):
        self.__indexes_locked_by_jobs = {}
        self.__indexes_locked_by_job_errors = {}

        self._ngw_connection = ngw_connection
        if ngw_connection is not None:
            self._ngw_connection.setParent(self)

        self.__cleanModel()
        self.beginResetModel()

        self.root_item = QModelItem()

        request_error = None
        # Get NGW version.
        if ngw_connection is not None:
            try:
                self.ngw_version = self._ngw_connection.get_version()
                self.support_status = utils.is_version_supported(
                    self.ngw_version
                )
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

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_item = self.item(parent)
        child_item = parent_item.child(row)
        assert child_item is not None
        return self.createIndex(row, column, child_item)

    def parent(self, index):
        item = self.item(index)
        assert item is not self.root_item
        parent_item = item.parent()
        if parent_item is self.root_item:
            return QModelIndex()
        if parent_item is None:  # TODO: should not be without QTreeWidgetItem
            return QModelIndex()
        assert parent_item is not None
        return self.createIndex(
            parent_item.parent().indexOfChild(parent_item), 0, parent_item
        )

    def columnCount(self, parent):
        return 1

    def rowCount(self, parent):
        parent_item = self.item(parent)
        return parent_item.childCount()

    def canFetchMore(self, parent):
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

    def fetchMore(self, parent):
        parent_item = self.item(parent)
        assert isinstance(parent_item, QModelItem)
        if parent_item is self.root_item:
            worker = NGWRootResourcesLoader(self._ngw_connection)
            logger.debug("Fetch root resource")
        else:
            ngw_resource = parent_item.data(QNGWResourceItem.NGWResourceRole)
            worker = NGWResourceUpdater(ngw_resource)
            logger.debug(f"Fetch children for id={ngw_resource.resource_id}")

        self._startJob(worker, parent)

    def data(self, index, role):
        item = self.item(index)
        return item.data(role)

    def hasChildren(self, parent):
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

    def flags(self, index):
        item = self.item(index)
        return item.flags()

    # TODO job должен уметь не стартовать, например есди запущен job обновления
    # дочерних ресурсов - нельзя запускать обновление
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
        job.deleteLater()
        self.jobs.remove(job)

    def __jobErrorOccurredProcess(self, error):
        job = cast(NGWResourcesModelJob, self.sender())
        self.errorOccurred.emit(job.getJobId(), job.getJobUuid(), error)

    def __jobWarningOccurredProcess(self, error):
        job = cast(NGWResourcesModelJob, self.sender())
        self.warningOccurred.emit(job.getJobId(), job.getJobUuid(), error)

    def addNGWResourceToTree(self, parent: QModelIndex, ngw_resource):
        parent_item = self.item(parent)

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
        self.endInsertRows()

        return self.index(i, 0, parent)

    def _lockIndexByJob(self, indexes: List[QModelIndex], job):
        if job not in self.__indexes_locked_by_jobs:
            self.__indexes_locked_by_jobs[job] = []
        self.__indexes_locked_by_jobs[job].extend(indexes)

        self.layoutAboutToBeChanged.emit()

        for index in indexes:
            item = self.item(index)
            # self.beginInsertRows(index, item.childCount(), item.childCount())
            item.lock()
            # self.endInsertRows()

        self.layoutChanged.emit()

        QCoreApplication.processEvents()

        self.indexesLocked.emit()

    def _unlockIndexesByJob(self, job):
        indexes = self.__indexes_locked_by_jobs.get(job, [])
        self.__indexes_locked_by_jobs[job] = []

        self.layoutAboutToBeChanged.emit()

        for index in indexes:
            item = self.item(index)

            # self.beginRemoveRows(index, item.childCount(), item.childCount())
            item.unlock()
            # self.endRemoveRows()

            if job.error() is not None:
                self.__indexes_locked_by_job_errors[index] = job.error()

        self.layoutChanged.emit()

        QCoreApplication.processEvents()

        self.indexesUnlocked.emit()

    def _isIndexLockedByJob(self, index):
        for indexes in self.__indexes_locked_by_jobs.values():
            if index in indexes:
                return True
        return False

    def _isIndexLockedByJobError(self, index):
        return index in self.__indexes_locked_by_job_errors

    def getIndexByNGWResourceId(self, ngw_resource_id, parent=None):
        if parent is None:
            parent = self.index(0, 0, QModelIndex())
        item = parent.internalPointer()

        if (
            isinstance(item, QNGWResourceItem)
            and item.ngw_resource_id() == ngw_resource_id
        ):
            return parent

        for i in range(item.childCount()):
            index = self.getIndexByNGWResourceId(
                ngw_resource_id, self.index(i, 0, parent)
            )

            if index is not None:
                return index

        return None

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
        for ngw_resource in job_result.added_resources:
            if ngw_resource.common.parent is None:
                index = QModelIndex()
                new_index = self.addNGWResourceToTree(index, ngw_resource)
            else:
                parent_id = ngw_resource.common.parent.id
                if parent_id not in indexes:
                    indexes[parent_id] = self.getIndexByNGWResourceId(
                        parent_id
                    )
                index = indexes[parent_id]

                item = index.internalPointer()
                current_ids = [
                    item.child(i).ngw_resource_id()
                    for i in range(item.childCount())
                    if isinstance(item.child(i), QNGWResourceItem)
                ]
                if ngw_resource.common.id not in current_ids:
                    new_index = self.addNGWResourceToTree(index, ngw_resource)
                else:
                    continue

            if job_result.main_resource_id == ngw_resource.common.id:
                if job.model_response is not None:
                    job.model_response.done.emit(new_index)

        if len(indexes) == 0 and job.getJobId() == NGWResourceUpdater.__name__:
            ngw_index = self.getIndexByNGWResourceId(
                job_result.main_resource_id
            )
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
                index = QModelIndex()
            else:
                index = self.getIndexByNGWResourceId(
                    ngw_resource.common.parent.id,
                )
                item = index.internalPointer()

                for i in range(item.childCount()):
                    if (
                        item.child(i).ngw_resource_id()
                        == ngw_resource.common.id
                    ):
                        self.beginRemoveRows(index, i, i)
                        item.removeChild(item.child(i))
                        self.endRemoveRows()
                        break
                else:
                    # TODO exception: not find deleted resource in corrent tree
                    return

            new_index = self.addNGWResourceToTree(index, ngw_resource)

            if job.model_response is not None:
                job.model_response.done.emit(new_index)

        for ngw_resource in job_result.deleted_resources:
            index = self.getIndexByNGWResourceId(
                ngw_resource.common.parent.id,
            )
            item = index.internalPointer()

            for i in range(item.childCount()):
                if item.child(i).ngw_resource_id() == ngw_resource.common.id:
                    self.beginRemoveRows(index, i, i)
                    item.removeChild(item.child(i))
                    self.endRemoveRows()
                    break
            else:
                # TODO exception: not find deleted resource in corrent tree
                return

            ngw_resource = item.data(QNGWResourceItem.NGWResourceRole)
            ngw_resource.update()

            if job.model_response is not None:
                job.model_response.done.emit(index)

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
    def createWMSForVector(self, index, ngw_resource_style_id):
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
            NGWCreateWMSForVector(
                ngw_resource, ngw_parent_resource, ngw_resource_style_id
            )
        )

    @modelRequest
    def updateNGWLayer(self, index, qgs_vector_layer):
        if not index.isValid():
            index = self.index(0, 0, index)

        item = index.internalPointer()
        ngw_vector_layer = item.data(QNGWResourceItem.NGWResourceRole)

        return self._startJob(
            NGWUpdateVectorLayer(ngw_vector_layer, qgs_vector_layer),
        )

    @modelRequest
    def fetch_group(
        self, group_indexes: Union[QModelIndex, List[QModelIndex]]
    ) -> Optional[NGWResourcesModelJob]:
        def collect_indexes(index: QModelIndex) -> List[QModelIndex]:
            ngw_resource = index.data(QNGWResourceItem.NGWResourceRole)
            if not isinstance(ngw_resource, NGWGroupResource):
                return []

            if self.canFetchMore(index):
                return [index]

            indexes: List[QModelIndex] = []
            for row in range(self.rowCount(index)):
                child_index = self.index(row, 0, index)
                indexes.extend(collect_indexes(child_index))

            return indexes

        if isinstance(group_indexes, QModelIndex):
            group_indexes = [group_indexes]

        indexes_for_fetch: List[QModelIndex] = []
        for group_index in group_indexes:
            indexes_for_fetch.extend(collect_indexes(group_index))

        if len(indexes_for_fetch) == 0:
            return None

        resources: List[NGWResource] = [
            index.data(QNGWResourceItem.NGWResourceRole)
            for index in indexes_for_fetch
        ]

        worker = NGWResourceUpdater(resources, recursive=True)
        return self._startJob(worker, lock_indexes=indexes_for_fetch)

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
                # TODO set instance id
                if cache_manager.exists(
                    f"{instance_subdir}/{ngw_resource.common.id}.gpkg"
                ):
                    return [index], []
                return [index], [index]

            if isinstance(ngw_resource, NGWQGISVectorStyle):
                # TODO set instance id
                parent = index.parent()
                parent_resource = parent.data(QNGWResourceItem.NGWResourceRole)
                if cache_manager.exists(
                    f"{instance_subdir}/{parent_resource.common.id}.gpkg"
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

        if isinstance(indexes, QModelIndex):
            indexes = [indexes]

        indexes_for_lock: List[QModelIndex] = []
        indexes_for_fetch: List[QModelIndex] = []
        for index in indexes:
            lock_indexes, fetch_indexes = collect_indexes(index)
            indexes_for_lock.extend(lock_indexes)
            indexes_for_fetch.extend(fetch_indexes)

        if len(indexes_for_fetch) == 0:
            return None

        vector_layers: List[NGWVectorLayer] = [
            index.data(QNGWResourceItem.NGWResourceRole)
            for index in set(indexes_for_fetch)
        ]

        worker = NgwCreateVectorLayersStubs(vector_layers)
        return self._startJob(worker, lock_indexes=list(set(indexes_for_lock)))
