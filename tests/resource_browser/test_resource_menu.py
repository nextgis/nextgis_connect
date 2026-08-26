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

from typing import Set

from qgis import core as qgis_core
from qgis.PyQt.QtGui import QIcon, QPalette
from qgis.PyQt.QtWidgets import QLabel, QMenu, QWidget

from nextgis_connect.features.resource_browser.domain import (
    LayerKind,
    ResourceKind,
    ResourceMenuAction,
    ResourceMenuContext,
    ResourceMenuItem,
    ResourceMenuItemAdapter,
    ResourceMenuLayout,
    ResourceMenuPolicy,
    ResourceMenuSection,
    ResourceMenuSectionKind,
    ResourceMenuSectionLabel,
    ResourceMenuSubmenu,
    ResourceMenuSubmenuKind,
    ResourceMenuSubmenuSection,
    ResourceTypeBinding,
)
from nextgis_connect.features.resource_browser.presentation import (
    resource_context_menu,
)
from nextgis_connect.features.resource_browser.presentation.resource_context_menu import (
    ResourceContextMenuController,
    ResourceContextMenuFactory,
    ResourceMenuSectionAction,
)
from nextgis_connect.platform.qgis.compat import is_mvt_supported
from nextgis_connect.ui_kit.graphics import mix_colors


class _Resource:
    pass


class _VectorResource(_Resource):
    pass


class _FormResource(_Resource):
    def __init__(self) -> None:
        self.common = type("Common", (), {"cls": "formbuilder_form"})()


class TestResourceMenuItemAdapter:
    def test_maps_external_types_without_domain_dependency(self) -> None:
        adapter = ResourceMenuItemAdapter(
            (
                ResourceTypeBinding(
                    ResourceKind.VECTOR_LAYER,
                    (_VectorResource,),
                ),
            )
        )

        item = adapter.adapt(
            _VectorResource(),
            is_root=False,
            is_preview_supported=True,
            is_versioning_enabled=True,
        )

        assert item == ResourceMenuItem(
            kind=ResourceKind.VECTOR_LAYER,
            is_preview_supported=True,
            is_versioning_enabled=True,
        )

    def test_maps_geometry_capability(self) -> None:
        adapter = ResourceMenuItemAdapter(
            (
                ResourceTypeBinding(
                    ResourceKind.VECTOR_LAYER,
                    (_VectorResource,),
                ),
            )
        )

        item = adapter.adapt(
            _VectorResource(),
            is_root=False,
            is_preview_supported=False,
            is_versioning_enabled=False,
            has_geometry=False,
        )

        assert item.has_geometry is False

    def test_uses_unknown_kind_for_unregistered_type(self) -> None:
        adapter = ResourceMenuItemAdapter(())

        item = adapter.adapt(
            _Resource(),
            is_root=True,
            is_preview_supported=False,
            is_versioning_enabled=False,
        )

        assert item.kind == ResourceKind.UNKNOWN
        assert item.is_root is True

    def test_maps_external_resource_class_without_sdk_type(self) -> None:
        adapter = ResourceMenuItemAdapter(
            (
                ResourceTypeBinding(
                    ResourceKind.FORM,
                    (),
                    ("formbuilder_form",),
                ),
            )
        )

        item = adapter.adapt(
            _FormResource(),
            is_root=False,
            is_preview_supported=False,
            is_versioning_enabled=False,
        )

        assert item.kind == ResourceKind.FORM


