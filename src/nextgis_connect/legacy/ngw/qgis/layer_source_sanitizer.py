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

import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Tuple

from nextgis_connect.legacy.detached_editing import utils as detached_utils
from nextgis_connect.legacy.ngw_connection.application.connections_manager import (
    NgwConnectionsManager,
)
from nextgis_connect.platform.logging import logger
from qgis.core import (
    QgsDataSourceUri,
    QgsMapLayer,
    QgsProviderRegistry,
    QgsVectorLayer,
)


@dataclass(frozen=True)
class _NgwReference:
    base_url: str
    resource_id: int


class QgisLayerSourceSanitizer:
    """Create a safe, human-readable description of a layer source."""

    _DATABASE_SCHEMES: ClassVar[Dict[str, str]] = {
        "mssql": "mssql",
        "mysql": "mysql",
        "oracle": "oracle",
        "postgres": "postgresql",
        "postgresraster": "postgresql",
    }
    _LAYER_PARAMETERS: ClassVar[Tuple[str, ...]] = (
        "layers",
        "layer",
        "layername",
        "typename",
        "identifier",
        "coverage",
        "collection",
        "entity",
        "table",
    )
    _QGIS_PARAMETERS: ClassVar[Tuple[str, ...]] = (
        "url",
        "path",
        "baseUrl",
        "serviceUrl",
        "uri",
        "layers",
        "layer",
        "layerName",
        "typename",
        "identifier",
        "coverage",
        "collection",
        "entity",
        "table",
    )
    _URL_PARAMETERS: ClassVar[Tuple[str, ...]] = (
        "url",
        "path",
        "baseurl",
        "serviceurl",
        "uri",
    )
    _VSI_PREFIXES: ClassVar[Tuple[str, ...]] = (
        "/vsicurl_streaming/",
        "/vsicurl/",
    )

    def __init__(
        self,
        connections_manager: Optional[NgwConnectionsManager] = None,
    ) -> None:
        self._connections_manager = connections_manager

    def sanitize(self, layer: QgsMapLayer) -> Optional[str]:
        source = layer.source()
        provider_type = layer.providerType()
        parameters = self._decode_uri(provider_type, source)
        source_urls = self._source_urls(parameters, source)
        qualifier = self._ngw_qualifier(
            provider_type,
            parameters,
            source_urls,
        )

        detached_source = self._detached_source(
            layer,
            source_urls,
            qualifier,
        )
        if detached_source is not None:
            return detached_source

        ngw_source = self._ngw_source_from_properties(
            layer,
            source_urls,
            qualifier,
        )
        if ngw_source is not None:
            return ngw_source

        ngw_reference = self._ngw_reference_from_urls(source_urls)
        if ngw_reference is not None:
            resource_url = self._canonical_ngw_url(
                ngw_reference.base_url,
                ngw_reference.resource_id,
            )
            return self._add_qualifiers(resource_url, qualifier)

        external_source = self._external_source(
            provider_type,
            parameters,
            source_urls,
        )
        if external_source is not None:
            return external_source

        local_source = self._local_source(provider_type, parameters, source)
        if local_source is not None:
            return local_source

        return self._database_source(provider_type, parameters)

    def _decode_uri(
        self,
        provider_type: str,
        source: str,
    ) -> Dict[str, Any]:
        decoded: Dict[str, Any] = {}
        provider_metadata = QgsProviderRegistry.instance().providerMetadata(
            provider_type
        )
        if provider_metadata is not None:
            try:
                provider_parameters = provider_metadata.decodeUri(source)
            except Exception:
                logger.debug("Could not decode the QGIS layer source")
            else:
                if isinstance(provider_parameters, dict):
                    decoded.update(
                        {
                            str(name).lower(): value
                            for name, value in provider_parameters.items()
                        }
                    )

        data_source_uri = QgsDataSourceUri(source)
        for parameter_name in self._QGIS_PARAMETERS:
            normalized_name = parameter_name.lower()
            if normalized_name in decoded:
                continue
            value = data_source_uri.param(parameter_name)
            if value:
                decoded[normalized_name] = value

        return decoded

    def _detached_source(
        self,
        layer: QgsMapLayer,
        source_urls: Iterable[str],
        qualifier: Optional[str],
    ) -> Optional[str]:
        if not isinstance(layer, QgsVectorLayer):
            return None
        if not detached_utils.is_ngw_container(layer):
            return None

        try:
            metadata = detached_utils.container_metadata(
                detached_utils.container_path(layer)
            )
        except Exception:
            logger.debug(
                "Could not read detached layer metadata",
                exc_info=True,
            )
            return None

        connection_id = layer.customProperty("ngw_connection_id")
        if connection_id is None:
            connection_id = metadata.connection_id

        resource_url = self._ngw_resource_url(
            str(connection_id) if connection_id is not None else None,
            metadata.resource_id,
            source_urls,
        )
        if resource_url is None:
            return None

        return self._add_qualifiers(
            resource_url,
            qualifier,
            is_modified=metadata.has_changes,
        )

    def _ngw_source_from_properties(
        self,
        layer: QgsMapLayer,
        source_urls: Iterable[str],
        qualifier: Optional[str],
    ) -> Optional[str]:
        resource_id_value = layer.customProperty("ngw_resource_id")
        if resource_id_value is None or isinstance(resource_id_value, bool):
            return None

        resource_id_text = str(resource_id_value)
        if not resource_id_text.isdigit():
            return None
        resource_id = int(resource_id_text)
        if resource_id <= 0:
            return None

        connection_id_value = layer.customProperty("ngw_connection_id")
        connection_id = (
            str(connection_id_value)
            if connection_id_value is not None
            else None
        )
        resource_url = self._ngw_resource_url(
            connection_id,
            resource_id,
            source_urls,
        )
        if resource_url is None:
            return None

        return self._add_qualifiers(resource_url, qualifier)

    def _ngw_resource_url(
        self,
        connection_id: Optional[str],
        resource_id: int,
        source_urls: Iterable[str],
    ) -> Optional[str]:
        if connection_id is not None:
            connections_manager = self._connections_manager
            if connections_manager is None:
                connections_manager = NgwConnectionsManager()
            connection = connections_manager.connection(connection_id)
            if connection is not None:
                resource_url = self._canonical_ngw_url(
                    connection.url,
                    resource_id,
                )
                if resource_url is not None:
                    return resource_url

        reference = self._ngw_reference_from_urls(source_urls)
        if reference is None:
            return None
        return self._canonical_ngw_url(reference.base_url, resource_id)

    def _ngw_reference_from_urls(
        self,
        source_urls: Iterable[str],
    ) -> Optional[_NgwReference]:
        for source_url in source_urls:
            reference = self._ngw_reference(source_url)
            if reference is not None:
                return reference
        return None

    def _ngw_reference(self, source_url: str) -> Optional[_NgwReference]:
        sanitized_url = self._sanitize_url(source_url)
        if sanitized_url is None:
            return None

        parsed_url = urllib.parse.urlsplit(sanitized_url)
        path_match = re.search(
            r"(?:^|/)(?:api/)?resource/(\d+)(?:/|$)",
            parsed_url.path,
        )
        if path_match is not None:
            resource_id = int(path_match.group(1))
        elif parsed_url.path.rstrip("/").endswith(
            ("/render/tile", "/feature_layer/mvt")
        ):
            query = urllib.parse.parse_qs(parsed_url.query)
            resource_values = query.get("resource", [])
            if len(resource_values) == 0:
                return None
            resource_id_text = resource_values[0].split(",", maxsplit=1)[0]
            if not resource_id_text.isdigit():
                return None
            resource_id = int(resource_id_text)
        else:
            return None

        if resource_id <= 0:
            return None

        base_url = urllib.parse.urlunsplit(
            (parsed_url.scheme, parsed_url.netloc, "", "", "")
        )
        return _NgwReference(base_url, resource_id)

    def _canonical_ngw_url(
        self,
        base_url: str,
        resource_id: int,
    ) -> Optional[str]:
        sanitized_url = self._sanitize_url(base_url)
        if sanitized_url is None:
            return None
        parsed_url = urllib.parse.urlsplit(sanitized_url)
        return urllib.parse.urlunsplit(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                f"/resource/{resource_id}",
                "",
                "",
            )
        )

    def _external_source(
        self,
        provider_type: str,
        parameters: Dict[str, Any],
        source_urls: Iterable[str],
    ) -> Optional[str]:
        source_url = next(iter(source_urls), None)
        if source_url is None:
            return None

        sanitized_url = self._sanitize_url(source_url)
        if sanitized_url is None:
            return None
        if self._is_tile_source(provider_type, parameters):
            return sanitized_url

        layer_name = self._layer_name(parameters)
        if layer_name is None:
            return sanitized_url

        if provider_type.lower().startswith("arcgis"):
            url_layer = (
                urllib.parse.urlsplit(sanitized_url)
                .path.rstrip("/")
                .rsplit("/", maxsplit=1)[-1]
            )
            if url_layer == layer_name:
                return sanitized_url

        return f"{sanitized_url}|layername={layer_name}"

    def _local_source(
        self,
        provider_type: str,
        parameters: Dict[str, Any],
        source: str,
    ) -> Optional[str]:
        path_value = next(
            (
                parameters[name]
                for name in ("path", "file", "filename")
                if isinstance(parameters.get(name), str)
            ),
            None,
        )
        if isinstance(path_value, str) and self._normalize_url(path_value):
            path_value = None

        if path_value is None:
            url_value = parameters.get("url")
            if isinstance(url_value, str) and url_value.startswith("file://"):
                path_value = urllib.parse.unquote(
                    urllib.parse.urlsplit(url_value).path
                )

        if path_value is None:
            path_value = self._plain_local_path(source)
        if path_value is None:
            return None

        filename = self._filename(path_value)
        if filename is None:
            return None

        layer_name = self._layer_name(parameters)
        if provider_type.lower() == "gdal" and layer_name == "NULL":
            layer_name = None
        if layer_name is None:
            return filename
        return f"{filename}|layername={layer_name}"

    def _database_source(
        self,
        provider_type: str,
        parameters: Dict[str, Any],
    ) -> Optional[str]:
        endpoint = parameters.get("host") or parameters.get("service")
        if endpoint is None:
            return None
        endpoint = str(endpoint).strip()
        if len(endpoint) == 0:
            return None

        provider_key = provider_type.lower()
        scheme = self._DATABASE_SCHEMES.get(provider_key)
        if scheme is None:
            scheme = re.sub(r"[^a-z0-9+.-]", "", provider_key)
        if len(scheme) == 0:
            return None

        if ":" in endpoint and not endpoint.startswith("["):
            endpoint = f"[{endpoint}]"
        authority = urllib.parse.quote(endpoint, safe="[].:-_~")

        port = parameters.get("port")
        if port is not None and str(port).isdigit():
            authority = f"{authority}:{port}"

        database = parameters.get("dbname") or parameters.get("database")
        path = ""
        if database is not None and len(str(database).strip()) > 0:
            path = "/" + urllib.parse.quote(
                str(database).strip(),
                safe="-._~",
            )

        database_url = urllib.parse.urlunsplit(
            (scheme, authority, path, "", "")
        )
        table = parameters.get("table")
        if table is None or len(str(table).strip()) == 0:
            return database_url

        layer_name = str(table).strip()
        schema = parameters.get("schema")
        if schema is not None and len(str(schema).strip()) > 0:
            layer_name = f"{str(schema).strip()}.{layer_name}"
        return f"{database_url}|layername={layer_name}"

    def _source_urls(
        self,
        parameters: Dict[str, Any],
        source: str,
    ) -> List[str]:
        result: List[str] = []
        for parameter_name in self._URL_PARAMETERS:
            value = parameters.get(parameter_name)
            if not isinstance(value, str):
                continue
            candidate = self._normalize_url(value)
            if candidate is not None and candidate not in result:
                result.append(candidate)

        raw_candidate = self._normalize_url(source)
        if raw_candidate is not None and raw_candidate not in result:
            result.append(raw_candidate)

        if len(result) == 0 and (
            "/resource/" in source or "resource=" in source
        ):
            match = re.search(r"(?:NGW:|/vsi\w+/)?https?://[^\s'\"]+", source)
            if match is not None:
                candidate = self._normalize_url(match.group(0))
                if candidate is not None:
                    result.append(candidate)

        return result

    def _normalize_url(self, value: str) -> Optional[str]:
        candidate = value.strip().strip("'\"")
        if candidate.startswith("NGW:"):
            candidate = candidate[len("NGW:") :]
        for prefix in self._VSI_PREFIXES:
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix) :]
                break

        if candidate.lower().startswith("file://"):
            return None
        if (
            re.match(
                r"^[a-zA-Z][a-zA-Z0-9+.-]*://",
                candidate,
            )
            is None
        ):
            return None
        return candidate

    def _sanitize_url(self, url: str) -> Optional[str]:
        candidate = self._normalize_url(url)
        if candidate is None:
            return None

        try:
            parsed_url = urllib.parse.urlsplit(candidate)
            port = parsed_url.port
        except ValueError:
            return None
        if parsed_url.hostname is None:
            return None

        hostname = parsed_url.hostname
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = hostname if port is None else f"{hostname}:{port}"

        query_parameters = urllib.parse.parse_qsl(
            parsed_url.query,
            keep_blank_values=True,
        )
        safe_query = [
            (name, value)
            for name, value in query_parameters
            if not self._is_sensitive_query_parameter(name)
        ]
        query = urllib.parse.urlencode(
            safe_query,
            doseq=True,
            safe="{}:/,",
        )
        return urllib.parse.urlunsplit(
            (parsed_url.scheme, netloc, parsed_url.path, query, "")
        )

    @staticmethod
    def _is_sensitive_query_parameter(name: str) -> bool:
        normalized_name = re.sub(r"[^a-z0-9]", "", name.lower())
        if normalized_name in {
            "apikey",
            "key",
            "login",
            "pass",
            "pwd",
            "user",
            "username",
        }:
            return True
        return any(
            marker in normalized_name
            for marker in (
                "accesskey",
                "apikey",
                "auth",
                "credential",
                "passwd",
                "password",
                "secret",
                "signature",
                "token",
            )
        )

    def _ngw_qualifier(
        self,
        provider_type: str,
        parameters: Dict[str, Any],
        source_urls: Iterable[str],
    ) -> Optional[str]:
        combined_urls = " ".join(source_urls).lower()
        provider_key = provider_type.lower()
        if "/cog" in combined_urls:
            return "cog"
        if "/geojson" in combined_urls:
            return "geojson"
        if "/ogcf" in combined_urls or provider_key == "oapif":
            return "ogcf"
        if "/wfs" in combined_urls or provider_key == "wfs":
            return "wfs"
        if self._is_tile_source(provider_type, parameters) or any(
            marker in combined_urls
            for marker in ("/render/tile", "/feature_layer/mvt")
        ):
            return "tms"
        if "/wms" in combined_urls or provider_key == "wms":
            return "wms"
        return None

    @staticmethod
    def _add_qualifiers(
        resource_url: Optional[str],
        qualifier: Optional[str],
        *,
        is_modified: bool = False,
    ) -> Optional[str]:
        if resource_url is None:
            return None

        qualifiers = []
        if qualifier is not None:
            qualifiers.append(qualifier)
        if is_modified:
            qualifiers.append("modified")
        if len(qualifiers) == 0:
            return resource_url
        return f"{resource_url} ({', '.join(qualifiers)})"

    @staticmethod
    def _is_tile_source(
        provider_type: str,
        parameters: Dict[str, Any],
    ) -> bool:
        source_type = parameters.get("type")
        return (
            source_type is not None
            and str(source_type).lower() in ("tms", "xyz")
        ) or provider_type.lower() in (
            "mbtilesvectortiles",
            "vectortile",
            "xyzvectortiles",
        )

    def _layer_name(self, parameters: Dict[str, Any]) -> Optional[str]:
        value = next(
            (
                parameters[name]
                for name in self._LAYER_PARAMETERS
                if parameters.get(name) is not None
            ),
            None,
        )
        if isinstance(value, (list, tuple)):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return ",".join(parts) if len(parts) > 0 else None
        if value is None or isinstance(value, bool):
            return None
        layer_name = str(value).strip()
        return layer_name if len(layer_name) > 0 else None

    @staticmethod
    def _plain_local_path(source: str) -> Optional[str]:
        candidate = source.split("|", maxsplit=1)[0].strip().strip("'\"")
        if candidate.startswith("file://"):
            return urllib.parse.unquote(urllib.parse.urlsplit(candidate).path)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
            return None
        if "=" in candidate and not re.match(r"^[a-zA-Z]:[\\/]", candidate):
            return None

        path_without_query = candidate.split("?", maxsplit=1)[0]
        if Path(path_without_query).suffix == "" and not re.match(
            r"^[a-zA-Z]:[\\/]",
            path_without_query,
        ):
            return None
        return path_without_query

    @staticmethod
    def _filename(path_value: str) -> Optional[str]:
        normalized_path = urllib.parse.unquote(path_value).strip()
        if normalized_path.startswith("file://"):
            normalized_path = urllib.parse.urlsplit(normalized_path).path
        if len(normalized_path) == 0:
            return None

        if re.match(r"^[a-zA-Z]:[\\/]", normalized_path):
            filename = PureWindowsPath(normalized_path).name
        else:
            filename = Path(normalized_path).name
        return filename or None
