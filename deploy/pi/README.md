# Raspberry Pi deployment

Kept here so the Pi can be rebuilt if its microSD card fails.

- `Serials.txt`: the USB serial numbers the udev rules match on, to give
  the boards fixed names (`/dev/SKR`, `/dev/S_LASER`, `/dev/TFT35`).
  Which number belongs to which board is not recorded yet.
- **Owed:** the udev rules file itself, copied from the Pi
  (`/etc/udev/rules.d/`).
- **Owed:** SSH access and the install steps (uv, Python 3.14, Tk),
  written in Phase 0/1.
