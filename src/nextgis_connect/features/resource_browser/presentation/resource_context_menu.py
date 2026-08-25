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

from dataclasses import dataclass
from enum import Enum, auto
from typing import ClassVar, Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import QObject, QPoint, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QColor, QIcon, QPalette
from qgis.PyQt.QtWidgets import (
    QAction,
    QHBoxLayout,
    QLabel,
    QMenu,
    QWidget,
    QWidgetAction,
)

from nextgis_connect.features.resource_browser.domain import (
    ResourceKind,
    ResourceMenuAction,
    ResourceMenuContext,
    ResourceMenuItem,
    ResourceMenuLayout,
    ResourceMenuPolicy,
    ResourceMenuSection,
    ResourceMenuSectionKind,
    ResourceMenuSectionLabel,
    ResourceMenuSubmenu,
    ResourceMenuSubmenuKind,
)
from nextgis_connect.platform.qgis.compat import is_mvt_supported
from nextgis_connect.ui_kit.graphics import mix_colors
from nextgis_connect.ui_kit.icons import (
    NgwResourceCreationIconFactory,
    material_icon,
    plugin_icon,
    qgis_icon,
)


@dataclass(frozen=True)
class BuiltResourceContextMenu:
    """Keep a menu and the command actions created for it together."""

    menu: QMenu
    actions: Tuple[QAction, ...]


class ResourceMenuSectionAction(QWidgetAction):
    """Render a theme-aware section title inside plugin resource menus."""

    LABEL_OBJECT_NAME = "NgConnectResourceMenuSectionLabel"
    _TEXT_BACKGROUND_FACTOR = 0.5

    def __init__(self, text: str, parent: QObject) -> None:
        super().__init__(parent)
        self.setText(text)

    def createWidget(self, parent: QWidget) -> QWidget:
        """Create a menu section widget using the current menu palette."""
        widget = QWidget(parent)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(12, 5, 12, 3)
        layout.setSpacing(0)

        label = QLabel(self.text(), widget)
        label.setObjectName(self.LABEL_OBJECT_NAME)
        label.setPalette(
            self._label_palette(label.palette(), parent.palette())
        )
        layout.addWidget(label)

        return widget

    @classmethod
    def _label_palette(
        cls,
        label_palette: QPalette,
        menu_palette: QPalette,
    ) -> QPalette:
        palette = QPalette(label_palette)
        palette.setColor(
            QPalette.ColorRole.WindowText,
            cls._muted_text_color(menu_palette),
        )
        return palette

    @classmethod
    def _muted_text_color(cls, palette: QPalette) -> QColor:
        foreground_color = palette.color(QPalette.ColorRole.Text)
        background_color = palette.color(QPalette.ColorRole.Window)
        return mix_colors(
            foreground_color,
            background_color,
            cls._TEXT_BACKGROUND_FACTOR,
        )


class ResourceMenuActionTextMode(Enum):
    """Describe how much action context should be included in labels."""

    CONTEXTUAL = auto()
    CONTEXTUAL_IMPORT_OPTION = auto()
    CREATE_OPTION = auto()
    STANDALONE_IMPORT = auto()


