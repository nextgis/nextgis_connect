from pathlib import Path

from qgis.core import QgsFeature, QgsGeometry

from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    AttachmentConflictResolution,
    ConflictResolution,
    DescriptionConflictResolution,
    FeatureConflictResolution,
    ResolutionType,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    AttachmentDataConflictResolvingItem,
    DescriptionConflictResolvingItem,
    FeatureDataConflictResolvingItem,
    FeatureDeleteConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentDataConflict,
    DescriptionConflict,
    FeatureDataConflict,
    LocalFeatureDeletionConflict,
)
from nextgis_connect.detached_editing.conflicts.item_to_resolution_converter import (
    ItemToResolutionConverter,
)
from nextgis_connect.detached_editing.sync.common.changes import (
    AttachmentUpdate,
    DescriptionPut,
    FeatureDeletion,
    FeatureUpdate,
)
from nextgis_connect.detached_editing.sync.common.serialization import (
    serialize_geometry,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    AttachmentUpdateAction,
    DescriptionPutAction,
    FeatureUpdateAction,
)
from nextgis_connect.detached_editing.utils import (
    AttachmentMetadata,
    DetachedContainerContext,
    DetachedContainerMetaData,
)
from nextgis_connect.resources.ngw_field import NgwField
from nextgis_connect.resources.ngw_fields import NgwFields
from tests.ng_connect_testcase import NgConnectTestCase


