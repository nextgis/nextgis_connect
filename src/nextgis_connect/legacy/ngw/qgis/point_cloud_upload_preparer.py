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

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
    QgsNgwConnection,
)
from nextgis_connect.platform.qgis.errors import (
    DataPreparationError,
    NgConnectError,
)
from qgis.core import (
    QgsApplication,
    QgsFeedback,
    QgsFileDownloader,
    QgsPointCloudLayer,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProviderRegistry,
)
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QEventLoop,
    QObject,
    Qt,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)

NGW_CONNECTION_ID_PROPERTY = "ngw_connection_id"
NGW_RESOURCE_ID_PROPERTY = "ngw_resource_id"
COPC_SUFFIX = ".copc.laz"


class _CreateCopcRequest(QObject):
    """Carry one COPC conversion request between the upload and GUI threads."""

    completed = pyqtSignal()

    def __init__(
        self,
        source_path: Path,
        output_directory: Path,
        feedback: Optional[QgsFeedback],
    ) -> None:
        """Initialize a request for a local point-cloud source.

        :param source_path: Existing source file to convert.
        :param output_directory: Directory for the generated COPC file.
        :param feedback: Feedback controlling cancellation of the operation.
        """
        super().__init__()
        self.source_path = source_path
        self.output_directory = output_directory
        self.feedback = feedback
        self.successful = False
        self.outputs: Dict[str, Any] = {}
        self.error_message: Optional[str] = None

    def finish(
        self,
        successful: bool,
        outputs: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Record a main-thread task result and wake the waiting worker.

        :param successful: Whether QGIS Processing completed successfully.
        :param outputs: Processing outputs when the task completed.
        :param error_message: Failure description when the task could not start.
        """
        self.successful = successful
        self.outputs = outputs or {}
        self.error_message = error_message
        self.completed.emit()


class _CreateCopcTaskRunner(QObject):
    """Create and schedule Processing tasks in the QGIS GUI thread."""

    requested = pyqtSignal(object)

    def __init__(self) -> None:
        """Initialize the GUI-thread task scheduler."""
        super().__init__()
        self._task_state: Optional[
            Tuple[
                QgsProcessingContext,
                QgsProcessingFeedback,
                QgsProcessingAlgRunnerTask,
            ]
        ] = None
        self.requested.connect(
            self._start,
            Qt.ConnectionType.QueuedConnection,
        )

    @pyqtSlot(object)
    def _start(self, request: _CreateCopcRequest) -> None:
        """Create a Processing task after a worker requests conversion.

        :param request: Conversion request owned by the upload worker.
        """
        if request.feedback is not None and request.feedback.isCanceled():
            request.finish(False, error_message="Request was canceled")
            self.deleteLater()
            return

        algorithm = QgsApplication.processingRegistry().algorithmById(
            "pdal:createcopc"
        )
        if algorithm is None:
            request.finish(
                False,
                error_message="QGIS Create COPC algorithm is unavailable",
            )
            self.deleteLater()
            return

        context = QgsProcessingContext()
        processing_feedback = QgsProcessingFeedback()
        task = QgsProcessingAlgRunnerTask(
            algorithm,
            {
                "LAYERS": [str(request.source_path)],
                "OUTPUT": str(request.output_directory),
            },
            context,
            processing_feedback,
        )
        if request.feedback is not None:
            request.feedback.canceled.connect(task.cancel)

        # QgsProcessingAlgRunnerTask retains references to these objects.
        self._task_state = (context, processing_feedback, task)

        def on_executed(successful: bool, outputs: Dict[str, Any]) -> None:
            request.finish(successful, outputs)
            self._task_state = None
            self.deleteLater()

        task.executed.connect(on_executed)
        QgsApplication.taskManager().addTask(task)


@dataclass(frozen=True)
class PreparedPointCloudFile:
    """Represent a COPC payload prepared for upload.

    :ivar upload_path: COPC file to pass to TUS upload.
    :ivar temporary_directory: Directory to remove after upload, if owned.
    """

    upload_path: Path
    temporary_directory: Optional[Path]

    @property
    def is_temporary(self) -> bool:
        """Return whether cleanup owns the upload payload.

        :return: ``True`` when the preparer owns the payload directory.
        """
        return self.temporary_directory is not None

    def cleanup(self) -> None:
        """Remove temporary preparation artifacts owned by this payload."""
        if self.temporary_directory is not None:
            shutil.rmtree(self.temporary_directory, ignore_errors=True)


class PointCloudUploadPreparer:
    """Prepare point-cloud layers as COPC files for NGW upload."""

    def __init__(
        self,
        feedback: Optional[QgsFeedback] = None,
        download_progress_callback: Optional[Callable[[int], None]] = None,
    ) -> None:
        """Initialize a point-cloud upload preparer.

        :param feedback: Feedback controlling cancellation of preparation.
        :param download_progress_callback: Receives remote download progress.
        """
        self._feedback = feedback
        self._download_progress_callback = download_progress_callback

    def prepare(self, layer: QgsPointCloudLayer) -> PreparedPointCloudFile:
        """Prepare a point-cloud layer for upload.

        :param layer: Source QGIS point-cloud layer.
        :return: COPC payload and its cleanup ownership.
        :raises DataPreparationError: If the source cannot produce a COPC file.
        :raises NgConnectError: If preparation is canceled.
        """
        self._raise_if_canceled()
        self._validate_layer(layer)

        source_path, source_url, auth_config_id = self._source(layer)
        if source_path is not None:
            return self._prepare_source_file(source_path)

        return self._prepare_remote_source(layer, source_url, auth_config_id)

    @staticmethod
    def _validate_layer(layer: QgsPointCloudLayer) -> None:
        """Validate a point-cloud layer before its source is read.

        :param layer: Source QGIS point-cloud layer.
        :raises DataPreparationError: If the layer or its CRS is invalid.
        """
        if not layer.isValid():
            raise DataPreparationError("Point-cloud layer is not valid")
        if not layer.crs().isValid():
            raise DataPreparationError("Point-cloud layer CRS is not valid")

    def _prepare_remote_source(
        self,
        layer: QgsPointCloudLayer,
        source_url: Optional[QUrl],
        auth_config_id: str,
    ) -> PreparedPointCloudFile:
        """Download and prepare a remote point-cloud source.

        :param layer: Source layer, possibly linked to an NGW resource.
        :param source_url: Direct source URL when available.
        :param auth_config_id: QGIS authentication configuration for the URL.
        :return: COPC payload and its cleanup ownership.
        :raises DataPreparationError: If the remote source cannot be accessed.
        """
        temporary_directory = self._temporary_directory()
        try:
            if self._is_ngw_layer(layer):
                source_path = self._download_ngw_copc(
                    layer, temporary_directory
                )
            elif source_url is not None:
                source_path = self._download_source(
                    source_url,
                    auth_config_id,
                    temporary_directory,
                )
            else:
                raise DataPreparationError(
                    f"Cannot access point-cloud source for layer {layer.name()}"
                )

            return self._prepare_source_file(source_path, temporary_directory)
        except Exception:
            shutil.rmtree(temporary_directory, ignore_errors=True)
            raise

    def _prepare_source_file(
        self,
        source_path: Path,
        temporary_directory: Optional[Path] = None,
    ) -> PreparedPointCloudFile:
        """Reuse COPC input or convert another source to COPC.

        :param source_path: Existing local point-cloud source file.
        :param temporary_directory: Directory owned by the returned payload.
        :return: COPC payload and its cleanup ownership.
        """
        if self._is_copc(source_path):
            return PreparedPointCloudFile(source_path, temporary_directory)

        return self._convert_to_copc(source_path, temporary_directory)

    def _source(
        self,
        layer: QgsPointCloudLayer,
    ) -> Tuple[Optional[Path], Optional[QUrl], str]:
        """Extract a local path or remote URL from a point-cloud URI.

        :param layer: Layer whose provider URI is inspected.
        :return: Local path, remote URL, and optional QGIS auth configuration.
        """
        source_reference = self._source_reference(layer.source(), "")
        if source_reference[0] is not None or source_reference[1] is not None:
            return source_reference

        provider_metadata = QgsProviderRegistry.instance().providerMetadata(
            layer.providerType()
        )
        if provider_metadata is None:
            return None, None, ""

        try:
            uri_parts = provider_metadata.decodeUri(layer.source())
        except Exception:
            return None, None, ""

        source_value = uri_parts.get("path") or uri_parts.get("url")
        auth_config_id = str(uri_parts.get("authcfg") or "")
        if not source_value:
            return None, None, auth_config_id

        return self._source_reference(str(source_value), auth_config_id)

    @staticmethod
    def _source_reference(
        source: str,
        auth_config_id: str,
    ) -> Tuple[Optional[Path], Optional[QUrl], str]:
        """Classify a source value as a local file or supported remote URL.

        :param source: Provider source value to inspect.
        :param auth_config_id: QGIS authentication configuration for the source.
        :return: Local path, remote URL, and the authentication configuration.
        """
        source_path = Path(source)
        if source_path.is_file():
            return source_path, None, auth_config_id

        source_url = QUrl(source)
        if source_url.isValid() and source_url.scheme() in ("http", "https"):
            return None, source_url, auth_config_id

        return None, None, auth_config_id

    @staticmethod
    def _is_copc(path: Path) -> bool:
        """Return whether a filename has the canonical COPC suffix.

        :param path: File path to inspect.
        :return: ``True`` when the path ends with ``.copc.laz``.
        """
        return path.name.casefold().endswith(COPC_SUFFIX)

    @staticmethod
    def _is_ngw_layer(layer: QgsPointCloudLayer) -> bool:
        """Return whether a layer has NGW resource metadata.

        :param layer: Layer whose custom properties are inspected.
        :return: ``True`` when the layer references an NGW resource.
        """
        return (
            layer.customProperty(NGW_CONNECTION_ID_PROPERTY) is not None
            and layer.customProperty(NGW_RESOURCE_ID_PROPERTY) is not None
        )

    def _download_ngw_copc(
        self,
        layer: QgsPointCloudLayer,
        temporary_directory: Path,
    ) -> Path:
        """Download the canonical COPC stream from an NGW resource.

        :param layer: Layer carrying NGW resource metadata.
        :param temporary_directory: Directory for the downloaded COPC file.
        :return: Downloaded COPC file path.
        :raises DataPreparationError: If the NGW resource identifier is invalid.
        """
        connection_id = layer.customProperty(NGW_CONNECTION_ID_PROPERTY)
        resource_id = layer.customProperty(NGW_RESOURCE_ID_PROPERTY)
        try:
            normalized_resource_id = int(resource_id)
        except (TypeError, ValueError) as error:
            raise DataPreparationError(
                "Point-cloud NGW resource ID is invalid"
            ) from error

        connection = QgsNgwConnection(str(connection_id)).connection
        source_url = QUrl(
            f"{connection.url}/api/resource/{normalized_resource_id}/point_cloud.copc.laz"
        )
        output_path = temporary_directory / "point_cloud.copc.laz"
        self._download(
            source_url, connection.auth_config_id or "", output_path
        )
        return output_path

    def _download_source(
        self,
        source_url: QUrl,
        auth_config_id: str,
        temporary_directory: Path,
    ) -> Path:
        """Download a remote point-cloud source to a temporary file.

        :param source_url: URL of the source file.
        :param auth_config_id: QGIS authentication configuration for the URL.
        :param temporary_directory: Directory for the downloaded source.
        :return: Downloaded source file path.
        """
        source_name = Path(source_url.path()).name
        if len(source_name) == 0:
            source_name = "point_cloud.download"
        output_path = temporary_directory / source_name
        self._download(source_url, auth_config_id, output_path)
        return output_path

    def _download(
        self,
        source_url: QUrl,
        auth_config_id: str,
        output_path: Path,
    ) -> None:
        """Stream a remote source to disk through the QGIS network stack.

        :param source_url: URL to download.
        :param auth_config_id: QGIS authentication configuration for the URL.
        :param output_path: Destination path for the streamed data.
        :raises DataPreparationError: If the download fails or returns no data.
        :raises NgConnectError: If the download is canceled.
        """
        self._raise_if_canceled()
        loop = QEventLoop()
        errors: List[str] = []
        completed = []
        downloader = QgsFileDownloader(
            source_url,
            str(output_path),
            auth_config_id,
            True,
        )
        downloader.downloadProgress.connect(self._update_download_progress)
        downloader.downloadCompleted.connect(
            lambda _url: completed.append(True)
        )
        downloader.downloadError.connect(errors.extend)
        downloader.downloadExited.connect(loop.quit)
        if self._feedback is not None:
            self._feedback.canceled.connect(downloader.cancelDownload)

        downloader.startDownload()
        loop.exec()
        self._raise_if_canceled()
        self._validate_download(source_url, output_path, completed, errors)

    def _update_download_progress(self, received: int, total: int) -> None:
        """Propagate download progress to the upload workflow.

        :param received: Number of downloaded bytes.
        :param total: Expected total number of bytes.
        """
        if total <= 0:
            return

        if self._feedback is not None:
            self._feedback.setProgress(received * 100.0 / total)
        if self._download_progress_callback is not None:
            self._download_progress_callback(int(received * 100 / total))

    @staticmethod
    def _validate_download(
        source_url: QUrl,
        output_path: Path,
        completed: List[bool],
        errors: List[str],
    ) -> None:
        """Validate the terminal state of a file download.

        :param source_url: URL requested from the QGIS network stack.
        :param output_path: Expected local destination path.
        :param completed: Completion signals received from the downloader.
        :param errors: Error messages received from the downloader.
        :raises DataPreparationError: If the download did not produce a file.
        """
        if errors:
            raise DataPreparationError("; ".join(errors))
        if (
            not completed
            or not output_path.is_file()
            or output_path.stat().st_size == 0
        ):
            raise DataPreparationError(
                f"Cannot download point-cloud source {source_url.toString()}"
            )

    def _convert_to_copc(
        self,
        source_path: Path,
        temporary_directory: Optional[Path] = None,
    ) -> PreparedPointCloudFile:
        """Convert a local source to COPC with the QGIS Processing algorithm.

        :param source_path: Existing point-cloud source file.
        :param temporary_directory: Existing directory for generated artifacts.
        :return: Generated COPC payload and its cleanup ownership.
        :raises DataPreparationError: If QGIS cannot generate a valid COPC file.
        """
        self._raise_if_canceled()
        if not source_path.is_file():
            raise DataPreparationError(
                f"Point-cloud source does not exist: {source_path}"
            )

        owns_temporary_directory = temporary_directory is None
        if temporary_directory is None:
            temporary_directory = self._temporary_directory()
        try:
            output_path = self._validate_copc_output(
                source_path,
                self._run_create_copc(source_path, temporary_directory),
            )
            return PreparedPointCloudFile(output_path, temporary_directory)
        except Exception:
            if owns_temporary_directory:
                shutil.rmtree(temporary_directory, ignore_errors=True)
            raise

    def _validate_copc_output(
        self,
        source_path: Path,
        output_layers: List[str],
    ) -> Path:
        """Validate and return the single COPC output from Processing.

        :param source_path: Input passed to the Create COPC algorithm.
        :param output_layers: Paths reported by the Processing algorithm.
        :return: Existing non-empty COPC output path.
        :raises DataPreparationError: If Processing did not produce one valid COPC file.
        """
        if len(output_layers) != 1:
            raise DataPreparationError(
                f"Cannot create COPC from point-cloud source {source_path}"
            )

        output_path = Path(output_layers[0])
        if (
            not self._is_copc(output_path)
            or not output_path.is_file()
            or output_path.stat().st_size == 0
        ):
            raise DataPreparationError(
                f"COPC output is invalid: {output_path}"
            )

        return output_path

    def _run_create_copc(
        self,
        source_path: Path,
        output_directory: Path,
    ) -> List[str]:
        """Run Create COPC through a task created in the GUI thread.

        :param source_path: Existing point-cloud source file.
        :param output_directory: Directory for the Processing output.
        :return: Paths reported by ``pdal:createcopc``.
        :raises DataPreparationError: If the QGIS application or algorithm is unavailable.
        """
        application = QCoreApplication.instance()
        if application is None:
            raise DataPreparationError("QGIS application is unavailable")

        request = _CreateCopcRequest(
            source_path,
            output_directory,
            self._feedback,
        )
        runner = _CreateCopcTaskRunner()
        runner.moveToThread(application.thread())
        loop = QEventLoop()
        request.completed.connect(
            loop.quit, Qt.ConnectionType.QueuedConnection
        )
        runner.requested.emit(request)
        loop.exec()
        self._raise_if_canceled()
        if not request.successful:
            raise DataPreparationError(
                request.error_message
                or f"Cannot create COPC from point-cloud source {source_path}"
            )

        output_layers = request.outputs.get("OUTPUT_LAYERS", [])
        if not isinstance(output_layers, list):
            raise DataPreparationError("Create COPC returned invalid output")
        return [str(output) for output in output_layers]

    @staticmethod
    def _temporary_directory() -> Path:
        """Create a private directory for one preparation operation.

        :return: Newly created temporary directory.
        """
        return Path(tempfile.mkdtemp(prefix="nextgis-connect-point-cloud-"))

    def _raise_if_canceled(self) -> None:
        """Raise when the caller canceled preparation.

        :raises NgConnectError: If the feedback reports cancellation.
        """
        if self._feedback is not None and self._feedback.isCanceled():
            raise NgConnectError("Request was canceled")
