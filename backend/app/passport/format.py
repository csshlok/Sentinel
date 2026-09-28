"""Portable Passport limits shared by exporter and standalone verifier."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence

MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024


def serialize_archive(members: Sequence[tuple[str, bytes]]) -> bytes:
    """The one allowed ZIP byte layout for an exported Passport.

    A verifier reserializes its parsed, bounded member list and requires byte
    equality. This rejects alternate central directories, ZIP64, slack and
    free header fields even when Python and Windows extractors disagree.
    """
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        for path, content in members:
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return output.getvalue()
