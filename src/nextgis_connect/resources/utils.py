import re
from typing import List, Sequence


def generate_unique_name(name: str, existing_names: Sequence) -> str:
    if name not in existing_names:
        return name

    if re.search(r"\(\d\)$", name):
        name = name[: name.rfind("(")].rstrip()

    new_name = name.rstrip()
    new_name_with_space = None
    suffix_id = 1
    while new_name in existing_names or new_name_with_space in existing_names:
        new_name = f"{name}({suffix_id})"
        new_name_with_space = f"{name} ({suffix_id})"
        suffix_id += 1

    return new_name if new_name_with_space is None else new_name_with_space


def extract_closest_to_root(
    model: "QNGWResourceTreeModel", resources_id: List[int]
) -> List[int]:
    closest_to_root = set()

    for resource_id in resources_id:
        index = model.index_from_id(resource_id)

        has_parent_in_found_list = False

        while index and index.isValid():
            parent = index.parent()
            if not parent.isValid():
                break

            parent_id = model.resource(parent).resource_id
            if parent_id != 0 and parent_id in resources_id:
                has_parent_in_found_list = True
                break

            index = parent

        if not has_parent_in_found_list:
            closest_to_root.add(resource_id)

    return list(closest_to_root)
