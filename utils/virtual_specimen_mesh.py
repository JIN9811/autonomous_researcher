"""Shared, bounded file identity for host-generated virtual camera meshes."""

import hashlib
import os
from pathlib import Path
import stat

# Dense 30 mm gyroids can exceed 100 MiB. Keep a finite rendering budget
# without rejecting valid meshes at the former 64 MiB boundary.
MAX_VIRTUAL_STL_BYTES = 256 * 1024 * 1024


def virtual_stl_sha256(path: Path) -> str:
    if path.suffix.lower() != ".stl" or not path.is_file():
        raise ValueError("candidate mesh must be a regular STL file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_VIRTUAL_STL_BYTES:
            raise ValueError("candidate STL must be nonempty and at most 256 MiB")
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_VIRTUAL_STL_BYTES:
                raise ValueError("candidate STL exceeds 256 MiB during hashing")
            digest.update(chunk)
        if size != info.st_size:
            raise ValueError("candidate mesh size changed during hashing")
    return digest.hexdigest()
