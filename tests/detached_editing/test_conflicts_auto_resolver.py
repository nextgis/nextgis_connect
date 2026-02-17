from qgis.core import QgsGeometry

from nextgis_connect.detached_editing.conflicts.auto_resolver import (
    ConflictsAutoResolver,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    AttachmentConflictResolution,
    DescriptionConflictResolution,
    FeatureConflictResolution,
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentDataConflict,
    DescriptionConflict,
    FeatureDataConflict,
    LocalAttachmentDeletionConflict,
    LocalFeatureDeletionConflict,
    RemoteFeatureDeletionConflict,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentUpdate,
    DescriptionPut,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentDeleteAction,
    AttachmentRestoreAction,
    AttachmentUpdateAction,
    DescriptionPutAction,
    FeatureDeleteAction,
    FeatureRestoreAction,
    FeatureUpdateAction,
)
from nextgis_connect.types import Unset
from tests.ng_connect_testcase import NgConnectTestCase


class TestConflictsAutoResolver(NgConnectTestCase):
    LOCAL_FID = 1
    LOCAL_AID = 10
    NGW_FID = 101
    NGW_AID = 201
    FEATURE_VID = 11
    EXTENSION_VID = 21

    def _resolve(self, conflicts):
        resolver = ConflictsAutoResolver()
        return resolver.resolve(conflicts)

    def test_returns_empty_result_for_empty_input(self) -> None:
        result = self._resolve([])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [])

    def test_resolves_feature_deletion_both_sides_as_remote(self) -> None:
        conflict = LocalFeatureDeletionConflict(
            local_change=FeatureDeletion(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
            ),
            remote_actions=[
                FeatureDeleteAction(
                    fid=self.NGW_FID,
                    vid=self.FEATURE_VID,
                )
            ],
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_resolves_attachment_deletion_both_sides_as_remote(
        self,
    ) -> None:
        conflict = LocalAttachmentDeletionConflict(
            local_change=AttachmentDeletion(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
            ),
            remote_action=AttachmentDeleteAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_resolves_local_feature_delete_vs_remote_attachment_delete(
        self,
    ) -> None:
        conflict = LocalFeatureDeletionConflict(
            local_change=FeatureDeletion(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
            ),
            remote_actions=[
                AttachmentDeleteAction(
                    fid=self.NGW_FID,
                    aid=self.NGW_AID,
                    vid=self.EXTENSION_VID,
                ),
                AttachmentDeleteAction(
                    fid=self.NGW_FID,
                    aid=self.NGW_AID + 1,
                    vid=self.EXTENSION_VID,
                ),
            ],
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Local,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_resolves_remote_feature_delete_vs_local_attachment_delete(
        self,
    ) -> None:
        conflict = RemoteFeatureDeletionConflict(
            local_changes=[
                AttachmentDeletion(
                    fid=self.LOCAL_FID,
                    aid=self.LOCAL_AID,
                    ngw_fid=self.NGW_FID,
                    ngw_aid=self.NGW_AID,
                ),
                AttachmentDeletion(
                    fid=self.LOCAL_FID,
                    aid=self.LOCAL_AID + 1,
                    ngw_fid=self.NGW_FID,
                    ngw_aid=self.NGW_AID + 1,
                ),
            ],
            remote_action=FeatureDeleteAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_keeps_local_feature_delete_conflict_with_mixed_remote_actions(
        self,
    ) -> None:
        conflict = LocalFeatureDeletionConflict(
            local_change=FeatureDeletion(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
            ),
            remote_actions=[
                AttachmentDeleteAction(
                    fid=self.NGW_FID,
                    aid=self.NGW_AID,
                    vid=self.EXTENSION_VID,
                ),
                AttachmentUpdateAction(
                    fid=self.NGW_FID,
                    aid=self.NGW_AID + 1,
                    vid=self.EXTENSION_VID,
                    name="remote-name",
                ),
            ],
        )

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])

    def test_keeps_remote_feature_delete_conflict_with_mixed_local_changes(
        self,
    ) -> None:
        conflict = RemoteFeatureDeletionConflict(
            local_changes=[
                AttachmentDeletion(
                    fid=self.LOCAL_FID,
                    aid=self.LOCAL_AID,
                    ngw_fid=self.NGW_FID,
                    ngw_aid=self.NGW_AID,
                ),
                AttachmentUpdate(
                    fid=self.LOCAL_FID,
                    aid=self.LOCAL_AID + 1,
                    ngw_fid=self.NGW_FID,
                    ngw_aid=self.NGW_AID + 1,
                    name="local-name",
                ),
            ],
            remote_action=FeatureDeleteAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])

    def test_resolves_same_description_as_remote(self) -> None:
        conflict = DescriptionConflict(
            local_change=DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description="same-description",
            ),
            remote_action=DescriptionPutAction(
                fid=self.NGW_FID,
                vid=self.EXTENSION_VID,
                value="same-description",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertIsInstance(
            result.resolved_conflicts[0],
            DescriptionConflictResolution,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_resolves_same_fields_and_geometry_as_remote(self) -> None:
        geometry = QgsGeometry.fromWkt("Point (10 20)")
        conflict = FeatureDataConflict(
            local_change=FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "same")],
                geometry=geometry,
            ),
            remote_action=FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "same")],
                geom=geometry,
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertIsInstance(
            result.resolved_conflicts[0],
            FeatureConflictResolution,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_resolves_same_fields_in_different_order_as_remote(
        self,
    ) -> None:
        geometry = QgsGeometry.fromWkt("Point (10 20)")
        conflict = FeatureDataConflict(
            local_change=FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "a"), (11, "b"), (12, "c")],
                geometry=geometry,
            ),
            remote_action=FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(12, "c"), (10, "a"), (11, "b")],
                geom=geometry,
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertIsInstance(
            result.resolved_conflicts[0],
            FeatureConflictResolution,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_keeps_feature_data_conflict_when_geometry_differs(
        self,
    ) -> None:
        conflict = FeatureDataConflict(
            local_change=FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "same")],
                geometry=QgsGeometry.fromWkt("Point (10 20)"),
            ),
            remote_action=FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "same")],
                geom=QgsGeometry.fromWkt("Point (20 10)"),
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])

    def test_resolves_same_feature_data_when_both_parts_are_unset(
        self,
    ) -> None:
        conflict = FeatureDataConflict(
            local_change=FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=Unset,
                geometry=Unset,
            ),
            remote_action=FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=Unset,
                geom=Unset,
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_keeps_conflict_when_description_values_differ(self) -> None:
        conflict = DescriptionConflict(
            local_change=DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description="local-description",
            ),
            remote_action=DescriptionPutAction(
                fid=self.NGW_FID,
                vid=self.EXTENSION_VID,
                value="remote-description",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])

    def test_resolves_same_attachment_name_as_remote(self) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="same-name",
            ),
            remote_action=AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="same-name",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertIsInstance(
            result.resolved_conflicts[0],
            AttachmentConflictResolution,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_resolves_same_attachment_description_as_remote(self) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                description="same-description",
            ),
            remote_action=AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                description="same-description",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertIsInstance(
            result.resolved_conflicts[0],
            AttachmentConflictResolution,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_resolves_same_attachment_keyname_and_mime_type_as_remote(
        self,
    ) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                keyname="same-keyname",
                mime_type="image/png",
            ),
            remote_action=AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                keyname="same-keyname",
                mime_type="image/png",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertIsInstance(
            result.resolved_conflicts[0],
            AttachmentConflictResolution,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_keeps_attachment_data_conflict_when_file_changed(self) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="same-name",
                fileobj=None,
            ),
            remote_action=AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="same-name",
                fileobj=123,
            ),
        )

        self.assertTrue(conflict.local_change.is_file_new)
        self.assertTrue(conflict.remote_action.is_file_new)

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])

    def test_keeps_conflict_when_attachment_name_same_but_description_differs(
        self,
    ) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="same-name",
                description="local-description",
            ),
            remote_action=AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="same-name",
                description="remote-description",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])

    def test_keeps_conflict_when_attachment_description_same_but_name_differs(
        self,
    ) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="local-name",
                description="same-description",
            ),
            remote_action=AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="remote-name",
                description="same-description",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])

    def test_resolves_same_restored_feature_data_as_remote(self) -> None:
        geometry = QgsGeometry.fromWkt("Point (10 20)")
        conflict = FeatureDataConflict(
            local_change=FeatureRestoration(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "same")],
                geometry=geometry,
            ),
            remote_action=FeatureRestoreAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "same")],
                geom=geometry,
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertIsInstance(
            result.resolved_conflicts[0],
            FeatureConflictResolution,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_keeps_restored_feature_data_conflict_when_fields_differ(
        self,
    ) -> None:
        geometry = QgsGeometry.fromWkt("Point (10 20)")
        conflict = FeatureDataConflict(
            local_change=FeatureRestoration(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "local")],
                geometry=geometry,
            ),
            remote_action=FeatureRestoreAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "remote")],
                geom=geometry,
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])

    def test_resolves_same_restored_attachment_data_as_remote(self) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentRestoration(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="same-name",
            ),
            remote_action=AttachmentRestoreAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="same-name",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(len(result.resolved_conflicts), 1)
        self.assertEqual(
            result.resolved_conflicts[0].resolution_type,
            ResolutionType.Remote,
        )
        self.assertIsInstance(
            result.resolved_conflicts[0],
            AttachmentConflictResolution,
        )
        self.assertEqual(result.remaining_conflicts, [])

    def test_keeps_restored_attachment_conflict_when_name_differs(
        self,
    ) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentRestoration(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="local-name",
            ),
            remote_action=AttachmentRestoreAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="remote-name",
            ),
        )

        result = self._resolve([conflict])

        self.assertEqual(result.resolved_conflicts, [])
        self.assertEqual(result.remaining_conflicts, [conflict])
