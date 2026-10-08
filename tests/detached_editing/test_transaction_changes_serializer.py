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

import json

import pytest

from nextgis_connect.legacy.detached_editing.sync.common.changes import (
    AttachmentCreation,
    AttachmentDeletion,
    AttachmentRestoration,
    AttachmentUpdate,
    DescriptionPut,
    FeatureCreation,
    FeatureDeletion,
    FeatureRestoration,
    FeatureUpdate,
)
from nextgis_connect.legacy.detached_editing.sync.versioned.transaction_changes_serializer import (
    TransactionChangesSerializer,
)
from nextgis_connect.platform.qgis.errors import SynchronizationError


def test_stores_only_confirmation_identity_and_cache_state():
    changes = [
        FeatureCreation(fid=-1, fields=[(1, "large attribute value")]),
        FeatureUpdate(fid=2, ngw_fid=102),
        FeatureDeletion(fid=3, ngw_fid=103),
        FeatureRestoration(fid=4, ngw_fid=104),
        DescriptionPut(fid=2, ngw_fid=102, description="large description"),
        AttachmentCreation(fid=2, aid=-5, ngw_fid=102, name="photo.jpg"),
        AttachmentUpdate(fid=2, aid=6, ngw_fid=102, ngw_aid=206, fileobj=None),
        AttachmentUpdate(fid=2, aid=7, ngw_fid=102, ngw_aid=207, fileobj=507),
        AttachmentDeletion(
            fid=2, aid=8, ngw_fid=102, ngw_aid=208, fileobj=508
        ),
        AttachmentRestoration(
            fid=2, aid=9, ngw_fid=102, ngw_aid=209, fileobj=None
        ),
    ]
    serializer = TransactionChangesSerializer()
    confirmation = serializer.from_changes(changes)
    payload = serializer.to_json(confirmation)

    assert json.loads(payload) == [
        {"action": "feature.create", "id": -1},
        {"action": "feature.update", "id": 2},
        {"action": "feature.delete", "id": 3},
        {"action": "feature.restore", "id": 4},
        {"action": "description.put", "id": 2},
        {"action": "attachment.create", "id": -5},
        {"action": "attachment.update", "id": 6, "file_changed": True},
        {"action": "attachment.update", "id": 7, "file_changed": False},
        {"action": "attachment.delete", "id": 8, "fileobj": 508},
        {"action": "attachment.restore", "id": 9, "file_changed": True},
    ]
    assert serializer.from_json(payload) == confirmation


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "{",
        "null",
        "{}",
        "[]",
        "[null]",
        '[{"action":"continue","id":1}]',
        '[{"action":"unknown","id":1}]',
        '[{"action":"feature.create","id":true}]',
        '[{"action":"attachment.update","id":1}]',
        '[{"action":"attachment.update","id":1,"file_changed":1}]',
        '[{"action":"attachment.delete","id":1,"fileobj":"5"}]',
    ],
)
def test_rejects_unusable_recovery_records(payload):
    with pytest.raises(
        SynchronizationError, match="Invalid transaction recovery data"
    ):
        TransactionChangesSerializer().from_json(payload)
