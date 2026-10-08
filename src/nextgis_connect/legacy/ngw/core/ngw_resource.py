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

import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set

from qgis.core import QgsFeedback

from nextgis_connect.features.search.domain.resource_blueprint import (
    ResourceBlueprintLabelParser,
)
from nextgis_connect.legacy.ngw.resources.utils import generate_unique_name
from nextgis_connect.platform.logging import logger

if TYPE_CHECKING:
    from nextgis_connect.legacy.ngw.qgis.qgis_ngw_connection import (
        QgsNgwConnection,
    )

ICONS_DIR = Path(__file__).parents[3] / "assets" / "icons" / "ngw_resources"


def API_RESOURCE_URL(res_id: int) -> str:
    return f"/api/resource/{res_id}"


API_COLLECTION_URL = "/api/resource/"
API_RESOURCE_BLUEPRINT_URL = "/api/component/resource/blueprint"


def RESOURCE_URL(res_id: int) -> str:
    return f"/resource/{res_id}"


def API_LAYER_EXTENT(res_id: int) -> str:
    return f"/api/resource/{res_id}/extent"


class Wrapper:
    def __init__(self, **params):
        self.__dict__.update(params)

    if TYPE_CHECKING:

        def __setattr__(self, __name: str, __value: Any, /) -> None: ...

        def __getattr__(self, __name: str, /) -> Any: ...


def dict_to_object(d):
    return Wrapper(**d)


def list_dict_to_list_object(list_dict):
    return [Wrapper(**el) for el in list_dict]


@dataclass(frozen=True)
class NGWResourceDeleteSummary:
    count: int
    resources: Dict[str, int]

    @classmethod
    def empty(cls) -> "NGWResourceDeleteSummary":
        return cls(count=0, resources={})

    @classmethod
    def from_json(cls, data: Any) -> "NGWResourceDeleteSummary":
        if not isinstance(data, dict):
            return cls.empty()

        resources: Dict[str, int] = {}
        raw_resources = data.get("resources", {})
        if isinstance(raw_resources, dict):
            for resource_class, resource_count in raw_resources.items():
                if not isinstance(resource_class, str):
                    continue

                count = cls._int_value(resource_count)
                if count <= 0:
                    continue

                resources[resource_class] = count

        count = cls._int_value(data.get("count"))
        if count <= 0 and len(resources) > 0:
            count = sum(resources.values())

        return cls(count=count, resources=resources)

    @staticmethod
    def _int_value(value: Any) -> int:
        if isinstance(value, bool):
            return 0

        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


@dataclass(frozen=True)
class NGWResourceDeletePreview:
    affected: NGWResourceDeleteSummary
    unaffected: NGWResourceDeleteSummary
    resource_labels: Dict[str, str]

    @classmethod
    def empty(cls) -> "NGWResourceDeletePreview":
        return cls(
            affected=NGWResourceDeleteSummary.empty(),
            unaffected=NGWResourceDeleteSummary.empty(),
            resource_labels={},
        )

    @classmethod
    def from_json(cls, data: Any) -> "NGWResourceDeletePreview":
        if not isinstance(data, dict):
            return cls.empty()

        return cls(
            affected=NGWResourceDeleteSummary.from_json(data.get("affected")),
            unaffected=NGWResourceDeleteSummary.from_json(
                data.get("unaffected")
            ),
            resource_labels={},
        )

    def with_resource_labels(
        self,
        resource_labels: Dict[str, str],
    ) -> "NGWResourceDeletePreview":
        return NGWResourceDeletePreview(
            affected=self.affected,
            unaffected=self.unaffected,
            resource_labels=dict(resource_labels),
        )


