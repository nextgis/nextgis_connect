import json

from qgis.core import QgsGeometry

from nextgis_connect.detached_editing.sync.common.serialization import (
    geometry_to_wkb64,
)
from nextgis_connect.detached_editing.sync.versioned.actions import (
    ActionType,
    AttachmentCreateAction,
    AttachmentDeleteAction,
    AttachmentRestoreAction,
    AttachmentUpdateAction,
    ContinueAction,
    DescriptionPutAction,
    FeatureCreateAction,
    FeatureDeleteAction,
    FeatureRestoreAction,
    FeatureUpdateAction,
)
from nextgis_connect.detached_editing.sync.versioned.actions_serializer import (
    ActionSerializer,
)
from nextgis_connect.exceptions import SerializationError
from nextgis_connect.types import Unset
from tests.detached_editing.utils import mock_container
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestData,
)


class TestActionsDeserialization(NgConnectTestCase):
    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_from_json_deserializes_actions_from_json_string(
        self, container_mock, _qgs_layer
    ) -> None:
        payload = json.dumps(
            [
                {
                    "action": str(ActionType.CONTINUE),
                    "url": "https://example.test/next",
                }
            ]
        )

        serializer = ActionSerializer(container_mock.metadata)
        result = serializer.from_json(payload)

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], ContinueAction)
        assert isinstance(result[0], ContinueAction)
        self.assertEqual(result[0].url, "https://example.test/next")

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_from_json_deserializes_preparsed_actions(
        self, container_mock, _qgs_layer
    ) -> None:
        serializer = ActionSerializer(container_mock.metadata)
        payload = [
            {
                "action": str(ActionType.CONTINUE),
                "url": "https://example.test/preparsed",
            }
        ]

        result = serializer.from_json(payload)

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], ContinueAction)
        assert isinstance(result[0], ContinueAction)
        self.assertEqual(result[0].url, "https://example.test/preparsed")

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_from_json_raises_serialization_error_for_unknown_action(
        self, container_mock, _qgs_layer
    ) -> None:
        payload = json.dumps([{"action": "unknown.action"}])

        serializer = ActionSerializer(container_mock.metadata)

        with self.assertRaises(SerializationError):
            serializer.from_json(payload)

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_from_json_raises_serialization_error_for_invalid_json(
        self, container_mock, _qgs_layer
    ) -> None:
        serializer = ActionSerializer(container_mock.metadata)

        with self.assertRaises(SerializationError):
            serializer.from_json("not a json")

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_from_json_raises_serialization_error_for_invalid_geometry(
        self, container_mock, _qgs_layer
    ) -> None:
        serializer = ActionSerializer(container_mock.metadata)
        payload = json.dumps(
            [
                {
                    "action": str(ActionType.FEATURE_CREATE),
                    "fid": 101,
                    "vid": 1,
                    "geom": "invalid-wkb64",
                }
            ]
        )

        with self.assertRaises(SerializationError):
            serializer.from_json(payload)

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_from_json_deserializes_each_action_type(
        self, container_mock, _qgs_layer
    ) -> None:
        serializer = ActionSerializer(container_mock.metadata)
        expected_geometry = QgsGeometry.fromWkt("Point (1 2)")

        action_cases = [
            {
                "payload": {
                    "action": str(ActionType.CONTINUE),
                    "url": "https://example.test/next-1",
                },
                "expected_class": ContinueAction,
                "assertions": lambda action: self.assertEqual(
                    action.url, "https://example.test/next-1"
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.FEATURE_CREATE),
                    "fid": 201,
                    "vid": 2,
                    "fields": [[1, "new"]],
                    "geom": geometry_to_wkb64(
                        QgsGeometry.fromWkt("Point (1 2)")
                    ),
                },
                "expected_class": FeatureCreateAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 201),
                    self.assertEqual(action.vid, 2),
                    self.assertEqual(action.fields, [[1, "new"]]),
                    self.assertTrue(action.geom.equals(expected_geometry)),
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.FEATURE_UPDATE),
                    "fid": 202,
                    "vid": 3,
                },
                "expected_class": FeatureUpdateAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 202),
                    self.assertEqual(action.vid, 3),
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.FEATURE_DELETE),
                    "fid": 203,
                    "vid": 4,
                },
                "expected_class": FeatureDeleteAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 203),
                    self.assertEqual(action.vid, 4),
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.FEATURE_RESTORE),
                    "fid": 204,
                    "vid": 5,
                },
                "expected_class": FeatureRestoreAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 204),
                    self.assertEqual(action.vid, 5),
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.DESCRIPTION_PUT),
                    "fid": 205,
                    "vid": 6,
                    "value": "description",
                },
                "expected_class": DescriptionPutAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 205),
                    self.assertEqual(action.vid, 6),
                    self.assertEqual(action.value, "description"),
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.ATTACHMENT_CREATE),
                    "fid": 206,
                    "aid": 11,
                    "vid": 7,
                    "keyname": "photo",
                    "name": "a.jpg",
                    "description": "desc",
                    "fileobj": 9001,
                    "mime_type": "image/jpeg",
                },
                "expected_class": AttachmentCreateAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 206),
                    self.assertEqual(action.aid, 11),
                    self.assertEqual(action.vid, 7),
                    self.assertEqual(action.keyname, "photo"),
                    self.assertEqual(action.name, "a.jpg"),
                    self.assertEqual(action.description, "desc"),
                    self.assertEqual(action.fileobj, 9001),
                    self.assertEqual(action.mime_type, "image/jpeg"),
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.ATTACHMENT_UPDATE),
                    "fid": 207,
                    "aid": 12,
                    "vid": 8,
                    "keyname": "doc",
                    "name": "b.pdf",
                    "description": "updated",
                    "fileobj": 9002,
                    "mime_type": "application/pdf",
                },
                "expected_class": AttachmentUpdateAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 207),
                    self.assertEqual(action.aid, 12),
                    self.assertEqual(action.vid, 8),
                    self.assertEqual(action.keyname, "doc"),
                    self.assertEqual(action.name, "b.pdf"),
                    self.assertEqual(action.description, "updated"),
                    self.assertEqual(action.fileobj, 9002),
                    self.assertEqual(action.mime_type, "application/pdf"),
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.ATTACHMENT_DELETE),
                    "fid": 208,
                    "aid": 13,
                    "vid": 9,
                },
                "expected_class": AttachmentDeleteAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 208),
                    self.assertEqual(action.aid, 13),
                    self.assertEqual(action.vid, 9),
                ),
            },
            {
                "payload": {
                    "action": str(ActionType.ATTACHMENT_RESTORE),
                    "fid": 209,
                    "aid": 14,
                    "vid": 10,
                    "keyname": "restore",
                    "name": "c.txt",
                    "description": "restored",
                    "fileobj": 9003,
                    "mime_type": "text/plain",
                },
                "expected_class": AttachmentRestoreAction,
                "assertions": lambda action: (
                    self.assertEqual(action.fid, 209),
                    self.assertEqual(action.aid, 14),
                    self.assertEqual(action.vid, 10),
                    self.assertEqual(action.keyname, "restore"),
                    self.assertEqual(action.name, "c.txt"),
                    self.assertEqual(action.description, "restored"),
                    self.assertEqual(action.fileobj, 9003),
                    self.assertEqual(action.mime_type, "text/plain"),
                ),
            },
        ]

        for case in action_cases:
            action_name = case["payload"]["action"]
            payload = json.dumps([case["payload"]])

            with self.subTest(action=action_name):
                result = serializer.from_json(payload)
                self.assertEqual(len(result), 1)
                self.assertIsInstance(result[0], case["expected_class"])
                assert isinstance(result[0], case["expected_class"])
                case["assertions"](result[0])

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_from_json_sets_unset_for_missing_feature_create_fields(
        self, container_mock, _qgs_layer
    ) -> None:
        serializer = ActionSerializer(container_mock.metadata)
        payload = json.dumps(
            [
                {
                    "action": str(ActionType.FEATURE_CREATE),
                    "fid": 301,
                    "vid": 11,
                }
            ]
        )

        result = serializer.from_json(payload)

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], FeatureCreateAction)
        assert isinstance(result[0], FeatureCreateAction)
        self.assertIs(result[0].fields, Unset)
        self.assertIs(result[0].geom, Unset)

    @mock_container(TestData.Points, is_versioning_enabled=True)
    def test_from_json_sets_unset_for_missing_attachment_change_fields(
        self, container_mock, _qgs_layer
    ) -> None:
        serializer = ActionSerializer(container_mock.metadata)
        payload = json.dumps(
            [
                {
                    "action": str(ActionType.ATTACHMENT_CREATE),
                    "fid": 302,
                    "aid": 33,
                    "vid": 12,
                }
            ]
        )

        result = serializer.from_json(payload)

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AttachmentCreateAction)
        assert isinstance(result[0], AttachmentCreateAction)
        self.assertIs(result[0].keyname, Unset)
        self.assertIs(result[0].name, Unset)
        self.assertIs(result[0].description, Unset)
        self.assertIs(result[0].fileobj, Unset)
        self.assertIs(result[0].mime_type, Unset)
