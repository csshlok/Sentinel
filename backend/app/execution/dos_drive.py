"""Per-run DOS drive letters that expose an AppContainer folder to its agent.

Windows PowerShell normalizes its location by listing every ancestor
directory, and an AppContainer may not list the user's profile folders, so a
box cannot stand in ``%LOCALAPPDATA%\\Packages\\<profile>\\AC\\ws``. Mapping a
drive letter to the AC folder gives the workspace the path ``<letter>:\\ws``,
whose only ancestor is the AC folder, which the box may list (spike 007).

A mapping lives in the user's logon session (``DefineDosDeviceW``), so other
processes of the same user see it while a run lasts. Removal always names the
exact target, so a mapping someone else made on the same letter is never
removed. Nothing here grants access: the AC folder is already the box's own.
"""

from __future__ import annotations

import ctypes
import os
import string
from ctypes import wintypes
from pathlib import Path

IS_WINDOWS = os.name == "nt"

DDD_RAW_TARGET_PATH = 0x00000001
DDD_REMOVE_DEFINITION = 0x00000002
DDD_EXACT_MATCH_ON_REMOVE = 0x00000004
_ERROR_INSUFFICIENT_BUFFER = 122
_DOS_PREFIX = "\\??\\"
# Z down to D: A/B are legacy floppy letters and C is the system drive.
CANDIDATE_LETTERS = tuple(f"{letter}:" for letter in reversed(string.ascii_uppercase[3:]))

if IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.DefineDosDeviceW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR]
    _kernel32.DefineDosDeviceW.restype = wintypes.BOOL
    _kernel32.QueryDosDeviceW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    _kernel32.QueryDosDeviceW.restype = wintypes.DWORD
    _kernel32.GetLogicalDrives.argtypes = []
    _kernel32.GetLogicalDrives.restype = wintypes.DWORD


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise OSError("DOS drive mappings exist only on Windows")


def _normal(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def query_drive(letter: str) -> list[str]:
    """Every target currently defined for ``letter`` (newest first); empty if none."""

    _require_windows()
    size = 1024
    while size <= 1 << 16:
        buffer = ctypes.create_unicode_buffer(size)
        count = _kernel32.QueryDosDeviceW(letter, buffer, size)
        if count:
            return [item for item in buffer[:count].split("\0") if item]
        if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER:
            return []
        size *= 2
    return []


def _target_path(device: str) -> str | None:
    """The Win32 path of a ``\\??\\C:\\...`` device target; None for anything else."""

    if not device.startswith(_DOS_PREFIX):
        return None
    return device[len(_DOS_PREFIX):]


def _logical_letters() -> set[str]:
    mask = _kernel32.GetLogicalDrives()
    return {f"{letter}:" for index, letter in enumerate(string.ascii_uppercase) if mask >> index & 1}


def map_drive(target: str | Path) -> str:
    """Map the first free letter (Z downward) to ``target`` and return it, e.g. ``"Z:"``.

    Raises ``OSError`` when no letter is free or the new mapping does not
    resolve to ``target``; a mapping that was made is removed first.
    """

    _require_windows()
    target_text = os.path.abspath(str(target))
    if not os.path.isdir(target_text):
        raise OSError(f"The drive target is not a directory: {target_text}")
    taken = _logical_letters()
    for letter in CANDIDATE_LETTERS:
        if letter in taken or query_drive(letter):
            continue
        if not _kernel32.DefineDosDeviceW(0, letter, target_text):
            continue
        current = query_drive(letter)
        resolved = _target_path(current[0]) if current else None
        if resolved is not None and _normal(resolved) == _normal(target_text):
            return letter
        unmap_drive(letter, target_text)
        raise OSError(f"The mapping of {letter} did not resolve to its target")
    raise OSError("No free drive letter is available for the workspace")


def unmap_drive(letter: str, target: str | Path) -> bool:
    """Remove exactly this ``letter`` → ``target`` mapping; True when it is gone."""

    _require_windows()
    target_text = os.path.abspath(str(target))
    for device in query_drive(letter):
        resolved = _target_path(device)
        if resolved is not None and _normal(resolved) == _normal(target_text):
            _kernel32.DefineDosDeviceW(
                DDD_REMOVE_DEFINITION | DDD_EXACT_MATCH_ON_REMOVE | DDD_RAW_TARGET_PATH,
                letter, device,
            )
    return not any(
        _target_path(device) is not None
        and _normal(_target_path(device) or "") == _normal(target_text)
        for device in query_drive(letter)
    )


def unmap_all(target: str | Path) -> list[str]:
    """Remove every letter mapped exactly to ``target``; the letters removed.

    Used by the workspace sweep for a run that ended before its own removal
    ran. It is driven by a recorded target, never by enumerating other
    profiles, so another Sentinel instance's live mapping is never touched.
    """

    _require_windows()
    target_text = os.path.abspath(str(target))
    removed: list[str] = []
    for letter in CANDIDATE_LETTERS:
        if any(_target_path(device) is not None
               and _normal(_target_path(device) or "") == _normal(target_text)
               for device in query_drive(letter)):
            if unmap_drive(letter, target_text):
                removed.append(letter)
    return removed
