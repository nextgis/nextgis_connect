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
from typing import Optional


def FEATURE_URL(res_id, feature_id):
    return f"/api/resource/{res_id:d}/feature/{feature_id:d}"


def FEATURE_ATTACHMENTS_URL(res_id, feature_id):
    return f"/api/resource/{res_id:d}/feature/{feature_id:d}/attachment/"


# Need refactoring!
class NGWFeature:
    def __init__(self, ngw_feature_dict, ngw_vector_layer):
        self.id = ngw_feature_dict.get("id")
        self.geom_wkt = ngw_feature_dict.get("geom")
        self.ngw_vector_layer = ngw_vector_layer

        self.fields = ngw_feature_dict.get("fields", {})

    def get_feature_url(self):
        return FEATURE_URL(self.ngw_vector_layer.resource_id, self.id)

    def get_feature_attachmets_url(self):
        return FEATURE_ATTACHMENTS_URL(
            self.ngw_vector_layer.resource_id, self.id
        )

    def get_attachments(self):
        return self.ngw_vector_layer.res_factory.connection.get(
            self.get_feature_attachmets_url()
        )

    def link_attachment(
        self,
        name: str,
        uploaded_file_info,
        mime_type: Optional[str] = None,
    ):
        json_data = dict(name=name, file_upload=uploaded_file_info)
        if mime_type:
            json_data["mime_type"] = mime_type
        res = self.ngw_vector_layer.res_factory.connection.post(
            self.get_feature_attachmets_url(), json=json_data
        )
        return res["id"]

    def asDict(self):
        feature_dict = {}

        if self.id is not None:
            feature_dict["id"] = self.id

        feature_dict["fields"] = self.fields
        feature_dict["geom"] = self.geom_wkt

        return feature_dict

    def setGeom(self, wkt):
        self.geom_wkt = wkt
