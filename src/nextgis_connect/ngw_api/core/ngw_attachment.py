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


def FEATURE_ATTACHMENT_URL(res_id, feature_id, attachment_id):
    return f"/api/resource/{res_id}/feature/{feature_id}/attachment/{attachment_id}"


def IMAGE_URL(res_id, feature_id, image_id):
    return f"{FEATURE_ATTACHMENT_URL(res_id, feature_id, image_id)}/image"


class NGWAttachment:
    def __init__(self, attachment_id, ngw_feature):
        self.id = attachment_id
        self.ngw_feature = ngw_feature

    def get_attachmet_url(self):
        return FEATURE_ATTACHMENT_URL(
            self.ngw_feature.ngw_vector_layer.resource_id,
            self.ngw_feature.id,
            self.id,
        )

    def unlink(self):
        self.ngw_feature.ngw_vector_layer.res_factory.connection.delete(
            self.get_attachmet_url()
        )

    def get_image_url(self):
        return IMAGE_URL(
            self.ngw_feature.ngw_vector_layer.resource_id,
            self.ngw_feature.id,
            self.id,
        )

    def get_image_full_url(self):
        base_url = (
            self.ngw_feature.ngw_vector_layer.res_factory.connection.server_url
        )
        return urllib.parse.urljoin(base_url, self.get_image_url())

    def get_image(self):
        attachment_info = (
            self.ngw_feature.ngw_vector_layer.res_factory.connection.get(
                self.get_attachmet_url()
            )
        )
        name = attachment_info["name"]
        if name is None:
            name = "image_%d" % attachment_info["id"]

        format = attachment_info["mime_type"].split("/")
        if len(format) == 2:
            format = format[1]
        else:
            format = "jpeg"

        file_contetnt = (
            self.ngw_feature.ngw_vector_layer.res_factory.connection.get(
                self.get_image_url(), is_lunkwill=True
            ).data()
        )

        return [name, format, file_contetnt]
