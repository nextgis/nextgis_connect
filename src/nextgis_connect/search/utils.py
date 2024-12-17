from enum import Enum


class SearchType(str, Enum):
    ByDisplayName = "by_display_name"
    ByMetadata = "by_metadata"

    def __str__(self) -> str:
        return str(self.value)
