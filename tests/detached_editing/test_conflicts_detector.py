from qgis.core import QgsGeometry

from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentDataConflict,
    DescriptionConflict,
    FeatureDataConflict,
    LocalAttachmentDeletionConflict,
    LocalFeatureDeletionConflict,
    RemoteAttachmentDeletionConflict,
    RemoteFeatureDeletionConflict,
)
from nextgis_connect.detached_editing.conflicts.detector import (
    ConflictsDetector,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentUpdate,
    DescriptionPut,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentCreateAction,
    AttachmentDeleteAction,
    AttachmentRestoreAction,
    AttachmentUpdateAction,
    DescriptionPutAction,
    FeatureDeleteAction,
    FeatureRestoreAction,
    FeatureUpdateAction,
)
from tests.ng_connect_testcase import NgConnectTestCase


class TestConflictsDetection(NgConnectTestCase):
    LOCAL_FID = 1
    LOCAL_AID = 1
    NGW_FID = 101
    NGW_AID = 201
    FEATURE_VID = 11
    EXTENSION_VID = 21

    def _detect(self, local_changes, remote_actions):
        detector = ConflictsDetector()
        return detector.detect(local_changes, remote_actions)

    def test_empty_local_changes_returns_no_conflicts(self) -> None:
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "remote")],
            )
        ]

        conflicts = self._detect([], remote_actions)

        self.assertEqual(conflicts, [])

    def test_empty_remote_actions_returns_no_conflicts(self) -> None:
        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "local")],
            )
        ]

        conflicts = self._detect(local_changes, [])

        self.assertEqual(conflicts, [])

    def test_empty_inputs_returns_no_conflicts(self) -> None:
        conflicts = self._detect([], [])

        self.assertEqual(conflicts, [])

    def test_feature_delete_local_and_remote_returns_single_local_conflict(
        self,
    ) -> None:
        local_changes = [
            FeatureDeletion(fid=self.LOCAL_FID, ngw_fid=self.NGW_FID),
        ]
        remote_actions = [
            FeatureDeleteAction(fid=self.NGW_FID, vid=self.FEATURE_VID),
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], LocalFeatureDeletionConflict)

    def test_attachment_delete_local_and_matching_remote_action_returns_single_local_conflict(
        self,
    ) -> None:
        scenarios = (
            {
                "name": "remote delete",
                "remote_actions": [
                    AttachmentDeleteAction(
                        fid=self.NGW_FID,
                        aid=self.NGW_AID,
                        vid=self.EXTENSION_VID,
                    )
                ],
            },
            {
                "name": "remote update",
                "remote_actions": [
                    AttachmentUpdateAction(
                        fid=self.NGW_FID,
                        aid=self.NGW_AID,
                        vid=self.EXTENSION_VID,
                        name="remote-name",
                    )
                ],
            },
            {
                "name": "remote restore",
                "remote_actions": [
                    AttachmentRestoreAction(
                        fid=self.NGW_FID,
                        aid=self.NGW_AID,
                        vid=self.EXTENSION_VID,
                        name="remote-name",
                    )
                ],
            },
        )

        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                local_changes = [
                    AttachmentDeletion(
                        fid=self.LOCAL_FID,
                        aid=self.LOCAL_AID,
                        ngw_fid=self.NGW_FID,
                        ngw_aid=self.NGW_AID,
                    )
                ]

                conflicts = self._detect(
                    local_changes,
                    scenario["remote_actions"],
                )

                self.assertEqual(len(conflicts), 1)
                self.assertIsInstance(
                    conflicts[0], LocalAttachmentDeletionConflict
                )

    def test_feature_delete_local_and_many_remote_actions_returns_conflict(
        self,
    ) -> None:
        local_changes = [
            FeatureDeletion(fid=self.LOCAL_FID, ngw_fid=self.NGW_FID),
        ]
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "remote-field")],
            ),
            DescriptionPutAction(
                fid=self.NGW_FID,
                vid=self.EXTENSION_VID,
                value="remote-description",
            ),
            AttachmentCreateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="remote-attachment",
            ),
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], LocalFeatureDeletionConflict)
        assert isinstance(conflicts[0], LocalFeatureDeletionConflict)
        self.assertEqual(conflicts[0].remote_actions, remote_actions)

    def test_feature_delete_remote_and_many_local_changes_returns_conflict(
        self,
    ) -> None:
        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "local")],
            ),
            DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description="local-description",
            ),
            AttachmentCreation(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                name="local-attachment",
            ),
        ]
        remote_actions = [
            FeatureDeleteAction(fid=self.NGW_FID, vid=self.FEATURE_VID),
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], RemoteFeatureDeletionConflict)
        assert isinstance(conflicts[0], RemoteFeatureDeletionConflict)
        self.assertEqual(conflicts[0].local_changes, local_changes)

    def test_detect_preserves_local_feature_order(self) -> None:
        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID + 1,
                ngw_fid=self.NGW_FID + 1,
                fields=[(11, "local-2")],
            ),
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "local-1")],
            ),
        ]
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "remote-1")],
            ),
            FeatureUpdateAction(
                fid=self.NGW_FID + 1,
                vid=self.FEATURE_VID + 1,
                fields=[(11, "remote-2")],
            ),
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 2)
        self.assertIsInstance(conflicts[0], FeatureDataConflict)
        self.assertIsInstance(conflicts[1], FeatureDataConflict)
        assert isinstance(conflicts[0], FeatureDataConflict)
        assert isinstance(conflicts[1], FeatureDataConflict)
        self.assertEqual(conflicts[0].ngw_fid, self.NGW_FID + 1)
        self.assertEqual(conflicts[1].ngw_fid, self.NGW_FID)

    def test_feature_conflicts_only_for_same_ngw_feature(self) -> None:
        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "local")],
            )
        ]
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID + 1,
                vid=self.FEATURE_VID,
                fields=[(10, "remote")],
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(conflicts, [])

    def test_description_conflicts_only_for_same_ngw_feature(self) -> None:
        local_changes = [
            DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description="local-description",
            )
        ]
        remote_actions = [
            DescriptionPutAction(
                fid=self.NGW_FID + 1,
                vid=self.EXTENSION_VID,
                value="remote-description",
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(conflicts, [])

    def test_description_overlap_returns_description_conflict(self) -> None:
        local_changes = [
            DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description="local-description",
            )
        ]
        remote_actions = [
            DescriptionPutAction(
                fid=self.NGW_FID,
                vid=self.EXTENSION_VID,
                value="remote-description",
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], DescriptionConflict)

    def test_attachment_conflicts_only_for_same_attachment(self) -> None:
        local_changes = [
            AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="local",
            )
        ]
        remote_actions = [
            AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID + 1,
                vid=self.EXTENSION_VID,
                name="remote",
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(conflicts, [])

    def test_feature_update_overlap_returns_feature_data_conflict(
        self,
    ) -> None:
        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "local")],
            )
        ]
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "remote")],
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], FeatureDataConflict)
        assert isinstance(conflicts[0], FeatureDataConflict)
        self.assertEqual(conflicts[0].conflicting_fields, {10})

    def test_feature_update_different_fields_returns_no_conflicts(
        self,
    ) -> None:
        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "local")],
            )
        ]
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(11, "remote")],
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(conflicts, [])

    def test_feature_update_geometry_and_field_returns_no_conflicts(
        self,
    ) -> None:
        geometry = QgsGeometry.fromWkt("Point (10 20)")
        other_geometry = QgsGeometry.fromWkt("Point (30 40)")

        scenarios = (
            {
                "name": "local geometry remote fields",
                "local_changes": [
                    FeatureUpdate(
                        fid=self.LOCAL_FID,
                        ngw_fid=self.NGW_FID,
                        geometry=geometry,
                    )
                ],
                "remote_actions": [
                    FeatureUpdateAction(
                        fid=self.NGW_FID,
                        vid=self.FEATURE_VID,
                        fields=[(10, "remote")],
                    )
                ],
            },
            {
                "name": "local fields remote geometry",
                "local_changes": [
                    FeatureUpdate(
                        fid=self.LOCAL_FID,
                        ngw_fid=self.NGW_FID,
                        fields=[(10, "local")],
                    )
                ],
                "remote_actions": [
                    FeatureUpdateAction(
                        fid=self.NGW_FID,
                        vid=self.FEATURE_VID,
                        geom=other_geometry,
                    )
                ],
            },
        )

        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                conflicts = self._detect(
                    scenario["local_changes"],
                    scenario["remote_actions"],
                )

                self.assertEqual(conflicts, [])

    def test_feature_data_and_extensions_returns_no_conflicts(
        self,
    ) -> None:
        scenarios = (
            {
                "name": "feature data and remote description",
                "local_changes": [
                    FeatureUpdate(
                        fid=self.LOCAL_FID,
                        ngw_fid=self.NGW_FID,
                        fields=[(10, "local")],
                    )
                ],
                "remote_actions": [
                    DescriptionPutAction(
                        fid=self.NGW_FID,
                        vid=self.EXTENSION_VID,
                        value="remote-description",
                    )
                ],
            },
            {
                "name": "feature data and remote attachment",
                "local_changes": [
                    FeatureUpdate(
                        fid=self.LOCAL_FID,
                        ngw_fid=self.NGW_FID,
                        fields=[(10, "local")],
                    )
                ],
                "remote_actions": [
                    AttachmentUpdateAction(
                        fid=self.NGW_FID,
                        aid=self.NGW_AID,
                        vid=self.EXTENSION_VID,
                        name="remote-name",
                    )
                ],
            },
            {
                "name": "local description and remote feature data",
                "local_changes": [
                    DescriptionPut(
                        fid=self.LOCAL_FID,
                        ngw_fid=self.NGW_FID,
                        description="local-description",
                    )
                ],
                "remote_actions": [
                    FeatureUpdateAction(
                        fid=self.NGW_FID,
                        vid=self.FEATURE_VID,
                        fields=[(10, "remote")],
                    )
                ],
            },
            {
                "name": "local attachment and remote feature data",
                "local_changes": [
                    AttachmentUpdate(
                        fid=self.LOCAL_FID,
                        aid=self.LOCAL_AID,
                        ngw_fid=self.NGW_FID,
                        ngw_aid=self.NGW_AID,
                        name="local-name",
                    )
                ],
                "remote_actions": [
                    FeatureUpdateAction(
                        fid=self.NGW_FID,
                        vid=self.FEATURE_VID,
                        fields=[(10, "remote")],
                    )
                ],
            },
        )

        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                conflicts = self._detect(
                    scenario["local_changes"],
                    scenario["remote_actions"],
                )

                self.assertEqual(conflicts, [])

    def test_multiple_local_changes_return_all_conflicts(self) -> None:
        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "local-field")],
            ),
            DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description="local-description",
            ),
            AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="local-attachment",
            ),
        ]
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "remote-field")],
            ),
            DescriptionPutAction(
                fid=self.NGW_FID,
                vid=self.EXTENSION_VID,
                value="remote-description",
            ),
            AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="remote-attachment",
            ),
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 3)
        self.assertIsInstance(conflicts[0], FeatureDataConflict)
        self.assertIsInstance(conflicts[1], DescriptionConflict)
        self.assertIsInstance(conflicts[2], AttachmentDataConflict)

    def test_attachment_name_update_overlap_returns_attachment_data_conflict(
        self,
    ) -> None:
        local_changes = [
            AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="local",
            )
        ]
        remote_actions = [
            AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="remote",
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], AttachmentDataConflict)
        assert isinstance(conflicts[0], AttachmentDataConflict)
        self.assertTrue(conflicts[0].has_name_conflict)
        self.assertFalse(conflicts[0].has_description_conflict)
        self.assertFalse(conflicts[0].has_file_conflict)

    def test_attachment_description_update_overlap_returns_attachment_data_conflict(
        self,
    ) -> None:
        local_changes = [
            AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                description="local",
            )
        ]
        remote_actions = [
            AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                description="remote",
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], AttachmentDataConflict)
        assert isinstance(conflicts[0], AttachmentDataConflict)
        self.assertFalse(conflicts[0].has_name_conflict)
        self.assertTrue(conflicts[0].has_description_conflict)
        self.assertFalse(conflicts[0].has_file_conflict)

    def test_attachment_file_update_overlap_returns_attachment_data_conflict(
        self,
    ) -> None:
        local_changes = [
            AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                fileobj=None,
            )
        ]
        remote_actions = [
            AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                fileobj=123,
            )
        ]
        self.assertTrue(local_changes[0].is_file_new)
        self.assertTrue(remote_actions[0].is_file_new)

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], AttachmentDataConflict)
        assert isinstance(conflicts[0], AttachmentDataConflict)
        self.assertFalse(conflicts[0].has_name_conflict)
        self.assertFalse(conflicts[0].has_description_conflict)
        self.assertTrue(conflicts[0].has_file_conflict)

    def test_attachment_update_different_fields_returns_no_conflicts(
        self,
    ) -> None:
        scenarios = (
            {
                "name": "local name remote description",
                "local_changes": [
                    AttachmentUpdate(
                        fid=self.LOCAL_FID,
                        aid=self.LOCAL_AID,
                        ngw_fid=self.NGW_FID,
                        ngw_aid=self.NGW_AID,
                        name="local-name",
                    )
                ],
                "remote_actions": [
                    AttachmentUpdateAction(
                        fid=self.NGW_FID,
                        aid=self.NGW_AID,
                        vid=self.EXTENSION_VID,
                        description="remote-description",
                    )
                ],
            },
            {
                "name": "local description remote name",
                "local_changes": [
                    AttachmentUpdate(
                        fid=self.LOCAL_FID,
                        aid=self.LOCAL_AID,
                        ngw_fid=self.NGW_FID,
                        ngw_aid=self.NGW_AID,
                        description="local-description",
                    )
                ],
                "remote_actions": [
                    AttachmentUpdateAction(
                        fid=self.NGW_FID,
                        aid=self.NGW_AID,
                        vid=self.EXTENSION_VID,
                        name="remote-name",
                    )
                ],
            },
        )

        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                conflicts = self._detect(
                    scenario["local_changes"],
                    scenario["remote_actions"],
                )

                self.assertEqual(conflicts, [])

    def test_attachment_remote_delete_returns_deletion_conflict(
        self,
    ) -> None:
        local_changes = [
            AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="local-name",
            )
        ]

        remote_actions = [
            AttachmentDeleteAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
            ),
        ]

        conflicts = self._detect(
            local_changes,
            remote_actions,
        )

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], RemoteAttachmentDeletionConflict)
        assert isinstance(conflicts[0], RemoteAttachmentDeletionConflict)
        self.assertEqual(
            conflicts[0].local_change,
            local_changes[0],
        )
        self.assertEqual(conflicts[0].remote_action, remote_actions[0])

    def test_feature_update_same_field_value_still_conflicts(self) -> None:
        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                fields=[(10, "same")],
            )
        ]
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                fields=[(10, "same")],
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], FeatureDataConflict)

    def test_feature_update_same_geometry_still_conflicts(self) -> None:
        geometry = QgsGeometry.fromWkt("Point (10 20)")

        local_changes = [
            FeatureUpdate(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                geometry=geometry,
            )
        ]
        remote_actions = [
            FeatureUpdateAction(
                fid=self.NGW_FID,
                vid=self.FEATURE_VID,
                geom=geometry,
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], FeatureDataConflict)

    def test_description_same_value_still_conflicts(self) -> None:
        local_changes = [
            DescriptionPut(
                fid=self.LOCAL_FID,
                ngw_fid=self.NGW_FID,
                description="same-description",
            )
        ]
        remote_actions = [
            DescriptionPutAction(
                fid=self.NGW_FID,
                vid=self.EXTENSION_VID,
                value="same-description",
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], DescriptionConflict)

    def test_attachment_update_same_name_still_conflicts(self) -> None:
        local_changes = [
            AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                name="same-name",
            )
        ]
        remote_actions = [
            AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                name="same-name",
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], AttachmentDataConflict)

    def test_attachment_update_same_description_still_conflicts(self) -> None:
        local_changes = [
            AttachmentUpdate(
                fid=self.LOCAL_FID,
                aid=self.LOCAL_AID,
                ngw_fid=self.NGW_FID,
                ngw_aid=self.NGW_AID,
                description="same-description",
            )
        ]
        remote_actions = [
            AttachmentUpdateAction(
                fid=self.NGW_FID,
                aid=self.NGW_AID,
                vid=self.EXTENSION_VID,
                description="same-description",
            )
        ]

        conflicts = self._detect(local_changes, remote_actions)

        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], AttachmentDataConflict)

    def test_feature_update_and_restore_overlap_returns_feature_data_conflict(
        self,
    ) -> None:
        scenarios = (
            {
                "name": "update and update",
                "local_changes": [
                    FeatureUpdate(
                        fid=self.LOCAL_FID,
                        ngw_fid=self.NGW_FID,
                        fields=[(10, "local")],
                    )
                ],
                "remote_actions": [
                    FeatureUpdateAction(
                        fid=self.NGW_FID,
                        vid=self.FEATURE_VID,
                        fields=[(10, "remote")],
                    )
                ],
            },
            {
                "name": "restore and restore",
                "local_changes": [
                    FeatureRestoration(
                        fid=self.LOCAL_FID,
                        ngw_fid=self.NGW_FID,
                        fields=[(10, "local")],
                    )
                ],
                "remote_actions": [
                    FeatureRestoreAction(
                        fid=self.NGW_FID,
                        vid=self.FEATURE_VID,
                        fields=[(10, "remote")],
                    )
                ],
            },
        )

        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                conflicts = self._detect(
                    scenario["local_changes"],
                    scenario["remote_actions"],
                )

                self.assertEqual(len(conflicts), 1)
                self.assertIsInstance(conflicts[0], FeatureDataConflict)
                assert isinstance(conflicts[0], FeatureDataConflict)
                self.assertEqual(conflicts[0].conflicting_fields, {10})

    def test_attachment_update_and_restore_overlap_returns_attachment_data_conflict(
        self,
    ) -> None:
        scenarios = (
            {
                "name": "update and update",
                "local_changes": [
                    AttachmentUpdate(
                        fid=self.LOCAL_FID,
                        aid=self.LOCAL_AID,
                        ngw_fid=self.NGW_FID,
                        ngw_aid=self.NGW_AID,
                        name="local-name",
                    )
                ],
                "remote_actions": [
                    AttachmentUpdateAction(
                        fid=self.NGW_FID,
                        aid=self.NGW_AID,
                        vid=self.EXTENSION_VID,
                        name="remote-name",
                    )
                ],
            },
            {
                "name": "restore and restore",
                "local_changes": [
                    AttachmentRestoration(
                        fid=self.LOCAL_FID,
                        aid=self.LOCAL_AID,
                        ngw_fid=self.NGW_FID,
                        ngw_aid=self.NGW_AID,
                        name="local-name",
                    )
                ],
                "remote_actions": [
                    AttachmentRestoreAction(
                        fid=self.NGW_FID,
                        aid=self.NGW_AID,
                        vid=self.EXTENSION_VID,
                        name="remote-name",
                    )
                ],
            },
        )

        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                conflicts = self._detect(
                    scenario["local_changes"],
                    scenario["remote_actions"],
                )

                self.assertEqual(len(conflicts), 1)
                self.assertIsInstance(conflicts[0], AttachmentDataConflict)
                assert isinstance(conflicts[0], AttachmentDataConflict)
                self.assertTrue(conflicts[0].has_name_conflict)
