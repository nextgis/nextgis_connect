from enum import IntEnum
from typing import Any, List, Optional

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    QVariant,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QIcon

from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    BaseConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    AttachmentConflict,
    DescriptionConflict,
    FeatureChangeConflict,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerContext,
)
from nextgis_connect.types import UnsetType
from nextgis_connect.ui.icon import material_icon


class ConflictsResolvingModel(QAbstractListModel):
    """Provide a Qt model for conflict resolving items.

    Manage a list of `ConflictResolvingItem` instances and expose model
    roles for view presentation and interaction.

    :ivar _context: DetachedContainerContext used to access container
        metadata.
    :ivar _conflict_resoving_items: list of `ConflictResolvingItem`
        objects managed by the model.
    """

    class Roles(IntEnum):
        RESOLVING_ITEM = Qt.ItemDataRole.UserRole + 1

    _context: DetachedContainerContext
    _conflict_resoving_items: List[BaseConflictResolvingItem]

    __not_resolved_icon: QIcon
    __resolved_icon: QIcon

    def __init__(
        self,
        context: DetachedContainerContext,
        items: List[BaseConflictResolvingItem],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._context = context
        self._conflict_resoving_items = items

        self.__not_resolved_icon = material_icon(
            "question_mark", color="#fbe94e", size=16
        )
        self.__resolved_icon = material_icon("check", color="#7bab4d", size=16)

    @property
    def resolved_count(self) -> int:
        """Return number of resolved conflicts.

        :return: Number of items currently marked as resolved.
        """

        return sum(
            1 for item in self._conflict_resoving_items if item.is_resolved
        )

    @property
    def is_all_resolved(self) -> bool:
        """Return True when all model items are resolved.

        :return: True if every `ConflictResolvingItem` is resolved.
        """

        return all(item.is_resolved for item in self._conflict_resoving_items)

    @property
    def items(self) -> List[BaseConflictResolvingItem]:
        """Return list of conflict resolving items managed by the model."""
        return self._conflict_resoving_items

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        """Return the number of conflicts in the model.

        :param parent: Parent index (not used).
        :return: Number of conflicts.
        """
        return len(self._conflict_resoving_items)

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        """Return data for the given index and role.

        :param index: QModelIndex for the requested data.
        :param role: Role for which data is requested.
        :return: QVariant containing the requested data.
        """
        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return QVariant()

        item = self._conflict_resoving_items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(item.conflict, AttachmentConflict):
                return QgsApplication.translate(
                    "ConflictsResolvingModel", "Attachment #"
                ) + str(item.conflict.ngw_aid)

            if isinstance(item.conflict, DescriptionConflict):
                return QgsApplication.translate(
                    "ConflictsResolvingModel", "Feature #{} description"
                ).format(item.conflict.ngw_fid)

            assert isinstance(item.conflict, FeatureChangeConflict)

            label_field = self._context.metadata.fields.label_field
            if label_field is None:
                return QgsApplication.translate(
                    "ConflictsResolvingModel", "Feature #"
                ) + str(item.conflict.fid)

            for feature in (
                item.local_item,
                item.remote_item,
                item.result_item,
            ):
                if feature is None or isinstance(feature, UnsetType):
                    continue

                return feature.attribute(label_field.attribute)

        if role == Qt.ItemDataRole.ToolTipRole:
            if isinstance(item.conflict, AttachmentConflict):
                return QgsApplication.translate(
                    "ConflictsResolvingModel", "Attachment #"
                ) + str(item.conflict.ngw_aid)

            if isinstance(item.conflict, DescriptionConflict):
                return QgsApplication.translate(
                    "ConflictsResolvingModel", "Feature #{} description"
                ).format(item.conflict.ngw_fid)

            assert isinstance(item.conflict, FeatureChangeConflict)
            return QgsApplication.translate(
                "ConflictsResolvingModel", "Feature #"
            ) + str(item.conflict.fid)

        if role == Qt.ItemDataRole.DecorationRole:
            return (
                self.__resolved_icon
                if item.is_resolved
                else self.__not_resolved_icon
            )

        if role == self.Roles.RESOLVING_ITEM:
            return item

        return QVariant()

    def setData(
        self,
        index: QModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        """Set data for the given index and role (not implemented).

        Currently this model does not support item editing via `setData`.

        :param index: QModelIndex to set.
        :param value: New value to assign.
        :param role: Role for which data should be set.
        :return: True if data was set, False otherwise.
        """

        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return False

        return False

    @pyqtSlot(QModelIndex)
    def resolve_as_local(self, index: QModelIndex) -> None:
        """Resolve item at `index` as local.

        :param index: QModelIndex of the item to resolve as local.
        """

        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return

        self._conflict_resoving_items[index.row()].resolve_as_local()
        self.dataChanged.emit(index, index)

    @pyqtSlot(QModelIndex)
    def resolve_as_remote(self, index: QModelIndex) -> None:
        """Resolve item at `index` as remote.

        :param index: QModelIndex of the item to resolve as remote.
        """

        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return

        self._conflict_resoving_items[index.row()].resolve_as_remote()
        self.dataChanged.emit(index, index)

    @pyqtSlot()
    def resolve_all_as_local(self) -> None:
        """Resolve all items in the model as local.

        This marks every `ConflictResolvingItem` as local and notifies
        views about the change.
        """

        for resolving_item in self._conflict_resoving_items:
            resolving_item.resolve_as_local()

        self.dataChanged.emit(
            self.index(0, 0), self.index(self.rowCount() - 1, 0)
        )

    @pyqtSlot()
    def resolve_all_as_remote(self) -> None:
        """Resolve all items in the model as remote.

        This marks every `ConflictResolvingItem` as remote and notifies
        views about the change.
        """

        for resolving_item in self._conflict_resoving_items:
            resolving_item.resolve_as_remote()

        self.dataChanged.emit(
            self.index(0, 0), self.index(self.rowCount() - 1, 0)
        )

    @pyqtSlot(QModelIndex)
    def update_state(self, index: QModelIndex) -> None:
        """Reevaluate resolving state for an item and emit change notification.

        :param index: QModelIndex of the item to update.
        """

        if not index.isValid() or index.row() >= len(
            self._conflict_resoving_items
        ):
            return

        self.dataChanged.emit(index, index)