class TestResourceMenuPolicy:
    def test_orders_vector_layer_actions_by_user_intent(self) -> None:
        context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(
                    kind=ResourceKind.VECTOR_LAYER,
                    is_preview_supported=True,
                    is_versioning_enabled=True,
                ),
            ),
            current_layer_kind=LayerKind.VECTOR,
            is_developer_mode=True,
            has_qgis_selection=True,
            has_project_layers=True,
            can_update_style=True,
            can_add_style=True,
        )

        layout = ResourceMenuPolicy().create_layout(context)

        assert layout.sections[0].actions == (ResourceMenuAction.ADD_TO_QGIS,)
        assert layout.sections[0].submenus[0].kind == (
            ResourceMenuSubmenuKind.ADD_TO_QGIS_AS
        )
        assert layout.sections[0].submenus[0].actions == (
            ResourceMenuAction.ADD_MVT_LAYER,
            ResourceMenuAction.ADD_TMS_LAYER,
            ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER,
        )
        assert layout.sections[1].actions == (
            ResourceMenuAction.OPEN_IN_WEB_GIS,
            ResourceMenuAction.VIEW_IN_BROWSER,
            ResourceMenuAction.OPEN_LAYER_HISTORY,
        )
        assert layout.sections[2].submenus[0].kind == (
            ResourceMenuSubmenuKind.CREATE
        )
        assert layout.sections[2].submenus[0].sections == (
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_IN_RESOURCE,
                actions=(ResourceMenuAction.CREATE_FORM,),
            ),
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_FOR_RESOURCE,
                actions=(
                    ResourceMenuAction.CREATE_WEB_MAP,
                    ResourceMenuAction.CREATE_WFS_SERVICE,
                    ResourceMenuAction.CREATE_OGCF_SERVICE,
                    ResourceMenuAction.CREATE_WMS_SERVICE,
                ),
            ),
        )
        assert layout.sections[2].actions == (
            ResourceMenuAction.DUPLICATE_RESOURCE,
            ResourceMenuAction.RENAME_RESOURCE,
        )
        assert layout.sections[3].actions == (
            ResourceMenuAction.DELETE_RESOURCE,
        )
        assert layout.sections[4].submenus[0].kind == (
            ResourceMenuSubmenuKind.TREE
        )
        assert layout.sections[4].submenus[0].actions == (
            ResourceMenuAction.EXPAND_ALL,
            ResourceMenuAction.COLLAPSE_ALL,
        )
        assert layout.sections[5].actions == (
            ResourceMenuAction.SHOW_PROPERTIES,
        )
        assert tuple(section.kind for section in layout.sections) == (
            ResourceMenuSectionKind.QGIS_IMPORT,
            ResourceMenuSectionKind.NAVIGATION,
            ResourceMenuSectionKind.MANAGEMENT,
            ResourceMenuSectionKind.DESTRUCTIVE,
            ResourceMenuSectionKind.TREE,
            ResourceMenuSectionKind.DEVELOPER,
        )

    def test_form_resource_exposes_ngfp_download(self) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.FORM),)
        )

        layout = ResourceMenuPolicy().create_layout(context)

        assert layout.sections[1].actions == (
            ResourceMenuAction.DOWNLOAD_NGFP,
        )

    def test_vector_layer_creation_actions_are_grouped_by_relation(
        self,
    ) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),)
        )

        layout = ResourceMenuPolicy().create_layout(context)

        create_submenu = layout.sections[2].submenus[0]
        assert create_submenu.sections == (
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_IN_RESOURCE,
                actions=(ResourceMenuAction.CREATE_FORM,),
            ),
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_FOR_RESOURCE,
                actions=(
                    ResourceMenuAction.CREATE_WEB_MAP,
                    ResourceMenuAction.CREATE_WFS_SERVICE,
                    ResourceMenuAction.CREATE_OGCF_SERVICE,
                    ResourceMenuAction.CREATE_WMS_SERVICE,
                ),
            ),
        )

    def test_toolbar_creation_actions_are_limited_to_groups(self) -> None:
        policy = ResourceMenuPolicy()
        group_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.GROUP),)
        )
        vector_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),)
        )
        style_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.QGIS_VECTOR_STYLE),)
        )

        assert policy.is_resource_creation_action_available(
            group_context,
            ResourceMenuAction.CREATE_GROUP,
        )
        assert policy.is_resource_creation_action_available(
            group_context,
            ResourceMenuAction.CREATE_VECTOR_LAYER,
        )
        assert not policy.is_resource_creation_action_available(
            vector_context,
            ResourceMenuAction.CREATE_GROUP,
        )
        assert not policy.is_resource_creation_action_available(
            style_context,
            ResourceMenuAction.CREATE_GROUP,
        )

    def test_postgis_layer_does_not_expose_form_creation(self) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.POSTGIS_LAYER),)
        )
        policy = ResourceMenuPolicy()
        layout = policy.create_layout(context)
        create_submenu = self._first_submenu(
            layout,
            ResourceMenuSubmenuKind.CREATE,
        )

        assert create_submenu.sections == (
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_FOR_RESOURCE,
                actions=(
                    ResourceMenuAction.CREATE_WFS_SERVICE,
                    ResourceMenuAction.CREATE_OGCF_SERVICE,
                    ResourceMenuAction.CREATE_WMS_SERVICE,
                ),
            ),
        )
        assert ResourceMenuAction.CREATE_FORM not in self._all_actions(layout)

    def test_group_create_in_resource_actions_are_grouped(self) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.GROUP),)
        )

        layout = ResourceMenuPolicy().create_layout(context)

        create_submenu = self._first_submenu(
            layout,
            ResourceMenuSubmenuKind.CREATE,
        )
        assert create_submenu.sections == (
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_IN_RESOURCE,
                actions=(
                    ResourceMenuAction.CREATE_GROUP,
                    ResourceMenuAction.CREATE_VECTOR_LAYER,
                ),
            ),
        )

    def test_create_for_style_actions_are_grouped(self) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.QGIS_VECTOR_STYLE),)
        )

        layout = ResourceMenuPolicy().create_layout(context)

        assert layout.sections[3].submenus[0].sections == (
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_FOR_RESOURCE,
                actions=(
                    ResourceMenuAction.CREATE_WEB_MAP,
                    ResourceMenuAction.CREATE_WMS_SERVICE,
                ),
            ),
        )

    def test_exposes_import_variants_by_resource_kind(self) -> None:
        policy = ResourceMenuPolicy()

        alternatives_by_kind = {
            resource_kind: policy.alternative_resource_import_actions(
                ResourceMenuContext(
                    resources=(ResourceMenuItem(kind=resource_kind),),
                )
            )
            for resource_kind in (
                ResourceKind.VECTOR_LAYER,
                ResourceKind.POSTGIS_LAYER,
                ResourceKind.WFS_LAYER,
                ResourceKind.QGIS_VECTOR_STYLE,
                ResourceKind.QGIS_RASTER_STYLE,
                ResourceKind.RASTER_LAYER,
                ResourceKind.TILESET,
                ResourceKind.WEB_MAP,
                ResourceKind.WMS_LAYER,
            )
        }

        assert alternatives_by_kind == {
            ResourceKind.VECTOR_LAYER: (
                ResourceMenuAction.ADD_MVT_LAYER,
                ResourceMenuAction.ADD_TMS_LAYER,
            ),
            ResourceKind.POSTGIS_LAYER: (
                ResourceMenuAction.ADD_MVT_LAYER,
                ResourceMenuAction.ADD_TMS_LAYER,
            ),
            ResourceKind.WFS_LAYER: (ResourceMenuAction.ADD_MVT_LAYER,),
            ResourceKind.QGIS_VECTOR_STYLE: (
                ResourceMenuAction.ADD_TMS_LAYER,
            ),
            ResourceKind.QGIS_RASTER_STYLE: (
                ResourceMenuAction.ADD_TMS_LAYER,
            ),
            ResourceKind.RASTER_LAYER: (ResourceMenuAction.ADD_TMS_LAYER,),
            ResourceKind.TILESET: (),
            ResourceKind.WEB_MAP: (ResourceMenuAction.ADD_TMS_LAYER,),
            ResourceKind.WMS_LAYER: (ResourceMenuAction.ADD_TMS_LAYER,),
        }
        assert all(
            policy.available_resource_import_actions(
                ResourceMenuContext(
                    resources=(ResourceMenuItem(kind=resource_kind),),
                )
            )[0]
            == ResourceMenuAction.ADD_TO_QGIS
            for resource_kind in alternatives_by_kind
        )

    def test_hides_mvt_import_when_qgis_does_not_support_it(self) -> None:
        policy = ResourceMenuPolicy(is_mvt_supported=False)
        vector_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),),
        )
        wfs_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.WFS_LAYER),),
        )

        assert policy.alternative_resource_import_actions(vector_context) == (
            ResourceMenuAction.ADD_TMS_LAYER,
        )
        assert policy.alternative_resource_import_actions(wfs_context) == ()
        assert ResourceMenuAction.ADD_MVT_LAYER not in (
            policy.resource_import_actions
        )
        assert not policy.create_layout(vector_context).contains_action(
            ResourceMenuAction.ADD_MVT_LAYER
        )

    def test_empty_resource_selection_has_no_qgis_import_actions(self) -> None:
        policy = ResourceMenuPolicy()
        context = ResourceMenuContext(resources=())

        assert policy.available_resource_import_actions(context) == ()
        assert policy.alternative_resource_import_actions(context) == ()

    def test_experimental_import_requires_developer_mode(self) -> None:
        policy = ResourceMenuPolicy()
        regular_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),),
        )
        developer_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),),
            is_developer_mode=True,
        )

        assert ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER not in (
            policy.available_resource_import_actions(regular_context)
        )
        assert ResourceMenuAction.ADD_EXPERIMENTAL_NGW_LAYER in (
            policy.available_resource_import_actions(developer_context)
        )

    def test_no_geometry_layer_only_exposes_default_import(self) -> None:
        context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(
                    kind=ResourceKind.VECTOR_LAYER,
                    has_geometry=False,
                ),
            ),
            is_developer_mode=True,
        )
        policy = ResourceMenuPolicy()

        assert policy.available_resource_import_actions(context) == (
            ResourceMenuAction.ADD_TO_QGIS,
        )
        assert policy.alternative_resource_import_actions(context) == ()

        layout = policy.create_layout(context)
        assert layout.sections[0].actions == (ResourceMenuAction.ADD_TO_QGIS,)
        assert layout.sections[0].submenus == ()

        style_context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(
                    kind=ResourceKind.QGIS_VECTOR_STYLE,
                    has_geometry=False,
                ),
            ),
        )
        assert policy.available_resource_import_actions(style_context) == (
            ResourceMenuAction.ADD_TO_QGIS,
        )

    def test_root_group_only_exposes_safe_single_resource_actions(
        self,
    ) -> None:
        context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(
                    kind=ResourceKind.GROUP,
                    is_root=True,
                ),
            )
        )

        layout = ResourceMenuPolicy().create_layout(context)

        all_actions = self._all_actions(layout)
        assert ResourceMenuAction.ADD_TO_QGIS not in all_actions
        assert ResourceMenuAction.DELETE_RESOURCE not in all_actions
        assert layout.sections[1].submenus[0].sections == (
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_IN_RESOURCE,
                actions=(
                    ResourceMenuAction.CREATE_GROUP,
                    ResourceMenuAction.CREATE_VECTOR_LAYER,
                ),
            ),
        )

    def test_multiple_selection_only_exposes_batch_actions(self) -> None:
        context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),
                ResourceMenuItem(kind=ResourceKind.RASTER_LAYER),
            )
        )

        layout = ResourceMenuPolicy().create_layout(context)

        assert tuple(section.actions for section in layout.sections) == (
            (ResourceMenuAction.ADD_TO_QGIS,),
            (ResourceMenuAction.DELETE_RESOURCE,),
            (),
        )
        assert layout.sections[2].submenus[0].actions == (
            ResourceMenuAction.EXPAND_ALL,
            ResourceMenuAction.COLLAPSE_ALL,
        )

    def test_unsupported_batch_cannot_be_added_to_qgis(self) -> None:
        context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),
                ResourceMenuItem(kind=ResourceKind.UNKNOWN),
            )
        )

        layout = ResourceMenuPolicy().create_layout(context)

        assert tuple(section.actions for section in layout.sections) == (
            (ResourceMenuAction.DELETE_RESOURCE,),
            (),
        )
        assert layout.sections[1].submenus[0].actions == (
            ResourceMenuAction.EXPAND_ALL,
            ResourceMenuAction.COLLAPSE_ALL,
        )

    def test_qgis_style_groups_transfer_and_creation_actions(self) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.QGIS_VECTOR_STYLE),)
        )

        layout = ResourceMenuPolicy().create_layout(context)

        assert layout.sections[2].actions == (
            ResourceMenuAction.DOWNLOAD_QML,
            ResourceMenuAction.COPY_STYLE,
        )
        assert layout.sections[3].submenus[0].sections == (
            ResourceMenuSubmenuSection(
                label=ResourceMenuSectionLabel.CREATE_FOR_RESOURCE,
                actions=(
                    ResourceMenuAction.CREATE_WEB_MAP,
                    ResourceMenuAction.CREATE_WMS_SERVICE,
                ),
            ),
        )

    def test_add_to_web_gis_availability_uses_shared_context(self) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),),
            current_layer_kind=LayerKind.VECTOR,
            has_qgis_selection=True,
            has_project_layers=True,
            can_update_style=True,
            can_add_style=False,
        )
        policy = ResourceMenuPolicy()

        availability = {
            action_id: policy.is_add_to_web_gis_action_available(
                context,
                action_id,
            )
            for action_id in policy.add_to_web_gis_actions
        }

        assert availability == {
            ResourceMenuAction.UPLOAD_SELECTED: False,
            ResourceMenuAction.UPLOAD_PROJECT: False,
            ResourceMenuAction.UPDATE_STYLE: True,
            ResourceMenuAction.ADD_STYLE: False,
            ResourceMenuAction.OVERWRITE_LAYER: True,
        }

    def test_no_geometry_layer_disables_style_manipulation_actions(
        self,
    ) -> None:
        context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(
                    kind=ResourceKind.VECTOR_LAYER,
                    has_geometry=False,
                ),
            ),
            current_layer_kind=LayerKind.VECTOR,
            can_update_style=True,
            can_add_style=True,
        )
        policy = ResourceMenuPolicy()

        assert not policy.is_add_to_web_gis_action_available(
            context,
            ResourceMenuAction.UPDATE_STYLE,
        )
        assert not policy.is_add_to_web_gis_action_available(
            context,
            ResourceMenuAction.ADD_STYLE,
        )

        layout = policy.create_layout(context)
        actions = self._all_actions(layout)

        assert ResourceMenuAction.UPDATE_STYLE not in actions
        assert ResourceMenuAction.ADD_STYLE not in actions

        style_context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(
                    kind=ResourceKind.QGIS_VECTOR_STYLE,
                    has_geometry=False,
                ),
            ),
            current_layer_kind=LayerKind.VECTOR,
            can_update_style=True,
        )
        style_layout = policy.create_layout(style_context)

        assert not policy.is_add_to_web_gis_action_available(
            style_context,
            ResourceMenuAction.UPDATE_STYLE,
        )
        assert ResourceMenuAction.UPDATE_STYLE not in self._all_actions(
            style_layout
        )

    def test_resource_menu_excludes_web_gis_transfer_actions(self) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.GROUP),),
            has_qgis_selection=True,
            has_project_layers=True,
        )

        layout = ResourceMenuPolicy().create_layout(context)

        assert all(
            section.kind != ResourceMenuSectionKind.WEB_GIS_TRANSFER
            for section in layout.sections
        )
        assert ResourceMenuAction.UPLOAD_SELECTED not in self._all_actions(
            layout
        )
        assert ResourceMenuAction.UPLOAD_PROJECT not in self._all_actions(
            layout
        )

    def test_upload_to_web_gis_requires_group_target(self) -> None:
        policy = ResourceMenuPolicy()
        vector_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),),
            has_qgis_selection=True,
            has_project_layers=True,
        )
        group_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.GROUP),),
            has_qgis_selection=True,
            has_project_layers=True,
        )

        assert not policy.is_add_to_web_gis_action_available(
            vector_context,
            ResourceMenuAction.UPLOAD_SELECTED,
        )
        assert not policy.is_add_to_web_gis_action_available(
            vector_context,
            ResourceMenuAction.UPLOAD_PROJECT,
        )
        assert policy.is_add_to_web_gis_action_available(
            group_context,
            ResourceMenuAction.UPLOAD_SELECTED,
        )
        assert policy.is_add_to_web_gis_action_available(
            group_context,
            ResourceMenuAction.UPLOAD_PROJECT,
        )

    def test_single_creation_action_is_not_wrapped_in_submenu(self) -> None:
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.MAPSERVER_STYLE),)
        )

        layout = ResourceMenuPolicy().create_layout(context)
        management_section = next(
            section
            for section in layout.sections
            if section.kind == ResourceMenuSectionKind.MANAGEMENT
        )

        assert management_section.entries == (
            ResourceMenuAction.CREATE_WEB_MAP,
            ResourceMenuAction.RENAME_RESOURCE,
        )

    def _all_actions(
        self,
        layout: ResourceMenuLayout,
    ) -> Set[ResourceMenuAction]:
        actions: Set[ResourceMenuAction] = set()
        for section in layout.sections:
            actions.update(section.actions)
            for submenu in section.submenus:
                actions.update(submenu.actions)
                for submenu_section in submenu.sections:
                    actions.update(submenu_section.actions)

        return actions

    def _first_submenu(
        self,
        layout: ResourceMenuLayout,
        submenu_kind: ResourceMenuSubmenuKind,
    ) -> ResourceMenuSubmenu:
        for section in layout.sections:
            for submenu in section.submenus:
                if submenu.kind == submenu_kind:
                    return submenu

        raise AssertionError(f"Submenu not found: {submenu_kind}")


