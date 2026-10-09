#!/usr/bin/env python3
"""
razer_deathadder_2013_win.py - custom driver for the Razer DeathAdder 2013 (Windows).

This mouse only has green LEDs (logo + scroll wheel), so it cannot show other
colours. What it CAN do is switch them on or off, which the generic static-colour
path does not know about. Behaviour of this driver:

  - black (000000) or --brightness 0  -> LEDs OFF
  - any other colour                  -> LEDs ON (stays green, it is the only colour it has)

It uses the classic Razer "set LED state" command (class 0x03, id 0x00) on the
logo (0x04), scroll wheel (0x01) and backlight (0x05) LEDs, as OpenRazer does
for old mice. The orchestrator in razer_static_win.py discovers this file automatically
(via its PIDS + apply_static contract).

Standalone use (mainly for debugging):
  python razer_deathadder_2013_win.py 000000     (off)
  python razer_deathadder_2013_win.py 00ff00     (on)
"""
import argparse
import os
import sys

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import razer_static_win as rs

PIDS = {0x0037: "Razer DeathAdder 2013"}

CMD_CLASS, CMD_LED_STATE, CMD_LED_BRIGHTNESS = 0x03, 0x00, 0x03
LEDS = {0x04: "logo", 0x01: "scroll wheel", 0x05: "backlight"}


def _set_state(h, on, brightness):
    """Try to switch the LEDs on/off through one open handle. Returns the list
    of LED names the device acknowledged."""
    acked = []
    for tid in rs.TRANSACTION_IDS:
        for led, name in LEDS.items():
            if rs.send(h, rs.build_report(tid, CMD_CLASS, CMD_LED_STATE,
                                          [rs.VARSTORE, led, 1 if on else 0])) == 0x02:
                acked.append(name)
                if on:
                    rs.send(h, rs.build_report(tid, CMD_CLASS, CMD_LED_BRIGHTNESS,
                                               [rs.VARSTORE, led, brightness]))
        if acked:
            break                                  # this transaction id works
    return acked


def apply_static(rgb, brightness, **_):
    """Switch the DeathAdder 2013 LEDs on (any colour) or off (black or
    brightness 0). Returns a list of (name, ok, detail)."""
    on = any(rgb) and brightness > 0
    found, done, why = {}, {}, {}
    for path in rs.hid_paths():
        if "vid_1532" not in path.lower():
            continue
        h = rs.open_path(path)
        if not h:
            continue
        try:
            vid, pid = rs.attributes(h)
            if vid != rs.RAZER_VID or pid not in PIDS:
                continue
            found[pid] = rs.product_name(h) or PIDS[pid]
            if pid in done:
                continue
            flen = rs.feature_len(h)
            if flen != rs.CONTROL_REPORT_LEN:
                why.setdefault(pid, f"control interface not found (feature report {flen} bytes)")
                continue
            acked = _set_state(h, on, max(0, min(255, brightness)))
            if acked:
                done[pid] = f"LEDs {'on' if on else 'off'} ({', '.join(acked)})"
        finally:
            rs.k32.CloseHandle(h)
    return [(name, pid in done,
             done.get(pid) or why.get(pid, "no interface accepted the LED command"))
            for pid, name in found.items()]


def main():
    p = argparse.ArgumentParser(description="LEDs on/off for the Razer DeathAdder 2013 (Windows).")
    p.add_argument("colour", type=rs.parse_colour, help="000000 = off, anything else = on")
    p.add_argument("--brightness", type=int, default=255, help="0-255 (0 = off, default 255)")
    a = p.parse_args()

    results = apply_static(a.colour, a.brightness)
    if not results:
        sys.exit("  no Razer DeathAdder 2013 found")
    rs.print_results(results)


if __name__ == "__main__":
    main()
