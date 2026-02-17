from dataclasses import replace
from typing import Union

from qgis.core import QgsGeometry, QgsVectorLayer, edit

from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    AttachmentConflictResolvingItem,
    AttachmentDataConflictResolvingItem,
    AttachmentDeleteConflictResolvingItem,
    DescriptionConflictResolvingItem,
    FeatureDataConflictResolvingItem,
    FeatureDeleteConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item_extractor import (
    ConflictResolvingItemExtractor,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentDataConflict,
    DescriptionConflict,
    FeatureDataConflict,
    LocalAttachmentDeletionConflict,
    LocalFeatureDeletionConflict,
    RemoteAttachmentDeletionConflict,
    RemoteFeatureDeletionConflict,
)
from nextgis_connect.detached_editing.container.editing.container_sessions import (
    ContainerReadWriteSession,
)
from nextgis_connect.detached_editing.detached_layer import DetachedLayer
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentDeletion,
    AttachmentUpdate,
    DescriptionPut,
    FeatureDeletion,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.sync.common.changes_extractor import (
    ChangesExtractor,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentDeleteAction,
    AttachmentUpdateAction,
    DescriptionPutAction,
    FeatureDeleteAction,
    FeatureRestoreAction,
    FeatureUpdateAction,
)
from nextgis_connect.detached_editing.utils import AttachmentMetadata
from nextgis_connect.resources.ngw_field import NgwField
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings
from nextgis_connect.types import Unset, UnsetType
from tests.detached_editing.utils import mock_container
from tests.ng_connect_testcase import NgConnectTestCase, TestData

FEATURE_CONFLICT_ITEM_TYPES = (
    FeatureDataConflictResolvingItem,
    FeatureDeleteConflictResolvingItem,
)

ATTACHMENT_CONFLICT_ITEM_TYPES = (
    AttachmentDataConflictResolvingItem,
    AttachmentDeleteConflictResolvingItem,
)


FeatureConflictResolvingItem = Union[
    FeatureDataConflictResolvingItem,
    FeatureDeleteConflictResolvingItem,
]


