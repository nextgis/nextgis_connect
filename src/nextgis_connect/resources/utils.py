import re
from typing import Sequence


def generate_unique_name(name: str, existing_names: Sequence[str]) -> str:
    if name not in existing_names:
        return name

    if re.search(r"\(\d\)$", name):
        name = name[: name.rfind("(")]

    new_name = name.rstrip()
    new_name_with_space = None
    suffix_id = 1
    while new_name in existing_names or new_name_with_space in existing_names:
        new_name = f"{name}({suffix_id})"
        new_name_with_space = f"{name} ({suffix_id})"
        suffix_id += 1

    return new_name if new_name_with_space is None else new_name_with_space
