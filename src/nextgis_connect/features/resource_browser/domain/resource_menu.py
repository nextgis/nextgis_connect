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
from typing import FrozenSet, List, Optional, Sequence, Tuple, Type, Union


class ResourceKind(Enum):
    """Identify resource capabilities without coupling to an SDK model."""

    UNKNOWN = auto()
    GROUP = auto()
    VECTOR_LAYER = auto()
    RASTER_LAYER = auto()
    POSTGIS_LAYER = auto()
    WFS_LAYER = auto()
    WFS_SERVICE = auto()
    OGCF_SERVICE = auto()
    WMS_LAYER = auto()
    WMS_SERVICE = auto()
    WMS_CONNECTION = auto()
    QGIS_VECTOR_STYLE = auto()
    QGIS_RASTER_STYLE = auto()
    RASTER_STYLE = auto()
    MAPSERVER_STYLE = auto()
    BASEMAP = auto()
    TMS_LAYER = auto()
    TMS_CONNECTION = auto()
    TILESET = auto()
    WEB_MAP = auto()
    FORM = auto()


class LayerKind(Enum):
    """Identify the active QGIS layer category relevant to menu policy."""

    NONE = auto()
    VECTOR = auto()
    RASTER = auto()


class ResourceMenuAction(Enum):
    """Identify commands exposed by the resource tree context menu."""

    ADD_TO_QGIS = auto()
    ADD_MVT_LAYER = auto()
    ADD_TMS_LAYER = auto()
    ADD_EXPERIMENTAL_NGW_LAYER = auto()
    UPLOAD_SELECTED = auto()
    UPLOAD_PROJECT = auto()
    UPDATE_STYLE = auto()
    ADD_STYLE = auto()
    OPEN_IN_WEB_GIS = auto()
    VIEW_IN_BROWSER = auto()
    OPEN_LAYER_HISTORY = auto()
    EXPAND_ALL = auto()
    COLLAPSE_ALL = auto()
    DOWNLOAD_QML = auto()
    DOWNLOAD_NGFP = auto()
    COPY_STYLE = auto()
    OVERWRITE_LAYER = auto()
    DUPLICATE_RESOURCE = auto()
    CREATE_GROUP = auto()
    CREATE_VECTOR_LAYER = auto()
    CREATE_FORM = auto()
    CREATE_WEB_MAP = auto()
    CREATE_WFS_SERVICE = auto()
    CREATE_OGCF_SERVICE = auto()
    CREATE_WMS_SERVICE = auto()
    RENAME_RESOURCE = auto()
    SHOW_PROPERTIES = auto()
    DELETE_RESOURCE = auto()


class ResourceMenuSubmenuKind(Enum):
    """Identify translated submenus in the resource context menu."""

    ADD_TO_QGIS_AS = auto()
    ADD_TO_WEB_GIS = auto()
    CREATE = auto()
    TREE = auto()


class ResourceMenuSectionKind(Enum):
    """Identify a menu section by user intent rather than presentation."""

    QGIS_IMPORT = auto()
    WEB_GIS_TRANSFER = auto()
    NAVIGATION = auto()
    CONTENT = auto()
    MANAGEMENT = auto()
    DESTRUCTIVE = auto()
    TREE = auto()
    DEVELOPER = auto()


class ResourceMenuSectionLabel(Enum):
    """Identify translated labels for separator-delimited menu sections."""

    WEB_GIS_UPLOAD = auto()
    WEB_GIS_MODIFICATION = auto()
    CREATE_IN_RESOURCE = auto()
    CREATE_FOR_RESOURCE = auto()


@dataclass(frozen=True)
class ResourceTypeBinding:
    """Bind external resource types to a dependency-free resource kind."""

    resource_kind: ResourceKind
    resource_types: Tuple[Type[object], ...]
    resource_classes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceMenuItem:
    """Describe one selected resource using menu-relevant capabilities."""

    kind: ResourceKind
    is_root: bool = False
    is_preview_supported: bool = False
    is_versioning_enabled: bool = False
    has_geometry: bool = True


