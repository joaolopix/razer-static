# RazerStatic

**Disclaimer:** This is an unofficial hobby project, not affiliated with or endorsed by Razer Inc, and I am not responsible if anything breaks. It sends lighting commands directly to your hardware over USB/HID, so use it at your own risk. Razer and Chroma are trademarks of Razer Inc.

This project lets you set a static colour on Razer devices without running Synapse, background services, or installing dependencies.

## Layout

```
razer_static/
├── razer_static.py            # optional launcher: picks the right backend for your OS
├── razer_static_win.py        # Windows backend (works on its own for most devices)
├── razer_static_mac.py        # macOS backend   (works on its own for most devices)
└── custom_drivers/            # only needed for devices with their own protocol
    ├── razer_kraken_ultimate_win.py / _mac.py
    ├── razer_kraken_7_1_chroma_win.py / _mac.py
    └── razer_deathadder_2013_win.py / _mac.py
```

## Why this exists

Razer Synapse and the big open-source alternatives do a lot, but they also run background services, ship drivers, auto-update and pull in many dependencies. If all you want is *"make my keyboard a fixed colour or no colour at all and leave it alone"*, that is a lot of software (and attack surface) for one tiny job.

This project goes the other way:

- **Standalone scripts.** Each file is a short, readable Python script you can audit in a few minutes.
- **Zero dependencies.** Python standard library only. On Windows it talks to the HID stack through the DLLs that ship with Windows (`hid.dll`, `setupapi.dll`, `kernel32.dll`) via `ctypes`. On macOS it uses the system IOKit framework via `ctypes`.
- **Nothing resident.** It sets the colour and exits. No service, no tray icon, no autostart.
- **No network code.** The scripts never open a socket or make any web request, and they don't spawn other programs.
- **Take only what you need.** You do not need the whole project. Copy just the script(s) for your OS and device (see below).
- **The colour sticks.** The effect is written with the VARSTORE flag, so most devices keep it in onboard memory after the script exits (the same mechanism OpenRazer and Polychromatic use).

## Requirements

- Python 3.6 or newer
- Windows, or macOS (macOS may ask for *Input Monitoring* permission for your terminal the first time)

You do not need the whole project; just grab the backend script for your OS (`razer_static_win.py` or `razer_static_mac.py`). The `razer_static_<os>.py` backend is the engine. It handles standard Razer devices (most keyboards and mice) by itself. A few devices (the Kraken headsets, the old DeathAdder 2013) don't speak the standard protocol, so they have small **custom drivers** in `custom_drivers/`. The backend finds them automatically: any `*_win.py` / `*_mac.py` file in that folder that exposes `PIDS` and `apply_static` is picked up, and nothing needs to be registered or edited. If some device doesn't work for you, likely you will need to implement a custom driver for it.

## Usage

```
python3 razer_static.py <colour> [--brightness 0-255]
python3 razer_static.py --list

```

| Option | Meaning |
|---|---|
| `<colour>` | Hex colour, with or without `#` (e.g. `ff0000`, `#00ff88`) |
| `--brightness N` | 0-255, default 255 |
| `--list` | List the connected Razer devices and which driver handles each |



## Tested Devices

This script has **only** been tested on the following devices:

- Razer BlackWidow Chroma (2016)
- Razer BlackWidow (2019)
- Razer DeathAdder (2013)
- Razer Viper
- Razer Kraken 7.1 Chroma
- Razer Kraken Ultimate

## Adding your own device

Most Razer keyboards and mice from the Chroma era onward should work through the generic path with no changes. If your device needs its own protocol, drop a `<name>_win.py` / `<name>_mac.py` into `custom_drivers/` that defines:

```python
PIDS = {0x1234: "Razer Something"}          # USB product IDs it handles

def apply_static(rgb, brightness):          # rgb is an (r, g, b) tuple
    ...                                     # return a list of (name, ok, detail)
```

and `import razer_static_win as rs` (or `_mac`) to reuse the HID helpers. The existing drivers in `custom_drivers/` are short and make good templates.