class TestConflictResolvingItemExtractor(NgConnectTestCase):
    FEATURE_VID = 11
    LOCAL_FID = 1
    NGW_FID = 101
    DESCRIPTION_VID = 21

    def _first_feature_id(self, qgs_layer: QgsVectorLayer) -> int:
        feature_ids = sorted(qgs_layer.allFeatureIds())
        self.assertGreater(len(feature_ids), 0)
        return feature_ids[0]

    def _second_feature_id(self, qgs_layer: QgsVectorLayer) -> int:
        feature_ids = sorted(qgs_layer.allFeatureIds())
        self.assertGreater(len(feature_ids), 1)
        return feature_ids[1]

    def _single_updated_feature_change(
        self,
        container_mock,
    ) -> FeatureUpdate:
        extractor = ChangesExtractor(container_mock.context)
        changes = extractor.extract_updated_features()
        self.assertEqual(len(changes), 1)
        self.assertIsInstance(changes[0], FeatureUpdate)
        return changes[0]

    def _single_deleted_feature_change(
        self,
        container_mock,
    ) -> FeatureDeletion:
        changes = ChangesExtractor(
            container_mock.context
        ).extract_deleted_features()
        self.assertEqual(len(changes), 1)
        self.assertIsInstance(changes[0], FeatureDeletion)
        return changes[0]

    def _single_updated_attachment_change(
        self,
        container_mock,
    ) -> AttachmentUpdate:
        changes = ChangesExtractor(
            container_mock.context
        ).extract_updated_attachments()
        self.assertEqual(len(changes), 1)
        self.assertIsInstance(changes[0], AttachmentUpdate)
        return changes[0]

    def _single_deleted_attachment_change(
        self,
        container_mock,
    ) -> AttachmentDeletion:
        changes = ChangesExtractor(
            container_mock.context
        ).extract_deleted_attachments()
        self.assertEqual(len(changes), 1)
        self.assertIsInstance(changes[0], AttachmentDeletion)
        return changes[0]

    def _extract_conflict_item(
        self,
        container_mock,
        conflict,
    ) -> FeatureConflictResolvingItem:
        result = ConflictResolvingItemExtractor(
            container_mock.context
        ).extract([conflict])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], FEATURE_CONFLICT_ITEM_TYPES)
        assert isinstance(result[0], FEATURE_CONFLICT_ITEM_TYPES)
        return result[0]

    def _extract_feature_data_conflict_item(
        self,
        container_mock,
        conflict: FeatureDataConflict,
    ) -> FeatureDataConflictResolvingItem:
        item = self._extract_conflict_item(container_mock, conflict)
        self.assertIsInstance(item, FeatureDataConflictResolvingItem)
        assert isinstance(item, FeatureDataConflictResolvingItem)
        return item

    def _extract_feature_delete_conflict_item(
        self,
        container_mock,
        conflict: Union[
            LocalFeatureDeletionConflict,
            RemoteFeatureDeletionConflict,
        ],
    ) -> FeatureDeleteConflictResolvingItem:
        item = self._extract_conflict_item(container_mock, conflict)
        self.assertIsInstance(item, FeatureDeleteConflictResolvingItem)
        assert isinstance(item, FeatureDeleteConflictResolvingItem)
        return item

    def _extract_attachment_conflict_item(
        self,
        container_mock,
        conflict,
    ) -> AttachmentConflictResolvingItem:
        result = ConflictResolvingItemExtractor(
            container_mock.context
        ).extract([conflict])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], ATTACHMENT_CONFLICT_ITEM_TYPES)
        assert isinstance(result[0], ATTACHMENT_CONFLICT_ITEM_TYPES)
        return result[0]

    def _extract_description_conflict_item(
        self,
        container_mock,
        conflict: DescriptionConflict,
    ) -> DescriptionConflictResolvingItem:
        result = ConflictResolvingItemExtractor(
            container_mock.context
        ).extract([conflict])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], DescriptionConflictResolvingItem)
        assert isinstance(result[0], DescriptionConflictResolvingItem)
        return result[0]

    def _description_conflict_item(
        self,
        local_description: str,
        remote_description: str,
    ) -> DescriptionConflictResolvingItem:
        conflict = DescriptionConflict(
            local_change=DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description=local_description,
            ),
            remote_action=DescriptionPutAction(
                fid=self.NGW_FID,
                vid=self.DESCRIPTION_VID,
                value=remote_description,
            ),
        )

        return DescriptionConflictResolvingItem(
            conflict=conflict,
            local_description=local_description,
            remote_description=remote_description,
        )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_builds_expected_conflicting_fields(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        LOCAL_STRING_VALUE = "local-value"
        REMOTE_STRING_VALUE = "remote-value"
        LOCAL_GEOMETRY = QgsGeometry.fromWkt("Point (10 20)")
        REMOTE_GEOMETRY = QgsGeometry.fromWkt("Point (30 40)")

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    LOCAL_STRING_VALUE,
                )
            )
            self.assertTrue(
                qgs_layer.changeGeometry(feature_id, LOCAL_GEOMETRY)
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[(string_field.ngw_id, REMOTE_STRING_VALUE)],
                geom=REMOTE_GEOMETRY,
            ),
        )

        item = self._extract_feature_data_conflict_item(
            container_mock,
            conflict,
        )
        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)

        self.assertIsNotNone(item.local_feature)
        assert item.local_feature is not None
        self.assertEqual(
            item.local_feature.attribute(string_field.attribute),
            LOCAL_STRING_VALUE,
        )
        self.assertTrue(item.local_feature.geometry().equals(LOCAL_GEOMETRY))

        self.assertIsNotNone(item.remote_feature)
        assert item.remote_feature is not None
        self.assertEqual(
            item.remote_feature.attribute(string_field.attribute),
            REMOTE_STRING_VALUE,
        )
        self.assertTrue(item.remote_feature.geometry().equals(REMOTE_GEOMETRY))

        self.assertIsNotNone(item.result_feature)
        assert item.result_feature is not None
        assert not isinstance(item.result_feature, UnsetType)
        self.assertIn(
            item.result_feature.attribute(string_field.attribute),
            (None, "NULL"),
        )
        self.assertTrue(item.result_feature.geometry().isNull())

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_builds_expected_not_conflicting_geometry(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        feature_state = qgs_layer.getFeature(feature_id)

        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        LOCAL_STRING_VALUE = "local-value"
        REMOTE_STRING_VALUE = "remote-value"
        LOCAL_GEOMETRY = QgsGeometry.fromWkt("Point (10 20)")
        REMOTE_GEOMETRY = feature_state.geometry()

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    LOCAL_STRING_VALUE,
                )
            )
            self.assertTrue(
                qgs_layer.changeGeometry(feature_id, LOCAL_GEOMETRY)
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[(string_field.ngw_id, REMOTE_STRING_VALUE)],
                geom=Unset,
            ),
        )

        item = self._extract_feature_data_conflict_item(
            container_mock,
            conflict,
        )
        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)

        self.assertIsNotNone(item.local_feature)
        assert item.local_feature is not None
        self.assertTrue(item.local_feature.geometry().equals(LOCAL_GEOMETRY))

        self.assertIsNotNone(item.remote_feature)
        assert item.remote_feature is not None
        self.assertTrue(item.remote_feature.geometry().equals(REMOTE_GEOMETRY))

        self.assertIsNotNone(item.result_feature)
        assert item.result_feature is not None
        assert not isinstance(item.result_feature, UnsetType)
        self.assertTrue(item.result_feature.geometry().equals(LOCAL_GEOMETRY))

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_extracts_remote_feature_from_restore_action(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        integer_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="INTEGER"
        )
        remote_geometry = QgsGeometry.fromWkt("Point (91 92)")

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    "local-restored-value",
                )
            )
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    integer_field.attribute,
                    777,
                )
            )
            self.assertTrue(
                qgs_layer.changeGeometry(feature_id, remote_geometry)
            )

        with ContainerReadWriteSession(container_mock.context) as cursor:
            cursor.execute(
                "DELETE FROM ngw_updated_attributes WHERE fid = ?",
                (feature_id,),
            )
            cursor.execute(
                "DELETE FROM ngw_updated_geometries WHERE fid = ?",
                (feature_id,),
            )
            cursor.execute(
                "INSERT INTO ngw_restored_features (fid) VALUES (?)",
                (feature_id,),
            )

        local_change = ChangesExtractor(
            container_mock.context
        ).extract_restored_features()[0]
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureRestoreAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[(string_field.ngw_id, "remote-restored-value")],
                geom=QgsGeometry.fromWkt("Point (11 12)"),
            ),
        )

        item = self._extract_feature_data_conflict_item(
            container_mock,
            conflict,
        )

        self.assertIsNotNone(item.remote_feature)
        assert item.remote_feature is not None
        self.assertEqual(
            item.remote_feature.attribute(string_field.attribute),
            "remote-restored-value",
        )
        self.assertIn(
            item.remote_feature.attribute(integer_field.attribute),
            (None, "NULL"),
        )
        self.assertTrue(
            item.remote_feature.geometry().equals(
                QgsGeometry.fromWkt("Point (11 12)")
            )
        )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_extracting_not_conflicting_fields(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        integer_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="INTEGER"
        )
        datetime_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="DATETIME"
        )

        initial_feature = qgs_layer.getFeature(feature_id)

        LOCAL_STRING_VALUE = "local-string-value"
        REMOTE_STRING_VALUE = "remote-string-value"
        LOCAL_INTEGER_VALUE = 777
        REMOTE_DATETIME_VALUE = "2024-01-01T12:00:00Z"

        initial_integer_value = initial_feature.attribute(
            integer_field.attribute
        )
        initial_datetime_value = initial_feature.attribute(
            datetime_field.attribute
        )

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    LOCAL_STRING_VALUE,
                )
            )
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    integer_field.attribute,
                    LOCAL_INTEGER_VALUE,
                )
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[
                    (string_field.ngw_id, REMOTE_STRING_VALUE),
                    (datetime_field.ngw_id, REMOTE_DATETIME_VALUE),
                ],
            ),
        )

        item = self._extract_feature_data_conflict_item(
            container_mock,
            conflict,
        )
        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)

        self.assertIsNotNone(item.local_feature)
        assert item.local_feature is not None
        self.assertEqual(
            item.local_feature.attribute(string_field.attribute),
            LOCAL_STRING_VALUE,
        )
        self.assertEqual(
            item.local_feature.attribute(integer_field.attribute),
            LOCAL_INTEGER_VALUE,
        )
        self.assertEqual(
            item.local_feature.attribute(datetime_field.attribute),
            initial_datetime_value,
        )

        self.assertIsNotNone(item.remote_feature)
        assert item.remote_feature is not None
        self.assertEqual(
            item.remote_feature.attribute(string_field.attribute),
            REMOTE_STRING_VALUE,
        )
        self.assertEqual(
            item.remote_feature.attribute(integer_field.attribute),
            initial_integer_value,
        )
        self.assertEqual(
            item.remote_feature.attribute(datetime_field.attribute),
            REMOTE_DATETIME_VALUE,
        )

        self.assertIsNotNone(item.result_feature)
        assert item.result_feature is not None
        assert not isinstance(item.result_feature, UnsetType)
        self.assertIn(
            item.result_feature.attribute(string_field.attribute),
            (None, "NULL"),
        )
        self.assertEqual(
            item.result_feature.attribute(integer_field.attribute),
            LOCAL_INTEGER_VALUE,
        )
        self.assertEqual(
            item.result_feature.attribute(datetime_field.attribute),
            REMOTE_DATETIME_VALUE,
        )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_extract_local_feature_deletion_conflict_uses_deleted_backup(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        integer_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="INTEGER"
        )
        initial_feature = qgs_layer.getFeature(feature_id)
        initial_integer_value = initial_feature.attribute(
            integer_field.attribute
        )
        EDITED_INTEGER_VALUE = 456
        REMOTE_STRING_VALUE = "remote-after-delete"
        intermediate_geometry = QgsGeometry.fromWkt("Point (15 25)")
        remote_geometry = QgsGeometry.fromWkt("Point (50 60)")

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    integer_field.attribute,
                    EDITED_INTEGER_VALUE,
                )
            )
            self.assertTrue(
                qgs_layer.changeGeometry(feature_id, intermediate_geometry)
            )

        with edit(qgs_layer):
            self.assertTrue(qgs_layer.deleteFeature(feature_id))

        local_change = self._single_deleted_feature_change(container_mock)
        conflict = LocalFeatureDeletionConflict(
            local_change=local_change,
            remote_actions=[
                FeatureUpdateAction(
                    fid=local_change.ngw_fid,
                    vid=self.FEATURE_VID,
                    fields=[(string_field.ngw_id, REMOTE_STRING_VALUE)],
                    geom=remote_geometry,
                )
            ],
        )

        item = self._extract_conflict_item(container_mock, conflict)
        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)

        self.assertIsNone(item.local_feature)
        self.assertIs(item.result_feature, Unset)
        self.assertIsNotNone(item.remote_feature)
        assert item.remote_feature is not None
        self.assertEqual(
            item.remote_feature.attribute(string_field.attribute),
            REMOTE_STRING_VALUE,
        )
        self.assertEqual(
            item.remote_feature.attribute(integer_field.attribute),
            initial_integer_value,
        )
        self.assertTrue(item.remote_feature.geometry().equals(remote_geometry))

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_extract_remote_feature_deletion_conflict_keeps_local_feature(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        integer_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="INTEGER"
        )
        initial_feature = qgs_layer.getFeature(feature_id)
        initial_integer_value = initial_feature.attribute(
            integer_field.attribute
        )
        LOCAL_STRING_VALUE = "local-survived"
        local_geometry = QgsGeometry.fromWkt("Point (70 80)")

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    LOCAL_STRING_VALUE,
                )
            )
            self.assertTrue(
                qgs_layer.changeGeometry(feature_id, local_geometry)
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = RemoteFeatureDeletionConflict(
            local_changes=[local_change],
            remote_action=FeatureDeleteAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
            ),
        )

        item = self._extract_conflict_item(container_mock, conflict)
        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)

        self.assertIsNotNone(item.local_feature)
        assert item.local_feature is not None
        self.assertEqual(
            item.local_feature.attribute(string_field.attribute),
            LOCAL_STRING_VALUE,
        )
        self.assertEqual(
            item.local_feature.attribute(integer_field.attribute),
            initial_integer_value,
        )
        self.assertTrue(item.local_feature.geometry().equals(local_geometry))
        self.assertIsNone(item.remote_feature)
        self.assertIs(item.result_feature, Unset)

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        descriptions={1: "initial-description"},
        attachments=[
            AttachmentMetadata(
                fid=1,
                aid=501,
                ngw_aid=501,
                version=11,
                name="initial-attachment",
                description="initial-attachment-description",
                mime_type="text/plain",
            ),
            AttachmentMetadata(
                fid=1,
                aid=502,
                ngw_aid=502,
                version=12,
                name="removed-locally-attachment",
                description="removed-locally-description",
                mime_type="text/plain",
            ),
        ],
    )
    def test_extract_local_feature_deletion_conflict_with_remote_description(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        detached_layer = DetachedLayer(container_mock, qgs_layer)
        feature_id = self._first_feature_id(qgs_layer)

        with edit(qgs_layer):
            detached_layer.set_feature_description(
                feature_id,
                "local-description-before-delete",
            )

        settings = NgConnectSettings()
        should_notify = settings.notify_when_deleting_features_with_attachments
        settings.notify_when_deleting_features_with_attachments = False
        try:
            with edit(qgs_layer):
                self.assertTrue(qgs_layer.deleteFeature(feature_id))
        finally:
            settings.notify_when_deleting_features_with_attachments = (
                should_notify
            )

        local_change = self._single_deleted_feature_change(container_mock)
        conflict = LocalFeatureDeletionConflict(
            local_change=local_change,
            remote_actions=[
                DescriptionPutAction(
                    fid=local_change.ngw_fid,
                    vid=self.DESCRIPTION_VID,
                    value="remote-description",
                )
            ],
        )

        item = self._extract_feature_delete_conflict_item(
            container_mock,
            conflict,
        )

        self.assertEqual(item.remote_description, "remote-description")
        self.assertIsNone(item.local_description)

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        descriptions={1: "initial-description"},
        attachments=[
            AttachmentMetadata(
                fid=1,
                aid=501,
                ngw_aid=501,
                version=11,
                name="initial-attachment",
                description="initial-attachment-description",
                mime_type="text/plain",
            ),
            AttachmentMetadata(
                fid=1,
                aid=502,
                ngw_aid=502,
                version=12,
                name="removed-locally-attachment",
                description="removed-locally-description",
                mime_type="text/plain",
            ),
        ],
    )
    def test_extract_local_feature_deletion_conflict_with_remote_attachments(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        detached_layer = DetachedLayer(container_mock, qgs_layer)
        feature_id = self._first_feature_id(qgs_layer)

        with edit(qgs_layer):
            detached_layer.remove_attachment(feature_id, 502)

        settings = NgConnectSettings()
        should_notify = settings.notify_when_deleting_features_with_attachments
        settings.notify_when_deleting_features_with_attachments = False
        try:
            with edit(qgs_layer):
                self.assertTrue(qgs_layer.deleteFeature(feature_id))
        finally:
            settings.notify_when_deleting_features_with_attachments = (
                should_notify
            )

        local_change = self._single_deleted_feature_change(container_mock)
        conflict = LocalFeatureDeletionConflict(
            local_change=local_change,
            remote_actions=[
                AttachmentUpdateAction(
                    fid=local_change.ngw_fid,
                    aid=501,
                    vid=self.FEATURE_VID,
                    name="remote-attachment-name",
                ),
                AttachmentUpdateAction(
                    fid=local_change.ngw_fid,
                    aid=502,
                    vid=self.FEATURE_VID + 1,
                    description="remote-removed-attachment-description",
                ),
            ],
        )

        item = self._extract_feature_delete_conflict_item(
            container_mock,
            conflict,
        )

        attachments_by_id = {
            attachment.ngw_aid: attachment
            for attachment in item.remote_attachments
        }
        self.assertIn(501, attachments_by_id)
        self.assertIn(502, attachments_by_id)
        self.assertEqual(
            attachments_by_id[501].name,
            "remote-attachment-name",
        )
        self.assertEqual(
            attachments_by_id[501].description,
            "initial-attachment-description",
        )
        self.assertEqual(
            attachments_by_id[502].name,
            "removed-locally-attachment",
        )
        self.assertEqual(
            attachments_by_id[502].description,
            "remote-removed-attachment-description",
        )

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        descriptions={2: "local-description"},
    )
    def test_extract_remote_feature_deletion_conflict_with_local_description(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        feature_id = self._second_feature_id(qgs_layer)
        conflict = RemoteFeatureDeletionConflict(
            local_changes=[
                DescriptionPut(
                    fid=feature_id,
                    ngw_fid=feature_id,
                    description="local-description",
                )
            ],
            remote_action=FeatureDeleteAction(
                fid=feature_id,
                vid=self.FEATURE_VID,
            ),
        )

        item = self._extract_feature_delete_conflict_item(
            container_mock,
            conflict,
        )

        self.assertEqual(item.local_description, "local-description")
        self.assertIsNone(item.remote_description)

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        attachments=[
            AttachmentMetadata(
                fid=2,
                aid=601,
                ngw_aid=701,
                version=13,
                name="initial-second-feature-attachment",
                description="initial-second-feature-description",
                mime_type="text/plain",
            ),
        ],
    )
    def test_extract_remote_feature_deletion_conflict_with_local_attachment(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        detached_layer = DetachedLayer(container_mock, qgs_layer)
        feature_id = self._second_feature_id(qgs_layer)

        with edit(qgs_layer):
            feature_attachment = detached_layer.feature_attachment(
                feature_id,
                601,
            )
            assert feature_attachment is not None
            detached_layer.update_attachment(
                replace(feature_attachment, name="local-attachment-name")
            )

        conflict = RemoteFeatureDeletionConflict(
            local_changes=[
                AttachmentUpdate(
                    fid=feature_id,
                    ngw_fid=feature_id,
                    aid=601,
                    ngw_aid=701,
                    name="local-attachment-name",
                )
            ],
            remote_action=FeatureDeleteAction(
                fid=feature_id,
                vid=self.FEATURE_VID,
            ),
        )

        item = self._extract_feature_delete_conflict_item(
            container_mock,
            conflict,
        )

        self.assertEqual(len(item.local_attachments), 1)
        local_attachments_by_id = {
            attachment.aid: attachment for attachment in item.local_attachments
        }
        self.assertIn(601, local_attachments_by_id)
        self.assertEqual(
            local_attachments_by_id[601].name,
            "local-attachment-name",
        )
        self.assertEqual(
            local_attachments_by_id[601].description,
            "initial-second-feature-description",
        )
        self.assertEqual(item.remote_attachments, [])

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_update_state_after_manual_field_resolution(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )

        LOCAL_STRING_VALUE = "local-value"
        REMOTE_STRING_VALUE = "remote-value"
        CUSTOM_STRING_VALUE = "custom-value"

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    LOCAL_STRING_VALUE,
                )
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[(string_field.ngw_id, REMOTE_STRING_VALUE)],
                geom=Unset,
            ),
        )

        for subtest_name, target_value, expected_resolution_type in (
            ("local_value", LOCAL_STRING_VALUE, ResolutionType.Local),
            ("remote_value", REMOTE_STRING_VALUE, ResolutionType.Remote),
            ("custom_value", CUSTOM_STRING_VALUE, ResolutionType.Custom),
        ):
            with self.subTest(resolved_as=subtest_name):
                item = self._extract_feature_data_conflict_item(
                    container_mock,
                    conflict,
                )
                self.assertFalse(item.is_resolved)
                self.assertEqual(
                    item.resolution_type,
                    ResolutionType.NoResolution,
                )

                assert item.result_feature is not None
                assert not isinstance(item.result_feature, UnsetType)
                item.result_feature.setAttribute(
                    string_field.attribute,
                    target_value,
                )
                item.changed_fields.add(string_field.ngw_id)

                self.assertTrue(item.is_resolved)
                self.assertEqual(
                    item.resolution_type,
                    expected_resolution_type,
                )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_update_state_after_manual_geometry_resolution(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        LOCAL_GEOMETRY = QgsGeometry.fromWkt("Point (10 20)")
        REMOTE_GEOMETRY = QgsGeometry.fromWkt("Point (30 40)")
        CUSTOM_GEOMETRY = QgsGeometry.fromWkt("Point (50 60)")

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeGeometry(feature_id, LOCAL_GEOMETRY)
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[],
                geom=REMOTE_GEOMETRY,
            ),
        )

        for (
            subtest_name,
            target_geometry,
            expected_resolution_type,
        ) in (
            ("local_geometry", LOCAL_GEOMETRY, ResolutionType.Local),
            ("remote_geometry", REMOTE_GEOMETRY, ResolutionType.Remote),
            ("custom_geometry", CUSTOM_GEOMETRY, ResolutionType.Custom),
        ):
            with self.subTest(resolved_as=subtest_name):
                item = self._extract_feature_data_conflict_item(
                    container_mock,
                    conflict,
                )
                self.assertFalse(item.is_resolved)
                self.assertEqual(
                    item.resolution_type,
                    ResolutionType.NoResolution,
                )

                assert item.result_feature is not None
                assert not isinstance(item.result_feature, UnsetType)
                item.result_feature.setGeometry(target_geometry)
                item.is_geometry_changed = True

                self.assertTrue(item.is_resolved)
                self.assertEqual(
                    item.resolution_type,
                    expected_resolution_type,
                )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_update_state_after_manual_mixed_two_fields_resolution(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        integer_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="INTEGER"
        )

        LOCAL_STRING_VALUE = "local-string-value"
        REMOTE_STRING_VALUE = "remote-string-value"
        LOCAL_INTEGER_VALUE = 111
        REMOTE_INTEGER_VALUE = 222

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    LOCAL_STRING_VALUE,
                )
            )
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    integer_field.attribute,
                    LOCAL_INTEGER_VALUE,
                )
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[
                    (string_field.ngw_id, REMOTE_STRING_VALUE),
                    (integer_field.ngw_id, REMOTE_INTEGER_VALUE),
                ],
                geom=Unset,
            ),
        )

        item = self._extract_feature_data_conflict_item(
            container_mock,
            conflict,
        )
        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)

        assert item.result_feature is not None
        assert not isinstance(item.result_feature, UnsetType)
        item.result_feature.setAttribute(
            string_field.attribute,
            LOCAL_STRING_VALUE,
        )
        item.result_feature.setAttribute(
            integer_field.attribute,
            REMOTE_INTEGER_VALUE,
        )
        item.changed_fields.add(string_field.ngw_id)
        item.changed_fields.add(integer_field.ngw_id)

        self.assertTrue(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.Custom)

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_resolve_as_local(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        LOCAL_STRING_VALUE = "local-value"
        REMOTE_STRING_VALUE = "remote-value"
        LOCAL_GEOMETRY = QgsGeometry.fromWkt("Point (10 20)")
        REMOTE_GEOMETRY = QgsGeometry.fromWkt("Point (30 40)")

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    LOCAL_STRING_VALUE,
                )
            )
            self.assertTrue(
                qgs_layer.changeGeometry(feature_id, LOCAL_GEOMETRY)
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[(string_field.ngw_id, REMOTE_STRING_VALUE)],
                geom=REMOTE_GEOMETRY,
            ),
        )

        item = self._extract_feature_data_conflict_item(
            container_mock,
            conflict,
        )
        self.assertFalse(item.is_resolved)

        item.resolve_as_local()

        self.assertTrue(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.Local)
        self.assertEqual(item.changed_fields, conflict.conflicting_fields)
        self.assertTrue(item.is_geometry_changed)
        self.assertIsNotNone(item.result_feature)
        self.assertIsNotNone(item.local_feature)
        assert item.result_feature is not None
        assert not isinstance(item.result_feature, UnsetType)
        assert item.local_feature is not None
        self.assertEqual(
            item.result_feature.attribute(string_field.attribute),
            item.local_feature.attribute(string_field.attribute),
        )
        self.assertTrue(
            item.result_feature.geometry().equals(
                item.local_feature.geometry()
            )
        )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_resolve_as_remote(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        LOCAL_STRING_VALUE = "local-value"
        REMOTE_STRING_VALUE = "remote-value"
        LOCAL_GEOMETRY = QgsGeometry.fromWkt("Point (10 20)")
        REMOTE_GEOMETRY = QgsGeometry.fromWkt("Point (30 40)")

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    LOCAL_STRING_VALUE,
                )
            )
            self.assertTrue(
                qgs_layer.changeGeometry(feature_id, LOCAL_GEOMETRY)
            )

        local_change = self._single_updated_feature_change(container_mock)
        conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[(string_field.ngw_id, REMOTE_STRING_VALUE)],
                geom=REMOTE_GEOMETRY,
            ),
        )

        item = self._extract_feature_data_conflict_item(
            container_mock,
            conflict,
        )
        self.assertFalse(item.is_resolved)

        item.resolve_as_remote()

        self.assertTrue(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.Remote)
        self.assertEqual(item.changed_fields, conflict.conflicting_fields)
        self.assertTrue(item.is_geometry_changed)
        self.assertIsNotNone(item.result_feature)
        self.assertIsNotNone(item.remote_feature)
        assert item.result_feature is not None
        assert item.remote_feature is not None
        assert not isinstance(item.result_feature, UnsetType)
        self.assertEqual(
            item.result_feature.attribute(string_field.attribute),
            item.remote_feature.attribute(string_field.attribute),
        )
        self.assertTrue(
            item.result_feature.geometry().equals(
                item.remote_feature.geometry()
            )
        )

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_resolve_deletion_conflicts(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        local_deletion_feature_id = self._first_feature_id(qgs_layer)
        remote_deletion_feature_id = self._second_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        REMOTE_STRING_VALUE = "remote-after-delete"
        REMOTE_GEOMETRY = QgsGeometry.fromWkt("Point (40 50)")

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    local_deletion_feature_id,
                    string_field.attribute,
                    "local-before-delete",
                )
            )

        with edit(qgs_layer):
            self.assertTrue(qgs_layer.deleteFeature(local_deletion_feature_id))

        local_deletion_change = self._single_deleted_feature_change(
            container_mock
        )

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    remote_deletion_feature_id,
                    string_field.attribute,
                    "local-survived",
                )
            )

        local_update_change = self._single_updated_feature_change(
            container_mock
        )

        local_deletion_conflict = LocalFeatureDeletionConflict(
            local_change=local_deletion_change,
            remote_actions=[
                FeatureUpdateAction(
                    fid=local_deletion_change.ngw_fid,
                    vid=self.FEATURE_VID,
                    fields=[(string_field.ngw_id, REMOTE_STRING_VALUE)],
                    geom=REMOTE_GEOMETRY,
                )
            ],
        )
        remote_deletion_conflict = RemoteFeatureDeletionConflict(
            local_changes=[local_update_change],
            remote_action=FeatureDeleteAction(
                fid=local_update_change.ngw_fid,
                vid=self.FEATURE_VID,
            ),
        )

        with self.subTest(conflict_type="local_deletion"):
            local_deletion_item = self._extract_conflict_item(
                container_mock,
                local_deletion_conflict,
            )
            self.assertFalse(local_deletion_item.is_resolved)

            local_deletion_item.resolve_as_local()
            self.assertTrue(local_deletion_item.is_resolved)
            self.assertEqual(
                local_deletion_item.resolution_type,
                ResolutionType.Local,
            )
            self.assertIsNone(local_deletion_item.result_feature)

            local_deletion_item = self._extract_conflict_item(
                container_mock,
                local_deletion_conflict,
            )
            local_deletion_item.resolve_as_remote()
            self.assertTrue(local_deletion_item.is_resolved)
            self.assertEqual(
                local_deletion_item.resolution_type,
                ResolutionType.Remote,
            )
            self.assertIsNotNone(local_deletion_item.result_feature)
            self.assertIsNotNone(local_deletion_item.remote_feature)
            assert local_deletion_item.result_feature is not None
            assert not isinstance(
                local_deletion_item.result_feature, UnsetType
            )
            assert local_deletion_item.remote_feature is not None
            self.assertEqual(
                local_deletion_item.result_feature.attribute(
                    string_field.attribute
                ),
                local_deletion_item.remote_feature.attribute(
                    string_field.attribute
                ),
            )
            self.assertTrue(
                local_deletion_item.result_feature.geometry().equals(
                    local_deletion_item.remote_feature.geometry()
                )
            )

        with self.subTest(conflict_type="remote_deletion"):
            remote_deletion_item = self._extract_conflict_item(
                container_mock,
                remote_deletion_conflict,
            )
            self.assertFalse(remote_deletion_item.is_resolved)

            remote_deletion_item.resolve_as_local()
            self.assertTrue(remote_deletion_item.is_resolved)
            self.assertEqual(
                remote_deletion_item.resolution_type,
                ResolutionType.Local,
            )
            self.assertIsNotNone(remote_deletion_item.result_feature)
            self.assertIsNotNone(remote_deletion_item.local_feature)
            assert remote_deletion_item.result_feature is not None
            assert not isinstance(
                remote_deletion_item.result_feature, UnsetType
            )
            assert remote_deletion_item.local_feature is not None
            self.assertEqual(
                remote_deletion_item.result_feature.attribute(
                    string_field.attribute
                ),
                remote_deletion_item.local_feature.attribute(
                    string_field.attribute
                ),
            )
            self.assertTrue(
                remote_deletion_item.result_feature.geometry().equals(
                    remote_deletion_item.local_feature.geometry()
                )
            )

            remote_deletion_item = self._extract_conflict_item(
                container_mock,
                remote_deletion_conflict,
            )
            remote_deletion_item.resolve_as_remote()
            self.assertTrue(remote_deletion_item.is_resolved)
            self.assertEqual(
                remote_deletion_item.resolution_type,
                ResolutionType.Remote,
            )
            self.assertIsNone(remote_deletion_item.result_feature)

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_extract_description_conflict(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        local_description = "local-description"
        remote_description = "remote-description"

        conflict = DescriptionConflict(
            local_change=DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description=local_description,
            ),
            remote_action=DescriptionPutAction(
                fid=self.NGW_FID,
                vid=self.DESCRIPTION_VID,
                value=remote_description,
            ),
        )

        item = self._extract_description_conflict_item(
            container_mock,
            conflict,
        )

        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)
        self.assertEqual(item.local_description, local_description)
        self.assertEqual(item.remote_description, remote_description)
        self.assertIs(item.result_description, Unset)

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_extract_mixed_feature_and_description_conflicts(
        self, container_mock, qgs_layer: QgsVectorLayer
    ) -> None:
        _detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )

        local_string_value = "local-value"
        remote_string_value = "remote-value"
        local_description = "local-description"
        remote_description = "remote-description"

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    local_string_value,
                )
            )

        local_change = self._single_updated_feature_change(container_mock)
        feature_conflict = FeatureDataConflict(
            local_change=local_change,
            remote_action=FeatureUpdateAction(
                fid=local_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[(string_field.ngw_id, remote_string_value)],
                geom=Unset,
            ),
        )
        description_conflict = DescriptionConflict(
            local_change=DescriptionPut(
                fid=feature_id,
                ngw_fid=local_change.ngw_fid,
                description=local_description,
            ),
            remote_action=DescriptionPutAction(
                fid=local_change.ngw_fid,
                vid=self.DESCRIPTION_VID,
                value=remote_description,
            ),
        )

        items = ConflictResolvingItemExtractor(container_mock.context).extract(
            [feature_conflict, description_conflict]
        )

        self.assertEqual(len(items), 2)

        feature_items = [
            item
            for item in items
            if isinstance(item, FEATURE_CONFLICT_ITEM_TYPES)
        ]
        description_items = [
            item
            for item in items
            if isinstance(item, DescriptionConflictResolvingItem)
        ]

        self.assertEqual(len(feature_items), 1)
        self.assertEqual(len(description_items), 1)
        self.assertEqual(
            description_items[0].local_description,
            local_description,
        )
        self.assertEqual(
            description_items[0].remote_description,
            remote_description,
        )

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        attachments=[
            AttachmentMetadata(
                fid=1,
                aid=201,
                ngw_aid=201,
                version=11,
                name="initial-name",
                description="initial-description",
                mime_type="text/plain",
                fileobj=100,
            )
        ],
    )
    def test_extract_attachment_data_conflict_uses_updated_backup(
        self,
        container_mock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        attachment_id = 201

        with edit(qgs_layer):
            initial_attachment = detached_layer.feature_attachment(
                feature_id,
                attachment_id,
            )
            assert initial_attachment is not None
            detached_layer.update_attachment(
                replace(
                    initial_attachment,
                    name="local-name",
                    description="local-description",
                )
            )

        local_change = self._single_updated_attachment_change(container_mock)
        conflict = AttachmentDataConflict(
            local_change=local_change,
            remote_action=AttachmentUpdateAction(
                fid=local_change.ngw_fid,
                aid=local_change.ngw_aid,
                vid=31,
                description="remote-description",
            ),
        )

        item = self._extract_attachment_conflict_item(container_mock, conflict)

        self.assertIsInstance(item, AttachmentDataConflictResolvingItem)
        assert isinstance(item, AttachmentDataConflictResolvingItem)

        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)
        assert item.local_attachment is not None
        assert item.remote_attachment is not None
        self.assertEqual(item.local_attachment.name, "local-name")
        self.assertEqual(
            item.local_attachment.description,
            "local-description",
        )
        self.assertEqual(item.remote_attachment.name, "initial-name")
        self.assertEqual(
            item.remote_attachment.description,
            "remote-description",
        )
        self.assertIsNot(item.result_attachment, Unset)
        self.assertIsNotNone(item.result_attachment)
        self.assertEqual(
            item.result_attachment,
            replace(
                item.remote_attachment, name="local-name", description=Unset
            ),
        )

        self.assertFalse(item.is_name_changed)
        self.assertFalse(item.is_description_changed)
        self.assertFalse(item.is_file_changed)

        item.result_attachment = replace(
            item.result_attachment,  # pyright: ignore[reportArgumentType]
            description="resolved-description",
        )
        self.assertTrue(item.is_description_changed)

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        attachments=[
            AttachmentMetadata(
                fid=1,
                aid=202,
                ngw_aid=202,
                version=12,
                name="before-local-update",
                description="before-local-update-description",
                mime_type="text/plain",
            )
        ],
    )
    def test_extract_local_attachment_deletion_conflict_uses_deleted_backup(
        self,
        container_mock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        attachment_id = 202

        with edit(qgs_layer):
            initial_attachment = detached_layer.feature_attachment(
                feature_id,
                attachment_id,
            )
            assert initial_attachment is not None
            detached_layer.update_attachment(
                replace(
                    initial_attachment,
                    name="local-updated-before-delete",
                )
            )

        with edit(qgs_layer):
            detached_layer.remove_attachment(feature_id, attachment_id)

        local_change = self._single_deleted_attachment_change(container_mock)
        conflict = LocalAttachmentDeletionConflict(
            local_change=local_change,
            remote_action=AttachmentUpdateAction(
                fid=local_change.ngw_fid,
                aid=local_change.ngw_aid,
                vid=41,
                description="remote-after-delete",
            ),
        )

        item = self._extract_attachment_conflict_item(container_mock, conflict)

        self.assertIsInstance(item, AttachmentDeleteConflictResolvingItem)

        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)
        self.assertIs(item.result_attachment, Unset)
        self.assertIsNone(item.local_attachment)
        self.assertIsNotNone(item.remote_attachment)
        assert item.remote_attachment is not None
        self.assertEqual(item.remote_attachment.name, "before-local-update")
        self.assertEqual(
            item.remote_attachment.description,
            "remote-after-delete",
        )

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        attachments=[
            AttachmentMetadata(
                fid=1,
                aid=203,
                ngw_aid=203,
                version=13,
                name="initial-attachment",
                description="initial-description",
                mime_type="text/plain",
            )
        ],
    )
    def test_extract_remote_attachment_deletion_conflict_keeps_local_attachment(
        self,
        container_mock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        attachment_id = 203

        with edit(qgs_layer):
            initial_attachment = detached_layer.feature_attachment(
                feature_id,
                attachment_id,
            )
            assert initial_attachment is not None
            detached_layer.update_attachment(
                replace(initial_attachment, name="local-survived")
            )

        local_change = self._single_updated_attachment_change(container_mock)
        conflict = RemoteAttachmentDeletionConflict(
            local_change=local_change,
            remote_action=AttachmentDeleteAction(
                fid=local_change.ngw_fid,
                aid=local_change.ngw_aid,
                vid=51,
            ),
        )

        item = self._extract_attachment_conflict_item(container_mock, conflict)

        self.assertIsInstance(item, AttachmentDeleteConflictResolvingItem)

        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)
        self.assertIs(item.result_attachment, Unset)
        self.assertIsNotNone(item.local_attachment)
        self.assertIsNone(item.remote_attachment)
        assert item.local_attachment is not None
        self.assertEqual(item.local_attachment.name, "local-survived")

    @mock_container(
        TestData.Points,
        is_versioning_enabled=True,
        attachments=[
            AttachmentMetadata(
                fid=1,
                aid=204,
                ngw_aid=204,
                version=14,
                name="mixed-initial",
                description="mixed-initial-description",
                mime_type="text/plain",
            )
        ],
    )
    def test_extract_mixed_feature_and_attachment_conflicts(
        self,
        container_mock,
        qgs_layer: QgsVectorLayer,
    ) -> None:
        detached_layer = DetachedLayer(container_mock, qgs_layer)

        feature_id = self._first_feature_id(qgs_layer)
        string_field: NgwField = container_mock.metadata.fields.get_with(
            keyname="STRING"
        )
        attachment_id = 204

        with edit(qgs_layer):
            self.assertTrue(
                qgs_layer.changeAttributeValue(
                    feature_id,
                    string_field.attribute,
                    "local-feature-value",
                )
            )
            initial_attachment = detached_layer.feature_attachment(
                feature_id,
                attachment_id,
            )
            assert initial_attachment is not None
            detached_layer.update_attachment(
                replace(initial_attachment, description="local-attachment")
            )

        local_feature_change = self._single_updated_feature_change(
            container_mock
        )
        local_attachment_change = self._single_updated_attachment_change(
            container_mock
        )
        feature_conflict = FeatureDataConflict(
            local_change=local_feature_change,
            remote_action=FeatureUpdateAction(
                fid=local_feature_change.ngw_fid,
                vid=self.FEATURE_VID,
                fields=[(string_field.ngw_id, "remote-feature-value")],
                geom=Unset,
            ),
        )
        attachment_conflict = AttachmentDataConflict(
            local_change=local_attachment_change,
            remote_action=AttachmentUpdateAction(
                fid=local_attachment_change.ngw_fid,
                aid=local_attachment_change.ngw_aid,
                vid=61,
                description="remote-attachment",
            ),
        )

        items = ConflictResolvingItemExtractor(container_mock.context).extract(
            [feature_conflict, attachment_conflict]
        )

        self.assertEqual(len(items), 2)
        feature_items = [
            item
            for item in items
            if isinstance(item, FEATURE_CONFLICT_ITEM_TYPES)
        ]
        attachment_items = [
            item
            for item in items
            if isinstance(item, AttachmentConflictResolvingItem)
        ]

        self.assertEqual(len(feature_items), 1)
        self.assertEqual(len(attachment_items), 1)
        self.assertIsNotNone(attachment_items[0].local_attachment)
        self.assertIsNotNone(attachment_items[0].remote_attachment)

    def test_description_conflict_manual_resolution_state(self) -> None:
        local_description = "local-description"
        remote_description = "remote-description"
        custom_description = "custom-description"

        for (
            subtest_name,
            target_description,
            expected_resolution_type,
        ) in (
            (
                "local_description",
                local_description,
                ResolutionType.Local,
            ),
            (
                "remote_description",
                remote_description,
                ResolutionType.Remote,
            ),
            (
                "custom_description",
                custom_description,
                ResolutionType.Custom,
            ),
        ):
            with self.subTest(resolved_as=subtest_name):
                item = self._description_conflict_item(
                    local_description,
                    remote_description,
                )
                self.assertFalse(item.is_resolved)
                self.assertEqual(
                    item.resolution_type,
                    ResolutionType.NoResolution,
                )

                item.result_description = target_description

                self.assertTrue(item.is_resolved)
                self.assertEqual(
                    item.resolution_type,
                    expected_resolution_type,
                )

    def test_description_conflict_resolve_as_local(self) -> None:
        local_description = "local-description"
        remote_description = "remote-description"

        item = self._description_conflict_item(
            local_description,
            remote_description,
        )
        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)

        item.resolve_as_local()

        self.assertTrue(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.Local)
        self.assertEqual(item.result_description, local_description)

    def test_description_conflict_resolve_as_remote(self) -> None:
        local_description = "local-description"
        remote_description = "remote-description"

        item = self._description_conflict_item(
            local_description,
            remote_description,
        )
        self.assertFalse(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.NoResolution)

        item.resolve_as_remote()

        self.assertTrue(item.is_resolved)
        self.assertEqual(item.resolution_type, ResolutionType.Remote)
        self.assertEqual(item.result_description, remote_description)
