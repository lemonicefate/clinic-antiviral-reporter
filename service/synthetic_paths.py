"""Read-only validation for disposable, fixed-local-disk synthetic sources."""

import ctypes
from pathlib import Path
import tempfile


def fixture_root(state_dir: Path) -> Path:
    if not state_dir.is_absolute() or str(state_dir).startswith("\\\\"):
        raise ValueError("Synthetic fixture output must be local temporary storage")
    drive_type = ctypes.windll.kernel32.GetDriveTypeW
    drive_type.argtypes = [ctypes.c_wchar_p]
    drive_type.restype = ctypes.c_uint
    if drive_type(state_dir.anchor) != 3:
        raise ValueError("Synthetic fixture output requires a fixed local disk")
    temporary = Path(tempfile.gettempdir()).resolve()
    root = state_dir / "synthetic-dbf"
    if state_dir.resolve() == temporary or not state_dir.resolve().is_relative_to(temporary):
        raise ValueError("Synthetic fixture output must be a dedicated directory beneath system temporary storage")
    for path in [root, *root.parents, *(root.iterdir() if root.is_dir() else [])]:
        if path.is_symlink() or path.is_junction():
            raise ValueError("Synthetic fixture output must not traverse reparse points")
    return root
