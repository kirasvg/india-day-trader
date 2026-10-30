"""Environment credentials with optional macOS Keychain storage; never log values."""

import ctypes
import hashlib
import os
import sys
from pathlib import Path

ENV_NAMES = {
    "zerodha": {"api_key": "KITE_API_KEY", "access_token": "KITE_ACCESS_TOKEN"},
    "groww": {"access_token": "GROWW_ACCESS_TOKEN"},
}


class Keychain:
    """Use Security.framework directly: secrets never enter process arguments."""

    def __init__(self, workspace):
        if sys.platform != "darwin":
            raise ValueError(
                "Keychain is available on macOS; use process environment credentials on this platform"
            )
        self.scope = hashlib.sha256(str(Path(workspace).resolve()).encode()).hexdigest()[:24]
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.sec = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        ptr, index = ctypes.c_void_p, ctypes.c_long
        self.cf.CFStringCreateWithCString.argtypes = [ptr, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFStringCreateWithCString.restype = ptr
        self.cf.CFDataCreate.argtypes = [ptr, ptr, index]
        self.cf.CFDataCreate.restype = ptr
        self.cf.CFDataGetLength.argtypes = [ptr]
        self.cf.CFDataGetLength.restype = index
        self.cf.CFDataGetBytePtr.argtypes = [ptr]
        self.cf.CFDataGetBytePtr.restype = ptr
        self.cf.CFDictionaryCreate.argtypes = [
            ptr,
            ctypes.POINTER(ptr),
            ctypes.POINTER(ptr),
            index,
            ptr,
            ptr,
        ]
        self.cf.CFDictionaryCreate.restype = ptr
        self.cf.CFRelease.argtypes = [ptr]
        for name, arguments in (
            ("SecItemCopyMatching", [ptr, ctypes.POINTER(ptr)]),
            ("SecItemAdd", [ptr, ptr]),
            ("SecItemUpdate", [ptr, ptr]),
            ("SecItemDelete", [ptr]),
        ):
            getattr(self.sec, name).argtypes = arguments
            getattr(self.sec, name).restype = ctypes.c_int32

    def constant(self, name):
        library = self.cf if name.startswith("kCF") else self.sec
        return ctypes.c_void_p.in_dll(library, name).value

    def dictionary(self, broker, name, secret=None, returning=False, attributes=False):
        refs = []
        values = {}
        if not attributes:
            values["kSecClass"] = self.constant("kSecClassGenericPassword")
            for field, value in (
                ("kSecAttrService", "india-day-trader"),
                ("kSecAttrAccount", self.scope + ":" + broker + ":" + name),
            ):
                ref = self.cf.CFStringCreateWithCString(None, value.encode(), 0x08000100)
                refs.append(ref)
                values[field] = ref
        if secret is not None:
            raw = secret.encode()
            buffer = ctypes.create_string_buffer(raw)
            ref = self.cf.CFDataCreate(None, ctypes.cast(buffer, ctypes.c_void_p), len(raw))
            refs.append(ref)
            values["kSecValueData"] = ref
        if returning:
            values["kSecReturnData"] = self.constant("kCFBooleanTrue")
            values["kSecMatchLimit"] = self.constant("kSecMatchLimitOne")
        keys = (ctypes.c_void_p * len(values))(*(self.constant(k) for k in values))
        entries = (ctypes.c_void_p * len(values))(*values.values())
        result = self.cf.CFDictionaryCreate(None, keys, entries, len(values), None, None)
        return result, refs

    def release(self, query):
        pointer, refs = query
        self.cf.CFRelease(pointer)
        for ref in refs:
            self.cf.CFRelease(ref)

    def get(self, broker, name):
        query = self.dictionary(broker, name, returning=True)
        result = ctypes.c_void_p()
        try:
            status = self.sec.SecItemCopyMatching(query[0], ctypes.byref(result))
            if status == -25300:
                return None
            if status:
                raise ValueError(
                    "Keychain read unavailable (status %d); unlock Keychain or use environment credentials"
                    % status
                )
            return ctypes.string_at(
                self.cf.CFDataGetBytePtr(result), self.cf.CFDataGetLength(result)
            ).decode()
        finally:
            if result.value:
                self.cf.CFRelease(result)
            self.release(query)

    def set(self, broker, name, value):
        if not value or "\n" in value or "\r" in value:
            raise ValueError("Credential must be a non-empty single line")
        query = self.dictionary(broker, name)
        attributes = self.dictionary(broker, name, secret=value, attributes=True)
        try:
            status = self.sec.SecItemUpdate(query[0], attributes[0])
            if status == -25300:
                addition = self.dictionary(broker, name, secret=value)
                try:
                    status = self.sec.SecItemAdd(addition[0], None)
                finally:
                    self.release(addition)
            if status:
                raise ValueError("Keychain write unavailable (status %d)" % status)
        finally:
            self.release(query)
            self.release(attributes)

    def delete(self, broker, name):
        query = self.dictionary(broker, name)
        try:
            status = self.sec.SecItemDelete(query[0])
            if status not in (0, -25300):
                raise ValueError("Keychain deletion unavailable (status %d)" % status)
        finally:
            self.release(query)


def credentials(broker, workspace=None, use_keychain=False):
    names = ENV_NAMES[broker]
    result = {name: os.environ.get(env, "") for name, env in names.items()}
    if use_keychain and workspace and not all(result.values()):
        store = Keychain(workspace)
        for name in names:
            if not result[name]:
                result[name] = store.get(broker, name) or ""
    return result
