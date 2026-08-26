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

from typing import TYPE_CHECKING, List, Optional

import qgis.utils
from qgis.core import (
    Qgis,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextScope,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsGeometry,
    QgsIdentifyContext,
    QgsMapLayer,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import (
    QgisInterface,
    QgsMapCanvas,
    QgsMapLayerAction,
    QgsMapToolIdentify,
)
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    Qt,
    QTimer,
    QUrl,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QAction

from nextgis_connect.legacy.detached_editing.identification.identification_tool import (
    IdentificationTool,
)
from nextgis_connect.legacy.detached_editing.identification.identification_tool_handler import (
    IdentificationToolHandler,
)
from nextgis_connect.legacy.detached_editing.identification.settings import (
    IdentificationSettings,
)
from nextgis_connect.legacy.detached_editing.identification.ui.identification_results_widget import (
    IdentificationResultsWidget,
)
from nextgis_connect.legacy.detached_editing.utils import is_ngw_container
from nextgis_connect.legacy.ngw_connection import NgwConnectionsManager
from nextgis_connect.platform.logging import logger
from nextgis_connect.platform.qgis.compat import (
    QT_VERSION_MAJOR,
    GeometryType,
    LayerType,
)
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.ui_kit.icons import plugin_icon, qgis_icon

if TYPE_CHECKING:
    from qgis.gui import QgisInterface


class IdentificationManager(QObject):
    def __init__(
        self, canvas: QgsMapCanvas, parent: Optional[QObject] = None
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._action = None
        self._identify_tool = None
        self._tool_handler = None
        self._results_dialog = None
        self._toolbar_timer = QTimer(self)
        self._toolbar_timer.setSingleShot(True)
        self._toolbar_timer.timeout.connect(self.__add_icon_to_toolbar)
        self._results_dialog_timer = QTimer(self)
        self._results_dialog_timer.setSingleShot(True)
        self._results_dialog_timer.timeout.connect(self._show_results_dialog)

    @property
    def _iface(self) -> "QgisInterface":
        iface = qgis.utils.iface
        assert isinstance(iface, QgisInterface)
        return iface

    def load(self) -> None:
        """Load identification manager and set the identify tool."""
        self._action = QAction(self.tr("Identify"), self)
        self._action.setIcon(plugin_icon("actions/identify.svg"))
        # Add after toolbar initialization
        self._toolbar_timer.start(2)

        self._identify_tool = IdentificationTool(self._canvas)
        self._identify_tool.geometry_changed.connect(
            self._identify_from_geometry
        )
        self._identify_tool.clear.connect(self.clear_results)

        identify_menu = self._identify_tool.identifyMenu()

        open_in_ngw_action = QgsMapLayerAction(
            self.tr("Open in NextGIS Web"),
            identify_menu,
            LayerType.Vector,
            Qgis.MapLayerActionTarget.SingleFeature,
        )
        open_in_ngw_action.setIcon(plugin_icon("branding/ngw_logo.svg"))
        open_in_ngw_action.triggeredForFeatureV2.connect(
            self.open_feature_in_nextgis_web
        )
        identify_menu.addCustomAction(open_in_ngw_action)

        if QT_VERSION_MAJOR == 5:
            open_in_attributes_table_targets = (
                Qgis.MapLayerActionTargets()  # pyright: ignore[reportAttributeAccessIssue]
                | Qgis.MapLayerActionTarget.SingleFeature
                | Qgis.MapLayerActionTarget.MultipleFeatures
            )
        else:
            open_in_attributes_table_targets = (
                Qgis.MapLayerActionTarget.SingleFeature
                | Qgis.MapLayerActionTarget.MultipleFeatures
            )

        open_in_attributes_table_action = QgsMapLayerAction(
            self.tr("Show in Attribute Table"),
            identify_menu,
            LayerType.Vector,
            open_in_attributes_table_targets,
        )
        open_in_attributes_table_action.setIcon(qgis_icon("attributes.svg"))
        open_in_attributes_table_action.triggeredForFeaturesV2.connect(
            self.open_features_in_attributes_table
        )
        identify_menu.addCustomAction(open_in_attributes_table_action)

        self._tool_handler = IdentificationToolHandler(
            self._identify_tool, self._action
        )
        iface = self._iface
        iface.registerMapToolHandler(self._tool_handler)
        iface.layerTreeView().selectionModel().selectionChanged.connect(
            self._update_action_enabled
        )
        QgsProject.instance().layersRemoved.connect(
            self._update_action_enabled
        )
        self._update_action_enabled()

    def unload(self) -> None:
        """Unload identification manager and reset the map tool."""
        self._toolbar_timer.stop()
        self._results_dialog_timer.stop()
        try:
            self._toolbar_timer.timeout.disconnect(self.__add_icon_to_toolbar)
            self._results_dialog_timer.timeout.disconnect(
                self._show_results_dialog
            )
        except (RuntimeError, TypeError):
            pass

        if self._results_dialog is not None:
            self._results_dialog.unload()
            self._iface.removeDockWidget(self._results_dialog)
            self._results_dialog.deleteLater()
            self._results_dialog = None  # type: ignore

        iface = self._iface
        if self._tool_handler is not None:
            iface.unregisterMapToolHandler(self._tool_handler)
            self._tool_handler = None
        try:
            iface.layerTreeView().selectionModel().selectionChanged.disconnect(
                self._update_action_enabled
            )
        except TypeError:
            pass
        try:
            QgsProject.instance().layersRemoved.disconnect(
                self._update_action_enabled
            )
        except TypeError:
            pass

        if self._identify_tool is not None:
            identify_tool = self._identify_tool
            self._canvas.unsetMapTool(identify_tool)
            identify_tool.unload()
            identify_tool.identifyMenu().removeCustomActions()
            identify_tool.deleteLater()
            QCoreApplication.sendPostedEvents(
                identify_tool,
                QEvent.Type.DeferredDelete,
            )
            self._identify_tool = None  # type: ignore

        if self._action is not None:
            self._action.deleteLater()
            self._action = None  # type: ignore

    @property
    def action(self) -> QAction:
        assert self._action is not None
        return self._action

    def results_dialog(self) -> IdentificationResultsWidget:
        if self._results_dialog is not None:
            return self._results_dialog

        self._results_dialog = IdentificationResultsWidget(self._canvas)
        self._results_dialog.open_feature_in_nextgis_web.connect(
            self.open_feature_in_nextgis_web
        )
        self._results_dialog.open_features_in_attributes_table.connect(
            self.open_features_in_attributes_table
        )
        iface = self._iface
        if not iface.mainWindow().restoreDockWidget(self._results_dialog):
            iface.addDockWidget(
                Qt.DockWidgetArea.RightDockWidgetArea, self._results_dialog
            )

        self._results_dialog_timer.start(0)

        return self._results_dialog

    def _show_results_dialog(self) -> None:
        if self._results_dialog is None:
            return

        self._results_dialog.setUserVisible(True)

    def clear_results(self) -> None:
        self.results_dialog().clear()

    # @pyqtSlot("QgsMapLayer*", QgsFeature)
    def open_feature_in_nextgis_web(
        self,
        layer: QgsMapLayer,
        feature: QgsFeature,
    ) -> None:
        """Open feature in NextGIS Web."""

        connection_id = layer.customProperty("ngw_connection_id")
        resource_id = layer.customProperty("ngw_resource_id")

        connection_manager = NgwConnectionsManager()
        connection = connection_manager.connection(connection_id)
        assert connection is not None

        context = QgsExpressionContext(
            QgsExpressionContextUtils.globalProjectLayerScopes(layer)
        )
        expression = QgsExpression("ngw_feature_id()")
        expression.prepare(context)
        context.setFeature(feature)
        feature_ngw_fid = expression.evaluate(context)

        url = QUrl(connection.url)
        url.setPath(f"/resource/{resource_id}/feature/{feature_ngw_fid}")

        QDesktopServices.openUrl(url)

    # @pyqtSlot("QgsMapLayer*", "QList<QgsFeature>")
    def open_features_in_attributes_table(
        self,
        layer: QgsVectorLayer,
        features: List[QgsFeature],
    ) -> None:
        """Open features in attributes table."""
        id_list = ",".join(str(f.id()) for f in features)
        iface = self._iface
        iface.showAttributeTable(layer, f"$id IN ({id_list})")

    @pyqtSlot(QgsGeometry, Qt.MouseButton, Qt.KeyboardModifier)
    def _identify_from_geometry(
        self,
        geometry: QgsGeometry,
        button: Qt.MouseButton,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        self.results_dialog().clear()

        iface = self._iface
        self._identify_tool.identifyMessage.connect(
            iface.statusBarIface().showMessage
        )

        is_single_point = geometry.type() == GeometryType.Point
        show_extended_menu = is_single_point and (
            bool(button == Qt.MouseButton.RightButton)
            or bool(modifiers == Qt.KeyboardModifier.ShiftModifier)
        )

        if is_single_point:
            self._set_click_context_scope(geometry.asPoint())

        identify_mode = (
            QgsMapToolIdentify.IdentifyMode.LayerSelection
            if show_extended_menu
            else IdentificationSettings().mode
        )

        identify_menu = self._identify_tool.identifyMenu()
        identify_menu.setResultsIfExternalAction(False)

        # enable the right click for extended menu so it behaves as a
        # contextual menu this would be removed when a true contextual
        # menu is brought in QGIS
        identify_menu.setExecWithSingleResult(show_extended_menu)
        identify_menu.setShowFeatureActions(show_extended_menu)

        layers = []
        if identify_mode == QgsMapToolIdentify.IdentifyMode.ActiveLayer:
            layers = iface.layerTreeView().selectedLayersRecursive()
        else:
            layers = iface.mapCanvas().layers(True)

        layers = list(filter(is_ngw_container, layers))

        identify_context = QgsIdentifyContext()
        if self._canvas.mapSettings().isTemporal():
            identify_context.setTemporalRange(self._canvas.temporalRange())
        if hasattr(identify_context, "setZRange"):
            identify_context.setZRange(self._canvas.zRange())
        results = self._identify_tool.identify(
            geometry,
            identify_mode,
            layers,
            QgsMapToolIdentify.Type.VectorLayer,
            identify_context,
        )

        logger.debug(f"Identified {len(results)} features")

        self._identify_tool.identifyMessage.disconnect(
            iface.statusBarIface().showMessage
        )

        if len(results) == 0:
            self.results_dialog().clear()
            iface.statusBarIface().showMessage(
                self.tr("No features found at this position."), 2000
            )
            return

        self.results_dialog().set_found_features(results)
        self.results_dialog().setUserVisible(True)

    def _set_click_context_scope(self, point: QgsPointXY) -> None:
        scope = QgsExpressionContextScope()
        scope.addVariable(
            QgsExpressionContextScope.StaticVariable(
                "click_x", point.x(), True
            )
        )
        scope.addVariable(
            QgsExpressionContextScope.StaticVariable(
                "click_y", point.y(), True
            )
        )

        self.results_dialog().set_expression_context_scope(scope)

        if self._identify_tool.identifyMenu():
            self._identify_tool.identifyMenu().setExpressionContextScope(scope)

    def _to_canvas_coordinates(self, point: QgsPointXY) -> QPoint:
        canvas_point = self._canvas.getCoordinateTransform().transform(point)
        return QPoint(round(canvas_point.x()), round(canvas_point.y()))

    @pyqtSlot()
    def __add_icon_to_toolbar(self) -> None:
        plugin = NgConnectInterface.instance()
        plugin.toolbar.addAction(self._action)

    def _update_action_enabled(self, *_args) -> None:
        if self._action is None:
            return

        iface = self._iface
        layer_tree_view = iface.layerTreeView()
        layers = list(layer_tree_view.selectedLayersRecursive())
        current_layer = layer_tree_view.currentLayer()
        if current_layer is not None and current_layer not in layers:
            layers.append(current_layer)

        self._action.setEnabled(
            any(is_ngw_container(layer) for layer in layers)
        )