@dataclass(frozen=True)
class ResourceMenuContext:
    """Store the complete input used to resolve a resource menu."""

    resources: Tuple[ResourceMenuItem, ...]
    current_layer_kind: LayerKind = LayerKind.NONE
    is_developer_mode: bool = False
    has_qgis_selection: bool = False
    has_project_layers: bool = False
    can_update_style: bool = False
    can_add_style: bool = False


@dataclass(frozen=True)
class ResourceMenuSubmenuSection:
    """Describe one optional-title section inside a submenu."""

    label: ResourceMenuSectionLabel
    actions: Tuple[ResourceMenuAction, ...] = ()


@dataclass(frozen=True)
class ResourceMenuSubmenu:
    """Describe an ordered submenu and its actions."""

    kind: ResourceMenuSubmenuKind
    actions: Tuple[ResourceMenuAction, ...] = ()
    sections: Tuple[ResourceMenuSubmenuSection, ...] = ()

    def contains_action(self, action_id: ResourceMenuAction) -> bool:
        """Return whether the submenu contains the requested command."""
        return action_id in self.actions or any(
            action_id in section.actions for section in self.sections
        )

    @property
    def action_count(self) -> int:
        """Return the number of commands represented by the submenu."""
        return len(self.ordered_actions)

    @property
    def ordered_actions(self) -> Tuple[ResourceMenuAction, ...]:
        """Return every submenu command in presentation order."""
        return self.actions + tuple(
            action_id
            for section in self.sections
            for action_id in section.actions
        )


ResourceMenuEntry = Union[ResourceMenuAction, ResourceMenuSubmenu]


@dataclass(frozen=True)
class ResourceMenuSection:
    """Describe a separator-delimited section of a context menu."""

    kind: ResourceMenuSectionKind
    entries: Tuple[ResourceMenuEntry, ...] = ()

    @property
    def actions(self) -> Tuple[ResourceMenuAction, ...]:
        """Return direct commands while preserving their entry order."""
        return tuple(
            entry
            for entry in self.entries
            if isinstance(entry, ResourceMenuAction)
        )

    @property
    def submenus(self) -> Tuple[ResourceMenuSubmenu, ...]:
        """Return child menus while preserving their entry order."""
        return tuple(
            entry
            for entry in self.entries
            if isinstance(entry, ResourceMenuSubmenu)
        )

    def contains_action(self, action_id: ResourceMenuAction) -> bool:
        """Return whether this section contains the requested command."""
        return action_id in self.actions or any(
            submenu.contains_action(action_id) for submenu in self.submenus
        )


@dataclass(frozen=True)
class ResourceMenuLayout:
    """Describe a complete resource menu independently of Qt widgets."""

    sections: Tuple[ResourceMenuSection, ...] = ()

    def contains_action(self, action_id: ResourceMenuAction) -> bool:
        """Return whether the layout exposes the requested command."""
        return any(
            section.contains_action(action_id) for section in self.sections
        )


class ResourceMenuItemAdapter:
    """Adapt SDK-specific resource objects through configured type bindings."""

    def __init__(self, bindings: Sequence[ResourceTypeBinding]) -> None:
        self._bindings = tuple(bindings)

    def adapt(
        self,
        resource: object,
        *,
        is_root: bool,
        is_preview_supported: bool,
        is_versioning_enabled: bool,
        has_geometry: bool = True,
    ) -> ResourceMenuItem:
        """Return a neutral descriptor for an external resource instance."""
        return ResourceMenuItem(
            kind=self._resolve_kind(resource),
            is_root=is_root,
            is_preview_supported=is_preview_supported,
            is_versioning_enabled=is_versioning_enabled,
            has_geometry=has_geometry,
        )

    def _resolve_kind(self, resource: object) -> ResourceKind:
        resource_class = getattr(getattr(resource, "common", None), "cls", "")
        for binding in self._bindings:
            if isinstance(resource, binding.resource_types):
                return binding.resource_kind
            if resource_class in binding.resource_classes:
                return binding.resource_kind

        return ResourceKind.UNKNOWN


