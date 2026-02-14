import hashlib
import logging
import re
import shutil
from pathlib import Path
from time import time
from typing import List, Optional, Tuple, Union

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QMimeDatabase

from nextgis_connect.core.constants import PLUGIN_NAME
from nextgis_connect.detached_editing.utils import (
    container_metadata,
    container_path,
    is_ngw_container,
)
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings
from nextgis_connect.types import FileObjectId, UnsetType


class NgConnectCacheManager:
    __settings: NgConnectSettings
    __project_containers: Optional[List[Path]]

    def __init__(self) -> None:
        self.__settings = NgConnectSettings()
        self.__project_containers = None
        Path(self.cache_directory).mkdir(parents=True, exist_ok=True)

    @property
    def default_user_profile_cache_directory(self) -> str:
        return self.__settings.user_profile_cache_directory

    @property
    def cache_directory(self) -> str:
        return self.__settings.cache_directory

    @cache_directory.setter
    def cache_directory(self, value: Optional[str]) -> None:
        old_value = self.__settings.cache_directory
        self.__settings.cache_directory = value
        new_value = self.__settings.cache_directory
        if old_value == new_value:
            return

        old_cache_directory = Path(old_value)
        new_cache_directory = Path(new_value)
        shutil.copytree(
            old_cache_directory, new_cache_directory, dirs_exist_ok=True
        )
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
            for file_path in Path(self.cache_directory).glob("**/*.gpkg")
        )

    @property
    def need_migration(self) -> bool:
        old_plugin_cache_path = Path(
            self.__settings.old_plugin_cache_directory
        )
        custom_cache_path = Path(
            self.cache_directory,
        )
        for cache_path in (old_plugin_cache_path, custom_cache_path):
            for directory in cache_path.glob("*"):
                if not _is_uuid(directory.name):
                    continue

                if any(True for _ in directory.glob("*.gpkg")):
                    return True

        return False

    @property
    def can_migrate(self) -> bool:
        old_plugin_cache_path = Path(
            self.__settings.old_plugin_cache_directory
        )
        custom_cache_path = Path(
            self.cache_directory,
        )

        for cache_path in (old_plugin_cache_path, custom_cache_path):
            for directory in cache_path.glob("*"):
                if not _is_uuid(directory.name):
                    continue

                gpkg_files = list(directory.glob("*.gpkg"))
                for gpkg_file in gpkg_files:
                    if self.__is_file_used_by_project(gpkg_file):
                        return False

        return True

    def exists(self, path: Union[str, Path]) -> bool:
        path_to_file = Path(path)
        if not path_to_file.is_absolute():
            path_to_file = self.cache_directory / path_to_file
        return path_to_file.exists()

    def detached_container_path(
        self, domain_uuid: str, resource_id: Union[int, str]
    ) -> Path:
        seed = f"{domain_uuid}_{resource_id}"
        sha1_hash = hashlib.sha1(seed.encode()).hexdigest()
        sha1_hash_prefix = sha1_hash[:2]
        return (
            Path(self.cache_directory)
            / domain_uuid
            / sha1_hash_prefix
            / sha1_hash
            / f"{resource_id}.gpkg"
        )

    def attachment_directory(
        self,
        domain_uuid: str,
        resource_id: Union[int, str],
        attachment_id: Union[int, str],
        *,
        fileobj: Union[UnsetType, None, FileObjectId] = None,
    ) -> Path:
        seed = f"{domain_uuid}_{resource_id}_{attachment_id}"
        if bool(fileobj) and fileobj != -1:
            seed += f"_{fileobj}"

        sha1_hash = hashlib.sha1(seed.encode()).hexdigest()
        sha1_hash_prefix = sha1_hash[:2]
        return (
            Path(self.cache_directory)
            / domain_uuid
            / sha1_hash_prefix
            / sha1_hash
        )

    def attachment_path(
        self,
        domain_uuid: str,
        resource_id: Union[int, str],
        attachment_id: Union[int, str],
        *,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        fileobj: Union[UnsetType, None, FileObjectId] = None,
    ) -> Path:
        attachment_directory = self.attachment_directory(
            domain_uuid, resource_id, attachment_id, fileobj=fileobj
        )
        extension = _guess_extension(file_name=file_name, mime_type=mime_type)
        return attachment_directory / f"{attachment_id}{extension}"

    def attachment_thumbnail_directory(
        self,
        domain_uuid: str,
        resource_id: Union[int, str],
        attachment_id: Union[int, str],
        *,
        fileobj: Union[UnsetType, None, FileObjectId] = None,
    ) -> Path:
        seed = f"{domain_uuid}_{resource_id}_{attachment_id}"
        if bool(fileobj) and fileobj != -1:
            seed += f"_{fileobj}"
        seed += "_thumbnail"

        sha1_hash = hashlib.sha1(seed.encode()).hexdigest()
        sha1_hash_prefix = sha1_hash[:2]
        return (
            Path(self.cache_directory)
            / domain_uuid
            / sha1_hash_prefix
            / sha1_hash
        )

    def attachment_thumbnail_path(
        self,
        domain_uuid: str,
        resource_id: Union[int, str],
        attachment_id: Union[int, str],
        *,
        fileobj: Union[UnsetType, None, FileObjectId] = None,
    ) -> Path:
        thumbnail_directory = self.attachment_thumbnail_directory(
            domain_uuid, resource_id, attachment_id, fileobj=fileobj
        )
        return thumbnail_directory / f"{attachment_id}.jpg"

    def migrate(self) -> bool:
        logger = logging.getLogger(PLUGIN_NAME)
        logger.debug("Start cache migration")

        old_plugin_cache_path = Path(
            self.__settings.old_plugin_cache_directory
        )

        # Migrate from default cache directory
        self.__migrate(old_plugin_cache_path, Path(self.cache_directory))

        if self.cache_directory != self.__settings.old_plugin_cache_directory:
            # Just update structure if custom cache directory was used
            self.__migrate(
                Path(self.cache_directory), Path(self.cache_directory)
            )

        if self.cache_directory == self.__settings.old_plugin_cache_directory:
            # Reset if default value was stored in settings
            self.cache_directory = self.__settings.user_profile_cache_directory

        logger.debug("Cache migration completed")

        return True

    def clear_cache(self) -> bool:
        cache_path = Path(self.cache_directory)

        logger = logging.getLogger(PLUGIN_NAME)

        try:
            shutil.rmtree(cache_path)
        except Exception:
            logger.debug("Cache clearing error")
            return False

        cache_path.mkdir()

        return True

    def purge_cache(self) -> bool:
        logger = logging.getLogger(PLUGIN_NAME)

        need_check_size = self.cache_max_size != -1
        need_check_date = self.cache_duration != -1
        if not need_check_size and not need_check_date:
            logger.debug("Cache limits is disabled")
            return True

        cache_duration_in_s = self.cache_duration * 24 * 60 * 60
        current_time_in_s = time()

        # Collect cache files information
        cache_size = 0
        has_old_files = False
        files_with_time: List[Tuple[Path, float, float]] = []
        for file_path in Path(self.cache_directory).glob("**/*"):
            if not file_path.is_file():
                continue

            file_stat = file_path.stat()

            file_size = file_stat.st_size / 1024**2
            file_time = file_stat.st_mtime
            cache_size += file_size

            if need_check_date:
                has_old_files = has_old_files or (
                    current_time_in_s - file_time > cache_duration_in_s
                )

            files_with_time.append((file_path, file_time, file_size))

        # Check purge neccesity
        limit_exceeded = need_check_size and cache_size > self.cache_max_size
        if not limit_exceeded and not has_old_files:
            logger.debug("There is no need to purge the cache")
            return True

        # Sort by date
        files_with_time.sort(key=lambda x: x[1])
        has_errors = False

        # Purge cache
        deleted_files_count = 0
        for file_path, file_time, file_size in files_with_time:
            limit_exceeded = (
                need_check_size and cache_size > self.cache_max_size
            )
            file_is_old = (
                need_check_date
                and current_time_in_s - file_time > cache_duration_in_s
            )

            if limit_exceeded or file_is_old:
                if self.__is_file_used_by_project(file_path):
                    continue

                if self.__is_container_with_changes(file_path):
                    continue

                try:
                    file_path.unlink()
                    cache_size -= file_size
                except Exception:
                    logger.debug(f"Error deleting file {file_path}")
                    has_errors = True
            else:
                break

        logger.debug(f"Deleted {deleted_files_count} files")

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
        try:
            metadata = container_metadata(file_path)
        except Exception:
            return False

        return metadata.has_changes

    def __is_file_used_by_project(self, file_path: Path) -> bool:
        if self.__project_containers is None:
            self.__project_containers = [
                container_path(layer)
                for layer in QgsProject().instance().mapLayers().values()
                if is_ngw_container(layer)
            ]

        return file_path in self.__project_containers

    def __migrate(self, old_base: Path, new_base: Path) -> bool:
        if not old_base.exists():
            return True

        for directory in old_base.glob("*"):
            if not _is_uuid(directory.name):
                continue

            gpkg_files = list(directory.glob("*.gpkg"))
            for gpkg_file in gpkg_files:
                connection_id = directory.name
                resource_id = gpkg_file.stem
                relative_path = self.detached_container_path(
                    connection_id, resource_id
                ).relative_to(self.cache_directory)
                new_path = new_base / relative_path
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(gpkg_file, new_path)

            if old_base != new_base:
                shutil.rmtree(directory)

        if not any(old_base.iterdir()):
            old_base.rmdir()

        return True


def _is_uuid(name: str) -> bool:
    uuid_pattern = re.compile(
        r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$",
        re.IGNORECASE,
    )
    return bool(uuid_pattern.match(name))


def _guess_extension(
    file_name: Optional[str], mime_type: Optional[str]
) -> str:
    extension = ""

    mime_database = QMimeDatabase()

    if mime_type:
        mime = mime_database.mimeTypeForName(mime_type)
        if mime.isValid():
            extension = mime.preferredSuffix()
            if extension:
                extension = f".{extension}"

    if not extension and file_name:
        mime = mime_database.mimeTypeForFile(file_name)
        if mime.isValid():
            extension = mime.preferredSuffix()
            if extension:
                extension = f".{extension}"

        if not extension:
            extension = Path(file_name).suffix

    return extension
