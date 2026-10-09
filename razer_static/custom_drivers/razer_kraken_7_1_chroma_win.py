#!/usr/bin/env python3
"""
razer_kraken_7_1_chroma_win.py - custom driver for the Razer Kraken 7.1 Chroma (Windows).

The Kraken does not speak the normal Razer control protocol, so it needs its own
driver instead of the generic path in razer_static_win.py. The orchestrator in
razer_static_win.py discovers this file automatically (via its PIDS + apply_static
contract), so you normally never call it by hand.

It reuses the HID helpers from razer_static_win (imported from the parent folder),
so this file only contains what is specific to this headset.

Protocol follows OpenRazer's razerkraken driver: a 37-byte HID *output* report
(report ID 0x04) that writes values into the headset's memory:
  1) the colour (R, G, B) to the static colour slot
  2) the effect byte (0x01 = on/static) to the LED mode address
This model has no separate brightness setting, so --brightness is ignored.

Standalone use (mainly for debugging; the addresses can be overridden):
  python razer_kraken_7_1_chroma_win.py 0000ff
  python razer_kraken_7_1_chroma_win.py 0000ff --addr 1189 --mode-addr 1008
"""
import argparse
import ctypes
import os
import sys
import time

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import razer_static_win as rs

PIDS = {0x0504: "Razer Kraken 7.1 Chroma"}

LED_MODE_ADDR = 0x1008
COLOUR_ADDR = 0x1189
EFFECT_STATIC = 0x01          # bit 0 = on/static
REPORT_ID, WRITE_RAM, REPORT_LEN = 0x04, 0x40, 37

rs.hid.HidD_SetOutputReport.argtypes = [rs.H, ctypes.c_void_p, ctypes.c_ulong]
rs.hid.HidD_SetOutputReport.restype = ctypes.c_ubyte


def _report(address, args):
    r = (ctypes.c_ubyte * REPORT_LEN)()
    r[0], r[1], r[2] = REPORT_ID, WRITE_RAM, len(args)
    r[3], r[4] = address >> 8, address & 0xFF
    for i, b in enumerate(args):
        r[5 + i] = b
    return r


def _send(h, report):
    ok = rs.hid.HidD_SetOutputReport(h, report, REPORT_LEN)
    time.sleep(max(report[2] * 0.015, 0.05))
    return bool(ok)


def apply_static(rgb, brightness, addr=COLOUR_ADDR, mode_addr=LED_MODE_ADDR):
    """Apply a static colour to any Kraken 7.1 Chroma found. This model has no
    separate intensity byte, so `brightness` is ignored."""
    r, g, b = rgb
    found, handled, why = {}, set(), {}
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
            olen = rs.output_len(h)
            if olen != REPORT_LEN:
                why[pid] = f"mi_03 output report is {olen} bytes, expected {REPORT_LEN}"
                continue
            if (_send(h, _report(addr, [r, g, b]))
                    and _send(h, _report(mode_addr, [EFFECT_STATIC]))):
                handled.add(pid)
            else:
                why[pid] = "device rejected the output report"
        finally:
            rs.k32.CloseHandle(h)
    return [(name, pid in handled,
             "custom driver" if pid in handled
             else why.get(pid, "no lighting interface accepted the report"))
            for pid, name in found.items()]


def main():
    p = argparse.ArgumentParser(description="Static colour for the Razer Kraken 7.1 Chroma (Windows).")
    p.add_argument("colour", type=rs.parse_colour, help="hex colour, e.g. 0000ff")
    p.add_argument("--addr", type=lambda s: int(s, 16), default=COLOUR_ADDR,
                   help="colour address in hex (default 1189)")
    p.add_argument("--mode-addr", type=lambda s: int(s, 16), default=LED_MODE_ADDR,
                   help="LED mode address in hex (default 1008)")
    a = p.parse_args()

    print(f"Kraken 7.1 Chroma: applying {rs.hex_colour(a.colour)}\n")
    results = apply_static(a.colour, 255, a.addr, a.mode_addr)
    if not results:
        sys.exit("  no Kraken 7.1 Chroma found")
    rs.print_results(results)


if __name__ == "__main__":
    main()
