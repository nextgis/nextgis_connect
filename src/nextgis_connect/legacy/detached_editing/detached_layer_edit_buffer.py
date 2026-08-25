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

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, DefaultDict, Dict, List, Optional, Set

from qgis.core import Qgis
from qgis.PyQt.QtCore import (
    QFile,
    QIODevice,
    QMimeDatabase,
    QObject,
    pyqtSignal,
    pyqtSlot,
)

from nextgis_connect.legacy.detached_editing.storage_service_factory import (
    DetachedStorageServiceFactory,
)
from nextgis_connect.legacy.detached_editing.utils import AttachmentMetadata
from nextgis_connect.legacy.settings.ng_connect_settings import (
    NgConnectSettings,
)
from nextgis_connect.platform.qgis.compat import QgsFeatureId, QgsFeatureList
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.shared.types import AttachmentId

if TYPE_CHECKING:
    from nextgis_connect.legacy.detached_editing.detached_layer import (
        DetachedLayer,
    )


class DetachedLayerEditBuffer(QObject):
    """
    Edit buffer for the detached layer.

    This class tracks changes made to feature descriptions and attachments
    in a detached layer. It emits signals when descriptions or attachments are
    added, updated, or removed. It also provides properties to check for and
    retrieve these changes.
    """

    description_updated = pyqtSignal(QgsFeatureId, str)
    attachment_added = pyqtSignal(QgsFeatureId, AttachmentId)
    attachment_updated = pyqtSignal(QgsFeatureId, AttachmentId)
    attachment_removed = pyqtSignal(QgsFeatureId, AttachmentId)

    def __init__(self, layer: "DetachedLayer") -> None:
        super().__init__(layer)
        self._detached_layer = layer
        self.description_updated.connect(
            self._detached_layer.description_updated
        )
        self.attachment_added.connect(self._detached_layer.attachment_added)
        self.attachment_updated.connect(
            self._detached_layer.attachment_updated
        )
        self.attachment_removed.connect(
            self._detached_layer.attachment_removed
        )
        self._detached_layer.qgs_layer.beforeCommitChanges.connect(
            self.__log_added_features
        )
        self._detached_layer.qgs_layer.committedFeaturesAdded.connect(
            self.__map_added_features
        )
        self._detached_layer.qgs_layer.editBuffer().featureAdded.connect(
            self.__on_feature_added
        )
        self._detached_layer.qgs_layer.editBuffer().featureDeleted.connect(
            self.__on_feature_deleted
        )

        self._updated_descriptions: Dict[QgsFeatureId, Optional[str]] = {}
        self._added_attachments: DefaultDict[
            QgsFeatureId, Dict[AttachmentId, AttachmentMetadata]
        ] = defaultdict(dict)
        self._updated_attachments: DefaultDict[
            QgsFeatureId, Dict[AttachmentId, AttachmentMetadata]
        ] = defaultdict(dict)
        self._removed_attachments: DefaultDict[
            QgsFeatureId, Set[AttachmentId]
        ] = defaultdict(set)

        self._next_attachment_id: AttachmentId = -1
        self._staged_attachments: Dict[AttachmentId, AttachmentMetadata] = {}

        self.__added_features: List[QgsFeatureId] = []
        self.__deleted_features: Set[QgsFeatureId] = set()

    @property
    def layer(self) -> "DetachedLayer":
        """Get the associated detached layer.

        :return: DetachedLayer instance.
        """
        return self._detached_layer

    @property
    def has_updated_descriptions(self) -> bool:
        """Check if there are any updated descriptions.

        :return: True if there are updated descriptions, False otherwise.
        """
        return any(
            fid not in self.__deleted_features
            for fid in self._updated_descriptions.keys()
        )

    @property
    def updated_descriptions(self) -> Dict[QgsFeatureId, Optional[str]]:
        """Get updated feature descriptions.

        :return: Dictionary mapping feature IDs to their updated descriptions.
        """
        return {
            fid: description
            for fid, description in self._updated_descriptions.items()
            if fid not in self.__deleted_features
        }

    @property
    def has_added_attachments(self) -> bool:
        """Check if there are any added attachments.

        :return: True if there are added attachments, False otherwise.
        """
        return any(
            len(attachments) > 0
            for fid, attachments in self._added_attachments.items()
            if fid not in self.__deleted_features
        )

    @property
    def added_attachments(
        self,
    ) -> Dict[QgsFeatureId, Dict[AttachmentId, AttachmentMetadata]]:
        """Get added attachments.

        :return: Dictionary mapping feature IDs to their added attachments.
        """
        return {
            fid: attachments
            for fid, attachments in self._added_attachments.items()
            if fid not in self.__deleted_features
        }

    @property
    def has_updated_attachments(self) -> bool:
        """Check if there are any updated attachments.

        :return: True if there are updated attachments, False otherwise.
        """
        return any(
            len(attachments) > 0
            for attachments in self._updated_attachments.values()
        )

    @property
    def updated_attachments(
        self,
    ) -> Dict[QgsFeatureId, Dict[AttachmentId, AttachmentMetadata]]:
        """Get updated attachments.

        :return: Dictionary mapping feature IDs to their updated attachments.
        """
        return self._updated_attachments

    @property
    def has_removed_attachments(self) -> bool:
        """Check if there are any removed attachments.

        :return: True if there are removed attachments, False otherwise.
        """
        return any(
            len(attachments) > 0
            for attachments in self._removed_attachments.values()
        )

    @property
    def removed_attachments(self) -> Dict[QgsFeatureId, Set[AttachmentId]]:
        """Get removed attachments.

        :return: Dictionary mapping feature IDs to their removed attachment IDs.
        """
        return self._removed_attachments

    @pyqtSlot()
    def clear(self) -> None:
        """Clear all changes."""
        for attachment in self._staged_attachments.values():
            self._remove_staged_attachment_file(attachment)

        self._updated_descriptions.clear()
        self._added_attachments.clear()
        self._updated_attachments.clear()
        self._removed_attachments.clear()
        self._staged_attachments.clear()
        self.__added_features.clear()
        self.__deleted_features.clear()

    def _stage_new_attachment_file(
        self, feature_id: QgsFeatureId, file_path: Path
    ) -> AttachmentMetadata:
        """Create attachment metadata for a new staged cache file.

        :param file_path: Source file path selected by the user.
        :return: AttachmentMetadata instance for the new attachment.
        """
        mime_database = QMimeDatabase()
        mime_type_name = ""
        file = QFile(str(file_path))
        if file.open(QIODevice.OpenModeFlag.ReadOnly):
            try:
                mime_type = mime_database.mimeTypeForFileNameAndData(
                    str(file_path), file
                )
                if mime_type.isValid():
                    mime_type_name = mime_type.name()
            finally:
                file.close()

        if not mime_type_name:
            for mime_type in mime_database.mimeTypesForFileName(
                file_path.name
            ):
                if mime_type.isValid() and mime_type.name():
                    mime_type_name = mime_type.name()
                    break

        if not mime_type_name:
            mime_type_name = "application/octet-stream"

        storage_service = DetachedStorageServiceFactory.create()
        attachment_id = self._next_attachment_id
        temp_file_path = storage_service.stage_attachment_file(
            self._detached_layer.container.metadata.instance_id,
            self._detached_layer.container.metadata.resource_id,
            attachment_id,
            file_path,
            file_name=file_path.name,
            mime_type=mime_type_name,
            feature_local_id=int(feature_id),
        )

        attachment = AttachmentMetadata(
            fid=feature_id,
            aid=attachment_id,
            name=file_path.name,
            file_path=temp_file_path,
            mime_type=mime_type_name,
            size=temp_file_path.stat().st_size,
        )
        self._staged_attachments[attachment_id] = attachment
        self._next_attachment_id -= 1
        return attachment

    def _remove_staged_attachment_file(
        self,
        attachment: AttachmentMetadata,
    ) -> None:
        if attachment.file_path is None:
            return

        storage_service = DetachedStorageServiceFactory.create()
        storage_service.discard_staged_attachment_file(
            self._detached_layer.container.metadata.instance_id,
            self._detached_layer.container.metadata.resource_id,
            attachment.aid,
            feature_local_id=int(attachment.fid),
        )

    @pyqtSlot()
    def __log_added_features(self) -> None:
        self.__added_features = list(
            self._detached_layer.qgs_layer.editBuffer().addedFeatures().keys()
        )
        self.__added_features.sort(reverse=True)

    @pyqtSlot(str, "QgsFeatureList")
    def __map_added_features(self, _: str, features: QgsFeatureList) -> None:
        for temporary_fid, permanent_feature in zip(
            self.__added_features, features
        ):
            if temporary_fid in self._updated_descriptions:
                self._updated_descriptions[permanent_feature.id()] = (
                    self._updated_descriptions.pop(temporary_fid)
                )
            if temporary_fid in self._added_attachments:
                self._added_attachments[permanent_feature.id()] = {
                    aid: replace(attachment, fid=permanent_feature.id())
                    for aid, attachment in self._added_attachments[
                        temporary_fid
                    ].items()
                }
                self._added_attachments.pop(temporary_fid)

    @pyqtSlot("QgsFeatureId")
    def __on_feature_added(self, feature_id: QgsFeatureId) -> None:
        if feature_id in self.__deleted_features:
            self.__deleted_features.remove(feature_id)

    @pyqtSlot("QgsFeatureId")
    def __on_feature_deleted(self, feature_id: QgsFeatureId) -> None:
        self.__deleted_features.add(feature_id)

        settings = NgConnectSettings()
        if (
            not settings.notify_when_deleting_features_with_attachments
            or self._detached_layer.feature_attachments_count(feature_id) == 0
        ):
            return

        message = self.tr(
            "A feature with attachments has been deleted. "
            "If you save the changes, the attachments will be lost permanently."
        )
        notifier = NgConnectInterface.instance().notifier
        notifier.display_message(
            message, level=Qgis.MessageLevel.Warning, duration=10
        )