class ResourceImportIconResolver:
    """Resolve QGIS import icons from resource import intent."""

    _GENERIC_IMPORT_ICON = "mActionAddLayer.svg"
    _VECTOR_IMPORT_ICON = "mActionAddOgrLayer.svg"
    _RASTER_IMPORT_ICON = "mActionAddRasterLayer.svg"
    _TMS_IMPORT_ICON = "mActionAddXyzLayer.svg"
    _WFS_IMPORT_ICON = "mActionAddWfsLayer.svg"
    _WMS_IMPORT_ICON = "mActionAddWmsLayer.svg"

    _VECTOR_RESOURCE_KINDS = frozenset(
        (
            ResourceKind.VECTOR_LAYER,
            ResourceKind.POSTGIS_LAYER,
            ResourceKind.QGIS_VECTOR_STYLE,
        )
    )
    _RASTER_RESOURCE_KINDS = frozenset(
        (
            ResourceKind.RASTER_LAYER,
            ResourceKind.QGIS_RASTER_STYLE,
            ResourceKind.RASTER_STYLE,
            ResourceKind.BASEMAP,
        )
    )
    _TMS_RESOURCE_KINDS = frozenset(
        (
            ResourceKind.TMS_LAYER,
            ResourceKind.TMS_CONNECTION,
            ResourceKind.TILESET,
        )
    )
    _WFS_RESOURCE_KINDS = frozenset(
        (
            ResourceKind.WFS_LAYER,
            ResourceKind.WFS_SERVICE,
            ResourceKind.OGCF_SERVICE,
        )
    )
    _WMS_RESOURCE_KINDS = frozenset(
        (
            ResourceKind.WMS_LAYER,
            ResourceKind.WMS_SERVICE,
            ResourceKind.WMS_CONNECTION,
        )
    )

    def icon(
        self,
        action_id: ResourceMenuAction,
        context: Optional[ResourceMenuContext] = None,
    ) -> QIcon:
        """Return an icon for a resource import action."""
        if action_id == ResourceMenuAction.ADD_MVT_LAYER:
            return qgis_icon("mActionAddVectorTileLayer.svg")
        if action_id == ResourceMenuAction.ADD_TMS_LAYER:
            return qgis_icon(self._TMS_IMPORT_ICON)
        if action_id == ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER:
            return qgis_icon(self._VECTOR_IMPORT_ICON)
        if action_id == ResourceMenuAction.ADD_TO_QGIS:
            return qgis_icon(self._default_import_icon_name(context))

        return QIcon()

    def _default_import_icon_name(
        self,
        context: Optional[ResourceMenuContext],
    ) -> str:
        if context is None or len(context.resources) == 0:
            return self._GENERIC_IMPORT_ICON

        icon_names = tuple(
            self._resource_import_icon_name(resource)
            for resource in context.resources
        )
        first_icon_name = icon_names[0]
        if all(icon_name == first_icon_name for icon_name in icon_names):
            return first_icon_name

        return self._GENERIC_IMPORT_ICON

    def _resource_import_icon_name(
        self,
        resource: ResourceMenuItem,
    ) -> str:
        if resource.kind in self._VECTOR_RESOURCE_KINDS:
            return self._VECTOR_IMPORT_ICON
        if resource.kind in self._RASTER_RESOURCE_KINDS:
            return self._RASTER_IMPORT_ICON
        if resource.kind in self._TMS_RESOURCE_KINDS:
            return self._TMS_IMPORT_ICON
        if resource.kind in self._WFS_RESOURCE_KINDS:
            return self._WFS_IMPORT_ICON
        if resource.kind in self._WMS_RESOURCE_KINDS:
            return self._WMS_IMPORT_ICON

        return self._GENERIC_IMPORT_ICON


