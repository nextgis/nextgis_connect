from enum import IntEnum, auto
from typing import TYPE_CHECKING

from nextgis_connect.compat import UndoCommand

if TYPE_CHECKING:
    from nextgis_connect.detached_editing.detached_layer import DetachedLayer


class UndoCommandType(IntEnum):
    """Enumerate NG Connect-specific command types for the undo stack."""

    NG_CONNECT_COMMANDS = 1000
    DESCRIPTION_CHANGE = auto()
    ATTACHMENT_ADD = auto()
    ATTACHMENT_REMOVE = auto()
    ATTACHMENT_UPDATE = auto()


class DetachedLayerBaseCommand(UndoCommand):
    """Provide base UndoCommand for DetachedLayer operations.

    Subclasses implement specific editing actions and integrate with the QGIS
    vector layer undo/redo stack. The command stores a reference to the target
    ``DetachedLayer`` for use within ``redo()`` and ``undo()`` implementations.

    :ivar _detached_layer: Target detached layer instance.
    :vartype _detached_layer: DetachedLayer
    """

    _detached_layer: "DetachedLayer"

    def __init__(
        self,
        detached_layer: "DetachedLayer",
    ) -> None:
        """Construct command for a specific detached layer.

        :param detached_layer: Target detached layer instance to operate on.
        :type detached_layer: DetachedLayer
        """
        super().__init__()
        self._detached_layer = detached_layer
