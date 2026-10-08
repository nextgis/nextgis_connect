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

from contextlib import suppress
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Set,
    cast,
)

from qgis.core import (
    QgsApplication,
    QgsCoordinateTransform,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextScope,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsMapLayer,
    QgsProject,
    QgsReferencedRectangle,
    QgsVectorLayer,
)
from qgis.gui import (
    QgsAttributeEditorContext,
    QgsAttributeForm,
    QgsDockWidget,
    QgsMapCanvas,
    QgsMapToolIdentify,
)
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QResizeEvent
from qgis.PyQt.QtWidgets import (
    QAction,
    QActionGroup,
    QComboBox,
    QFrame,
    QMenu,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import iface

from nextgis_connect.legacy.detached_editing.identification.highlight_handler import (
    HighlightHandler,
)
from nextgis_connect.legacy.detached_editing.identification.settings import (
    IdentificationSettings,
)
from nextgis_connect.legacy.detached_editing.identification.types import (
    FeatureKey,
    IdentificationTab,
)
from nextgis_connect.legacy.detached_editing.identification.ui.attachments_tab import (
    AttachmentsTab,
)
from nextgis_connect.legacy.detached_editing.identification.ui.description_tab import (
    DescriptionTab,
)
from nextgis_connect.legacy.detached_editing.identification.ui.no_features_widget import (
    NoFeaturesWidget,
)
from nextgis_connect.legacy.detached_editing.utils import DetachedLayerState
from nextgis_connect.platform.qgis.compat import GeometryType, QgsFeatureId
from nextgis_connect.plugin.plugin_interface import NgConnectInterface
from nextgis_connect.shared.constants import PLUGIN_NAME
from nextgis_connect.ui_kit.icons import (
    material_icon,
    plugin_icon,
    qgis_icon,
)

if TYPE_CHECKING:
    from qgis.gui import QgisInterface

    assert isinstance(iface, QgisInterface)

ResultsDialogBase, _ = uic.loadUiType(
    str(Path(__file__).parent / "identification_results_widget_base.ui")
)


class IdentificationResultsWidget(QgsDockWidget, ResultsDialogBase):
    open_feature_in_nextgis_web = pyqtSignal(QgsMapLayer, QgsFeature)
    open_features_in_attributes_table = pyqtSignal(QgsVectorLayer, list)

    def __init__(
        self, canvas: QgsMapCanvas, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NgConnectIdentificationResultsWidget")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        self._canvas = canvas
        self._features: Dict[
            FeatureKey, QgsMapToolIdentify.IdentifyResult
        ] = {}

        self._highlight_handler = HighlightHandler(canvas, self)
        self._last_selected_feature_key: Optional[FeatureKey] = None

        self._form: Optional[QgsAttributeForm] = None
        self._editing_stopped_connection = None
        self._editing_started_connection = None
        self._layer_state_changed_connection = None
        self._is_feature_data_available = False
        self._is_unloaded = False

        self._tracked_layers: Dict[str, QgsVectorLayer] = {}
        self._feature_deleted_connections: Dict[str, object] = {}
        self._features_removed_connections: Dict[str, object] = {}
        self._tracked_editing_started_connections: Dict[str, object] = {}
        self._tracked_editing_stopped_connections: Dict[str, object] = {}

        QgsProject.instance().layersWillBeRemoved.connect(
            self.__on_layers_will_be_removed
        )

        self.__load_ui()

    def __del__(self) -> None:
        with suppress(AttributeError, RuntimeError, TypeError):
            self.unload()

    def unload(self) -> None:
        """Detach project and layer signal handlers before deleting dock."""
        if self._is_unloaded:
            return

        self._is_unloaded = True

        with suppress(RuntimeError, TypeError):
            QgsProject.instance().layersWillBeRemoved.disconnect(
                self.__on_layers_will_be_removed
            )

        if not hasattr(self, "_attachments_tab"):
            return

        self.clear()
        with suppress(RuntimeError, TypeError):
            self.open_feature_in_nextgis_web.disconnect()
        with suppress(RuntimeError, TypeError):
            self.open_features_in_attributes_table.disconnect()

    def set_expression_context_scope(
        self, scope: QgsExpressionContextScope
    ) -> None:
        pass

    @pyqtSlot()
    def set_found_features(
        self,
        results: List[QgsMapToolIdentify.IdentifyResult],
    ) -> None:
        # self.attributes_tab.layout().addWidget(results[0].mLayer.createAttributeTableView())
        self.clear()

        layer_contexts: Dict[QgsVectorLayer, QgsExpressionContext] = {}
        layer_expressions: Dict[QgsVectorLayer, QgsExpression] = {}

        for result in reversed(results):
            layer = cast(QgsVectorLayer, result.mLayer)
            feature_key = self.__make_feature_key(
                layer.id(), result.mFeature.id()
            )
            self._highlight_handler.add_feature(feature_key, result)

        self.features_combobox.blockSignals(True)
        self.features_combobox.clear()
        self.features_combobox.setEnabled(True)

        for result in results:
            layer = cast(QgsVectorLayer, result.mLayer)
            self.__track_layer(layer)

            if layer not in layer_expressions:
                context = QgsExpressionContext(
                    QgsExpressionContextUtils.globalProjectLayerScopes(layer)
                )
                expression = QgsExpression(layer.displayExpression())
                expression.prepare(context)
                layer_contexts[layer] = context
                layer_expressions[layer] = expression

            feature = result.mFeature
            feature_key = self.__make_feature_key(layer.id(), feature.id())
            self._features[feature_key] = result

            context = layer_contexts[layer]
            expression = layer_expressions[layer]
            context.setFeature(feature)
            label_result = expression.evaluate(context)
            label = str(label_result) if label_result else str(feature.id())

            title = f"{label} ({layer.name()})"
            self.features_combobox.addItem(title, feature_key)
            self.features_combobox.setItemData(
                self.features_combobox.count() - 1,
                title,
                Qt.ItemDataRole.ToolTipRole,
            )

        self.tab_widget.setEnabled(True)
        self.features_combobox.blockSignals(False)
        self.__on_feature_changed(self.features_combobox.currentIndex())

    @pyqtSlot()
    def clear(self) -> None:
        self.__disconnect_current_feature_connections()
        self.__untrack_all_layers()

        self.features_combobox.blockSignals(True)
        self.features_combobox.clear()
        self.features_combobox.setDisabled(True)
        self.features_combobox.addItem(self.tr("No features"), None)
        self.features_combobox.blockSignals(False)
        self.features_combobox.setToolTip(None)

        self._last_selected_feature_key = None
        self._features.clear()
        self._highlight_handler.clear()
        self._is_feature_data_available = False

        if self._form is not None:
            self._attributes_form_layout.removeWidget(self._form)
            self._form.deleteLater()
            self._form = None

        self.__on_features_not_found()

        self.tab_widget.setEnabled(False)

        self.__update_overlay()

    def __make_feature_key(
        self, layer_id: str, feature_id: QgsFeatureId
    ) -> FeatureKey:
        return (layer_id, feature_id)

    def __current_feature_key(self) -> Optional[FeatureKey]:
        feature_key = self.features_combobox.currentData()
        if feature_key is None:
            return None

        return cast(FeatureKey, feature_key)

    def __current_feature_result(
        self,
    ) -> Optional[QgsMapToolIdentify.IdentifyResult]:
        feature_key = self.__current_feature_key()
        if feature_key is None:
            return None

        return self._features.get(feature_key)

    def __disconnect_connection(self, connection: object) -> None:
        try:
            self.disconnect(cast(Any, connection))
        except (RuntimeError, TypeError):
            pass

    def __disconnect_current_feature_connections(self) -> None:
        connection_names = (
            "_editing_started_connection",
            "_editing_stopped_connection",
            "_layer_state_changed_connection",
        )

        for connection_name in connection_names:
            connection = getattr(self, connection_name)
            if connection is None:
                continue

            self.__disconnect_connection(connection)
            setattr(self, connection_name, None)

    def __track_layer(self, layer: QgsVectorLayer) -> None:
        layer_id = layer.id()
        if layer_id in self._tracked_layers:
            return

        self._tracked_layers[layer_id] = layer
        self._features_removed_connections[layer_id] = (
            layer.committedFeaturesRemoved.connect(
                lambda _, removed_feature_ids, tracked_layer_id=layer_id: (
                    self.__on_committed_features_removed(
                        tracked_layer_id, removed_feature_ids
                    )
                )
            )
        )
        self._tracked_editing_started_connections[layer_id] = (
            layer.editingStarted.connect(
                lambda tracked_layer_id=layer_id: (
                    self.__on_tracked_layer_editing_started(tracked_layer_id)
                )
            )
        )
        self._tracked_editing_stopped_connections[layer_id] = (
            layer.editingStopped.connect(
                lambda tracked_layer_id=layer_id: (
                    self.__on_tracked_layer_editing_stopped(tracked_layer_id)
                )
            )
        )

        if layer.isEditable():
            self.__connect_feature_deleted_signal(layer)

    def __connect_feature_deleted_signal(self, layer: QgsVectorLayer) -> None:
        layer_id = layer.id()
        if layer_id in self._feature_deleted_connections:
            return

        edit_buffer = layer.editBuffer()
        if edit_buffer is None:
            return

        self._feature_deleted_connections[layer_id] = (
            edit_buffer.featureDeleted.connect(
                lambda feature_id, tracked_layer_id=layer_id: (
                    self.__on_feature_deleted(tracked_layer_id, feature_id)
                )
            )
        )

    def __disconnect_feature_deleted_signal(self, layer_id: str) -> None:
        connection = self._feature_deleted_connections.pop(layer_id, None)
        if connection is not None:
            self.__disconnect_connection(connection)

    def __untrack_layer(self, layer_id: str) -> None:
        self.__disconnect_feature_deleted_signal(layer_id)

        connection = self._features_removed_connections.pop(layer_id, None)
        if connection is not None:
            self.__disconnect_connection(connection)

        connection = self._tracked_editing_started_connections.pop(
            layer_id, None
        )
        if connection is not None:
            self.__disconnect_connection(connection)

        connection = self._tracked_editing_stopped_connections.pop(
            layer_id, None
        )
        if connection is not None:
            self.__disconnect_connection(connection)

        self._tracked_layers.pop(layer_id, None)

    def __untrack_unused_layers(self) -> None:
        used_layer_ids = {layer_id for layer_id, _ in self._features}
        for layer_id in list(self._tracked_layers):
            if layer_id not in used_layer_ids:
                self.__untrack_layer(layer_id)

    def __untrack_all_layers(self) -> None:
        for layer_id in list(self._tracked_layers):
            self.__untrack_layer(layer_id)

    def __remove_feature_keys(self, feature_keys: Set[FeatureKey]) -> None:
        removable_keys = {
            feature_key
            for feature_key in feature_keys
            if feature_key in self._features
        }
        if not removable_keys:
            return

        current_feature_key = self.__current_feature_key()
        current_index = self.features_combobox.currentIndex()
        current_feature_removed = current_feature_key in removable_keys

        self.features_combobox.blockSignals(True)
        for index in range(self.features_combobox.count() - 1, -1, -1):
            feature_key = self.features_combobox.itemData(index)
            if feature_key not in removable_keys:
                continue

            self.features_combobox.removeItem(index)
            if index < current_index:
                current_index -= 1

        if current_feature_removed and self.features_combobox.count() > 0:
            current_index = min(
                max(current_index, 0),
                self.features_combobox.count() - 1,
            )
            self.features_combobox.setCurrentIndex(current_index)

        self.features_combobox.blockSignals(False)

        for feature_key in removable_keys:
            self._features.pop(feature_key, None)

        self._highlight_handler.remove_features(removable_keys)

        if self._last_selected_feature_key in removable_keys:
            self._last_selected_feature_key = None

        self.__untrack_unused_layers()

        if not self._features:
            self.clear()
            return

        if current_feature_removed:
            self.__on_feature_changed(self.features_combobox.currentIndex())

    def __on_feature_deleted(
        self, layer_id: str, feature_id: QgsFeatureId
    ) -> None:
        self.__remove_feature_keys(
            {self.__make_feature_key(layer_id, feature_id)}
        )

    def __on_committed_features_removed(
        self, layer_id: str, removed_feature_ids: List[QgsFeatureId]
    ) -> None:
        feature_keys = {
            self.__make_feature_key(layer_id, feature_id)
            for feature_id in removed_feature_ids
        }
        self.__remove_feature_keys(feature_keys)

    def __on_tracked_layer_editing_started(self, layer_id: str) -> None:
        layer = self._tracked_layers.get(layer_id)
        if layer is None:
            return

        self.__connect_feature_deleted_signal(layer)
        self.__update_current_layer_edit_mode(layer_id, True)

    def __on_tracked_layer_editing_stopped(self, layer_id: str) -> None:
        self.__disconnect_feature_deleted_signal(layer_id)
        self.__update_current_layer_edit_mode(layer_id, False)

    def __update_current_layer_edit_mode(
        self, layer_id: str, is_enabled: bool
    ) -> None:
        selected_result = self.__current_feature_result()
        if selected_result is None:
            return

        layer = cast(QgsVectorLayer, selected_result.mLayer)
        if layer.id() != layer_id:
            return

        self.__update_edit_mode(is_enabled)

    @pyqtSlot("QStringList")
    def __on_layers_will_be_removed(self, layer_ids: List[str]) -> None:
        removed_layer_ids = set(layer_ids)
        feature_keys = {
            feature_key
            for feature_key in self._features
            if feature_key[0] in removed_layer_ids
        }
        self.__remove_feature_keys(feature_keys)

    def __load_ui(self) -> None:
        self.setupUi(self)
        self.setWindowTitle(
            PLUGIN_NAME + " " + self.tr("Identification Results")
        )

        self.features_combobox: QComboBox = self.features_combobox
        self.edit_button: QToolButton = self.edit_button
        self.extra_button: QToolButton = self.extra_button
        self.tab_widget: QTabWidget = self.tab_widget
        self.attributes_tab: QWidget = self.attributes_tab
        self.attributes_scroll_area = QScrollArea(self.attributes_tab)
        self.attributes_scroll_area.setWidgetResizable(True)
        self.attributes_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._attributes_form_container = QWidget(self.attributes_scroll_area)
        self._attributes_form_layout = QVBoxLayout(
            self._attributes_form_container
        )
        self._attributes_form_layout.setContentsMargins(0, 0, 0, 0)
        self._attributes_form_layout.setSpacing(0)
        self.attributes_scroll_area.setWidget(self._attributes_form_container)
        self.attributes_tab.layout().addWidget(self.attributes_scroll_area)

        self.features_combobox.currentIndexChanged.connect(
            self.__on_feature_changed
        )

        self.edit_button.setToolTip(self.tr("Toggle Editing"))
        self.edit_button.setIcon(qgis_icon("mActionToggleEditing.svg"))
        self.edit_button.setCheckable(True)
        self.edit_button.setFixedSize(
            self.features_combobox.sizeHint().height(),
            self.features_combobox.sizeHint().height(),
        )
        self.edit_button.clicked.connect(self.__toggle_edit_mode)

        self.extra_button.setFixedSize(
            self.features_combobox.sizeHint().height(),
            self.features_combobox.sizeHint().height(),
        )
        self.extra_button.setStyleSheet(
            """
            QToolButton::menu-indicator {
                image: none;
            }
            """
        )

        self._attachments_tab = AttachmentsTab(self)
        self.tab_widget.addTab(self._attachments_tab, self.tr("Attachments"))

        self._description_tab = DescriptionTab(self)
        self.tab_widget.addTab(self._description_tab, self.tr("Description"))

        self.tab_widget.setCurrentIndex(IdentificationSettings().last_used_tab)
        self.tab_widget.currentChanged.connect(self.__on_tab_changed)

        icon_color = QgsApplication.palette().text().color().name()
        self.extra_button.setIcon(material_icon("menu", color=icon_color))
        self.tab_widget.setTabIcon(
            IdentificationTab.ATTRIBUTES,
            material_icon("list", color=icon_color),
        )
        self.tab_widget.setTabIcon(
            IdentificationTab.DESCRIPTION,
            material_icon("description", color=icon_color),
        )
        self.tab_widget.setTabIcon(
            IdentificationTab.ATTACHMENTS,
            material_icon("attach_file", color=icon_color),
        )

        extra_menu = QMenu(self)
        # TODO: check is uploaded
        self.__open_feature_in_ngw_action = extra_menu.addAction(
            plugin_icon("branding/ngw_logo.svg"),
            self.tr("Open feature in NextGIS Web"),
            self.__open_feature_in_ngw,
        )
        self.__show_attribute_table_action = extra_menu.addAction(
            qgis_icon("attributes.svg"),
            self.tr("Show feature in Attribute Table"),
            self.__open_feature_in_attributes_table,
        )
        extra_menu.addSeparator()
        self.__show_attributes_table_action = extra_menu.addAction(
            qgis_icon("attributes.svg"),
            self.tr("Show features in Attribute Table"),
            self.__open_features_in_attributes_table,
        )
        extra_menu.addSeparator()

        settings = IdentificationSettings()

        current_mode = settings.mode
        selection_mode_menu = extra_menu.addMenu(self.tr("Selection Mode"))
        selection_mode_menu.setIcon(qgis_icon("mActionSelect.svg"))

        mode_current_layer_action = selection_mode_menu.addAction(
            QgsApplication.translate(
                "QgsIdentifyResultsDialog", "Current Layer"
            ),
        )
        mode_current_layer_action.setData(
            QgsMapToolIdentify.IdentifyMode.ActiveLayer
        )
        mode_current_layer_action.setCheckable(True)
        mode_current_layer_action.setChecked(
            current_mode == mode_current_layer_action.data()
        )

        mode_top_down_stop_at_first_action = selection_mode_menu.addAction(
            QgsApplication.translate(
                "QgsIdentifyResultsDialog", "Top Down, Stop at First"
            ),
        )
        mode_top_down_stop_at_first_action.setData(
            QgsMapToolIdentify.IdentifyMode.TopDownStopAtFirst
        )
        mode_top_down_stop_at_first_action.setCheckable(True)
        mode_top_down_stop_at_first_action.setChecked(
            current_mode == mode_top_down_stop_at_first_action.data()
        )

        mode_top_down_action = selection_mode_menu.addAction(
            QgsApplication.translate("QgsIdentifyResultsDialog", "Top Down"),
        )
        mode_top_down_action.setData(
            QgsMapToolIdentify.IdentifyMode.TopDownAll
        )
        mode_top_down_action.setCheckable(True)
        mode_top_down_action.setChecked(
            current_mode == mode_top_down_action.data()
        )

        mode_layer_selection_action = selection_mode_menu.addAction(
            QgsApplication.translate(
                "QgsIdentifyResultsDialog", "Layer Selection"
            ),
        )
        mode_layer_selection_action.setData(
            QgsMapToolIdentify.IdentifyMode.LayerSelection
        )
        mode_layer_selection_action.setCheckable(True)
        mode_layer_selection_action.setChecked(
            current_mode == mode_layer_selection_action.data()
        )

        selection_mode_group = QActionGroup(selection_mode_menu)
        selection_mode_group.addAction(mode_current_layer_action)
        selection_mode_group.addAction(mode_top_down_stop_at_first_action)
        selection_mode_group.addAction(mode_top_down_action)
        selection_mode_group.addAction(mode_layer_selection_action)
        selection_mode_group.setExclusive(True)
        selection_mode_group.triggered.connect(self.__selection_mode_changed)

        self._auto_pan_action = extra_menu.addAction(
            qgis_icon("mActionPanTo.svg"),
            self.tr("Automatically pan to the current feature"),
        )
        self._auto_pan_action.setCheckable(True)
        self._auto_pan_action.setChecked(settings.auto_pan)

        self._auto_zoom_action = extra_menu.addAction(
            qgis_icon("mActionZoomTo.svg"),
            self.tr("Automatically zoom to the current feature"),
        )
        self._auto_zoom_action.setCheckable(True)
        self._auto_zoom_action.setChecked(settings.auto_zoom)

        self._auto_pan_action.triggered.connect(self.__on_auto_pan_toggled)
        self._auto_zoom_action.triggered.connect(self.__on_auto_zoom_toggled)

        self.extra_button.setMenu(extra_menu)
        self.extra_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )

        self.__insert_no_features_widget()

    def __insert_no_features_widget(self) -> None:
        self._overlay_widget = NoFeaturesWidget(self.tab_widget)
        self._overlay_widget.hide()

    def _show_overlay(self, message: str) -> None:
        self._overlay_widget.set_message(message)
        self._overlay_widget.show()
        self._overlay_widget.raise_()

    def _hide_overlay(self) -> None:
        self._overlay_widget.hide()

    def __update_overlay(self) -> None:
        if self._last_selected_feature_key is None:
            self._show_overlay(
                self.tr("No features were found at the click location.")
            )
        elif (
            self._is_feature_data_available
            or self.tab_widget.currentIndex() == IdentificationTab.ATTRIBUTES
        ):
            self._hide_overlay()
        else:
            self._show_overlay(
                self.tr(
                    "Attachments and descriptions are unavailable for layers "
                    "without feature versioning."
                )
            )

        self._update_overlay_geometry()

    def resizeEvent(self, a0: Optional[QResizeEvent] = None) -> None:
        super().resizeEvent(a0)
        self._update_overlay_geometry()

    def _update_overlay_geometry(self) -> None:
        widget = self.attributes_scroll_area

        if self.tab_widget.currentIndex() == IdentificationTab.ATTACHMENTS:
            widget = self._attachments_tab.view
        elif self.tab_widget.currentIndex() == IdentificationTab.DESCRIPTION:
            widget = self._description_tab.text_edit

        size = widget.size()
        position = widget.mapTo(self.tab_widget, widget.rect().topLeft())

        self._overlay_widget.setGeometry(
            position.x(),
            position.y(),
            size.width(),
            size.height(),
        )

    def __on_feature_changed(self, index: int) -> None:
        self.__disconnect_current_feature_connections()
        self._attachments_tab.close_editor()

        if self._last_selected_feature_key is not None:
            self._highlight_handler.deactivate_feature()

        if index < 0:
            self._last_selected_feature_key = None
            self.__on_features_not_found()
            return

        feature_key = self.features_combobox.itemData(index)
        if feature_key is None or feature_key not in self._features:
            self._last_selected_feature_key = None
            self.__on_features_not_found()
            return

        self._last_selected_feature_key = feature_key
        self._highlight_handler.set_active_feature(feature_key)
        self._canvas.refresh()

        selected_result = self._features[feature_key]
        layer = cast(QgsVectorLayer, selected_result.mLayer)
        feature_id = selected_result.mFeature.id()
        self.__add_form(layer, feature_id)

        self.features_combobox.setToolTip(self.features_combobox.currentText())
        self.edit_button.setEnabled(not layer.readOnly())

        detached_editing_manager = (
            NgConnectInterface.instance().detached_editing
        )
        detached_layer = detached_editing_manager.layer(layer)

        is_feature_data_enabled = (
            detached_layer.container.metadata.is_versioning_enabled
        )
        self._is_feature_data_available = is_feature_data_enabled
        if is_feature_data_enabled:
            self._attachments_tab.set_feature(layer, feature_id)
            self._description_tab.set_feature(layer, feature_id)
        else:
            self._attachments_tab.clear_feature()
            self._description_tab.clear_feature()

        self.__update_overlay()

        self._editing_started_connection = layer.editingStarted.connect(
            self.__on_editing_started
        )
        self._editing_stopped_connection = layer.editingStopped.connect(
            self.__on_editing_stopped
        )
        self._layer_state_changed_connection = (
            detached_layer.container.state_changed.connect(
                self.__on_state_changed
            )
        )

        self.__on_features_found()
        self.__update_edit_mode(layer.isEditable())

        if self._auto_pan_action.isChecked():
            self._pan_to_feature(selected_result)
        if self._auto_zoom_action.isChecked():
            self._zoom_to_feature(selected_result)

    @pyqtSlot()
    def __on_editing_started(self) -> None:
        self.__update_edit_mode(True)

    @pyqtSlot()
    def __on_editing_stopped(self) -> None:
        self.__update_edit_mode(False)

    @pyqtSlot(bool)
    def __toggle_edit_mode(self, checked: bool) -> None:
        del checked

        selected_result = self.__current_feature_result()
        if selected_result is None:
            return

        layer = cast(QgsVectorLayer, selected_result.mLayer)
        cast(Any, iface.mainWindow()).toggleEditing(layer)
        self.__update_edit_mode(layer.isEditable())

    @pyqtSlot()
    def __on_features_found(self) -> None:
        self.__open_feature_in_ngw_action.setEnabled(True)
        self.__show_attribute_table_action.setEnabled(True)
        self.__show_attributes_table_action.setEnabled(True)

    @pyqtSlot()
    def __on_features_not_found(self) -> None:
        self.__update_edit_mode(False)
        self.edit_button.setEnabled(False)
        self.__open_feature_in_ngw_action.setDisabled(True)
        self.__show_attribute_table_action.setDisabled(True)
        self.__show_attributes_table_action.setDisabled(True)
        self._attachments_tab.clear_feature()
        self._description_tab.clear_feature()

    @pyqtSlot(bool)
    def __update_edit_mode(self, is_enabled: bool) -> None:
        self.edit_button.setChecked(is_enabled)
        self.__update_attachments_editing_availability()
        if not is_enabled:
            self._attachments_tab.close_editor()
        self._description_tab.set_read_only(not is_enabled)
        self.__set_attribute_form_edit_mode(is_enabled)

    def __set_attribute_form_edit_mode(self, is_enabled: bool) -> None:
        if self._form is None:
            return

        mode = (
            QgsAttributeEditorContext.Mode.SingleEditMode
            if is_enabled
            else QgsAttributeEditorContext.Mode.IdentifyMode
        )
        self._form.setMode(mode)

    def __update_attachments_editing_availability(self) -> None:
        selected_result = self.__current_feature_result()
        if selected_result is None:
            self._attachments_tab.set_read_only(True)
            return

        layer = cast(QgsVectorLayer, selected_result.mLayer)
        self._attachments_tab.set_read_only(layer.readOnly())

    def __refresh_current_feature_after_sync(self) -> None:
        selected_result = self.__current_feature_result()
        if selected_result is None:
            self.__on_feature_changed(self.features_combobox.currentIndex())
            return

        layer = cast(QgsVectorLayer, selected_result.mLayer)
        refreshed_feature = layer.getFeature(selected_result.mFeature.id())
        if not refreshed_feature.isValid():
            feature_key = self.__current_feature_key()
            if feature_key is not None:
                self.__remove_feature_keys({feature_key})
            else:
                self.__on_feature_changed(
                    self.features_combobox.currentIndex()
                )
            return

        selected_result.mFeature = refreshed_feature
        self.__on_feature_changed(self.features_combobox.currentIndex())

    def __is_feature_changed(
        self, previous_feature: QgsFeature, current_feature: QgsFeature
    ) -> bool:
        if previous_feature.id() != current_feature.id():
            return True

        if previous_feature.attributes() != current_feature.attributes():
            return True

        previous_geometry = previous_feature.geometry()
        current_geometry = current_feature.geometry()
        if previous_geometry.isNull() or current_geometry.isNull():
            return previous_geometry.isNull() != current_geometry.isNull()

        return previous_geometry.asWkb() != current_geometry.asWkb()

    def __add_form(
        self, layer: QgsVectorLayer, feature_id: QgsFeatureId
    ) -> None:
        if self._form is not None:
            self._attributes_form_layout.removeWidget(self._form)
            self._form.deleteLater()
            self._form = None

        context = QgsAttributeEditorContext()
        context.setVectorLayerTools(iface.vectorLayerTools())
        context.setMapCanvas(self._canvas)
        context.setCadDockWidget(iface.cadDockWidget())
        context.setMainMessageBar(iface.messageBar())
        context.setAttributeFormMode(
            QgsAttributeEditorContext.Mode.SingleEditMode
        )
        context.setFormMode(QgsAttributeEditorContext.FormMode.Embed)

        feature = layer.getFeature(feature_id)
        self._form = QgsAttributeForm(
            layer, feature, context, self._attributes_form_container
        )
        self._form.widgetValueChanged.connect(self.__on_value_changed)

        self._attributes_form_layout.addWidget(self._form)
        self._form.show()

    def __on_value_changed(self) -> None:
        if self._form is not None:
            self._form.save()

    @pyqtSlot()
    def __open_feature_in_ngw(self) -> None:
        selected_result = self.__current_feature_result()
        if selected_result is None:
            return

        self.open_feature_in_nextgis_web.emit(
            selected_result.mLayer,
            selected_result.mFeature,
        )

    @pyqtSlot()
    def __open_feature_in_attributes_table(self) -> None:
        selected_result = self.__current_feature_result()
        if selected_result is None:
            return

        self.open_features_in_attributes_table.emit(
            cast(QgsVectorLayer, selected_result.mLayer),
            [selected_result.mFeature],
        )

    @pyqtSlot()
    def __open_features_in_attributes_table(self) -> None:
        selected_result = self.__current_feature_result()
        if selected_result is None:
            return

        self.open_features_in_attributes_table.emit(
            cast(QgsVectorLayer, selected_result.mLayer),
            [f.mFeature for f in self._features.values()],
        )

    @pyqtSlot(QAction)
    def __selection_mode_changed(self, action: QAction) -> None:  # type: ignore[reportInvalidTypeForm]
        current_mode = action.data()
        if action.isChecked():
            IdentificationSettings().mode = current_mode

    @pyqtSlot(int)
    def __on_tab_changed(self, selected_tab: int) -> None:
        IdentificationSettings().last_used_tab = IdentificationTab(
            selected_tab
        )
        self.__update_overlay()

    @pyqtSlot(bool)
    def __on_auto_zoom_toggled(self, checked: bool) -> None:
        settings = IdentificationSettings()
        if checked:
            self._auto_pan_action.setChecked(False)
            settings.auto_pan = False

        settings.auto_zoom = checked

    @pyqtSlot(bool)
    def __on_auto_pan_toggled(self, checked: bool) -> None:
        settings = IdentificationSettings()
        if checked:
            self._auto_zoom_action.setChecked(False)
            settings.auto_zoom = False

        settings.auto_pan = checked

    def _pan_to_feature(
        self, identify_result: QgsMapToolIdentify.IdentifyResult
    ) -> None:
        feature_center = (
            identify_result.mFeature.geometry().centroid().asPoint()
        )

        transform = QgsCoordinateTransform(
            identify_result.mLayer.crs(),
            self._canvas.mapSettings().destinationCrs(),
            QgsProject.instance(),
        )
        result = transform.transform(feature_center)

        self._canvas.setCenter(result)
        self._canvas.refresh()

    def _zoom_to_feature(
        self, identify_result: QgsMapToolIdentify.IdentifyResult
    ) -> None:
        geometry = identify_result.mFeature.geometry()

        settings = IdentificationSettings()

        if geometry.type() == GeometryType.Point:
            self._pan_to_feature(identify_result)
            self._canvas.zoomScale(settings.zoom_map_scale)
        else:
            bounding_box = geometry.boundingBox()
            bounding_box.scale(settings.zoom_geometry_scale_factor)
            referenced_extent = QgsReferencedRectangle(
                bounding_box, identify_result.mLayer.crs()
            )
            self._canvas.setReferencedExtent(referenced_extent)

        self._canvas.refresh()

    @pyqtSlot(DetachedLayerState)
    def __on_state_changed(self, state: DetachedLayerState) -> None:
        if state in (
            DetachedLayerState.NotSynchronized,
            DetachedLayerState.Synchronized,
        ):
            QTimer.singleShot(0, self.__refresh_current_feature_after_sync)