class ResourceContextMenuFactory(QObject):
    """Create Qt menus from dependency-free resource menu layouts."""

    _MATERIAL_ICON_NAMES: ClassVar[Dict[ResourceMenuAction, str]] = {
        ResourceMenuAction.UPLOAD_SELECTED: "upload",
        ResourceMenuAction.UPLOAD_PROJECT: "upload_all",
        ResourceMenuAction.UPDATE_STYLE: "replace_style",
        ResourceMenuAction.ADD_STYLE: "add_style",
        ResourceMenuAction.OVERWRITE_LAYER: "sync_desktop",
        ResourceMenuAction.DOWNLOAD_QML: "download",
        ResourceMenuAction.DOWNLOAD_NGFP: "download",
    }
    _PLUGIN_ICON_NAMES: ClassVar[Dict[ResourceMenuAction, str]] = {
        ResourceMenuAction.OPEN_IN_WEB_GIS: "branding/ngw_logo.svg",
        ResourceMenuAction.VIEW_IN_BROWSER: "actions/open_map.svg",
    }
    _QGIS_ICON_NAMES: ClassVar[Dict[ResourceMenuAction, str]] = {
        ResourceMenuAction.OPEN_LAYER_HISTORY: "mIconHistory.svg",
        ResourceMenuAction.EXPAND_ALL: "mActionExpandTree.svg",
        ResourceMenuAction.COLLAPSE_ALL: "mActionCollapseTree.svg",
        ResourceMenuAction.DUPLICATE_RESOURCE: "mActionDuplicateLayer.svg",
        ResourceMenuAction.RENAME_RESOURCE: "mActionToggleEditing.svg",
        ResourceMenuAction.SHOW_PROPERTIES: "attributes.svg",
        ResourceMenuAction.DELETE_RESOURCE: "mActionDeleteSelected.svg",
    }
    _CREATION_ICON_RESOURCE_CLASSES: ClassVar[
        Dict[ResourceMenuAction, str]
    ] = {
        ResourceMenuAction.CREATE_GROUP: "resource_group",
        ResourceMenuAction.CREATE_VECTOR_LAYER: "vector_layer",
        ResourceMenuAction.CREATE_FORM: "formbuilder_form",
        ResourceMenuAction.CREATE_WEB_MAP: "webmap",
        ResourceMenuAction.CREATE_WFS_SERVICE: "wfsserver_service",
        ResourceMenuAction.CREATE_OGCF_SERVICE: "ogcfserver_service",
        ResourceMenuAction.CREATE_WMS_SERVICE: "wmsserver_service",
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._menu_parent = parent
        self._import_icon_resolver = ResourceImportIconResolver()
        self._creation_icon_factory = NgwResourceCreationIconFactory()
        self._action_texts: Dict[ResourceMenuAction, str] = {
            ResourceMenuAction.UPLOAD_SELECTED: self.tr("Upload selected"),
            ResourceMenuAction.UPLOAD_PROJECT: self.tr("Upload all"),
            ResourceMenuAction.UPDATE_STYLE: self.tr("Update layer style"),
            ResourceMenuAction.ADD_STYLE: self.tr("Add new style to layer"),
            ResourceMenuAction.OPEN_IN_WEB_GIS: self.tr("Open resource page"),
            ResourceMenuAction.VIEW_IN_BROWSER: self.tr("View in browser"),
            ResourceMenuAction.OPEN_LAYER_HISTORY: self.tr("Layer history"),
            ResourceMenuAction.EXPAND_ALL: self.tr("Expand All"),
            ResourceMenuAction.COLLAPSE_ALL: self.tr("Collapse All"),
            ResourceMenuAction.DOWNLOAD_QML: self.tr("Download as QML"),
            ResourceMenuAction.DOWNLOAD_NGFP: self.tr("Download as NGFP"),
            ResourceMenuAction.COPY_STYLE: self.tr("Copy style"),
            ResourceMenuAction.OVERWRITE_LAYER: self.tr(
                "Overwrite with current layer"
            ),
            ResourceMenuAction.DUPLICATE_RESOURCE: self.tr(
                "Duplicate resource"
            ),
            ResourceMenuAction.RENAME_RESOURCE: self.tr("Rename"),
            ResourceMenuAction.SHOW_PROPERTIES: self.tr(
                "Resource properties…"
            ),
            ResourceMenuAction.DELETE_RESOURCE: self.tr("Delete"),
        }
        self._creation_action_texts: Dict[ResourceMenuAction, str] = {
            ResourceMenuAction.CREATE_GROUP: self.tr("Resource group"),
            ResourceMenuAction.CREATE_VECTOR_LAYER: self.tr(
                "NextGIS Web vector layer"
            ),
            ResourceMenuAction.CREATE_FORM: self.tr("Form"),
            ResourceMenuAction.CREATE_WEB_MAP: self.tr("Web map"),
            ResourceMenuAction.CREATE_WFS_SERVICE: self.tr("WFS service"),
            ResourceMenuAction.CREATE_OGCF_SERVICE: self.tr(
                "OGC API - Features service"
            ),
            ResourceMenuAction.CREATE_WMS_SERVICE: self.tr("WMS service"),
        }

    def create(
        self,
        layout: ResourceMenuLayout,
        context: Optional[ResourceMenuContext] = None,
        text_mode: ResourceMenuActionTextMode = (
            ResourceMenuActionTextMode.CONTEXTUAL
        ),
    ) -> BuiltResourceContextMenu:
        """Build a context menu while preserving policy-defined ordering."""
        menu = self._create_menu(parent=self._menu_parent)
        actions: List[QAction] = []
        for section_index, section in enumerate(layout.sections):
            if section_index > 0:
                menu.addSeparator()

            for entry in section.entries:
                if isinstance(entry, ResourceMenuAction):
                    action = self.create_action(
                        entry,
                        menu,
                        context,
                        text_mode,
                    )
                    menu.addAction(action)
                    actions.append(action)
                    continue

                actions.extend(
                    self._add_submenu(menu, entry, context, text_mode)
                )

        return BuiltResourceContextMenu(menu=menu, actions=tuple(actions))

    def _add_submenu(
        self,
        parent_menu: QMenu,
        submenu_model: ResourceMenuSubmenu,
        context: Optional[ResourceMenuContext],
        text_mode: ResourceMenuActionTextMode,
    ) -> Tuple[QAction, ...]:
        submenu = self._create_menu(
            parent=parent_menu,
            title=self._submenu_text(submenu_model.kind),
        )
        submenu.setIcon(self._submenu_icon(submenu_model.kind))
        submenu.menuAction().setIconVisibleInMenu(True)
        parent_menu.addMenu(submenu)
        submenu_text_mode = self._submenu_text_mode(
            submenu_model.kind,
            text_mode,
        )
        actions: List[QAction] = []
        should_show_section_labels = len(submenu_model.sections) > 1
        for submenu_section in submenu_model.sections:
            if should_show_section_labels:
                submenu.addAction(
                    ResourceMenuSectionAction(
                        self._section_label_text(submenu_section.label),
                        submenu,
                    )
                )
            for action_id in submenu_section.actions:
                action = self.create_action(
                    action_id,
                    submenu,
                    context,
                    submenu_text_mode,
                )
                submenu.addAction(action)
                actions.append(action)

        for action_id in submenu_model.actions:
            action = self.create_action(
                action_id,
                submenu,
                context,
                submenu_text_mode,
            )
            submenu.addAction(action)
            actions.append(action)

        return tuple(actions)

    def _create_menu(
        self,
        parent: QWidget,
        title: str = "",
    ) -> QMenu:
        menu = QMenu(title, parent)
        return menu

    def create_action(
        self,
        action_id: ResourceMenuAction,
        parent: QObject,
        context: Optional[ResourceMenuContext] = None,
        text_mode: ResourceMenuActionTextMode = (
            ResourceMenuActionTextMode.CONTEXTUAL
        ),
    ) -> QAction:
        """Create one command action using the shared presentation rules."""
        action = QAction(
            self.action_icon(action_id, context),
            self._action_text(action_id, text_mode, context),
            parent,
        )
        action.setData(action_id)
        return action

    def action_icon(
        self,
        action_id: ResourceMenuAction,
        context: Optional[ResourceMenuContext] = None,
    ) -> QIcon:
        """Return one command icon using the shared presentation rules."""
        if action_id in (
            ResourceMenuAction.ADD_TO_QGIS,
            ResourceMenuAction.ADD_MVT_LAYER,
            ResourceMenuAction.ADD_TMS_LAYER,
            ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER,
        ):
            return self._import_icon_resolver.icon(action_id, context)

        return self._action_icon(action_id)

    def _action_text(
        self,
        action_id: ResourceMenuAction,
        text_mode: ResourceMenuActionTextMode,
        context: Optional[ResourceMenuContext],
    ) -> str:
        if action_id == ResourceMenuAction.ADD_TO_QGIS:
            if (
                text_mode
                == ResourceMenuActionTextMode.CONTEXTUAL_IMPORT_OPTION
            ):
                return self._default_import_option_text(context)
            return self.tr("Add to QGIS")

        import_action_texts = {
            ResourceMenuAction.ADD_MVT_LAYER: (
                self.tr("MVT"),
                self.tr("Add as MVT"),
            ),
            ResourceMenuAction.ADD_TMS_LAYER: (
                self.tr("TMS layer"),
                self.tr("Add as TMS layer"),
            ),
            ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER: (
                self.tr("NextGIS Web layer (experimental)"),
                self.tr("Add as NextGIS Web layer (experimental)"),
            ),
        }
        import_texts = import_action_texts.get(action_id)
        if import_texts is not None:
            if text_mode == ResourceMenuActionTextMode.STANDALONE_IMPORT:
                return import_texts[1]
            return import_texts[0]

        creation_text = self._creation_action_texts.get(action_id)
        if creation_text is not None:
            return self._creation_action_text(
                creation_text,
                text_mode,
            )

        try:
            return self._action_texts[action_id]
        except KeyError as error:
            raise ValueError(
                f"Unsupported resource menu action: {action_id}"
            ) from error

    def _creation_action_text(
        self,
        resource_text: str,
        text_mode: ResourceMenuActionTextMode,
    ) -> str:
        if text_mode == ResourceMenuActionTextMode.CREATE_OPTION:
            return resource_text

        return self.tr("Create {resource}").format(resource=resource_text)

    def _default_import_option_text(
        self,
        context: Optional[ResourceMenuContext],
    ) -> str:
        if context is None or len(context.resources) != 1:
            return self.tr("Default")

        resource_kind = context.resources[0].kind
        if resource_kind in (
            ResourceKind.VECTOR_LAYER,
            ResourceKind.QGIS_VECTOR_STYLE,
        ):
            return self.tr("Synchronizable layer")
        if resource_kind in (
            ResourceKind.RASTER_LAYER,
            ResourceKind.QGIS_RASTER_STYLE,
        ):
            return self.tr("Cloud Optimized GeoTIFF")
        if resource_kind == ResourceKind.WEB_MAP:
            return self.tr("Project")
        if resource_kind == ResourceKind.WMS_LAYER:
            return self.tr("WMS layer")
        if resource_kind == ResourceKind.TILESET:
            return self.tr("TMS layer")

        return self.tr("Default")

    def _action_icon(self, action_id: ResourceMenuAction) -> QIcon:
        material_icon_name = self._MATERIAL_ICON_NAMES.get(action_id)
        if material_icon_name is not None:
            return material_icon(material_icon_name)

        plugin_icon_name = self._PLUGIN_ICON_NAMES.get(action_id)
        if plugin_icon_name is not None:
            return plugin_icon(plugin_icon_name)

        qgis_icon_name = self._QGIS_ICON_NAMES.get(action_id)
        if qgis_icon_name is not None:
            return qgis_icon(qgis_icon_name)

        resource_class = self._CREATION_ICON_RESOURCE_CLASSES.get(action_id)
        if resource_class is not None:
            return self._creation_icon_factory.plugin_panel_icon(
                resource_class
            )

        return QIcon()

    def _submenu_text(self, submenu_kind: ResourceMenuSubmenuKind) -> str:
        if submenu_kind == ResourceMenuSubmenuKind.ADD_TO_QGIS_AS:
            return self.tr("Add to QGIS as")
        if submenu_kind == ResourceMenuSubmenuKind.ADD_TO_WEB_GIS:
            return self.tr("Add to Web GIS")
        if submenu_kind == ResourceMenuSubmenuKind.CREATE:
            return self.tr("Create")
        if submenu_kind == ResourceMenuSubmenuKind.TREE:
            return self.tr("Tree")

        raise ValueError(f"Unsupported resource submenu: {submenu_kind}")

    def _submenu_icon(self, submenu_kind: ResourceMenuSubmenuKind) -> QIcon:
        if submenu_kind == ResourceMenuSubmenuKind.ADD_TO_QGIS_AS:
            return plugin_icon("actions/cloud_download.svg")
        if submenu_kind == ResourceMenuSubmenuKind.ADD_TO_WEB_GIS:
            return plugin_icon("actions/cloud_upload.svg")
        if submenu_kind == ResourceMenuSubmenuKind.CREATE:
            return self._creation_icon_factory.plugin_panel_icon(
                "resource_group"
            )
        if submenu_kind == ResourceMenuSubmenuKind.TREE:
            return qgis_icon("mActionExpandTree.svg")

        return QIcon()

    def _submenu_text_mode(
        self,
        submenu_kind: ResourceMenuSubmenuKind,
        text_mode: ResourceMenuActionTextMode,
    ) -> ResourceMenuActionTextMode:
        if (
            submenu_kind == ResourceMenuSubmenuKind.ADD_TO_QGIS_AS
            and text_mode == ResourceMenuActionTextMode.CONTEXTUAL
        ):
            return ResourceMenuActionTextMode.CONTEXTUAL_IMPORT_OPTION
        if submenu_kind == ResourceMenuSubmenuKind.CREATE:
            return ResourceMenuActionTextMode.CREATE_OPTION

        return text_mode

    def _section_label_text(
        self,
        section_label: ResourceMenuSectionLabel,
    ) -> str:
        if section_label == ResourceMenuSectionLabel.WEB_GIS_UPLOAD:
            return self.tr("Upload")
        if section_label == ResourceMenuSectionLabel.WEB_GIS_MODIFICATION:
            return self.tr("Modify resource")
        if section_label == ResourceMenuSectionLabel.CREATE_IN_RESOURCE:
            return self.tr("Create")
        if section_label == ResourceMenuSectionLabel.CREATE_FOR_RESOURCE:
            return self.tr("Create for resource")

        raise ValueError(f"Unsupported resource menu section: {section_label}")


class ResourceContextMenuController(QObject):
    """Coordinate menu policy, widget creation, and command requests."""

    action_requested = pyqtSignal(object, name="actionRequested")

    def __init__(
        self,
        parent: QWidget,
        policy: Optional[ResourceMenuPolicy] = None,
        menu_factory: Optional[ResourceContextMenuFactory] = None,
    ) -> None:
        super().__init__(parent)
        self._policy = policy or ResourceMenuPolicy(
            is_mvt_supported=is_mvt_supported()
        )
        self._menu_factory = menu_factory or ResourceContextMenuFactory(parent)
        self._default_resource_import_action: Optional[QAction] = None
        self._resource_import_separator: Optional[QAction] = None
        self._resource_import_actions: Tuple[QAction, ...] = ()
        self._add_to_web_gis_actions: Tuple[QAction, ...] = ()
        self._resource_creation_actions: Tuple[QAction, ...] = ()

    def create_add_to_web_gis_menu(self) -> QMenu:
        """Create the persistent toolbar menu from the shared policy."""
        if len(self._add_to_web_gis_actions) > 0:
            raise RuntimeError("Add to Web GIS menu is already created")

        layout = self._policy.create_add_to_web_gis_layout()
        built_menu = self._menu_factory.create(layout)
        self._connect_actions(built_menu.actions)
        self._add_to_web_gis_actions = built_menu.actions
        self.set_add_to_web_gis_actions_enabled(False)
        return built_menu.menu

    def create_resource_import_menu(self) -> QMenu:
        """Create the persistent Add to QGIS toolbar menu."""
        if len(self._resource_import_actions) > 0:
            raise RuntimeError("Add to QGIS menu is already created")

        alternative_layout = self._policy.create_resource_import_layout()
        layout = ResourceMenuLayout(
            sections=(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.QGIS_IMPORT,
                    entries=(ResourceMenuAction.ADD_TO_QGIS,),
                ),
                *alternative_layout.sections,
            )
        )
        built_menu = self._menu_factory.create(
            layout,
            text_mode=ResourceMenuActionTextMode.STANDALONE_IMPORT,
        )
        default_action = built_menu.actions[0]
        self._default_resource_import_action = default_action
        self._resource_import_actions = built_menu.actions
        self._resource_import_separator = self._first_separator(
            built_menu.menu
        )
        self._connect_actions(self._resource_import_actions)
        for action in built_menu.actions[1:]:
            action.setVisible(False)
        if self._resource_import_separator is not None:
            self._resource_import_separator.setVisible(False)
        self.set_resource_import_actions_enabled(False)
        return built_menu.menu

    def create_resource_creation_menu(self) -> QMenu:
        """Create the persistent toolbar menu from the shared policy."""
        if len(self._resource_creation_actions) > 0:
            raise RuntimeError("Resource creation menu is already created")

        layout = self._policy.create_resource_creation_layout()
        built_menu = self._menu_factory.create(
            layout,
            text_mode=ResourceMenuActionTextMode.CREATE_OPTION,
        )
        self._connect_actions(built_menu.actions)
        self._resource_creation_actions = built_menu.actions
        self.set_resource_creation_actions_enabled(False)
        return built_menu.menu

    def show(
        self,
        context: ResourceMenuContext,
        global_position: QPoint,
    ) -> None:
        """Show the applicable context menu at a global position."""
        layout = self._policy.create_layout(context)
        if len(layout.sections) == 0:
            return

        built_menu = self._menu_factory.create(layout, context)
        self._connect_actions(built_menu.actions)

        built_menu.menu.exec(global_position)
        built_menu.menu.deleteLater()

    def is_action_available(
        self,
        context: ResourceMenuContext,
        action_id: ResourceMenuAction,
    ) -> bool:
        """Return whether the policy includes an action for a context."""
        if action_id in self._policy.resource_import_actions:
            return self._policy.is_resource_import_action_available(
                context,
                action_id,
            )
        if action_id in self._policy.add_to_web_gis_actions:
            return self._policy.is_add_to_web_gis_action_available(
                context,
                action_id,
            )
        if action_id in self._policy.resource_creation_actions:
            return self._policy.is_resource_creation_action_available(
                context,
                action_id,
            )

        return self._policy.create_layout(context).contains_action(action_id)

    def update_resource_import_actions(
        self,
        context: ResourceMenuContext,
    ) -> None:
        """Show and enable only applicable Add to QGIS toolbar actions."""
        available_actions = self._policy.available_resource_import_actions(
            context
        )
        has_alternative_actions = False
        for action in self._resource_import_actions:
            action_id = action.data()
            is_available = action_id in available_actions
            action.setIcon(self._menu_factory.action_icon(action_id, context))
            action.setVisible(is_available)
            action.setEnabled(is_available)
            if action_id != ResourceMenuAction.ADD_TO_QGIS and is_available:
                has_alternative_actions = True

        if self._resource_import_separator is not None:
            self._resource_import_separator.setVisible(has_alternative_actions)

    def set_resource_import_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable visible persistent Add to QGIS actions."""
        for action in self._resource_import_actions:
            action.setEnabled(enabled and action.isVisible())

    def has_available_resource_import_actions(self) -> bool:
        """Return whether the Add to QGIS toolbar has an enabled command."""
        return any(
            action.isVisible() and action.isEnabled()
            for action in self._resource_import_actions
        )

    def has_available_alternative_resource_import_actions(self) -> bool:
        """Return whether the toolbar has a visible alternative command."""
        return any(
            action.data() != ResourceMenuAction.ADD_TO_QGIS
            and action.isVisible()
            and action.isEnabled()
            for action in self._resource_import_actions
        )

    def default_resource_import_action(
        self,
        context: ResourceMenuContext,
    ) -> Optional[QAction]:
        """Return the first applicable action, which is the default mode."""
        if not self._policy.is_resource_import_action_available(
            context,
            ResourceMenuAction.ADD_TO_QGIS,
        ):
            return None

        return self._default_resource_import_action

    def resource_import_action(
        self,
        action_id: ResourceMenuAction,
    ) -> QAction:
        """Return a persistent Add to QGIS action."""
        for action in self._resource_import_actions:
            if action.data() == action_id:
                return action

        raise KeyError(f"Add to QGIS action is not registered: {action_id}")

    def update_add_to_web_gis_actions(
        self,
        context: ResourceMenuContext,
    ) -> None:
        """Apply shared availability rules to persistent toolbar actions."""
        for action in self._add_to_web_gis_actions:
            action_id = action.data()
            if not isinstance(action_id, ResourceMenuAction):
                continue

            action.setEnabled(
                self._policy.is_add_to_web_gis_action_available(
                    context,
                    action_id,
                )
            )

    def set_add_to_web_gis_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable every persistent Add to Web GIS action."""
        for action in self._add_to_web_gis_actions:
            action.setEnabled(enabled)

    def has_available_add_to_web_gis_actions(self) -> bool:
        """Return whether the persistent toolbar menu has enabled actions."""
        return any(
            action.isEnabled() for action in self._add_to_web_gis_actions
        )

    def is_add_to_web_gis_action_enabled(
        self,
        action_id: ResourceMenuAction,
    ) -> bool:
        """Return the current state of a persistent toolbar action."""
        for action in self._add_to_web_gis_actions:
            if action.data() == action_id:
                return action.isEnabled()

        return False

    def add_to_web_gis_action(
        self,
        action_id: ResourceMenuAction,
    ) -> QAction:
        """Return a persistent Add to Web GIS action."""
        for action in self._add_to_web_gis_actions:
            if action.data() == action_id:
                return action

        raise KeyError(f"Add to Web GIS action is not registered: {action_id}")

    def update_resource_creation_actions(
        self,
        context: ResourceMenuContext,
    ) -> None:
        """Apply shared availability rules to creation toolbar actions."""
        for action in self._resource_creation_actions:
            action_id = action.data()
            if not isinstance(action_id, ResourceMenuAction):
                continue

            action.setEnabled(
                self._policy.is_resource_creation_action_available(
                    context,
                    action_id,
                )
            )

    def set_resource_creation_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable every persistent resource creation action."""
        for action in self._resource_creation_actions:
            action.setEnabled(enabled)

    def has_available_resource_creation_actions(self) -> bool:
        """Return whether the resource creation menu has enabled actions."""
        return any(
            action.isEnabled() for action in self._resource_creation_actions
        )

    def resource_creation_action(
        self,
        action_id: ResourceMenuAction,
    ) -> QAction:
        """Return a persistent action used by the creation toolbar menu."""
        for action in self._resource_creation_actions:
            if action.data() == action_id:
                return action

        raise KeyError(
            f"Resource creation action is not registered: {action_id}"
        )

    def _first_separator(self, menu: QMenu) -> Optional[QAction]:
        for action in menu.actions():
            if action.isSeparator():
                return action

        return None

    def _connect_actions(self, actions: Tuple[QAction, ...]) -> None:
        for action in actions:
            action.triggered.connect(self._on_action_triggered)

    @pyqtSlot()
    def _on_action_triggered(self) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return

        action_id = action.data()
        if not isinstance(action_id, ResourceMenuAction):
            return

        self.action_requested.emit(action_id)