class TestResourceContextMenuFactory:
    def test_builds_ordered_sections_and_submenus(self, qgis_app) -> None:
        del qgis_app
        parent = QWidget()
        context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(
                    kind=ResourceKind.VECTOR_LAYER,
                    is_preview_supported=True,
                ),
            ),
            current_layer_kind=LayerKind.VECTOR,
            has_qgis_selection=True,
            has_project_layers=True,
            can_update_style=True,
            can_add_style=True,
        )
        layout = ResourceMenuPolicy().create_layout(context)

        built_menu = ResourceContextMenuFactory(parent).create(layout, context)

        assert built_menu.actions[0].data() == ResourceMenuAction.ADD_TO_QGIS
        root_items = [
            "<separator>" if action.isSeparator() else action.text()
            for action in built_menu.menu.actions()
        ]
        assert root_items == [
            "Add to QGIS",
            "Add to QGIS as",
            "<separator>",
            "Open resource page",
            "View in browser",
            "<separator>",
            "Create",
            "Duplicate resource",
            "Rename",
            "<separator>",
            "Delete",
            "<separator>",
            "Tree",
        ]

        submenus = [
            action.menu()
            for action in built_menu.menu.actions()
            if action.menu() is not None
        ]
        assert all(isinstance(submenu, QMenu) for submenu in submenus)
        assert [action.text() for action in submenus[0].actions()] == [
            "MVT",
            "TMS layer",
        ]
        assert [action.text() for action in submenus[1].actions()] == [
            "Create",
            "Form",
            "Create for resource",
            "Web map",
            "WFS service",
            "OGC API - Features service",
            "WMS service",
        ]
        assert [action.text() for action in submenus[2].actions()] == [
            "Expand All",
            "Collapse All",
        ]

        parent.deleteLater()

    def test_inline_creation_action_keeps_its_intent(self, qgis_app) -> None:
        del qgis_app
        parent = QWidget()
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.MAPSERVER_STYLE),)
        )
        layout = ResourceMenuPolicy().create_layout(context)

        built_menu = ResourceContextMenuFactory(parent).create(layout, context)

        assert "Create Web map" in (
            action.text() for action in built_menu.menu.actions()
        )

        parent.deleteLater()

    def test_controller_finds_actions_in_labeled_submenu_sections(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        controller = ResourceContextMenuController(parent)
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),)
        )

        assert controller.is_action_available(
            context,
            ResourceMenuAction.CREATE_FORM,
        )

        parent.deleteLater()

    def test_single_submenu_section_does_not_show_separator_label(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        layout = ResourceMenuLayout(
            sections=(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.WEB_GIS_TRANSFER,
                    entries=(
                        ResourceMenuSubmenu(
                            kind=ResourceMenuSubmenuKind.ADD_TO_WEB_GIS,
                            sections=(
                                ResourceMenuSubmenuSection(
                                    label=(
                                        ResourceMenuSectionLabel.WEB_GIS_UPLOAD
                                    ),
                                    actions=(
                                        ResourceMenuAction.UPLOAD_SELECTED,
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

        built_menu = ResourceContextMenuFactory(parent).create(layout)
        submenu = built_menu.menu.actions()[0].menu()

        assert submenu is not None
        assert [action.text() for action in submenu.actions()] == [
            "Upload selected",
        ]

        parent.deleteLater()

    def test_section_labels_use_theme_derived_muted_color(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        plain_menu = QMenu(parent)
        layout = ResourceMenuLayout(
            sections=(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.WEB_GIS_TRANSFER,
                    entries=(
                        ResourceMenuSubmenu(
                            kind=ResourceMenuSubmenuKind.ADD_TO_WEB_GIS,
                            sections=(
                                ResourceMenuSubmenuSection(
                                    label=(
                                        ResourceMenuSectionLabel.WEB_GIS_UPLOAD
                                    ),
                                    actions=(
                                        ResourceMenuAction.UPLOAD_SELECTED,
                                    ),
                                ),
                                ResourceMenuSubmenuSection(
                                    label=(
                                        ResourceMenuSectionLabel.WEB_GIS_MODIFICATION
                                    ),
                                    actions=(
                                        ResourceMenuAction.OVERWRITE_LAYER,
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

        built_menu = ResourceContextMenuFactory(parent).create(layout)
        submenu = built_menu.menu.actions()[0].menu()

        assert submenu is not None
        section_action = submenu.actions()[0]
        assert isinstance(section_action, ResourceMenuSectionAction)
        assert section_action.text() == "Upload"
        assert not section_action.isSeparator()

        section_widget = section_action.createWidget(submenu)
        label = section_widget.findChild(
            QLabel,
            ResourceMenuSectionAction.LABEL_OBJECT_NAME,
        )
        assert label is not None

        label_color = label.palette().color(QPalette.ColorRole.WindowText)
        menu_palette = submenu.palette()
        background_color = menu_palette.color(QPalette.ColorRole.Window)
        expected_color = mix_colors(
            menu_palette.color(QPalette.ColorRole.Text),
            background_color,
            ResourceMenuSectionAction._TEXT_BACKGROUND_FACTOR,
        )
        assert label_color != menu_palette.color(QPalette.ColorRole.Text)
        assert label_color != background_color
        assert label_color == expected_color
        assert plain_menu.styleSheet() == ""

        parent.deleteLater()

    def test_add_to_qgis_toolbar_uses_contextual_default_action(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        controller = ResourceContextMenuController(parent)
        menu = controller.create_resource_import_menu()
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),),
            is_developer_mode=True,
        )

        controller.update_resource_import_actions(context)

        visible_actions = [
            action
            for action in menu.actions()
            if action.isVisible() and not action.isSeparator()
        ]
        expected_action_texts = [
            "Add to QGIS",
        ]
        if is_mvt_supported():
            expected_action_texts.append("Add as MVT")
        expected_action_texts.extend(
            (
                "Add as TMS layer",
                "Add as NextGIS Web layer (experimental)",
            )
        )
        assert [
            action.text() for action in visible_actions
        ] == expected_action_texts
        default_action = controller.default_resource_import_action(context)
        assert default_action is not None
        assert default_action.text() == "Add to QGIS"
        assert default_action in menu.actions()
        assert any(
            action.isVisible() and action.isSeparator()
            for action in menu.actions()
        )
        assert (
            controller.has_available_alternative_resource_import_actions()
            is True
        )

        parent.deleteLater()

    def test_add_to_qgis_toolbar_disables_empty_selection(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        controller = ResourceContextMenuController(parent)
        menu = controller.create_resource_import_menu()

        controller.update_resource_import_actions(
            ResourceMenuContext(resources=())
        )

        assert all(not action.isVisible() for action in menu.actions())
        assert controller.has_available_resource_import_actions() is False
        assert (
            controller.has_available_alternative_resource_import_actions()
            is False
        )

        parent.deleteLater()

    def test_add_to_qgis_toolbar_omits_unsupported_mvt_action(
        self,
        qgis_app,
        monkeypatch,
    ) -> None:
        del qgis_app
        monkeypatch.delattr(qgis_core, "QgsVectorTileLayer", raising=False)
        parent = QWidget()
        controller = ResourceContextMenuController(parent)
        menu = controller.create_resource_import_menu()
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),),
        )

        controller.update_resource_import_actions(context)

        action_ids = tuple(
            action.data()
            for action in menu.actions()
            if not action.isSeparator()
        )
        assert ResourceMenuAction.ADD_MVT_LAYER not in action_ids

        parent.deleteLater()

    def test_add_to_qgis_toolbar_keeps_default_without_alternatives(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        controller = ResourceContextMenuController(parent)
        menu = controller.create_resource_import_menu()
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.TILESET),),
        )

        controller.update_resource_import_actions(context)

        assert [
            action.text()
            for action in menu.actions()
            if action.isVisible() and not action.isSeparator()
        ] == ["Add to QGIS"]
        assert all(
            not action.isVisible()
            for action in menu.actions()
            if action.isSeparator()
        )
        default_action = controller.default_resource_import_action(context)
        assert default_action is not None
        assert default_action.text() == "Add to QGIS"
        assert default_action.isEnabled()
        assert controller.has_available_resource_import_actions() is True
        assert (
            controller.has_available_alternative_resource_import_actions()
            is False
        )

        parent.deleteLater()

    def test_add_to_qgis_toolbar_hides_no_geometry_alternatives(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        controller = ResourceContextMenuController(parent)
        menu = controller.create_resource_import_menu()
        context = ResourceMenuContext(
            resources=(
                ResourceMenuItem(
                    kind=ResourceKind.VECTOR_LAYER,
                    has_geometry=False,
                ),
            ),
            is_developer_mode=True,
        )

        controller.update_resource_import_actions(context)

        assert [
            action.text()
            for action in menu.actions()
            if action.isVisible() and not action.isSeparator()
        ] == ["Add to QGIS"]
        assert all(
            not action.isVisible()
            for action in menu.actions()
            if action.isSeparator()
        )
        assert controller.default_resource_import_action(context) is not None
        assert (
            controller.has_available_alternative_resource_import_actions()
            is False
        )

        parent.deleteLater()

    def test_toolbar_menu_uses_same_actions_and_includes_overwrite(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        controller = ResourceContextMenuController(parent)
        menu = controller.create_add_to_web_gis_menu()
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.RASTER_LAYER),),
            current_layer_kind=LayerKind.RASTER,
            has_qgis_selection=True,
            has_project_layers=True,
            can_update_style=True,
            can_add_style=True,
        )

        controller.update_add_to_web_gis_actions(context)

        menu_items = [
            "<separator>" if action.isSeparator() else action.text()
            for action in menu.actions()
        ]
        assert menu_items == [
            "Upload selected",
            "Upload all",
            "<separator>",
            "Add new style to layer",
            "Update layer style",
            "Overwrite with current layer",
        ]
        assert [
            action.isEnabled()
            for action in menu.actions()
            if not action.isSeparator()
        ] == [False, False, True, True, True]

        parent.deleteLater()

    def test_factory_uses_requested_qgis_action_icons(
        self,
        qgis_app,
        monkeypatch,
    ) -> None:
        del qgis_app
        requested_icon_names = []

        def qgis_icon_stub(icon_name: str) -> QIcon:
            requested_icon_names.append(icon_name)
            return QIcon()

        monkeypatch.setattr(
            resource_context_menu,
            "qgis_icon",
            qgis_icon_stub,
        )
        parent = QWidget()
        factory = ResourceContextMenuFactory(parent)

        for action_id in (
            ResourceMenuAction.EXPAND_ALL,
            ResourceMenuAction.COLLAPSE_ALL,
            ResourceMenuAction.RENAME_RESOURCE,
            ResourceMenuAction.DUPLICATE_RESOURCE,
        ):
            factory.create_action(action_id, parent)

        assert requested_icon_names == [
            "mActionExpandTree.svg",
            "mActionCollapseTree.svg",
            "mActionToggleEditing.svg",
            "mActionDuplicateLayer.svg",
        ]

        parent.deleteLater()

    def test_factory_uses_requested_resource_import_icons(
        self,
        qgis_app,
        monkeypatch,
    ) -> None:
        del qgis_app
        requested_icon_names = []

        def qgis_icon_stub(icon_name: str) -> QIcon:
            requested_icon_names.append(icon_name)
            return QIcon()

        monkeypatch.setattr(
            resource_context_menu,
            "qgis_icon",
            qgis_icon_stub,
        )
        parent = QWidget()
        factory = ResourceContextMenuFactory(parent)

        factory.create_action(ResourceMenuAction.ADD_MVT_LAYER, parent)
        factory.create_action(ResourceMenuAction.ADD_TMS_LAYER, parent)
        for resource_kind in (
            ResourceKind.VECTOR_LAYER,
            ResourceKind.RASTER_LAYER,
            ResourceKind.TMS_LAYER,
            ResourceKind.TILESET,
            ResourceKind.WFS_LAYER,
            ResourceKind.WMS_LAYER,
        ):
            factory.create_action(
                ResourceMenuAction.ADD_TO_QGIS,
                parent,
                ResourceMenuContext(
                    resources=(ResourceMenuItem(kind=resource_kind),),
                ),
            )
        factory.create_action(
            ResourceMenuAction.ADD_TO_QGIS,
            parent,
            ResourceMenuContext(
                resources=(
                    ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),
                    ResourceMenuItem(kind=ResourceKind.RASTER_LAYER),
                ),
            ),
        )

        assert requested_icon_names == [
            "mActionAddVectorTileLayer.svg",
            "mActionAddXyzLayer.svg",
            "mActionAddOgrLayer.svg",
            "mActionAddRasterLayer.svg",
            "mActionAddXyzLayer.svg",
            "mActionAddXyzLayer.svg",
            "mActionAddWfsLayer.svg",
            "mActionAddWmsLayer.svg",
            "mActionAddLayer.svg",
        ]

        parent.deleteLater()

    def test_context_menu_uses_contextual_default_import_icon(
        self,
        qgis_app,
        monkeypatch,
    ) -> None:
        del qgis_app
        requested_icon_names = []

        def qgis_icon_stub(icon_name: str) -> QIcon:
            requested_icon_names.append(icon_name)
            return QIcon()

        monkeypatch.setattr(
            resource_context_menu,
            "qgis_icon",
            qgis_icon_stub,
        )
        parent = QWidget()
        context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.RASTER_LAYER),)
        )
        layout = ResourceMenuPolicy().create_layout(context)

        ResourceContextMenuFactory(parent).create(layout, context)

        assert requested_icon_names[0] == "mActionAddRasterLayer.svg"

        parent.deleteLater()

    def test_factory_uses_cloud_upload_for_web_gis_menu(
        self,
        qgis_app,
        monkeypatch,
    ) -> None:
        del qgis_app
        requested_icon_names = []

        def plugin_icon_stub(icon_name: str) -> QIcon:
            requested_icon_names.append(icon_name)
            return QIcon()

        monkeypatch.setattr(
            resource_context_menu,
            "plugin_icon",
            plugin_icon_stub,
        )
        parent = QWidget()
        factory = ResourceContextMenuFactory(parent)
        layout = ResourceMenuLayout(
            sections=(
                ResourceMenuSection(
                    kind=ResourceMenuSectionKind.WEB_GIS_TRANSFER,
                    entries=(
                        ResourceMenuSubmenu(
                            kind=ResourceMenuSubmenuKind.ADD_TO_WEB_GIS,
                            actions=(ResourceMenuAction.UPLOAD_SELECTED,),
                        ),
                    ),
                ),
            ),
        )

        factory.create(layout)

        assert requested_icon_names == ["actions/cloud_upload.svg"]

        parent.deleteLater()

    def test_factory_uses_custom_material_icons_for_style_uploads(
        self,
        qgis_app,
        monkeypatch,
    ) -> None:
        del qgis_app
        requested_icon_names = []

        def material_icon_stub(icon_name: str) -> QIcon:
            requested_icon_names.append(icon_name)
            return QIcon()

        monkeypatch.setattr(
            resource_context_menu,
            "material_icon",
            material_icon_stub,
        )
        parent = QWidget()
        factory = ResourceContextMenuFactory(parent)

        factory.create_action(ResourceMenuAction.ADD_STYLE, parent)
        factory.create_action(ResourceMenuAction.UPDATE_STYLE, parent)

        assert requested_icon_names == ["add_style", "replace_style"]

        parent.deleteLater()

    def test_factory_uses_material_download_for_resource_downloads(
        self,
        qgis_app,
        monkeypatch,
    ) -> None:
        del qgis_app
        requested_icon_names = []

        def material_icon_stub(icon_name: str) -> QIcon:
            requested_icon_names.append(icon_name)
            return QIcon()

        monkeypatch.setattr(
            resource_context_menu,
            "material_icon",
            material_icon_stub,
        )
        parent = QWidget()
        factory = ResourceContextMenuFactory(parent)

        factory.create_action(ResourceMenuAction.DOWNLOAD_QML, parent)
        factory.create_action(ResourceMenuAction.DOWNLOAD_NGFP, parent)

        assert requested_icon_names == ["download", "download"]

        parent.deleteLater()

    def test_creation_toolbar_reuses_context_menu_actions(
        self,
        qgis_app,
    ) -> None:
        del qgis_app
        parent = QWidget()
        controller = ResourceContextMenuController(parent)
        menu = controller.create_resource_creation_menu()
        group_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.GROUP),),
        )

        controller.update_resource_creation_actions(group_context)

        assert [action.text() for action in menu.actions()] == [
            "Resource group",
            "NextGIS Web vector layer",
        ]
        assert all(action.isEnabled() for action in menu.actions())
        assert (
            controller.resource_creation_action(
                ResourceMenuAction.CREATE_GROUP
            )
            is menu.actions()[0]
        )
        assert (
            controller.resource_creation_action(
                ResourceMenuAction.CREATE_VECTOR_LAYER
            )
            is menu.actions()[1]
        )

        vector_context = ResourceMenuContext(
            resources=(ResourceMenuItem(kind=ResourceKind.VECTOR_LAYER),),
        )
        controller.update_resource_creation_actions(vector_context)

        assert all(not action.isEnabled() for action in menu.actions())

        parent.deleteLater()