class ResourceMenuPolicy:
    """Resolve applicable commands and their semantic ordering."""

    _DOWNLOADABLE_KINDS: FrozenSet[ResourceKind] = frozenset(
        {
            ResourceKind.GROUP,
            ResourceKind.VECTOR_LAYER,
            ResourceKind.RASTER_LAYER,
            ResourceKind.POSTGIS_LAYER,
            ResourceKind.WFS_LAYER,
            ResourceKind.WFS_SERVICE,
            ResourceKind.OGCF_SERVICE,
            ResourceKind.WMS_LAYER,
            ResourceKind.WMS_SERVICE,
            ResourceKind.WMS_CONNECTION,
            ResourceKind.QGIS_VECTOR_STYLE,
            ResourceKind.QGIS_RASTER_STYLE,
            ResourceKind.BASEMAP,
            ResourceKind.TMS_LAYER,
            ResourceKind.TMS_CONNECTION,
            ResourceKind.TILESET,
            ResourceKind.WEB_MAP,
        }
    )
    _FEATURE_SERVICE_KINDS: FrozenSet[ResourceKind] = frozenset(
        {
            ResourceKind.VECTOR_LAYER,
            ResourceKind.POSTGIS_LAYER,
            ResourceKind.WFS_LAYER,
        }
    )
    _QGIS_STYLE_KINDS: FrozenSet[ResourceKind] = frozenset(
        {
            ResourceKind.QGIS_VECTOR_STYLE,
            ResourceKind.QGIS_RASTER_STYLE,
        }
    )
    _WEB_MAP_LAYER_KINDS: FrozenSet[ResourceKind] = frozenset(
        {
            ResourceKind.VECTOR_LAYER,
            ResourceKind.RASTER_LAYER,
            ResourceKind.WMS_LAYER,
        }
    )
    _WEB_MAP_STYLE_KINDS: FrozenSet[ResourceKind] = frozenset(
        {
            ResourceKind.QGIS_VECTOR_STYLE,
            ResourceKind.QGIS_RASTER_STYLE,
            ResourceKind.RASTER_STYLE,
            ResourceKind.MAPSERVER_STYLE,
        }
    )
    _WEB_MAP_KINDS: FrozenSet[ResourceKind] = (
        _WEB_MAP_LAYER_KINDS | _WEB_MAP_STYLE_KINDS
    )
    _WMS_ONLY_SERVICE_KINDS: FrozenSet[ResourceKind] = frozenset(
        {
            ResourceKind.RASTER_LAYER,
            ResourceKind.QGIS_VECTOR_STYLE,
            ResourceKind.QGIS_RASTER_STYLE,
        }
    )
    _ADD_TO_WEB_GIS_SECTIONS: Tuple[Tuple[ResourceMenuAction, ...], ...] = (
        (
            ResourceMenuAction.UPLOAD_SELECTED,
            ResourceMenuAction.UPLOAD_PROJECT,
        ),
        (
            ResourceMenuAction.ADD_STYLE,
            ResourceMenuAction.UPDATE_STYLE,
            ResourceMenuAction.OVERWRITE_LAYER,
        ),
    )
    _ADD_TO_WEB_GIS_ACTIONS: Tuple[ResourceMenuAction, ...] = (
        _ADD_TO_WEB_GIS_SECTIONS[0] + _ADD_TO_WEB_GIS_SECTIONS[1]
    )
    _RESOURCE_CREATION_ACTIONS: Tuple[ResourceMenuAction, ...] = (
        ResourceMenuAction.CREATE_GROUP,
        ResourceMenuAction.CREATE_VECTOR_LAYER,
    )
    _RESOURCE_IMPORT_ACTIONS: Tuple[ResourceMenuAction, ...] = (
        ResourceMenuAction.ADD_TO_QGIS,
        ResourceMenuAction.ADD_MVT_LAYER,
        ResourceMenuAction.ADD_TMS_LAYER,
        ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER,
    )
    _ALTERNATIVE_RESOURCE_IMPORT_ACTIONS: Tuple[ResourceMenuAction, ...] = (
        ResourceMenuAction.ADD_MVT_LAYER,
        ResourceMenuAction.ADD_TMS_LAYER,
        ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER,
    )
    _TREE_VIEW_ACTIONS: Tuple[ResourceMenuAction, ...] = (
        ResourceMenuAction.EXPAND_ALL,
        ResourceMenuAction.COLLAPSE_ALL,
    )

    def __init__(self, *, is_mvt_supported: bool = True) -> None:
        self._is_mvt_supported = is_mvt_supported

    @property
    def add_to_web_gis_actions(self) -> Tuple[ResourceMenuAction, ...]:
        """Return the canonical action order for Add to Web GIS menus."""
        return self._ADD_TO_WEB_GIS_ACTIONS

    @property
    def resource_creation_actions(self) -> Tuple[ResourceMenuAction, ...]:
        """Return the canonical action order for resource creation menus."""
        return self._RESOURCE_CREATION_ACTIONS

    @property
    def resource_import_actions(self) -> Tuple[ResourceMenuAction, ...]:
        """Return every command supported by Add to QGIS surfaces."""
        return self._supported_import_actions(self._RESOURCE_IMPORT_ACTIONS)

    def create_add_to_web_gis_layout(self) -> ResourceMenuLayout:
        """Return the canonical toolbar menu layout."""
        return ResourceMenuLayout(
            sections=tuple(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.WEB_GIS_TRANSFER,
                    entries=actions,
                )
                for actions in self._ADD_TO_WEB_GIS_SECTIONS
            )
        )

    def create_resource_creation_layout(self) -> ResourceMenuLayout:
        """Return the canonical resource creation toolbar layout."""
        return ResourceMenuLayout(
            sections=(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.MANAGEMENT,
                    entries=self._RESOURCE_CREATION_ACTIONS,
                ),
            )
        )

    def create_resource_import_layout(self) -> ResourceMenuLayout:
        """Return the persistent toolbar layout containing alternatives."""
        return ResourceMenuLayout(
            sections=(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.QGIS_IMPORT,
                    entries=self._supported_import_actions(
                        self._ALTERNATIVE_RESOURCE_IMPORT_ACTIONS
                    ),
                ),
            )
        )

    def available_resource_import_actions(
        self,
        context: ResourceMenuContext,
    ) -> Tuple[ResourceMenuAction, ...]:
        """Return applicable import commands in their canonical order."""
        if not self._can_add_to_qgis(context.resources):
            return ()

        return (
            ResourceMenuAction.ADD_TO_QGIS,
            *self.alternative_resource_import_actions(context),
        )

    def alternative_resource_import_actions(
        self,
        context: ResourceMenuContext,
    ) -> Tuple[ResourceMenuAction, ...]:
        """Return applicable non-default import commands."""
        if not self._can_add_to_qgis(context.resources):
            return ()

        if len(context.resources) != 1:
            return ()

        resource = context.resources[0]
        resource_kind = resource.kind
        if (
            resource_kind
            in (
                ResourceKind.VECTOR_LAYER,
                ResourceKind.POSTGIS_LAYER,
                ResourceKind.WFS_LAYER,
                ResourceKind.QGIS_VECTOR_STYLE,
            )
            and not resource.has_geometry
        ):
            return ()

        if resource_kind == ResourceKind.VECTOR_LAYER:
            actions = [
                ResourceMenuAction.ADD_MVT_LAYER,
                ResourceMenuAction.ADD_TMS_LAYER,
            ]
            if context.is_developer_mode:
                actions.append(ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER)
            return self._supported_import_actions(tuple(actions))

        if resource_kind == ResourceKind.POSTGIS_LAYER:
            return self._supported_import_actions(
                (
                    ResourceMenuAction.ADD_MVT_LAYER,
                    ResourceMenuAction.ADD_TMS_LAYER,
                )
            )

        if resource_kind == ResourceKind.WFS_LAYER:
            return self._supported_import_actions(
                (ResourceMenuAction.ADD_MVT_LAYER,)
            )

        if resource_kind == ResourceKind.QGIS_VECTOR_STYLE:
            return (ResourceMenuAction.ADD_TMS_LAYER,)

        if resource_kind == ResourceKind.QGIS_RASTER_STYLE:
            return (ResourceMenuAction.ADD_TMS_LAYER,)

        if resource_kind in (
            ResourceKind.RASTER_LAYER,
            ResourceKind.WEB_MAP,
            ResourceKind.WMS_LAYER,
        ):
            return (ResourceMenuAction.ADD_TMS_LAYER,)

        return ()

    def _supported_import_actions(
        self,
        actions: Tuple[ResourceMenuAction, ...],
    ) -> Tuple[ResourceMenuAction, ...]:
        if self._is_mvt_supported:
            return actions

        return tuple(
            action_id
            for action_id in actions
            if action_id != ResourceMenuAction.ADD_MVT_LAYER
        )

    def is_resource_import_action_available(
        self,
        context: ResourceMenuContext,
        action_id: ResourceMenuAction,
    ) -> bool:
        """Return whether an Add to QGIS command is applicable."""
        return action_id in self.available_resource_import_actions(context)

    def is_add_to_web_gis_action_available(
        self,
        context: ResourceMenuContext,
        action_id: ResourceMenuAction,
    ) -> bool:
        """Return whether an Add to Web GIS command is applicable."""
        if action_id == ResourceMenuAction.UPLOAD_SELECTED:
            return (
                self._can_upload_to_web_gis(context)
                and context.has_qgis_selection
            )
        if action_id == ResourceMenuAction.UPLOAD_PROJECT:
            return (
                self._can_upload_to_web_gis(context)
                and context.has_project_layers
            )
        if action_id == ResourceMenuAction.UPDATE_STYLE:
            return (
                context.can_update_style
                and self._can_manipulate_resource_styles(context)
            )
        if action_id == ResourceMenuAction.ADD_STYLE:
            return (
                context.can_add_style
                and self._can_manipulate_resource_styles(context)
            )
        if action_id == ResourceMenuAction.OVERWRITE_LAYER:
            return len(context.resources) == 1 and self._can_overwrite(
                context.resources[0],
                context.current_layer_kind,
            )

        return False

    def is_resource_creation_action_available(
        self,
        context: ResourceMenuContext,
        action_id: ResourceMenuAction,
    ) -> bool:
        """Return whether a resource creation command is applicable."""
        if action_id not in self._RESOURCE_CREATION_ACTIONS:
            return False

        return (
            len(context.resources) == 1
            and context.resources[0].kind == ResourceKind.GROUP
        )

    def create_layout(
        self,
        context: ResourceMenuContext,
    ) -> ResourceMenuLayout:
        """Return applicable actions grouped by user intent."""
        if len(context.resources) == 0:
            return ResourceMenuLayout()

        if len(context.resources) > 1:
            return self._create_multiple_selection_layout(context)

        return self._create_single_selection_layout(context)

    def _create_multiple_selection_layout(
        self,
        context: ResourceMenuContext,
    ) -> ResourceMenuLayout:
        sections: List[ResourceMenuSection] = []
        if self._can_add_to_qgis(context.resources):
            sections.append(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.QGIS_IMPORT,
                    entries=(ResourceMenuAction.ADD_TO_QGIS,),
                )
            )

        if all(not resource.is_root for resource in context.resources):
            sections.append(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.DESTRUCTIVE,
                    entries=(ResourceMenuAction.DELETE_RESOURCE,),
                )
            )

        sections.append(
            ResourceMenuSection(
                kind=ResourceMenuSectionKind.TREE,
                entries=(self._tree_submenu(),),
            )
        )

        return ResourceMenuLayout(sections=tuple(sections))

    def _create_single_selection_layout(
        self,
        context: ResourceMenuContext,
    ) -> ResourceMenuLayout:
        resource = context.resources[0]
        sections: List[ResourceMenuSection] = []

        qgis_import_section = self._qgis_import_section(context)
        if qgis_import_section is not None:
            sections.append(qgis_import_section)

        sections.append(self._navigation_section(resource))

        content_section = self._content_section(resource)
        if content_section is not None:
            sections.append(content_section)

        sections.append(self._management_section(resource))

        if not resource.is_root:
            sections.append(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.DESTRUCTIVE,
                    entries=(ResourceMenuAction.DELETE_RESOURCE,),
                )
            )

        sections.append(
            ResourceMenuSection(
                kind=ResourceMenuSectionKind.TREE,
                entries=(self._tree_submenu(),),
            )
        )

        if context.is_developer_mode:
            sections.append(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.DEVELOPER,
                    entries=(ResourceMenuAction.SHOW_PROPERTIES,),
                )
            )

        return ResourceMenuLayout(sections=tuple(sections))

    def _qgis_import_section(
        self,
        context: ResourceMenuContext,
    ) -> Optional[ResourceMenuSection]:
        available_actions = self.available_resource_import_actions(context)
        if len(available_actions) == 0:
            return None

        entries: List[ResourceMenuEntry] = [ResourceMenuAction.ADD_TO_QGIS]
        alternative_actions = available_actions[1:]
        if len(alternative_actions) > 0:
            entries.append(
                ResourceMenuSubmenu(
                    kind=ResourceMenuSubmenuKind.ADD_TO_QGIS_AS,
                    actions=alternative_actions,
                )
            )

        return ResourceMenuSection(
            kind=ResourceMenuSectionKind.QGIS_IMPORT,
            entries=tuple(entries),
        )

    def _navigation_section(
        self,
        resource: ResourceMenuItem,
    ) -> ResourceMenuSection:
        actions = [ResourceMenuAction.OPEN_IN_WEB_GIS]
        if resource.is_preview_supported:
            actions.append(ResourceMenuAction.VIEW_IN_BROWSER)
        if (
            resource.kind == ResourceKind.VECTOR_LAYER
            and resource.is_versioning_enabled
        ):
            actions.append(ResourceMenuAction.OPEN_LAYER_HISTORY)

        return ResourceMenuSection(
            kind=ResourceMenuSectionKind.NAVIGATION,
            entries=tuple(actions),
        )

    def _content_section(
        self,
        resource: ResourceMenuItem,
    ) -> Optional[ResourceMenuSection]:
        actions = self._content_actions(resource)
        if len(actions) == 0:
            return None

        return ResourceMenuSection(
            kind=ResourceMenuSectionKind.CONTENT,
            entries=tuple(actions),
        )

    def _management_section(
        self,
        resource: ResourceMenuItem,
    ) -> ResourceMenuSection:
        entries = (
            *self._compact_submenus(self._creation_submenus(resource)),
            *self._duplicate_actions(resource),
            ResourceMenuAction.RENAME_RESOURCE,
        )
        return ResourceMenuSection(
            kind=ResourceMenuSectionKind.MANAGEMENT,
            entries=entries,
        )

    def _content_actions(
        self,
        resource: ResourceMenuItem,
    ) -> List[ResourceMenuAction]:
        actions: List[ResourceMenuAction] = []
        if resource.kind in self._QGIS_STYLE_KINDS:
            actions.extend(
                [
                    ResourceMenuAction.DOWNLOAD_QML,
                    ResourceMenuAction.COPY_STYLE,
                ]
            )
        if resource.kind == ResourceKind.FORM:
            actions.append(ResourceMenuAction.DOWNLOAD_NGFP)

        return actions

    def _compact_submenus(
        self,
        submenus: Sequence[ResourceMenuSubmenu],
    ) -> Tuple[ResourceMenuEntry, ...]:
        entries: List[ResourceMenuEntry] = []
        for submenu in submenus:
            if submenu.action_count == 1:
                entries.append(submenu.ordered_actions[0])
                continue

            entries.append(submenu)

        return tuple(entries)

    def _tree_submenu(self) -> ResourceMenuSubmenu:
        return ResourceMenuSubmenu(
            kind=ResourceMenuSubmenuKind.TREE,
            actions=self._TREE_VIEW_ACTIONS,
        )

    def _duplicate_actions(
        self,
        resource: ResourceMenuItem,
    ) -> List[ResourceMenuAction]:
        actions: List[ResourceMenuAction] = []
        if resource.kind in (
            ResourceKind.VECTOR_LAYER,
            ResourceKind.RASTER_LAYER,
        ):
            actions.append(ResourceMenuAction.DUPLICATE_RESOURCE)

        return actions

    def _creation_submenus(
        self,
        resource: ResourceMenuItem,
    ) -> List[ResourceMenuSubmenu]:
        submenus: List[ResourceMenuSubmenu] = []
        submenu_sections = self._creation_submenu_sections(resource)
        if len(submenu_sections) > 0:
            submenus.append(
                ResourceMenuSubmenu(
                    kind=ResourceMenuSubmenuKind.CREATE,
                    sections=submenu_sections,
                )
            )

        return submenus

    def _creation_submenu_sections(
        self,
        resource: ResourceMenuItem,
    ) -> Tuple[ResourceMenuSubmenuSection, ...]:
        create_in_resource_actions: List[ResourceMenuAction] = []
        create_for_resource_actions: List[ResourceMenuAction] = []
        if resource.kind == ResourceKind.GROUP:
            create_in_resource_actions.extend(
                (
                    ResourceMenuAction.CREATE_GROUP,
                    ResourceMenuAction.CREATE_VECTOR_LAYER,
                )
            )
        if resource.kind == ResourceKind.VECTOR_LAYER:
            create_in_resource_actions.append(ResourceMenuAction.CREATE_FORM)
        if resource.kind in self._WEB_MAP_KINDS:
            create_for_resource_actions.append(
                ResourceMenuAction.CREATE_WEB_MAP
            )
        if resource.kind in self._FEATURE_SERVICE_KINDS:
            create_for_resource_actions.extend(
                [
                    ResourceMenuAction.CREATE_WFS_SERVICE,
                    ResourceMenuAction.CREATE_OGCF_SERVICE,
                    ResourceMenuAction.CREATE_WMS_SERVICE,
                ]
            )
        elif resource.kind in self._WMS_ONLY_SERVICE_KINDS:
            create_for_resource_actions.append(
                ResourceMenuAction.CREATE_WMS_SERVICE
            )

        submenu_sections: List[ResourceMenuSubmenuSection] = []
        if len(create_in_resource_actions) > 0:
            submenu_sections.append(
                ResourceMenuSubmenuSection(
                    label=ResourceMenuSectionLabel.CREATE_IN_RESOURCE,
                    actions=tuple(create_in_resource_actions),
                )
            )
        if len(create_for_resource_actions) > 0:
            submenu_sections.append(
                ResourceMenuSubmenuSection(
                    label=ResourceMenuSectionLabel.CREATE_FOR_RESOURCE,
                    actions=tuple(create_for_resource_actions),
                )
            )
        return tuple(submenu_sections)

    def _can_add_to_qgis(
        self,
        resources: Sequence[ResourceMenuItem],
    ) -> bool:
        return len(resources) > 0 and all(
            not resource.is_root and resource.kind in self._DOWNLOADABLE_KINDS
            for resource in resources
        )

    def _can_manipulate_resource_styles(
        self,
        context: ResourceMenuContext,
    ) -> bool:
        if len(context.resources) != 1:
            return False

        return context.resources[0].has_geometry

    def _can_upload_to_web_gis(
        self,
        context: ResourceMenuContext,
    ) -> bool:
        return (
            len(context.resources) == 1
            and context.resources[0].kind == ResourceKind.GROUP
        )

    def _can_overwrite(
        self,
        resource: ResourceMenuItem,
        current_layer_kind: LayerKind,
    ) -> bool:
        return (
            resource.kind == ResourceKind.VECTOR_LAYER
            and current_layer_kind == LayerKind.VECTOR
        ) or (
            resource.kind == ResourceKind.RASTER_LAYER
            and current_layer_kind == LayerKind.RASTER
        )
