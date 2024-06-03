import logging
import shutil
from pathlib import Path
from time import time
from typing import List, Optional, Tuple, Union

from qgis.core import QgsProject

from nextgis_connect.detached_editing.utils import (
    container_metadata,
    container_path,
    is_ngw_container,
)
from nextgis_connect.ng_connect_interface import NgConnectInterface
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings


class NgConnectCacheManager:
    __settings: NgConnectSettings

    def __init__(self) -> None:
        self.__settings = NgConnectSettings()
        Path(self.cache_directory).mkdir(parents=True, exist_ok=True)

    @property
    def cache_directory(self) -> str:
        return self.__settings.cache_directory

    @property
    def cache_directory_default(self) -> str:
        return self.__settings.cache_directory_default

    @cache_directory.setter
    def cache_directory(self, value: Optional[str]) -> None:
        old_value = self.__settings.cache_directory
        self.__settings.cache_directory = value
        new_value = self.__settings.cache_directory
        if old_value == new_value:
            return

        old_cache_directory = Path(old_value)
        new_cache_directory = Path(new_value)
        shutil.copytree(old_cache_directory, new_cache_directory)
        shutil.rmtree(old_cache_directory)

    @property
    def cache_duration(self) -> int:
        """Keeping cache duration in days"""
        return self.__settings.cache_duration

    @cache_duration.setter
    def cache_duration(self, value: int) -> None:
        self.__settings.cache_duration = value

    @property
    def cache_size(self) -> float:
        """Current cache size in KB"""
        cache_path = Path(self.cache_directory)
        cache_size = 0.0
        for file_path in cache_path.glob("**/*"):
            if not file_path.is_file():
                continue
            cache_size += file_path.stat().st_size / 1024
        return cache_size

    @property
    def cache_max_size(self) -> int:
        """Cache max size in MB"""
        return self.__settings.cache_max_size

    @cache_max_size.setter
    def cache_max_size(self, value: int) -> None:
        self.__settings.cache_max_size = value

    @property
    def has_files_used_by_project(self) -> bool:
        return any(
            self.__is_file_used_by_project(file_path)
            for file_path in Path(self.cache_directory).glob("**/*")
        )

    @property
    def has_containers_with_changes(self) -> bool:
        return any(
            self.__is_container_with_changes(file_path)
            for file_path in Path(self.cache_directory).glob("**/*")
        )

    def exists(self, path: str) -> bool:
        path_to_file = Path(path)
        if not path_to_file.is_absolute():
            path_to_file = self.cache_directory / path_to_file
        return path_to_file.exists()

    def absolute_path(self, path: str) -> str:
        path_to_file = Path(path)
        if not path_to_file.is_absolute():
            path_to_file = self.cache_directory / path_to_file

        return str(path_to_file.absolute())

    def clear_cache(self) -> bool:
        cache_path = Path(self.cache_directory)

        logger = logging.getLogger(NgConnectInterface.PLUGIN_NAME)

        try:
            shutil.rmtree(cache_path)
        except Exception:
            logger.debug("Cache clearing error")
            return False

        cache_path.mkdir()

        return True

    def purge_cache(self) -> bool:
        cache_path = Path(self.cache_directory)

        cache_size = 0
        files_with_time: List[Tuple[Path, float, float]] = []
        for file_path in cache_path.glob("**/*"):
            if not file_path.is_file():
                continue

            file_size = file_path.stat().st_size / 1024**2
            cache_size += file_size
            files_with_time.append(
                (file_path, file_path.stat().st_mtime, file_size)
            )

        files_with_time.sort(key=lambda x: x[1])

        cache_max_size = self.cache_max_size
        cache_duration = self.cache_duration * 24 * 60 * 60
        current_time = time()

        check_size = cache_max_size != -1
        check_date = cache_duration != -1

        logger = logging.getLogger(NgConnectInterface.PLUGIN_NAME)

        has_errors = False

        for file_path, mtime, file_size in files_with_time:
            if (check_size and cache_size > cache_max_size) or (
                check_date and current_time - mtime > cache_duration
            ):
                if self.__is_file_used_by_project(file_path):
                    continue

                if self.__is_container_with_changes(file_path):
                    continue

                cache_size -= file_size
                try:
                    file_path.unlink()
                except Exception:
                    logger.debug("Cache clearing error")
                    has_errors = True

        self.__remove_empty_dirs(self.cache_directory)

        return not has_errors

    def __remove_empty_dirs(self, path: Union[str, Path]):
        path = Path(path)

        for sub_path in path.iterdir():
            if not sub_path.is_dir():
                continue
            self.__remove_empty_dirs(sub_path)

        if not any(path.iterdir()):
            path.rmdir()

    def __is_container_with_changes(self, file_path: Path) -> bool:
        if not is_ngw_container(file_path):
            return False

        try:
            metadata = container_metadata(file_path)
        except Exception:
            return False

        return metadata.has_changes

    def __is_file_used_by_project(self, file_path: Path) -> bool:
        if not is_ngw_container(file_path):
            return False

        layers = filter(
            is_ngw_container, QgsProject().instance().mapLayers().values()
        )
        return any(container_path(layer) == file_path for layer in layers)
