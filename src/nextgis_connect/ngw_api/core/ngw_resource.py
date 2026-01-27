"""
/***************************************************************************
    NextGIS WEB API
                              -------------------
        begin                : 2014-11-19
        git sha              : $Format:%H$
        copyright            : (C) 2014 by NextGIS
        email                : info@nextgis.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from nextgis_connect.logging import logger
from nextgis_connect.resources.utils import generate_unique_name

if TYPE_CHECKING:
    from nextgis_connect.ngw_api.qgis.qgis_ngw_connection import (
        QgsNgwConnection,
    )

ICONS_DIR = Path(__file__).parents[1] / "icons"


def API_RESOURCE_URL(res_id: int) -> str:
    return f"/api/resource/{res_id}"


API_COLLECTION_URL = "/api/resource/"


def RESOURCE_URL(res_id: int) -> str:
    return f"/resource/{res_id}"


def API_LAYER_EXTENT(res_id: int) -> str:
    return f"/api/resource/{res_id}/extent"


class Wrapper:
    def __init__(self, **params):
        self.__dict__.update(params)

    if TYPE_CHECKING:

        def __setattr__(self, __name: str, __value: Any) -> None: ...

        def __getattr__(self, __name: str) -> Any: ...


def dict_to_object(d):
    return Wrapper(**d)


def list_dict_to_list_object(list_dict):
    return [Wrapper(**el) for el in list_dict]


class NGWResource:
    type_id = "resource"
    icon_path = str(ICONS_DIR / "resource.svg")
    type_title = "NGW Resource"

    res_factory: Any  # NGWResourceFactory

    # STATIC
    @classmethod
    def receive_resource_obj(cls, ngw_con, res_id) -> Dict[str, Any]:
        """
        :rtype : json obj
        """
        return ngw_con.get(API_RESOURCE_URL(res_id))

    @classmethod
    def receive_resource_children(cls, ngw_con, res_id):
        """
        :rtype : json obj
        """

        logger.debug(f"↓ Fetch children for id={res_id}")
        return ngw_con.get(f"{API_COLLECTION_URL}?parent={res_id}")

    @classmethod
    def delete_resource(cls, ngw_resource):
        ngw_con = ngw_resource.res_factory.connection
        url = API_RESOURCE_URL(ngw_resource.resource_id)
        ngw_con.delete(url)

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

    def get_children(self) -> List["NGWResource"]:
        if not self.common.children:
            return []

        children_json = NGWResource.receive_resource_children(
            self.res_factory.connection, self.resource_id
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

    def update(self, *, skip_children: bool = False):
        self._json = self.receive_resource_obj(
            self.res_factory.connection, self.resource_id
        )

        self._construct()

        if not skip_children:
            children = self.get_children()
            self.set_children_count(len(children))

    def generate_unique_child_name(self, name: str) -> str:
        chd_names = [ch.display_name for ch in self.get_children()]
        return generate_unique_name(name, chd_names)
