from typing import Optional

from qgis.core import QgsMapLayer
from qgis.gui import QgsAbstractMapToolHandler, QgsMapTool
from qgis.PyQt.QtWidgets import QAction

from nextgis_connect.detached_editing.utils import is_ngw_container


class IdentificationToolHandler(QgsAbstractMapToolHandler):
    """Handle identification map tool.

    Provide compatibility checks that restrict the associated map
    tool to layers that represent NGW containers. The handler is a
    lightweight adapter around QGIS' `QgsAbstractMapToolHandler` and
    is used by the detached editing identification UI.

    :ivar map_tool: The map tool instance used by the handler.
    :vartype map_tool: QgsMapTool
    :ivar action: The associated action object.
    :vartype action: QAction
    """

    def __init__(self, map_tool: QgsMapTool, action: QAction) -> None:  # pyright: ignore[reportInvalidTypeForm]
        """Initialize the handler.

        :param map_tool: Map tool used for identification.
        :type map_tool: QgsMapTool
        :param action: Associated QAction.
        :type action: QAction
        """
        super().__init__(map_tool, action)

    def isCompatibleWithLayer(
        self,
        layer: Optional[QgsMapLayer],
        context: QgsAbstractMapToolHandler.Context,
    ) -> bool:
        """Return whether the handler is compatible with the provided layer.

        The handler considers a layer compatible when it is not ``None``
        and represents a detached container according to
        :func:`nextgis_connect.detached_editing.utils.is_ngw_container`.

        :param layer: Layer to check compatibility for, may be ``None``.
        :type layer: Optional[QgsMapLayer]
        :param context: Context of the map tool handler.
        :type context: QgsAbstractMapToolHandler.Context
        :return: True if the layer is an NGW container, False otherwise.
        :rtype: bool
        """
        return layer is not None and is_ngw_container(layer)
