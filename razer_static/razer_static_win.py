#!/usr/bin/env python3
"""
razer_static_win.py - set a static colour on Razer devices, then exit (Windows).

Standard library only. Uses ctypes to talk to the HID stack through DLLs that
ship with Windows (hid.dll, setupapi.dll, kernel32.dll). No pip, no drivers.

The effect is written with the VARSTORE flag, so most devices keep it in onboard
memory after the script exits (the same mechanism OpenRazer / Polychromatic use).

This file is also the Windows orchestrator: it applies the colour to standard
Razer devices itself, and automatically hands tricky devices (such as the
Kraken) to the matching module under ./custom_drivers/. Custom drivers import
this file (as `razer_static_win`) and reuse its HID and output helpers, so they
never duplicate the Win32 plumbing.

Normally you run this through razer_static.py (the cross-platform launcher), but
it also works on its own:

  python razer_static_win.py ff0000
  python razer_static_win.py 00ff88 --brightness 180
  python razer_static_win.py --list
"""
import argparse
import ctypes
import importlib
import os
import sys
import time
from ctypes import wintypes as wt

sys.dont_write_bytecode = True   # don't scatter __pycache__ folders

if sys.platform != "win32":
    sys.exit("This tool is Windows-only.")

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --------------------------------------------------------------- Win32 types
class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD),
                ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wt.DWORD), ("Reserved", ctypes.c_size_t)]

class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT),
                ("ProductID", wt.USHORT), ("VersionNumber", wt.USHORT)]

# 64-byte struct; index 3 = OutputReportByteLength, index 4 = FeatureReportByteLength.
HIDP_CAPS = ctypes.c_ushort * 32

H = wt.HANDLE
INVALID_HANDLE = ctypes.c_void_p(-1).value
DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x02, 0x10
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_RW, OPEN_EXISTING = 0x3, 3
HIDP_STATUS_SUCCESS = 0x00110000

hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetHidGuid.restype = None
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
setupapi.SetupDiGetClassDevsW.restype = H
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [H, ctypes.c_void_p, ctypes.POINTER(GUID),wt.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [H, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),ctypes.c_void_p, wt.DWORD,ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [H]
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,wt.DWORD, wt.DWORD, H]
k32.CreateFileW.restype = H
k32.CloseHandle.argtypes = [H]
hid.HidD_GetAttributes.argtypes = [H, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wt.BOOLEAN
hid.HidD_GetPreparsedData.argtypes = [H, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wt.BOOLEAN
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = ctypes.c_long
for _fn in (hid.HidD_SetFeature, hid.HidD_GetFeature, hid.HidD_GetProductString):
    _fn.argtypes = [H, ctypes.c_void_p, wt.ULONG]
    _fn.restype = wt.BOOLEAN

# --------------------------------------------------------------- HID helpers
def hid_paths():
    """Yield the device path of every present HID interface."""
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not info or info == INVALID_HANDLE:
        return
    try:
        i = 0
        while True:
            ifd = SP_DEVICE_INTERFACE_DATA()
            ifd.cbSize = ctypes.sizeof(ifd)
            if not setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(guid),i, ctypes.byref(ifd)):
                break
            i += 1
            need = wt.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(ifd), None, 0,ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W: 8 on 64-bit, 6 on 32-bit.
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(ifd), buf,need.value, None, None):
                yield ctypes.wstring_at(ctypes.addressof(buf) + 4)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)


