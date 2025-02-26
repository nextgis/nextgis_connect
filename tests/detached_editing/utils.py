import functools
from dataclasses import replace
from typing import Callable, Dict, Tuple

from qgis.core import QgsVectorLayer

from nextgis_connect.detached_editing.detached_layer_factory import (
    DetachedLayerFactory,
)
from nextgis_connect.detached_editing.utils import (
    container_metadata,
    detached_layer_uri,
)
from nextgis_connect.ngw_api.core.ngw_vector_layer import NGWVectorLayer
from tests.magic_qobject_mock import MagicQObjectMock
from tests.ng_connect_testcase import (
    NgConnectTestCase,
    TestData,
)


def mock_container(
    test_data: TestData,
    *,
    is_versioning_enabled: bool = False,
    **metadata_values: Dict,
) -> Callable:
    def create_container_mock(
        self: NgConnectTestCase,
    ) -> Tuple[MagicQObjectMock, QgsVectorLayer]:
        ngw_layer = self.resource(test_data)
        assert isinstance(ngw_layer, NGWVectorLayer)
        qgs_layer = self.layer(test_data)
        assert isinstance(qgs_layer, QgsVectorLayer)

        container_path = self.create_temp_file(".gpkg")

        factory = DetachedLayerFactory()
        factory.create_initial_container(ngw_layer, container_path)
        factory.fill_container(
            ngw_layer,
            source_path=self.data_path(test_data),
            container_path=container_path,
        )

        metadata = replace(
            container_metadata(container_path),
            epoch=1 if is_versioning_enabled else None,
            version=1 if is_versioning_enabled else None,
            **metadata_values,
        )

        container_mock = MagicQObjectMock()
        container_mock.metadata = metadata
        container_mock.path = container_path

        qgs_layer = QgsVectorLayer(
            detached_layer_uri(container_path, metadata),
            metadata.layer_name,
            "ogr",
        )

        return container_mock, qgs_layer

    def decorator(
        method: Callable[..., None],
    ) -> Callable[..., None]:
        @functools.wraps(method)
        def wrapper(
            self: NgConnectTestCase, *args: Tuple, **kwargs: Dict
        ) -> None:
            container_mock, qgs_layer = create_container_mock(self)
            try:
                method(self, container_mock, qgs_layer, *args, **kwargs)
            finally:
                container_mock.deleteLater()

        return wrapper

    return decorator
