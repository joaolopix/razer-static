#!/usr/bin/env python3
"""
razer_kraken_ultimate_win.py - custom driver for the Razer Kraken Ultimate (Windows).

The Kraken does not speak the normal Razer control protocol, so it needs its own
driver instead of the generic path in razer_static_win.py. The orchestrator in
razer_static_win.py discovers this file automatically (via its PIDS + apply_static
contract), so you normally never call it by hand.

It reuses the Win32 / HID helpers from razer_static_win (imported from the parent
folder), so this file only contains what is specific to the Kraken.

Protocol follows OpenRazer's razerkraken driver: a 37-byte HID *output* report
(report ID 0x04) on interface 3 that writes values into the headset's memory:
  1) the colour (R, G, B, intensity) to the static colour slot
  2) the effect byte (0x01 = on/static) to the LED mode address

Standalone use (mainly for debugging):
  python razer_kraken_ultimate_win.py 0000ff
  python razer_kraken_ultimate_win.py ff0000 --brightness 128
"""
import argparse
import ctypes
import os
import sys
import time

sys.dont_write_bytecode = True   # don't scatter __pycache__ folders

# This driver lives in razer_static/custom_drivers/ and reuses the shared toolkit
# in razer_static/razer_static_win.py, so put the parent folder on the import path
# before importing it. When launched by the orchestrator this is a no-op.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import razer_static_win as rs

# Contract used by the orchestrator: USB product IDs this driver handles.
# A PID identifies the device *model* (same on every PC), not an individual unit.
PIDS = {0x0527: "Razer Kraken Ultimate"}

LED_MODE_ADDR = 0x172D        # "Kylie" LED mode address (OpenRazer: KYLIE_SET_LED_ADDRESS)
COLOUR_ADDR = 0x1189          # live colour slot used by custom mode (KYLIE_CUSTOM_ADDRESS_START)
EFFECT_STATIC = 0x01          # bit 0 = on/static
REPORT_ID, WRITE_RAM, REPORT_LEN = 0x04, 0x40, 37

rs.hid.HidD_SetOutputReport.argtypes = [rs.H, ctypes.c_void_p, ctypes.c_ulong]
rs.hid.HidD_SetOutputReport.restype = ctypes.c_ubyte


def _report(address, args):
    """Build a 37-byte Kraken output report that writes `args` to `address`."""
    r = (ctypes.c_ubyte * REPORT_LEN)()
    r[0], r[1], r[2] = REPORT_ID, WRITE_RAM, len(args)
    r[3], r[4] = address >> 8, address & 0xFF
    for i, b in enumerate(args):
        r[5 + i] = b
    return r


def _send(h, report):
    """Send one output report; the device wants ~15 ms per written byte."""
    ok = rs.hid.HidD_SetOutputReport(h, report, REPORT_LEN)
    time.sleep(max(report[2] * 0.015, 0.05))
    return bool(ok)


def apply_static(rgb, brightness, addr=COLOUR_ADDR):
    """Apply a static colour to any Kraken found. Returns a list of
    (name, ok, detail), one per Kraken present (empty if none)."""
    r, g, b = rgb
    intensity = max(0, min(255, brightness))
    found, handled = {}, set()
    for path in rs.hid_paths():
        low = path.lower()
        if "vid_1532" not in low:
            continue
        h = rs.open_path(path)
        if not h:
            continue
        try:
            vid, pid = rs.attributes(h)
            if vid != rs.RAZER_VID or pid not in PIDS:
                continue
            found[pid] = rs.product_name(h) or PIDS[pid]
            if "mi_03" not in low or pid in handled:
                continue
            if rs.output_len(h) != REPORT_LEN:
                continue                     # not the lighting collection
            if (_send(h, _report(addr, [r, g, b, intensity]))
                    and _send(h, _report(LED_MODE_ADDR, [EFFECT_STATIC]))):
                handled.add(pid)
        finally:
            rs.k32.CloseHandle(h)
    return [(name, pid in handled,
             "custom driver" if pid in handled else "no lighting interface accepted the report")
            for pid, name in found.items()]


def main():
    p = argparse.ArgumentParser(description="Static colour for the Razer Kraken Ultimate (Windows).")
    p.add_argument("colour", type=rs.parse_colour, help="hex colour, e.g. 0000ff")
    p.add_argument("--brightness", type=int, default=255, help="0-255 (default 255)")
    p.add_argument("--addr", type=lambda s: int(s, 16), default=COLOUR_ADDR,
                   help="colour address in hex (default 1189)")
    a = p.parse_args()

    print(f"Kraken: applying {rs.hex_colour(a.colour)} at brightness "
          f"{max(0, min(255, a.brightness))}\n")
    results = apply_static(a.colour, a.brightness, a.addr)
    if not results:
        sys.exit("  no supported Kraken found")
    rs.print_results(results)


if __name__ == "__main__":
    main()