class TestItemToResolutionConverter(NgConnectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._metadata = DetachedContainerMetaData(
            container_version="1",
            connection_id="connection-id",
            instance_id="instance-id",
            resource_id=1,
            table_name="layer",
            layer_name="layer",
            description=None,
            geometry_name="geom",
            transaction_id=None,
            epoch=1,
            version=1,
            sync_date=None,
            is_auto_sync_enabled=False,
            fields=NgwFields(
                [
                    NgwField(
                        ngw_id=1,
                        datatype="STRING",
                        keyname="first",
                        display_name="First",
                        is_label=False,
                        attribute=0,
                    ),
                    NgwField(
                        ngw_id=2,
                        datatype="STRING",
                        keyname="second",
                        display_name="Second",
                        is_label=False,
                        attribute=1,
                    ),
                ]
            ),
            fid_field="fid",
            geom_field="geom",
            features_count=0,
            has_changes=False,
            srs_id=4326,
        )
        self._context = DetachedContainerContext(
            path=Path("/tmp/test.gpkg"),
            metadata=self._metadata,
        )
        self._converter = ItemToResolutionConverter(self._context)

    def test_convert_feature_item_preserves_full_resolved_state(
        self,
    ) -> None:
        local_geometry = QgsGeometry.fromWkt("POINT(1 1)")
        remote_geometry = QgsGeometry.fromWkt("POINT(2 2)")
        result_geometry = QgsGeometry.fromWkt("POINT(3 3)")

        conflict = FeatureDataConflict(
            local_change=FeatureUpdate(
                fid=1,
                ngw_fid=101,
                fields=[(1, "local-first")],
                geometry=local_geometry,
            ),
            remote_action=FeatureUpdateAction(
                fid=101,
                vid=11,
                fields=[(1, "remote-first")],
                geom=remote_geometry,
            ),
        )
        item = FeatureDataConflictResolvingItem(
            conflict=conflict,
            local_feature=self._feature(
                ["local-first", "base-second"],
                local_geometry,
            ),
            remote_feature=self._feature(
                ["remote-first", "base-second"],
                remote_geometry,
            ),
            result_feature=self._feature(
                ["custom-first", "custom-second"],
                result_geometry,
            ),
        )
        item.changed_fields = {1}
        item.is_geometry_changed = True

        result = self._converter.convert([item])

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], FeatureConflictResolution)
        resolution = result[0]
        assert isinstance(resolution, FeatureConflictResolution)
        self.assertEqual(resolution.resolution_type, ResolutionType.Custom)
        self.assertEqual(
            resolution.feature_data.fields,
            [(1, "custom-first"), (2, "custom-second")],
        )
        self.assertEqual(
            resolution.feature_data.geom,
            serialize_geometry(result_geometry, True),
        )

    def test_convert_description_item_keeps_selected_side(self) -> None:
        conflict = DescriptionConflict(
            local_change=DescriptionPut(
                fid=1,
                ngw_fid=101,
                description="local-description",
            ),
            remote_action=DescriptionPutAction(
                fid=101,
                vid=21,
                value="remote-description",
            ),
        )
        item = DescriptionConflictResolvingItem(
            conflict=conflict,
            local_description="local-description",
            remote_description="remote-description",
        )
        item.resolve_as_local()

        result = self._converter.convert([item])

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], DescriptionConflictResolution)
        resolution = result[0]
        assert isinstance(resolution, DescriptionConflictResolution)
        self.assertEqual(resolution.resolution_type, ResolutionType.Local)
        self.assertEqual(resolution.value, "local-description")

    def test_convert_attachment_item_preserves_custom_values(self) -> None:
        conflict = AttachmentDataConflict(
            local_change=AttachmentUpdate(
                fid=1,
                aid=10,
                ngw_fid=101,
                ngw_aid=201,
                name="local-name",
                description="local-description",
                fileobj=None,
            ),
            remote_action=AttachmentUpdateAction(
                fid=101,
                aid=201,
                vid=31,
                name="remote-name",
                description="remote-description",
                fileobj=301,
            ),
        )
        item = AttachmentDataConflictResolvingItem(
            conflict=conflict,
            local_attachment=AttachmentMetadata(
                fid=1,
                aid=10,
                ngw_fid=101,
                ngw_aid=201,
                version=1,
                keyname="local-key",
                name="local-name",
                description="local-description",
                fileobj=101,
                mime_type="text/plain",
            ),
            remote_attachment=AttachmentMetadata(
                fid=1,
                aid=10,
                ngw_fid=101,
                ngw_aid=201,
                version=1,
                keyname="remote-key",
                name="remote-name",
                description="remote-description",
                fileobj=301,
                mime_type="application/json",
            ),
            result_attachment=AttachmentMetadata(
                fid=1,
                aid=10,
                ngw_fid=101,
                ngw_aid=201,
                version=1,
                keyname="custom-key",
                name="custom-name",
                description="custom-description",
                fileobj=401,
                mime_type="image/png",
            ),
        )

        result = self._converter.convert([item])

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AttachmentConflictResolution)
        resolution = result[0]
        assert isinstance(resolution, AttachmentConflictResolution)
        self.assertEqual(resolution.resolution_type, ResolutionType.Custom)
        self.assertEqual(resolution.attachment_data.keyname, "custom-key")
        self.assertEqual(resolution.attachment_data.name, "custom-name")
        self.assertEqual(
            resolution.attachment_data.description,
            "custom-description",
        )
        self.assertEqual(resolution.attachment_data.fileobj, 401)
        self.assertEqual(resolution.attachment_data.mime_type, "image/png")

    def test_convert_delete_item_returns_base_resolution(self) -> None:
        conflict = LocalFeatureDeletionConflict(
            local_change=FeatureDeletion(
                fid=1,
                ngw_fid=101,
            ),
            remote_actions=[
                FeatureUpdateAction(
                    fid=101,
                    vid=11,
                    fields=[(1, "remote-first")],
                )
            ],
        )
        item = FeatureDeleteConflictResolvingItem(
            conflict=conflict,
            local_feature=None,
            remote_feature=self._feature(
                ["remote-first", "remote-second"],
                QgsGeometry.fromWkt("POINT(1 1)"),
            ),
        )
        item.resolve_as_remote()

        result = self._converter.convert([item])

        self.assertEqual(len(result), 1)
        self.assertEqual(type(result[0]), ConflictResolution)
        self.assertEqual(result[0].resolution_type, ResolutionType.Remote)

    def _feature(
        self,
        values,
        geometry: QgsGeometry,
    ) -> QgsFeature:
        feature = QgsFeature(self._metadata.fields.qgs_fields)
        feature.setAttributes(list(values))
        feature.setGeometry(geometry)
        return feature
