#!/usr/bin/env python3
"""
razer_static_mac.py - set a static colour on Razer devices, then exit (macOS).

Standard library only. Uses ctypes to talk to the HID stack through the
CoreFoundation and IOKit frameworks that ship with macOS. No pip, no drivers,
no Homebrew - the macOS mirror of razer_static_win.py.

This file is the macOS orchestrator: it applies the colour to standard Razer
devices itself, and automatically hands tricky devices (such as the Kraken) to
the matching module under ./custom_drivers/ (files ending in `_mac.py`). Custom
drivers import this file (as `razer_static_mac`) and reuse its HID and output
helpers, so they never duplicate the IOKit plumbing.

Normally you run this through razer_static.py (the cross-platform launcher), but
it also works on its own:

  python3 razer_static_mac.py ff0000
  python3 razer_static_mac.py 00ff88 --brightness 180
  python3 razer_static_mac.py --list

Note: talking to HID devices on macOS may require running from a terminal that
has been granted Input Monitoring permission (System Settings > Privacy), or
running with sudo, depending on the device and macOS version.
"""
import argparse
import ctypes
import importlib
import os
import sys
import time

sys.dont_write_bytecode = True   # don't scatter __pycache__ folders

if sys.platform != "darwin":
    sys.exit("This tool is macOS-only.")

cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")

# ------------------------------------------------------------ CoreFoundation / IOKit types
CFTypeRef = ctypes.c_void_p
CFAllocatorRef = ctypes.c_void_p
CFStringRef = ctypes.c_void_p
CFSetRef = ctypes.c_void_p
IOHIDManagerRef = ctypes.c_void_p
IOHIDDeviceRef = ctypes.c_void_p
CFIndex = ctypes.c_long
IOReturn = ctypes.c_int
Boolean = ctypes.c_ubyte

kCFStringEncodingUTF8 = 0x08000100
kCFNumberSInt32Type = 3
kIOReturnSuccess = 0
kIOHIDReportTypeOutput = 1
kIOHIDReportTypeFeature = 2

cf.CFRelease.argtypes = [CFTypeRef]
cf.CFStringCreateWithCString.restype = CFStringRef
cf.CFStringCreateWithCString.argtypes = [CFAllocatorRef, ctypes.c_char_p, ctypes.c_uint32]
cf.CFStringGetCString.restype = Boolean
cf.CFStringGetCString.argtypes = [CFStringRef, ctypes.c_char_p, CFIndex, ctypes.c_uint32]
cf.CFNumberGetValue.restype = Boolean
cf.CFNumberGetValue.argtypes = [CFTypeRef, ctypes.c_int, ctypes.c_void_p]
cf.CFSetGetCount.restype = CFIndex
cf.CFSetGetCount.argtypes = [CFSetRef]
cf.CFSetGetValues.argtypes = [CFSetRef, ctypes.POINTER(ctypes.c_void_p)]

iokit.IOHIDManagerCreate.restype = IOHIDManagerRef
iokit.IOHIDManagerCreate.argtypes = [CFAllocatorRef, ctypes.c_uint32]
iokit.IOHIDManagerSetDeviceMatching.argtypes = [IOHIDManagerRef, CFTypeRef]
iokit.IOHIDManagerCopyDevices.restype = CFSetRef
iokit.IOHIDManagerCopyDevices.argtypes = [IOHIDManagerRef]
iokit.IOHIDManagerOpen.restype = IOReturn
iokit.IOHIDManagerOpen.argtypes = [IOHIDManagerRef, ctypes.c_uint32]
iokit.IOHIDDeviceGetProperty.restype = CFTypeRef
iokit.IOHIDDeviceGetProperty.argtypes = [IOHIDDeviceRef, CFStringRef]
iokit.IOHIDDeviceOpen.restype = IOReturn
iokit.IOHIDDeviceOpen.argtypes = [IOHIDDeviceRef, ctypes.c_uint32]
iokit.IOHIDDeviceClose.restype = IOReturn
iokit.IOHIDDeviceClose.argtypes = [IOHIDDeviceRef, ctypes.c_uint32]
iokit.IOHIDDeviceSetReport.restype = IOReturn
iokit.IOHIDDeviceSetReport.argtypes = [IOHIDDeviceRef, ctypes.c_int, CFIndex,
                                       ctypes.c_void_p, CFIndex]