class NGWResource:
    type_id = "resource"
    icon_path = str(ICONS_DIR / "resource.svg")
    type_title = "NGW Resource"

    res_factory: Any  # NGWResourceFactory

    # STATIC
    @classmethod
    def receive_resource_obj(
        cls,
        ngw_con,
        res_id,
        *,
        feedback: Optional[QgsFeedback] = None,
    ) -> Dict[str, Any]:
        """
        :rtype : json obj
        """
        return ngw_con.get(API_RESOURCE_URL(res_id), feedback=feedback)

    @classmethod
    def receive_resource_children(
        cls,
        ngw_con,
        res_id,
        *,
        feedback: Optional[QgsFeedback] = None,
    ):
        """
        :rtype : json obj
        """

        logger.debug(f"↓ Fetch children for id={res_id}")
        return ngw_con.get(
            f"{API_COLLECTION_URL}?parent={res_id}",
            feedback=feedback,
        )

    @classmethod
    def delete_resource(cls, ngw_resource):
        ngw_con = ngw_resource.res_factory.connection
        url = API_RESOURCE_URL(ngw_resource.resource_id)
        ngw_con.delete(url)

    @classmethod
    def delete_resources(
        cls, ngw_resources: Sequence["NGWResource"]
    ) -> List["NGWResource"]:
        resources_to_delete = cls._extract_deletion_roots(ngw_resources)
        if not resources_to_delete:
            return []

        resource_ids = [
            ngw_resource.resource_id for ngw_resource in resources_to_delete
        ]
        resources_query = ",".join(
            str(resource_id) for resource_id in resource_ids
        )
        ngw_con = resources_to_delete[0].res_factory.connection
        if ngw_con is None:
            return []

        ngw_con.post(
            f"{API_COLLECTION_URL}delete?resources={resources_query}"
            "&partial=true",
            params={"resources": resources_query, "partial": "true"},
        )

        return resources_to_delete

    @classmethod
    def simulate_delete_resources(
        cls,
        ngw_resources: Sequence["NGWResource"],
        *,
        feedback: Optional[QgsFeedback] = None,
    ) -> NGWResourceDeletePreview:
        resources_to_delete = cls._extract_deletion_roots(ngw_resources)
        if not resources_to_delete:
            return NGWResourceDeletePreview.empty()

        resource_ids = [
            ngw_resource.resource_id for ngw_resource in resources_to_delete
        ]
        resources_query = ",".join(
            str(resource_id) for resource_id in resource_ids
        )
        ngw_con = resources_to_delete[0].res_factory.connection
        if ngw_con is None:
            return NGWResourceDeletePreview.empty()

        response = ngw_con.get(
            f"{API_COLLECTION_URL}delete?resources={resources_query}",
            feedback=feedback,
        )

        preview = NGWResourceDeletePreview.from_json(response)
        try:
            resource_labels = cls.receive_resource_blueprint_labels(
                ngw_con,
                feedback=feedback,
            )
        except Exception:
            logger.exception("Can't fetch resource blueprint labels")
            resource_labels = {}

        return preview.with_resource_labels(resource_labels)

    @classmethod
    def receive_resource_blueprint_labels(
        cls,
        ngw_con,
        *,
        feedback: Optional[QgsFeedback] = None,
    ) -> Dict[str, str]:
        response = ngw_con.get(API_RESOURCE_BLUEPRINT_URL, feedback=feedback)
        return ResourceBlueprintLabelParser().parse(response)

    @classmethod
    def _extract_deletion_roots(
        cls, ngw_resources: Sequence["NGWResource"]
    ) -> List["NGWResource"]:
        resources_by_id: Dict[int, NGWResource] = {}
        for ngw_resource in ngw_resources:
            if ngw_resource.resource_id == 0:
                continue

            resources_by_id.setdefault(ngw_resource.resource_id, ngw_resource)

        resource_ids = set(resources_by_id)
        return [
            ngw_resource
            for ngw_resource in resources_by_id.values()
            if not cls._has_selected_parent(ngw_resource, resource_ids)
        ]

    @classmethod
    def _has_selected_parent(
        cls, ngw_resource: "NGWResource", resource_ids: Set[int]
    ) -> bool:
        parent = getattr(ngw_resource.common, "parent", None)
        while parent:
            parent_id = cls._parent_value(parent, "id")
            if parent_id != 0 and parent_id in resource_ids:
                return True

            parent = cls._parent_value(parent, "parent")

        return False

    @staticmethod
    def _parent_value(parent: Any, name: str) -> Any:
        if isinstance(parent, dict):
            return parent.get(name)

        return getattr(parent, name, None)

    # INSTANCE
    def __init__(self, resource_factory, resource_json):
        """
        Init resource from json representation
        :param ngw_resource: any ngw_resource
        """
        self.res_factory = resource_factory
        self._json = resource_json
        self._construct()
        self.children_count = None

        icon_path = ICONS_DIR / f"{self.common.cls}.svg"
        if icon_path.exists():
            self.icon_path = str(icon_path)
        else:
            icon_path = ICONS_DIR / f"{self.type_id}.svg"
            if icon_path.exists():
                self.icon_path = str(icon_path)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"<{class_name}: {self.display_name} ({self.common.cls}, id={self.resource_id})>"

    def set_children_count(self, children_count):
        self.children_count = children_count

    def _construct(self):
        """
        Construct resource from self._json
        Can be overridden in a derived class
        """
        # resource
        self.common = dict_to_object(self._json["resource"])
        if self.common.parent:
            self.common.parent = dict_to_object(self.common.parent)
        if self.common.owner_user:
            self.common.owner_user = dict_to_object(self.common.owner_user)
        # resmeta
        if "resmeta" in self._json:
            self.metadata = dict_to_object(self._json["resmeta"])

    def get_parent(self):
        if self.common.parent:
            return self.res_factory.get_resource(self.parent_id)
        else:
            return None

    def get_children(
        self,
        *,
        feedback: Optional[QgsFeedback] = None,
    ) -> List["NGWResource"]:
        if not self.common.children:
            return []

        children_json = NGWResource.receive_resource_children(
            self.res_factory.connection,
            self.resource_id,
            feedback=feedback,
        )
        children: List[NGWResource] = []
        for child_json in children_json:
            children.append(self.res_factory.get_resource_by_json(child_json))
        return children

    def get_absolute_url(self) -> str:
        base_url = self.res_factory.connection.server_url
        return urllib.parse.urljoin(base_url, RESOURCE_URL(self.resource_id))

    def get_absolute_api_url(self) -> str:
        base_url = self.res_factory.connection.server_url
        return urllib.parse.urljoin(
            base_url, API_RESOURCE_URL(self.resource_id)
        )

    def get_absolute_vsicurl_url(self) -> str:
        return f"/vsicurl/{self.get_absolute_api_url()}"

    def get_relative_url(self) -> str:
        return RESOURCE_URL(self.resource_id)

    def get_relative_api_url(self) -> str:
        return API_RESOURCE_URL(self.resource_id)

    @property
    def connection_id(self) -> str:
        return self.res_factory.connection.connection_id

    @property
    def connection(self) -> "QgsNgwConnection":
        return self.res_factory.connection

    @classmethod
    def get_api_collection_url(cls) -> str:
        return API_COLLECTION_URL

    @property
    def parent_id(self) -> int:
        return self.common.parent.id

    @property
    def grandparent_id(self) -> int:
        return self.common.parent.parent["id"]

    @property
    def resource_id(self) -> int:
        return self.common.id

    @property
    def display_name(self) -> str:
        return self.common.display_name

    @property
    def description(self) -> str:
        return self.common.description

    @property
    def is_preview_supported(self) -> bool:
        return self.type_id in (
            "raster_layer",
            "basemap_layer",
            "webmap",
            "gallery",
        ) or any(
            context
            in (
                "IFeatureLayer",
                "IRenderableStyle",
                "RasterLayer",
                "BasemapLayer",
            )
            for context in self.common.interfaces
        )

    @property
    def preview_url(self):
        return f"{self.get_absolute_url()}/preview"

    def change_name(self, name):
        new_name = self.generate_unique_child_name(name)
        params = dict(
            resource=dict(
                display_name=new_name,
            ),
        )

        connection = self.res_factory.connection
        url = self.get_relative_api_url()
        connection.put(url, params=params)
        self.update()

    def move_to(self, parent: "NGWResource") -> None:
        if self.connection.server_url.rstrip(
            "/"
        ) != parent.connection.server_url.rstrip("/"):
            raise ValueError("Resources belong to different Web GIS servers")
        if parent.common.cls != "resource_group" or self.resource_id == 0:
            raise ValueError(
                "Resources can only be moved into a resource group"
            )

        self.update(skip_children=True)
        current_parent = self.get_parent()
        if current_parent is None or current_parent.common.cls not in (
            "resource_group",
            "demo_project",
        ):
            raise ValueError(
                "Only children of groups or demo projects can be moved"
            )
        ancestor = parent
        visited = set()
        while ancestor is not None:
            if (
                ancestor.resource_id == self.resource_id
                or ancestor.resource_id in visited
            ):
                raise ValueError(
                    "A resource cannot be moved into its descendants"
                )
            visited.add(ancestor.resource_id)
            ancestor = ancestor.get_parent()

        self.connection.put(
            self.get_relative_api_url(),
            params={"resource": {"parent": {"id": parent.resource_id}}},
        )
        self.common.parent = dict_to_object({"id": parent.resource_id})
        self._json["resource"]["parent"] = {"id": parent.resource_id}

    def update_metadata(self, metadata):
        params = dict(
            resmeta=dict(
                items=metadata,
            ),
        )

        connection = self.res_factory.connection
        url = self.get_relative_api_url()
        connection.put(url, params=params)
        self.update()

    def update(
        self,
        *,
        skip_children: bool = False,
        feedback: Optional[QgsFeedback] = None,
    ):
        self._json = self.receive_resource_obj(
            self.res_factory.connection,
            self.resource_id,
            feedback=feedback,
        )

        self._construct()

        if not skip_children:
            children = self.get_children(feedback=feedback)
            self.set_children_count(len(children))

    def generate_unique_child_name(self, name: str) -> str:
        chd_names = [ch.display_name for ch in self.get_children()]
        return generate_unique_name(name, chd_names)
