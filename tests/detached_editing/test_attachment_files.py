# NextGIS Connect
# Copyright (C) 2026 NextGIS
# SPDX-License-Identifier: GPL-2.0-or-later

from unittest.mock import MagicMock, patch

import pytest

from nextgis_connect.legacy.detached_editing.attachment_files import (
    AttachmentFiles,
)
from nextgis_connect.legacy.detached_editing.utils import AttachmentMetadata


@pytest.fixture
def attachment_files(tmp_path):
    storage = MagicMock()
    storage.attachment_path.side_effect = lambda _, __, aid, **kwargs: (
        tmp_path / f"saved-{aid}.txt"
    )
    return AttachmentFiles(
        MagicMock(instance_id="instance", resource_id=1), storage
    )


def test_copy_failure_cleans_partial_destination_and_retains_source(
    tmp_path, attachment_files
):
    source = tmp_path / "source.txt"
    source.write_text("original content")
    attachment = AttachmentMetadata(fid=1, aid=1, file_path=source)

    def fail_copy(source_file, destination):
        destination.write(b"partial copy")
        raise OSError("Injected disk error")

    with patch(
        "nextgis_connect.legacy.detached_editing.attachment_files.shutil.copyfileobj",
        side_effect=fail_copy,
    ), pytest.raises(OSError, match="Injected disk error"):
        attachment_files.prepare(attachment)
    attachment_files.rollback()
    assert source.read_text() == "original content"
    assert not (tmp_path / "saved-1.txt").exists()
    attachment_files.storage.register_attachment_file.assert_not_called()


def test_collision_does_not_overwrite_or_remove_existing_file(
    tmp_path, attachment_files
):
    source = tmp_path / "source.txt"
    source.write_text("new content")
    destination = tmp_path / "saved-1.txt"
    destination.write_text("existing content")
    with pytest.raises(FileExistsError):
        attachment_files.prepare(
            AttachmentMetadata(fid=1, aid=1, file_path=source)
        )
    attachment_files.rollback()
    assert destination.read_text() == "existing content"
    assert source.read_text() == "new content"


def test_cache_index_failure_keeps_committed_file(tmp_path, attachment_files):
    source = tmp_path / "source.txt"
    source.write_text("content")
    attachment_files.prepare(
        AttachmentMetadata(fid=1, aid=1, file_path=source)
    )
    attachment_files.storage.register_attachment_file.side_effect = OSError(
        "Injected index error"
    )
    attachment_files.register()
    assert (tmp_path / "saved-1.txt").read_text() == "content"
    assert source.read_text() == "content"
    assert attachment_files.prepared == []
