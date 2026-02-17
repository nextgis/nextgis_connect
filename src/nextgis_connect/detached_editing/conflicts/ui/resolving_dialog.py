from enum import IntEnum, auto
from pathlib import Path
from typing import List, Optional

from qgis.core import QgsVectorLayer
from qgis.PyQt import uic
from qgis.PyQt.QtCore import (
    QItemSelection,
    QMetaObject,
    QPoint,
    Qt,
    QUrl,
    pyqtSlot,
)
from qgis.PyQt.QtGui import QDesktopServices, QIcon, QKeyEvent
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMenu,
    QWidget,
)

from nextgis_connect.compat import GeometryType
from nextgis_connect.detached_editing.conflicts.conflict_resolution import (
    ConflictResolution,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item import (
    AttachmentDataConflictResolvingItem,
    AttachmentDeleteConflictResolvingItem,
    BaseConflictResolvingItem,
    DescriptionConflictResolvingItem,
    FeatureDataConflictResolvingItem,
    FeatureDeleteConflictResolvingItem,
)
from nextgis_connect.detached_editing.conflicts.conflict_resolving_item_extractor import (
    ConflictResolvingItemExtractor,
)
from nextgis_connect.detached_editing.conflicts.conflicts import (
    VersioningConflict,
)
from nextgis_connect.detached_editing.conflicts.conflicts_model import (
    ConflictsResolvingModel,
)
from nextgis_connect.detached_editing.conflicts.item_to_resolution_converter import (
    ItemToResolutionConverter,
)
from nextgis_connect.detached_editing.conflicts.ui.attachment_data_conflict_tab import (
    AttachmentDataConflictTab,
)
from nextgis_connect.detached_editing.conflicts.ui.attachment_delete_conflict_tab import (
    AttachmentDeleteConflictTab,
)
from nextgis_connect.detached_editing.conflicts.ui.description_conflict_tab import (
    DescriptionConflictTab,
)
from nextgis_connect.detached_editing.conflicts.ui.feature_data_conflict_tab import (
    FeatureDataConflictTab,
)
from nextgis_connect.detached_editing.conflicts.ui.feature_delete_conflict_tab import (
    FeatureDeleteConflictTab,
)
from nextgis_connect.detached_editing.utils import (
    DetachedContainerContext,
    detached_layer_uri,
)
from nextgis_connect.ngw_connection.ngw_connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.types import NgwFeatureId
from nextgis_connect.ui.icon import material_icon

WIDGET, _ = uic.loadUiType(
    str(Path(__file__).parent / "resolving_dialog_base.ui")
)

RED_COLOR = "#d65252"
YELLOW_COLOR = "#fbe94e"
GREEN_COLOR = "#7bab4d"

MARKER_SIZE = 12


class Page(IntEnum):
    WELCOME = 0
    FEATURE_DATA = auto()
    FEATURE_DELETE = auto()
    DESCRIPTION = auto()
    ATTACHMENT_DATA = auto()
    ATTACHMENT_DELETE = auto()


class ResolvingDialog(QDialog, WIDGET):
    _context: DetachedContainerContext
    _geometry_type: GeometryType
    _resolving_model: ConflictsResolvingModel
    _resolutions: List[ConflictResolution]

    _unresolved_marker_icon: QIcon
    _resolved_marker_icon: QIcon
    _feature_data_tab: FeatureDataConflictTab
    _feature_delete_tab: FeatureDeleteConflictTab
    _description_tab: DescriptionConflictTab
    _attachment_data_tab: AttachmentDataConflictTab
    _attachment_delete_tab: AttachmentDeleteConflictTab

    def __init__(
        self,
        context: DetachedContainerContext,
        conflicts: List[VersioningConflict],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._context = context
        self._geometry_type = QgsVectorLayer(
            detached_layer_uri(context), "", "ogr"
        ).geometryType()  # TODO

        self._resolutions = []

        extractor = ConflictResolvingItemExtractor(self._context)
        unresolved_items = extractor.extract(conflicts)

        self._setup_ui(unresolved_items)

    @property
    def resolutions(self) -> List[ConflictResolution]:
        return self._resolutions

    @pyqtSlot()
    def accept(self) -> None:
        converter = ItemToResolutionConverter(self._context)
        self._resolutions = converter.convert(self._resolving_model.items)
        return super().accept()

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        assert a0 is not None
        if a0.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Escape,
        ):
            a0.accept()
            return

        super().keyPressEvent(a0)

    def _setup_ui(self, items: List[BaseConflictResolvingItem]) -> None:
        self.setupUi(self)
        self.setWindowTitle(
            self.tr('Conflict resolution in layer "{}"').format(
                self._context.metadata.layer_name
            )
        )

        self._unresolved_marker_icon = material_icon(
            "fiber_manual_record", color=YELLOW_COLOR, size=MARKER_SIZE
        )
        self._resolved_marker_icon = material_icon(
            "fiber_manual_record", color=GREEN_COLOR, size=MARKER_SIZE
        )

        self._setup_feature_data_page()
        self._setup_feature_delete_page()
        self._setup_description_page()
        self._setup_attachment_data_page()
        self._setup_attachment_delete_page()
        self._setup_left_panel(items)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        # Workaround for wrong scale on points at start
        QMetaObject.invokeMethod(
            self,
            "updateSelection",
            Qt.ConnectionType.QueuedConnection,
        )

        self._validate()

    def _setup_left_panel(
        self, items: List[BaseConflictResolvingItem]
    ) -> None:
        self._resolving_model = ConflictsResolvingModel(
            self._context, items, self
        )
        self._resolving_model.dataChanged.connect(self._validate)
        self.features_view.setModel(self._resolving_model)
        self.features_view.selectAll()
        self.features_view.selectionModel().selectionChanged.connect(
            self._update_selection
        )
        self.features_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.features_view.customContextMenuRequested.connect(
            self._open_context_menu
        )

        self.apply_local_button.setIcon(material_icon("computer"))
        self.apply_local_button.clicked.connect(self._resolve_as_local)

        self.apply_remote_button.setIcon(material_icon("cloud"))
        self.apply_remote_button.clicked.connect(self._resolve_as_remote)

        apply_local_text: str = self.apply_local_button.text()
        apply_remote_text: str = self.apply_remote_button.text()
        if len(apply_local_text) > 20 or len(apply_remote_text) > 20:
            apply_remote_text = apply_remote_text.replace(" ", "\n", 2)
            apply_local_text = apply_local_text.replace(" ", "\n", 2)

            self.apply_remote_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            )
            self.apply_local_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            )
            self.apply_remote_button.setText(apply_remote_text)
            self.apply_local_button.setText(apply_local_text)

    def _setup_feature_data_page(self) -> None:
        self._feature_data_tab = FeatureDataConflictTab(
            self._unresolved_marker_icon,
            self._resolved_marker_icon,
            self._geometry_type,
            self._context.metadata.fields,
            self,
        )
        self._feature_data_tab.item_changed.connect(self._on_item_changed)
        self.stacked_widget.insertWidget(
            Page.DESCRIPTION,
            self._feature_data_tab,
        )

    def _setup_feature_delete_page(self) -> None:
        self._feature_delete_tab = FeatureDeleteConflictTab(
            self._unresolved_marker_icon,
            self._geometry_type,
            self._context.metadata.fields,
            self,
        )
        self._feature_delete_tab.item_changed.connect(self._on_item_changed)
        self.stacked_widget.insertWidget(
            Page.FEATURE_DELETE,
            self._feature_delete_tab,
        )

    def _setup_description_page(self) -> None:
        self._description_tab = DescriptionConflictTab(
            self._unresolved_marker_icon,
            self._resolved_marker_icon,
            self,
        )
        self._description_tab.item_changed.connect(self._on_item_changed)
        self.stacked_widget.insertWidget(
            Page.DESCRIPTION, self._description_tab
        )

    def _setup_attachment_data_page(self) -> None:
        self._attachment_data_tab = AttachmentDataConflictTab(
            self._unresolved_marker_icon,
            self._resolved_marker_icon,
            self,
        )
        self._attachment_data_tab.item_changed.connect(self._on_item_changed)
        self.stacked_widget.insertWidget(
            Page.ATTACHMENT_DATA,
            self._attachment_data_tab,
        )

    def _setup_attachment_delete_page(self) -> None:
        self._attachment_delete_tab = AttachmentDeleteConflictTab(
            self._unresolved_marker_icon,
            self,
        )
        self._attachment_delete_tab.item_changed.connect(self._on_item_changed)
        self.stacked_widget.insertWidget(
            Page.ATTACHMENT_DELETE,
            self._attachment_delete_tab,
        )

    @pyqtSlot(name="updateSelection")
    def _update_selection(self) -> None:
        self._on_selection_changed(QItemSelection(), QItemSelection())

    @pyqtSlot("QItemSelection", "QItemSelection", name="onSelectionChanged")
    def _on_selection_changed(
        self, selected: QItemSelection, deselected: QItemSelection
    ) -> None:
        selected_indexes = (
            self.features_view.selectionModel().selectedIndexes()
        )

        selected_count = len(selected_indexes)
        is_empty = selected_count == 0

        self.apply_local_button.setEnabled(not is_empty)
        self.apply_remote_button.setEnabled(not is_empty)

        if selected_count != 1:
            self._feature_data_tab.item = None
            self._feature_delete_tab.item = None
            self._description_tab.item = None
            self._attachment_data_tab.item = None
            self._attachment_delete_tab.item = None
            self.stacked_widget.setCurrentIndex(Page.WELCOME)
            return

        item = self._resolving_model.data(
            selected_indexes[0],
            ConflictsResolvingModel.Roles.RESOLVING_ITEM,
        )

        self._feature_data_tab.item = None
        self._feature_delete_tab.item = None
        self._description_tab.item = None
        self._attachment_data_tab.item = None
        self._attachment_delete_tab.item = None

        if isinstance(item, FeatureDataConflictResolvingItem):
            self.stacked_widget.setCurrentIndex(Page.FEATURE_DATA)
            self._feature_data_tab.item = item
            return

        if isinstance(item, FeatureDeleteConflictResolvingItem):
            self.stacked_widget.setCurrentIndex(Page.FEATURE_DELETE)
            self._feature_delete_tab.item = item
            return

        if isinstance(item, DescriptionConflictResolvingItem):
            self.stacked_widget.setCurrentIndex(Page.DESCRIPTION)
            self._description_tab.item = item
            return

        if isinstance(item, AttachmentDataConflictResolvingItem):
            self.stacked_widget.setCurrentIndex(Page.ATTACHMENT_DATA)
            self._attachment_data_tab.item = item
            return

        if isinstance(item, AttachmentDeleteConflictResolvingItem):
            self.stacked_widget.setCurrentIndex(Page.ATTACHMENT_DELETE)
            self._attachment_delete_tab.item = item
            return

        self.stacked_widget.setCurrentIndex(Page.WELCOME)

    @pyqtSlot(BaseConflictResolvingItem)
    def _on_item_changed(self, item: BaseConflictResolvingItem) -> None:
        selected_indexes = (
            self.features_view.selectionModel().selectedIndexes()
        )
        if len(selected_indexes) != 1:
            return

        selected_item = self._resolving_model.data(
            selected_indexes[0],
            ConflictsResolvingModel.Roles.RESOLVING_ITEM,
        )
        if selected_item is not item:
            return

        self._resolving_model.update_state(selected_indexes[0])

    @pyqtSlot()
    def _resolve_as_local(self) -> None:
        selected_indexes = (
            self.features_view.selectionModel().selectedIndexes()
        )
        if len(selected_indexes) == self._resolving_model.rowCount():
            self._resolving_model.resolve_all_as_local()
        else:
            for index in selected_indexes:
                self._resolving_model.resolve_as_local(index)

        self._on_selection_changed(QItemSelection(), QItemSelection())

    @pyqtSlot()
    def _resolve_as_remote(self) -> None:
        selected_indexes = (
            self.features_view.selectionModel().selectedIndexes()
        )
        if len(selected_indexes) == self._resolving_model.rowCount():
            self._resolving_model.resolve_all_as_remote()
        else:
            for index in selected_indexes:
                self._resolving_model.resolve_as_remote(index)

        self._on_selection_changed(QItemSelection(), QItemSelection())

    @pyqtSlot()
    def _validate(self) -> None:
        resolved_count = self._resolving_model.resolved_count
        total_count = self._resolving_model.rowCount()

        self.resolved_count_label.setText(
            f"({resolved_count} / {total_count})"
        )

        self.button_box.button(
            QDialogButtonBox.StandardButton.Save
        ).setEnabled(resolved_count == total_count)

    @pyqtSlot(QPoint)
    def _open_context_menu(self, point: QPoint) -> None:
        indexes = self.features_view.selectedIndexes()

        menu = QMenu(self)
        if len(indexes) == 1:
            webgis_action = menu.addAction(self.tr("Open feature in Web GIS"))
            fid = (
                indexes[0]
                .data(ConflictsResolvingModel.Roles.RESOLVING_ITEM)
                .conflict.fid
            )
            webgis_action.triggered.connect(
                lambda _, fid=fid: self._open_feature_in_web_gis(fid)
            )

            menu.addSeparator()

        menu.exec(self.features_view.viewport().mapToGlobal(point))

    def _open_feature_in_web_gis(self, feature_id: NgwFeatureId) -> None:
        connection_manager = NgwConnectionsManager()
        connection = connection_manager.connection(
            self._context.metadata.connection_id
        )
        assert connection is not None

        resource_id = self._context.metadata.resource_id

        url = QUrl(connection.url)
        url.setPath(f"/resource/{resource_id}/feature/{feature_id}")
        QDesktopServices.openUrl(url)