def open_path(path):
    """Open a HID interface. Windows blocks read/write on keyboard/mouse
    collections, but a zero-access handle can still send feature reports, so
    fall back to that."""
    for access in (GENERIC_READ | GENERIC_WRITE, 0):
        h = k32.CreateFileW(path, access, FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
        if h and h != INVALID_HANDLE:
            return h
    return None


def attributes(h):
    """Return (vendor_id, product_id) for an open handle, or (0, 0)."""
    a = HIDD_ATTRIBUTES()
    a.Size = ctypes.sizeof(a)
    return (a.VendorID, a.ProductID) if hid.HidD_GetAttributes(h, ctypes.byref(a)) else (0, 0)


def _caps_len(h, index):
    pp = ctypes.c_void_p()
    if not hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
        return 0
    try:
        caps = HIDP_CAPS()
        if hid.HidP_GetCaps(pp, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
            return 0
        return caps[index]
    finally:
        hid.HidD_FreePreparsedData(pp)


def feature_len(h):
    """FeatureReportByteLength for an open handle (0 if unavailable)."""
    return _caps_len(h, 4)


def output_len(h):
    """OutputReportByteLength for an open handle (0 if unavailable)."""
    return _caps_len(h, 3)


def product_name(h):
    """Human-readable product string for an open handle, or ""."""
    buf = ctypes.create_unicode_buffer(128)
    return buf.value if hid.HidD_GetProductString(h, buf, ctypes.sizeof(buf)) else ""

# --------------------------------------------------------------- Razer protocol
RAZER_VID = 0x1532
VARSTORE = 0x01
TRANSACTION_IDS = [0x1F, 0x3F, 0xFF]
LED_IDS = [0x05, 0x00, 0x01, 0x04]
CONTROL_REPORT_LEN = 91          # Razer control interface uses 90 bytes + report ID


def build_report(tid, cmd_class, cmd_id, args):
    """Build a 90-byte Razer control report with its trailing XOR checksum."""
    r = bytearray(90)
    r[1], r[5], r[6], r[7] = tid, len(args), cmd_class, cmd_id
    r[8:8 + len(args)] = bytes(args)
    crc = 0
    for b in r[2:88]:
        crc ^= b
    r[88] = crc
    return r


def send(h, report):
    """Send a control report as a feature report; return the device status byte
    (0x02 = success) or None on failure."""
    out = (ctypes.c_ubyte * CONTROL_REPORT_LEN)(0, *report)   # report ID 0 + 90 bytes
    if not hid.HidD_SetFeature(h, out, CONTROL_REPORT_LEN):
        return None
    time.sleep(0.06)
    resp = (ctypes.c_ubyte * CONTROL_REPORT_LEN)()
    if not hid.HidD_GetFeature(h, resp, CONTROL_REPORT_LEN):
        return None
    return resp[1]


def set_static(h, rgb, brightness):
    """Try the known static-colour commands on an open handle. Returns a short
    description of the method that worked, or None."""
    r, g, b = rgb
    for tid in TRANSACTION_IDS:                      # newer devices
        for led in LED_IDS:
            if send(h, build_report(tid, 0x0F, 0x02,
                                    [VARSTORE, led, 0x01, 0x00, 0x00, 0x01, r, g, b])) == 0x02:
                send(h, build_report(tid, 0x0F, 0x04, [VARSTORE, led, brightness]))
                return f"extended matrix (tid=0x{tid:02X}, led=0x{led:02X})"
    for tid in TRANSACTION_IDS:                      # older devices
        if send(h, build_report(tid, 0x03, 0x0A, [0x06, r, g, b])) == 0x02:
            send(h, build_report(tid, 0x03, 0x03, [VARSTORE, 0x05, brightness]))
            return f"standard matrix (tid=0x{tid:02X})"
    return None

# --------------------------------------------------------------- colour helpers
def parse_colour(s):
    """Parse a hex colour like 'ff8800' or '#ff8800' into an (r, g, b) tuple."""
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError("colour must be 6 hex digits, e.g. ff8800")
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise argparse.ArgumentTypeError("colour must be 6 hex digits, e.g. ff8800")


def hex_colour(rgb):
    """Format an (r, g, b) tuple as '#rrggbb'."""
    return "#{:02x}{:02x}{:02x}".format(*rgb)

# --------------------------------------------------------------- custom drivers
CUSTOM_DRIVERS_DIR = "custom_drivers"
DRIVER_SUFFIX = "_win"           # only load this platform's drivers


def discover_custom_drivers():
    """Import the Windows custom drivers in ./custom_drivers/ (files ending in
    `_win.py`) that expose the PIDS + apply_static contract:

      PIDS          - dict of {product_id: name} it handles
      apply_static(rgb, brightness) -> list of (name, ok, detail) results
    """
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), CUSTOM_DRIVERS_DIR)
    if not os.path.isdir(folder):
        return []
    # Let custom drivers `import razer_static_win` and reuse this live module,
    # even while we are running as the __main__ script.
    sys.modules.setdefault("razer_static_win", sys.modules[__name__])
    if folder not in sys.path:
        sys.path.insert(0, folder)

    drivers = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(DRIVER_SUFFIX + ".py") or fn.startswith("_"):
            continue
        try:
            mod = importlib.import_module(fn[:-3])
        except Exception:
            continue
        if hasattr(mod, "PIDS") and hasattr(mod, "apply_static"):
            drivers.append(mod)
    return drivers

