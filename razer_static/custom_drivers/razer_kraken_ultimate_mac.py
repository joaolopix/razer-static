#!/usr/bin/env python3
"""
razer_kraken_ultimate_mac.py - custom driver for the Razer Kraken Ultimate (macOS).

The Kraken does not speak the normal Razer control protocol, so it needs its own
driver instead of the generic path in razer_static_mac.py. The orchestrator in
razer_static_mac.py discovers this file automatically (via its PIDS + apply_static
contract), so you normally never call it by hand.

It reuses the IOKit / HID helpers from razer_static_mac (imported from the parent
folder), so this file only contains what is specific to the Kraken.

Protocol follows OpenRazer's razerkraken driver: a 37-byte HID *output* report
(report ID 0x04) that writes values into the headset's memory:
  1) the colour (R, G, B, intensity) to the static colour slot
  2) the effect byte (0x01 = on/static) to the LED mode address

Standalone use (mainly for debugging):
  python3 razer_kraken_ultimate_mac.py 0000ff
  python3 razer_kraken_ultimate_mac.py ff0000 --brightness 128
"""
import argparse
import os
import sys
import time

sys.dont_write_bytecode = True   # don't scatter __pycache__ folders

# This driver lives in razer_static/custom_drivers/ and reuses the shared toolkit
# in razer_static/razer_static_mac.py, so put the parent folder on the import path
# before importing it. When launched by the orchestrator this is a no-op.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import razer_static_mac as rs

# Contract used by the orchestrator: USB product IDs this driver handles.
# A PID identifies the device *model* (same on every machine), not an individual unit.
PIDS = {0x0527: "Razer Kraken Ultimate"}

LED_MODE_ADDR = 0x172D        # "Kylie" LED mode address (OpenRazer: KYLIE_SET_LED_ADDRESS)
COLOUR_ADDR = 0x1189          # live colour slot used by custom mode (KYLIE_CUSTOM_ADDRESS_START)
EFFECT_STATIC = 0x01          # bit 0 = on/static
REPORT_ID, WRITE_RAM, REPORT_LEN = 0x04, 0x40, 37


def _report(address, args):
    """Build a 37-byte Kraken output report (byte 0 is the report ID) that writes
    `args` to `address`."""
    r = bytearray(REPORT_LEN)
    r[0], r[1], r[2] = REPORT_ID, WRITE_RAM, len(args)
    r[3], r[4] = address >> 8, address & 0xFF
    r[5:5 + len(args)] = bytes(args)
    return r


def _send(h, report):
    """Send one output report; the device wants ~15 ms per written byte."""
    ok = rs.set_report(h, rs.kIOHIDReportTypeOutput, report)
    time.sleep(max(report[2] * 0.015, 0.05))
    return ok


def apply_static(rgb, brightness, addr=COLOUR_ADDR):
    """Apply a static colour to any Kraken found. Returns a list of
    (name, ok, detail), one per Kraken present (empty if none).

    The Kraken exposes several HID interfaces; only the control interface
    defines output report 0x04, so instead of guessing which one that is (its
    reported sizes differ from Windows), we try each interface and let IOKit
    accept it on the right one and reject it on the others."""
    r, g, b = rgb
    intensity = max(0, min(255, brightness))
    colour_report = _report(addr, [r, g, b, intensity])
    mode_report = _report(LED_MODE_ADDR, [EFFECT_STATIC])

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
    p = argparse.ArgumentParser(description="Static colour for the Razer Kraken Ultimate (macOS).")
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
