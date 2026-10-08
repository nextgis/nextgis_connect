# NextGIS Connect
# Copyright (C) 2026 NextGIS
# SPDX-License-Identifier: GPL-2.0-or-later

import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from nextgis_connect.features.synchronization.infrastructure.storage import (
    DetachedStorageService,
)
from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.utils import (
    AttachmentMetadata,
    DetachedContainerMetaData,
)
from nextgis_connect.platform.logging import logger


class AttachmentFiles:
    """Publish attachment copies without consuming the edit buffer's originals."""

    def __init__(
        self,
        metadata: DetachedContainerMetaData,
        storage: Optional[DetachedStorageService] = None,
    ) -> None:
        self.metadata = metadata
        self._storage = storage
        self.prepared: List[Tuple[AttachmentMetadata, Path]] = []

    @property
    def storage(self) -> DetachedStorageService:
        if self._storage is None:
            self._storage = DetachedStorageServiceFactory.create()
        return self._storage

    def prepare(self, attachment: AttachmentMetadata) -> None:
        """Copy a staged attachment to its permanent ID before metadata commit."""
        path = self.storage.attachment_path(
            self.metadata.instance_id,
            self.metadata.resource_id,
            attachment.aid,
            file_name=attachment.name,
            mime_type=attachment.mime_type,
        )
        if attachment.file_path is None:
            raise ValueError("New attachment has no staged file")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite an existing cache file when an ID is reused.
        with path.open("xb") as destination:
            self.prepared.append((attachment, path))
            with attachment.file_path.open("rb") as source:
                shutil.copyfileobj(source, destination)

    def rollback(self) -> None:
        """Remove only copies created by this batch, retaining staged originals."""
        for _, path in self.prepared:
            try:
                path.unlink()
            except OSError:
                logger.exception("Can't remove an uncommitted attachment copy")
        self.prepared.clear()

    def register(self) -> None:
        """Index committed copies without failing an already committed batch."""
        # This is a derived cache index, not the container's synchronization
        # journal. Canonical files remain discoverable if registration fails.
        for attachment, _ in self.prepared:
            try:
                self.storage.register_attachment_file(
                    self.metadata.instance_id,
                    self.metadata.resource_id,
                    attachment.aid,
                    file_name=attachment.name,
                    mime_type=attachment.mime_type,
                    feature_local_id=int(attachment.fid),
                    is_dirty=True,
                )
            except Exception:
                logger.exception("Can't index a committed attachment file")
        self.prepared.clear()