iokit.IOHIDDeviceGetReport.restype = IOReturn
iokit.IOHIDDeviceGetReport.argtypes = [IOHIDDeviceRef, ctypes.c_int, CFIndex,
                                       ctypes.c_void_p, ctypes.POINTER(CFIndex)]


def _cfstr(text):
    """Create a CFString (caller owns it and must CFRelease)."""
    return cf.CFStringCreateWithCString(None, text.encode("utf-8"), kCFStringEncodingUTF8)


# Property keys are reused a lot, so create them once for the life of the process.
_KEY_VENDOR = _cfstr("VendorID")
_KEY_PRODUCT = _cfstr("ProductID")
_KEY_NAME = _cfstr("Product")
_KEY_FEATURE_LEN = _cfstr("MaxFeatureReportSize")
_KEY_OUTPUT_LEN = _cfstr("MaxOutputReportSize")

# ------------------------------------------------------------ HID helpers
def hid_devices():
    """Yield every present HID device (IOHIDDeviceRef). The refs stay valid for
    the duration of the iteration."""
    mgr = iokit.IOHIDManagerCreate(None, 0)
    if not mgr:
        return
    try:
        iokit.IOHIDManagerSetDeviceMatching(mgr, None)   # None matches all devices
        iokit.IOHIDManagerOpen(mgr, 0)
        device_set = iokit.IOHIDManagerCopyDevices(mgr)
        if not device_set:
            return
        try:
            n = cf.CFSetGetCount(device_set)
            arr = (ctypes.c_void_p * n)()
            cf.CFSetGetValues(device_set, arr)
            for i in range(n):
                yield arr[i]
        finally:
            cf.CFRelease(device_set)
    finally:
        cf.CFRelease(mgr)


def _int_prop(dev, key):
    ref = iokit.IOHIDDeviceGetProperty(dev, key)
    if not ref:
        return 0
    val = ctypes.c_int32(0)
    if cf.CFNumberGetValue(ref, kCFNumberSInt32Type, ctypes.byref(val)):
        return val.value
    return 0


def _str_prop(dev, key):
    ref = iokit.IOHIDDeviceGetProperty(dev, key)
    if not ref:
        return ""
    buf = ctypes.create_string_buffer(256)
    if cf.CFStringGetCString(ref, buf, len(buf), kCFStringEncodingUTF8):
        return buf.value.decode("utf-8", "replace")
    return ""


def attributes(dev):
    """Return (vendor_id, product_id) for a device."""
    return _int_prop(dev, _KEY_VENDOR), _int_prop(dev, _KEY_PRODUCT)


def product_name(dev):
    """Human-readable product string for a device, or ""."""
    return _str_prop(dev, _KEY_NAME)


def feature_len(dev):
    """MaxFeatureReportSize for a device (report-ID byte not included)."""
    return _int_prop(dev, _KEY_FEATURE_LEN)


def output_len(dev):
    """MaxOutputReportSize for a device (report-ID byte not included)."""
    return _int_prop(dev, _KEY_OUTPUT_LEN)


def open_device(dev):
    return iokit.IOHIDDeviceOpen(dev, 0) == kIOReturnSuccess


def close_device(dev):
    iokit.IOHIDDeviceClose(dev, 0)


def set_report(dev, report_type, buf):
    """Send a report. `buf[0]` is the report ID; a 0 means an unnumbered report,
    so the leading byte is dropped (same convention hidapi uses on macOS)."""
    data = bytes(buf)
    report_id = data[0]
    payload = data[1:] if report_id == 0 else data
    cbuf = (ctypes.c_ubyte * len(payload))(*payload)
    return iokit.IOHIDDeviceSetReport(dev, report_type, report_id,
                                      cbuf, len(payload)) == kIOReturnSuccess


def get_report(dev, report_type, report_id, length):
    """Read a report of `length` bytes, or None on failure."""
    cbuf = (ctypes.c_ubyte * length)()
    ln = CFIndex(length)
    if iokit.IOHIDDeviceGetReport(dev, report_type, report_id,
                                  cbuf, ctypes.byref(ln)) != kIOReturnSuccess:
        return None
    return bytes(cbuf[:ln.value])

