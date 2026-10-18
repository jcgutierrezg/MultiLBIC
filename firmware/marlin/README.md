# Marlin configuration

Only the two files changed from upstream are kept here. The rest of the
firmware is stock **Marlin 2.1.2.4**. This was checked on 2026-10-17 by
diffing the original folder against the upstream tag: no other file
differed, `config.ini` included.

## Rebuilding

1. `git clone --depth 1 --branch 2.1.2.4 https://github.com/MarlinFirmware/Marlin.git`
2. Copy `Configuration.h` and `Configuration_adv.h` from here into
   `Marlin/Marlin/`, replacing the stock ones.
3. Build with PlatformIO, environment **`LPC1769`** (BTT SKR 1.4 Turbo).
4. Copy `firmware.bin` onto the SKR's SD card and power-cycle the board.

## Before trusting these values

`EEPROM_SETTINGS` is enabled, so the board may be running values saved
with `M500` that differ from what is compiled here. Read the live values
with `M503`. After a reflash, `M502` then `M500` restores the compiled
defaults.

What the settings mean for the software is in
[`docs/hardware.md`](../../docs/hardware.md#motion-controller-marlin).
