import shutil
import time
from pathlib import Path


def safe_remove(path: Path) -> None:
    i = 0
    max_tries = 5
    while True:
        try:
            if path.is_dir():
                shutil.rmtree(str(path))
            else:
                path.unlink(missing_ok=True)
        except PermissionError:
            if i == max_tries:
                raise
            time.sleep(1)
        else:
            break
        i += 1


def safe_move(from_path: Path, to_path: Path) -> None:
    i = 0
    max_tries = 5
    while True:
        try:
            shutil.copy(from_path, to_path)
        except PermissionError:
            if i == max_tries:
                raise
            time.sleep(1)
        else:
            break
        i += 1