# ------------------------------------------------------------ Razer protocol
RAZER_VID = 0x1532
VARSTORE = 0x01
TRANSACTION_IDS = [0x1F, 0x3F, 0xFF]
LED_IDS = [0x05, 0x00, 0x01, 0x04]
CONTROL_REPORT_LEN = 90          # Razer control report length (report ID 0, so 90 bytes)


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


def send(dev, report):
    """Send a control report as a feature report; return the device status byte
    (0x02 = success) or None on failure."""
    if not set_report(dev, kIOHIDReportTypeFeature, b"\x00" + bytes(report)):
        return None
    time.sleep(0.06)
    resp = get_report(dev, kIOHIDReportTypeFeature, 0, CONTROL_REPORT_LEN)
    if resp is None:
        return None
    return resp[0]                                   # status field of the reply


def set_static(dev, rgb, brightness):
    """Try the known static-colour commands on a device. Returns a short
    description of the method that worked, or None."""
    r, g, b = rgb
    for tid in TRANSACTION_IDS:                      # newer devices
        for led in LED_IDS:
            if send(dev, build_report(tid, 0x0F, 0x02,
                                      [VARSTORE, led, 0x01, 0x00, 0x00, 0x01, r, g, b])) == 0x02:
                send(dev, build_report(tid, 0x0F, 0x04, [VARSTORE, led, brightness]))
                return f"extended matrix (tid=0x{tid:02X}, led=0x{led:02X})"
    for tid in TRANSACTION_IDS:                      # older devices
        if send(dev, build_report(tid, 0x03, 0x0A, [0x06, r, g, b])) == 0x02:
            send(dev, build_report(tid, 0x03, 0x03, [VARSTORE, 0x05, brightness]))
            return f"standard matrix (tid=0x{tid:02X})"
    return None

# ------------------------------------------------------------ colour helpers
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

# ------------------------------------------------------------ custom drivers
CUSTOM_DRIVERS_DIR = "custom_drivers"
DRIVER_SUFFIX = "_mac"           # only load this platform's drivers


def discover_custom_drivers():
    """Import the macOS custom drivers in ./custom_drivers/ (files ending in
    `_mac.py`) that expose the PIDS + apply_static contract:

      PIDS          - dict of {product_id: name} it handles
      apply_static(rgb, brightness) -> list of (name, ok, detail) results
    """
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), CUSTOM_DRIVERS_DIR)
    if not os.path.isdir(folder):
        return []
    # Let custom drivers `import razer_static_mac` and reuse this live module,
    # even while we are running as the __main__ script.
    sys.modules.setdefault("razer_static_mac", sys.modules[__name__])
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

# ------------------------------------------------------------ actions
def apply_generic(rgb, brightness, skip_pids):
    """Apply a static colour to standard Razer control-interface devices.
    Devices whose PID is in `skip_pids` are left to their custom driver.
    Returns a list of (name, ok, detail)."""
    seen, done = {}, set()
    for dev in hid_devices():
        vid, pid = attributes(dev)
        if vid != RAZER_VID or pid in skip_pids:
            continue
        seen[pid] = product_name(dev) or f"PID 0x{pid:04X}"
        if pid in done or feature_len(dev) != CONTROL_REPORT_LEN:
            continue
        if not open_device(dev):
            continue
        try:
            if set_static(dev, rgb, brightness):
                done.add(pid)
        finally:
            close_device(dev)
    return [(name, pid in done, "" if pid in done else "no interface accepted the command")
            for pid, name in seen.items()]


def list_devices(drivers):
    """Return a list of (name, pid, handler) for every present Razer device."""
    owner = {pid: mod for mod in drivers for pid in mod.PIDS}
    found = {}
    for dev in hid_devices():
        vid, pid = attributes(dev)
        if vid != RAZER_VID:
            continue
        found.setdefault(pid, product_name(dev) or f"PID 0x{pid:04X}")
    rows = []
    for pid, name in sorted(found.items()):
        mod = owner.get(pid)
        handler = f"custom driver ({mod.__name__})" if mod else "generic"
        rows.append((name, pid, handler))
    return rows

# ------------------------------------------------------------ output
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

# ------------------------------------------------------------ main
def main():
    p = argparse.ArgumentParser(description="Set a static colour on Razer devices (macOS).")
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
