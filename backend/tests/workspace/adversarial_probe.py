"""The in-box half of the Phase 3 adversarial suite (runs as snapshot Python inside the box).

It is copied into the test repository and committed, so the workspace clone
carries it; ``python adversarial_probe.py <suite> <config-file>`` runs one suite
and prints exactly one ``PROBE {json}`` line. Every attempt records either
``{"ok": true, "value": ...}`` or ``{"ok": false, ...}`` with the OS error code
(``winerror`` / ``errno`` / NTSTATUS / ``last_error``), so a denial is always
observable with its reason. Standard library only: the box has no dependencies.
"""

import ctypes
import json
import os
import socket
import subprocess
import sys
import winreg
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class Denied(Exception):
    """A Win32 call failed; carries ``GetLastError`` or an NTSTATUS/HRESULT."""

    def __init__(self, what, code):
        super().__init__(f"{what} failed with {code:#x}")
        self.code = code


def attempt(out, name, fn):
    try:
        value = fn()
        out[name] = {"ok": True, "value": value}
    except Denied as exc:
        out[name] = {"ok": False, "last_error": exc.code, "message": str(exc)}
    except OSError as exc:
        out[name] = {"ok": False, "winerror": getattr(exc, "winerror", None),
                     "errno": exc.errno, "message": str(exc)[:200]}
    except Exception as exc:  # anything else is reported, never swallowed
        out[name] = {"ok": False, "error": type(exc).__name__, "message": str(exc)[:200]}


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def run_detached_output(argv, output_name):
    """Run ``argv`` with stdout/stderr in a workspace file (piped spawns can hang in a box)."""

    with open(output_name, "wb") as handle:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=handle, stderr=handle,
                                timeout=30)
    with open(output_name, "rb") as handle:
        return {"returncode": result.returncode,
                "output": handle.read().decode("utf-8", "replace")[:500]}


def connect(host, port, family=socket.AF_INET):
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect((host, port))
        return True
    finally:
        sock.close()


def open_pipe(name):
    handle = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0,
                                  None)
    if handle == INVALID_HANDLE_VALUE or handle is None:
        raise Denied("CreateFileW(pipe)", ctypes.get_last_error())
    kernel32.CloseHandle(handle)
    return True


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.c_void_p),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
advapi32.CredReadW.restype = wintypes.BOOL
advapi32.CredEnumerateW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD),
                                    ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(CREDENTIAL)))]
advapi32.CredEnumerateW.restype = wintypes.BOOL
advapi32.CredFree.argtypes = [ctypes.c_void_p]
advapi32.CredFree.restype = None


def cred_read(target):
    credential = ctypes.POINTER(CREDENTIAL)()
    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(credential)):
        raise Denied("CredReadW", ctypes.get_last_error())
    advapi32.CredFree(credential)
    return True


def cred_count():
    count = wintypes.DWORD()
    items = ctypes.POINTER(ctypes.POINTER(CREDENTIAL))()
    if not advapi32.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(items)):
        raise Denied("CredEnumerateW", ctypes.get_last_error())
    advapi32.CredFree(items)
    return count.value


def cng_open(provider, name):
    ncrypt = ctypes.WinDLL("ncrypt")
    ncrypt.NCryptOpenStorageProvider.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                                 wintypes.LPCWSTR, wintypes.DWORD]
    ncrypt.NCryptOpenKey.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                     wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    ncrypt.NCryptFreeObject.argtypes = [ctypes.c_void_p]
    for function in (ncrypt.NCryptOpenStorageProvider, ncrypt.NCryptOpenKey,
                     ncrypt.NCryptFreeObject):
        function.restype = ctypes.c_long
    handle = ctypes.c_void_p()
    status = ncrypt.NCryptOpenStorageProvider(ctypes.byref(handle), provider, 0)
    if status:
        raise Denied("NCryptOpenStorageProvider", status & 0xFFFFFFFF)
    try:
        key = ctypes.c_void_p()
        status = ncrypt.NCryptOpenKey(handle, ctypes.byref(key), name, 0, 0)
        if status:
            raise Denied("NCryptOpenKey", status & 0xFFFFFFFF)
        ncrypt.NCryptFreeObject(key)
        return True
    finally:
        ncrypt.NCryptFreeObject(handle)


def create_registry_key(root, path):
    key = winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE)
    winreg.CloseKey(key)
    return True


def denial_suite(cfg):
    out = {}
    for label, store in cfg["stores"].items():
        attempt(out, f"{label}_list", lambda s=store: len(os.listdir(s["dir"])))
        attempt(out, f"{label}_canary_read", lambda s=store: read_text(s["canary"]))
        attempt(out, f"{label}_write", lambda s=store: write_text(
            os.path.join(s["dir"], cfg["pwn_name"]), "pwned"))
    attempt(out, "db_read", lambda: len(open(cfg["db"], "rb").read(16)))
    attempt(out, "db_write", lambda: len(open(cfg["db"], "r+b").read(16)))
    attempt(out, "trust_read", lambda: read_text(cfg["trust"]))
    attempt(out, "trust_write", lambda: write_text(cfg["trust"], "{}"))
    attempt(out, "other_box_read", lambda: read_text(cfg["other_canary"]))
    attempt(out, "other_box_list", lambda: len(os.listdir(cfg["other_dir"])))
    attempt(out, "other_box_write", lambda: write_text(
        os.path.join(cfg["other_dir"], "pwned.txt"), "pwned"))
    attempt(out, "exec_outside", lambda: run_detached_output([cfg["outside_exe"]], "exec-out.txt"))
    if cfg.get("lan_ip"):
        attempt(out, "lan_connect", lambda: connect(cfg["lan_ip"], cfg["lan_port"]))
    attempt(out, "localhost_connect", lambda: connect("localhost", cfg["v4_port"]))
    if cfg.get("v6_port"):
        attempt(out, "ipv6_loopback_connect",
                lambda: connect("::1", cfg["v6_port"], socket.AF_INET6))
    attempt(out, "named_pipe", lambda: open_pipe(cfg["pipe"]))
    attempt(out, "cred_read", lambda: cred_read(cfg["cred_target"]))
    attempt(out, "cred_count", cred_count)
    for label, provider in cfg["cng_providers"].items():
        attempt(out, f"cng_test_key_{label}", lambda p=provider: cng_open(p, cfg["cng_test_key"]))
        attempt(out, f"cng_default_key_{label}",
                lambda p=provider: cng_open(p, cfg["cng_default_key"]))
    attempt(out, "hkcu_create", lambda: create_registry_key(winreg.HKEY_CURRENT_USER,
                                                           cfg["hkcu_key"]))
    attempt(out, "hklm_create", lambda: create_registry_key(winreg.HKEY_LOCAL_MACHINE,
                                                           cfg["hklm_key"]))
    attempt(out, "workspace_write", lambda: write_text("adversarial-probe.txt", "written-inside"))
    return out


SUITES = {"denial": denial_suite}


if __name__ == "__main__":
    # The config is a workspace file the host wrote: launch arguments are capped at 2048 chars.
    suite, config = sys.argv[1], json.loads(read_text(sys.argv[2]))
    result = SUITES[suite](config)
    sys.stdout.write("PROBE " + json.dumps(result) + "\n")
    sys.stdout.flush()
