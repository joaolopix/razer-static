#!/usr/bin/env python3
"""
razer_kraken_7_1_chroma_mac.py - custom driver for the Razer Kraken 7.1 Chroma (macOS).

The Kraken does not speak the normal Razer control protocol, so it needs its own
driver instead of the generic path in razer_static_mac.py. The orchestrator in
razer_static_mac.py discovers this file automatically (via its PIDS + apply_static
contract), so you normally never call it by hand.

It reuses the HID helpers from razer_static_mac (imported from the parent folder),
so this file only contains what is specific to this headset.

Protocol follows OpenRazer's razerkraken driver: a 37-byte HID *output* report
(report ID 0x04) that writes values into the headset's memory:
  1) the colour (R, G, B) to the static colour slot
  2) the effect byte (0x01 = on/static) to the LED mode address
This model has no separate brightness setting, so --brightness is ignored.

Standalone use (mainly for debugging; the addresses can be overridden):
  python3 razer_kraken_7_1_chroma_mac.py 0000ff
  python3 razer_kraken_7_1_chroma_mac.py 0000ff --addr 1189 --mode-addr 1008
"""
import argparse
import os
import sys
import time

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import razer_static_mac as rs

PIDS = {0x0504: "Razer Kraken 7.1 Chroma"}

LED_MODE_ADDR = 0x1008
COLOUR_ADDR = 0x1189
EFFECT_STATIC = 0x01
REPORT_ID, WRITE_RAM, REPORT_LEN = 0x04, 0x40, 37


def _report(address, args):
    r = bytearray(REPORT_LEN)
    r[0], r[1], r[2] = REPORT_ID, WRITE_RAM, len(args)
    r[3], r[4] = address >> 8, address & 0xFF
    r[5:5 + len(args)] = bytes(args)
    return r


def _send(h, report):
    ok = rs.set_report(h, rs.kIOHIDReportTypeOutput, report)
    time.sleep(max(report[2] * 0.015, 0.05))
    return ok


def apply_static(rgb, brightness, addr=COLOUR_ADDR, mode_addr=LED_MODE_ADDR):
    """Apply a static colour to any Kraken 7.1 Chroma found. `brightness` is
    ignored (this model has no intensity byte). Every HID interface is
    tried; IOKit rejects the report on the ones that don't define it."""
    r, g, b = rgb
    colour_report = _report(addr, [r, g, b])
    mode_report = _report(mode_addr, [EFFECT_STATIC])

    found, handled, opened = {}, set(), set()
    for dev in rs.hid_devices():
        vid, pid = rs.attributes(dev)
        if vid != rs.RAZER_VID or pid not in PIDS:
            continue
        found[pid] = rs.product_name(dev) or PIDS[pid]
        if pid in handled:
            continue
        if not rs.open_device(dev):
            continue
        opened.add(pid)
        try:
            if _send(dev, colour_report) and _send(dev, mode_report):
                handled.add(pid)
        finally:
            rs.close_device(dev)

    results = []
    for pid, name in found.items():
        if pid in handled:
            detail = "custom driver"
        elif pid not in opened:
            detail = "could not open device (try Input Monitoring permission or sudo)"
        else:
            detail = "no lighting interface accepted the report"
        results.append((name, pid in handled, detail))
    return results


def main():
    p = argparse.ArgumentParser(description="Static colour for the Razer Kraken 7.1 Chroma (macOS).")
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
