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

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qgis.core import QgsVectorLayer
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QEvent

from nextgis_connect.legacy.detached_editing.container.container import (
    DetachedContainer,
)
from nextgis_connect.legacy.detached_editing.sync.common import (
    FetchAdditionalDataTask,
)
from nextgis_connect.legacy.detached_editing.sync.versioned import (
    FetchDeltaTask,
)
from nextgis_connect.platform.qgis.errors import (
    ContainerError,
    ErrorCode,
    NgwError,
    SynchronizationError,
)
from tests.detached_editing.utils import (
    copy_legacy_36_points_container,
    mark_container_changed,
    mock_container,
    set_container_version,
)
from tests.ng_connect_testcase import NgConnectTestCase, TestData


class TestDetachedEditingTask(NgConnectTestCase):
    @mock_container(TestData.Points)
    def test_outdated_container_is_rejected_before_synchronization(
        self, container_mock: MagicMock, qgs_layer: QgsVectorLayer
    ) -> None:
        set_container_version(container_mock.path, "0.1.0")

        task = FetchAdditionalDataTask(
            container_mock.path, need_update_structure=True
        )

        assert task.error is not None
        assert task.error.code == ErrorCode.ContainerVersionIsOutdated
        assert task.run() is False

    def test_old_schema_container_is_rejected_before_synchronization(
        self,
    ) -> None:
        container_path = self.create_temp_file(".gpkg")
        copy_legacy_36_points_container(container_path)
        mark_container_changed(container_path)

        task = FetchAdditionalDataTask(
            container_path, need_update_structure=True
        )

        assert task.error is not None
        assert task.error.code == ErrorCode.ContainerVersionIsOutdated
        assert task.run() is False

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_versioning_epoch_mismatch_is_treated_as_epoch_changed(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        ngw_error = NgwError(
            "NGW communication error",
            user_message="Epoch mismatch.",
            ngw_exception_class=(
                "nextgisweb.feature_layer.versioning.exception."
                "FVersioningEpochMismatch"
            ),
        )
        module = (
            "nextgis_connect.legacy.detached_editing.sync.versioned."
            "fetch_delta_task"
        )
        with patch(f"{module}.QgsNgwConnection") as connection_mock:
            connection_mock.return_value.get.side_effect = ngw_error

            task = FetchDeltaTask(container_mock.path)

            assert task.run() is False

        assert task.error is not None
        assert task.error.code == ErrorCode.EpochChanged

    @mock_container(TestData.Points)
    def test_additional_data_network_error_preserves_network_context(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        network_error = NgwError(
            "Connection error",
            is_network_problem=True,
        )
        module = (
            "nextgis_connect.legacy.detached_editing.sync.common."
            "fetch_additional_data_task"
        )
        with patch(f"{module}.QgsNgwConnection") as connection_mock:
            connection_mock.return_value.get.side_effect = network_error
            task = FetchAdditionalDataTask(container_mock.path)

            assert task.run() is False

        assert task.error is not None
        assert task.error.is_network_problem
        assert "network problem" in task.error.user_message.lower()
        assert container_mock.metadata.layer_name in task.error.user_message
        assert (
            str(container_mock.metadata.resource_id)
            not in task.error.user_message
        )
        assert "fetching extra data" not in task.error.user_message.lower()

        error_notes = getattr(task.error, "__notes__", ())
        diagnostic_information = "\n".join(error_notes) + str(task.error)
        assert (
            str(container_mock.metadata.resource_id) in diagnostic_information
        )
        assert (
            f"Container path: {container_mock.path}" in diagnostic_information
        )

    @mock_container(TestData.Points)
    def test_stale_additional_data_callback_is_ignored_after_container_delete(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        container = DetachedContainer(container_mock.path)
        callback = container._DetachedContainer__on_additional_data_fetched

        container.deleteLater()
        QCoreApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )

        assert sip.isdeleted(container)

        callback()

    @mock_container(TestData.Points)
    def test_additional_data_error_has_human_readable_message(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        module = (
            "nextgis_connect.legacy.detached_editing.sync.common."
            "fetch_additional_data_task"
        )
        with patch(f"{module}.QgsNgwConnection") as connection_mock:
            connection_mock.return_value.get.side_effect = ValueError(
                "Malformed response"
            )
            task = FetchAdditionalDataTask(container_mock.path)

            assert task.run() is False

        assert task.error is not None
        assert task.error.user_message == (
            f'Could not synchronize layer "{container_mock.metadata.layer_name}".'
        )
        assert (
            str(container_mock.metadata.resource_id)
            not in task.error.user_message
        )

    @mock_container(TestData.Points)
    def test_structure_change_error_keeps_reason(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        task = FetchAdditionalDataTask(container_mock.path)
        error = SynchronizationError(code=ErrorCode.StructureChanged)

        prepared_error = task._prepare_error(error)

        assert isinstance(prepared_error, SynchronizationError)
        assert prepared_error.user_message.startswith(
            "The layer structure is different from the structure on the "
            "server."
        )
        assert (
            f'Affected layer: "{container_mock.metadata.layer_name}".'
            in prepared_error.user_message
        )

    @mock_container(TestData.Points)
    def test_additional_data_server_error_has_contact_action(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        server_error = NgwError.from_json(
            {
                "status_code": 500,
                "title": "Internal server error",
                "message": "Internal server error",
                "detail": "Database connection pool is exhausted",
            }
        )
        module = (
            "nextgis_connect.legacy.detached_editing.sync.common."
            "fetch_additional_data_task"
        )
        with patch(f"{module}.QgsNgwConnection") as connection_mock:
            connection_mock.return_value.get.side_effect = server_error
            task = FetchAdditionalDataTask(container_mock.path)

            assert task.run() is False

        assert task.error is not None
        assert task.error.is_server_unavailable
        assert task.error.status_code == 500
        assert task.error.detail is None
        assert "temporarily unavailable" in task.error.user_message
        assert "try again later" in task.error.user_message.lower()
        assert container_mock.metadata.layer_name in task.error.user_message
        assert (
            str(container_mock.metadata.resource_id)
            not in task.error.user_message
        )
        assert [name for name, _callback in task.error.actions] == [
            "Contact us"
        ]

    @mock_container(TestData.Points)
    def test_container_error_diagnostics_include_container_path(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        container = DetachedContainer(container_mock.path)
        self.addCleanup(container.deleteLater)

        error = ContainerError("Local container failure")
        process_error = container._DetachedContainer__process_error
        process_error(error, show_error=False)

        error_notes = getattr(error, "__notes__", ())
        diagnostic_information = "\n".join(error_notes) + str(error)
        assert (
            f"Container path: {container_mock.path}" in diagnostic_information
        )

    @mock_container(TestData.Points)
    def test_reset_required_error_offers_reset_action(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        container = DetachedContainer(container_mock.path)
        self.addCleanup(container.deleteLater)
        error = ContainerError(code=ErrorCode.StructureChanged)

        container._DetachedContainer__process_error(error, show_error=False)

        assert error.user_message.startswith(
            "The layer structure is different from the structure on the "
            "server."
        )
        assert "Affected layer:" in error.user_message
        assert [name for name, _callback in error.actions] == ["Reset layer"]
        assert error.detail is not None
        assert "further synchronization becomes impossible" in error.detail

    @mock_container(TestData.Points)
    def test_outdated_container_is_reset_automatically(
        self,
        container_mock: MagicMock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        del qgs_layer

        container = DetachedContainer(container_mock.path)
        self.addCleanup(container.deleteLater)
        error = ContainerError(code=ErrorCode.ContainerVersionIsOutdated)
        container._DetachedContainer__sync_task = SimpleNamespace(error=error)

        with patch.object(
            container, "_DetachedContainer__finish_sync"
        ) as finish_sync, patch.object(container, "reset_container") as reset:
            container._DetachedContainer__on_synchronization_finished(False)

        finish_sync.assert_called_once()
        reset.assert_called_once()
