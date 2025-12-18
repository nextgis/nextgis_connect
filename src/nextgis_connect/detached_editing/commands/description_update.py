from typing import TYPE_CHECKING, Optional

from qgis.PyQt.QtWidgets import QUndoCommand

from nextgis_connect.compat import QgsFeatureId
from nextgis_connect.detached_editing.container.editing.commands.base import (
    DetachedLayerBaseCommand,
    UndoCommandType,
)
from nextgis_connect.logging import logger

if TYPE_CHECKING:
    from nextgis_connect.detached_editing.detached_layer import DetachedLayer


class DescriptionUpdateCommand(DetachedLayerBaseCommand):
    """Command to update feature description in the edit buffer.

    This command stores the previous and new description values and
    applies changes to the detached layer edit buffer. It supports
    undo/redo operations and is intended to be pushed to a vector layer
    QUndoStack. Also it can be merged with subsequent description
    update commands for the same feature.

    :ivar _feature_id: ID of the feature whose description is changed.
    :vartype _feature_id: QgsFeatureId
    :ivar _old_description: Description before the change or None.
    :vartype _old_description: Optional[str]
    :ivar _new_description: Description after the change or None.
    :vartype _new_description: Optional[str]
    :ivar _is_first_change: True if this is the first description change
        recorded for the feature in the current edit buffer session.
    :vartype _is_first_change: bool
    """

    _feature_id: QgsFeatureId
    _old_description: Optional[str]
    _new_description: Optional[str]
    _is_first_change: bool

    def __init__(
        self,
        detached_layer: "DetachedLayer",
        feature_id: QgsFeatureId,
        old_description: Optional[str],
        new_description: Optional[str],
    ) -> None:
        """Initialize the command and record description states.

        :param detached_layer: Detached layer the command will operate on.
        :type detached_layer: DetachedLayer
        :param feature_id: ID of the feature to update.
        :type feature_id: QgsFeatureId
        :param old_description: Previous description value or None.
        :type old_description: Optional[str]
        :param new_description: New description value or None.
        :type new_description: Optional[str]
        """

        super().__init__(detached_layer)
        self._feature_id = feature_id
        self._old_description = old_description
        self._new_description = new_description
        # Determine whether this feature already has an updated
        # description recorded in the edit buffer.
        self._is_first_change = (
            self._detached_layer.edit_buffer._updated_descriptions.get(
                self._feature_id
            )
            is None
        )

    def undo(self) -> None:
        """Revert the description change.

        If this command represented the first recorded change for the
        feature, remove the entry from `_updated_descriptions`; otherwise
        restore the previous description value. Emit
        `description_updated` to notify listeners.
        """

        edit_buffer = self._detached_layer.edit_buffer
        if self._is_first_change:
            edit_buffer._updated_descriptions.pop(self._feature_id)
            logger.debug(
                "Reverted description change for feature %s: removed from edit buffer",
                self._feature_id,
            )
        else:
            edit_buffer._updated_descriptions[self._feature_id] = (
                self._old_description
            )
            logger.debug(
                "Reverted description change for feature %s: restored old description",
                self._feature_id,
            )

        edit_buffer.description_updated.emit(
            self._feature_id, self._old_description
        )

    def redo(self) -> None:
        """Apply the description change.

        Store the new description value in the edit buffer and emit
        `description_updated` so that UI and other components reflect the
        update.
        """

        edit_buffer = self._detached_layer.edit_buffer
        edit_buffer._updated_descriptions[self._feature_id] = (
            self._new_description
        )

        edit_buffer.description_updated.emit(
            self._feature_id, self._new_description
        )

        logger.debug(
            "Applied description change for feature %s", self._feature_id
        )

    def id(self) -> int:
        """Returns the ID of this command.

        A command ID is used in command compression.

        :return: Command ID.
        """
        return int(UndoCommandType.DESCRIPTION_CHANGE)

    def mergeWith(self, other: Optional[QUndoCommand]) -> bool:
        """Attempts to merge this command with another command.

        :param other: The other command to merge with.
        :type other: Optional[QUndoCommand]
        :return: True if the commands were merged, False otherwise.
        :rtype: bool
        """
        assert other is not None
        if self.id() != other.id():
            return False

        assert isinstance(other, DescriptionUpdateCommand)
        if self._feature_id != other._feature_id:
            return False

        # Accept the newer description so consecutive edits compress
        # into a single undoable action.
        self._new_description = other._new_description

        # If the net effect is no change, mark this command obsolete and
        # remove any recorded update if this was the first change.
        if self._old_description == self._new_description:
            self.setObsolete(True)

            if self._is_first_change:
                edit_buffer = self._detached_layer.edit_buffer
                edit_buffer._updated_descriptions.pop(self._feature_id)

        return True