# --------------------------------------------------------------- actions
def apply_generic(rgb, brightness, skip_pids):
    """Apply a static colour to standard Razer control-interface devices.
    Devices whose PID is in `skip_pids` are left to their custom driver.
    Returns a list of (name, ok, detail)."""
    seen, done = {}, set()
    for path in hid_paths():
        if "vid_1532" not in path.lower():
            continue
        h = open_path(path)
        if not h:
            continue
        try:
            vid, pid = attributes(h)
            if vid != RAZER_VID or pid in skip_pids:
                continue
            seen[pid] = product_name(h) or f"PID 0x{pid:04X}"
            if pid in done or feature_len(h) != CONTROL_REPORT_LEN:
                continue
            if set_static(h, rgb, brightness):
                done.add(pid)
        finally:
            k32.CloseHandle(h)
    return [(name, pid in done, "" if pid in done else "no interface accepted the command")
            for pid, name in seen.items()]


def list_devices(drivers):
    """Return a list of (name, pid, handler) for every present Razer device."""
    owner = {pid: mod for mod in drivers for pid in mod.PIDS}
    found = {}
    for path in hid_paths():
        if "vid_1532" not in path.lower():
            continue
        h = open_path(path)
        if not h:
            continue
        try:
            vid, pid = attributes(h)
            if vid != RAZER_VID:
                continue
            found.setdefault(pid, product_name(h) or f"PID 0x{pid:04X}")
        finally:
            k32.CloseHandle(h)
    rows = []
    for pid, name in sorted(found.items()):
        mod = owner.get(pid)
        handler = f"custom driver ({mod.__name__})" if mod else "generic"
        rows.append((name, pid, handler))
    return rows

# --------------------------------------------------------------- output
def print_results(results):
    """Print a tidy, aligned status line per device plus a summary."""
    if not results:
        print("  no Razer devices found")
        return
    width = max(len(name) for name, _, _ in results)
    for name, is_ok, detail in results:
        mark = "OK" if is_ok else "--"
        line = f"  [{mark}] {name:<{width}}"
        if detail:
            line += f"   {detail}"
        print(line.rstrip())
    n_ok = sum(1 for _, is_ok, _ in results if is_ok)
    print()
    print(f"  {n_ok} of {len(results)} device(s) set")


def print_devices(rows):
    if not rows:
        print("  no Razer devices found")
        return
    width = max(len(name) for name, _, _ in rows)
    for name, pid, handler in rows:
        print(f"  {name:<{width}}   PID 0x{pid:04X}   {handler}")

# --------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="Set a static colour on Razer devices (Windows).")
    p.add_argument("colour", type=parse_colour, nargs="?", help="hex colour, e.g. ff0000")
    p.add_argument("--brightness", type=int, default=255, help="0-255 (default 255)")
    p.add_argument("--list", action="store_true", help="list Razer devices and exit")
    a = p.parse_args()

    drivers = discover_custom_drivers()

    if a.list:
        print("Razer devices\n")
        print_devices(list_devices(drivers))
        return

    if a.colour is None:
        p.error("a colour is required (or use --list)")
    brightness = max(0, min(255, a.brightness))

    print(f"Applying {hex_colour(a.colour)} at brightness {brightness}\n")

    custom_pids = {pid for mod in drivers for pid in mod.PIDS}
    results = apply_generic(a.colour, brightness, skip_pids=custom_pids)
    for mod in drivers:
        try:
            results.extend(mod.apply_static(a.colour, brightness))
        except Exception as e:
            for name in mod.PIDS.values():
                results.append((name, False, f"driver error: {e}"))

    print_results(results)


if __name__ == "__main__":
    main()
