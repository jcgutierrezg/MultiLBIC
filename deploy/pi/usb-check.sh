#!/usr/bin/env bash
# MultiLBIC boot check: bring the laser board back if it is missing.
#
# Twice (2026-10-19 and -20) the laser Xiao did not appear on USB after
# the Pi started, with no error logged, and came back only when its
# cable was replugged. The cause is not pinned down: a cold start with
# the supply on first did not reproduce it. A replug works, and cutting
# the Pi's USB power in software is the same thing, so this does that,
# once, only when the Xiao is missing. See docs/hardware.md, "USB at boot".
#
# Runs as root at boot (multilbic-usb-check.service). By hand:
#   sudo multilbic-usb-check            check, cycle only if missing
#   sudo multilbic-usb-check --force    cycle even if present (a test)
#
# Every run logs one line per outcome to the journal:
#   journalctl -t multilbic-usb-check
#
# Exit status: 0 when the Xiao is present at the end, 1 when it is not.
set -u

# Overridable so tests/test_deploy.py can run this against a fake
# by-id folder and a fake uhubctl.
BYID="${MULTILBIC_BYID_DIR:-/dev/serial/by-id}"
XIAO_GLOB="$BYID/usb-Seeed_Seeed_XIAO_M0_*"
WAIT_AT_BOOT_S="${MULTILBIC_WAIT_AT_BOOT_S:-15}"
WAIT_AFTER_CYCLE_S="${MULTILBIC_WAIT_AFTER_CYCLE_S:-20}"
POWER_OFF_S="${MULTILBIC_POWER_OFF_S:-3}"

log() { echo "$*"; }

xiao_present() {
    compgen -G "$XIAO_GLOB" > /dev/null
}

wait_for_xiao() {
    local seconds=$1
    for _ in $(seq "$seconds"); do
        xiao_present && return 0
        sleep 1
    done
    xiao_present
}

others() {
    # What else is there, for the log: SKR, miniSMU, TFT adapter.
    local found=""
    compgen -G "$BYID/usb-marlinfw.org_*" > /dev/null && found+=" SKR"
    compgen -G "$BYID/usb-Undalogic_*" > /dev/null && found+=" miniSMU"
    compgen -G "$BYID/usb-FTDI_*" > /dev/null && found+=" TFT-adapter"
    echo "${found:- none}"
}

cycle_usb() {
    # On a Raspberry Pi 4 the USB ports share one power switch, reached
    # through both hubs: 1-1 (the USB 2 hub) and 2 (the USB 3 root hub).
    # Power is only cut when both are off. Every USB device drops for a
    # few seconds, which is harmless while nothing is using them.
    uhubctl -l 2 -a off > /dev/null
    uhubctl -l 1-1 -a off > /dev/null
    sleep "$POWER_OFF_S"
    uhubctl -l 1-1 -a on > /dev/null
    uhubctl -l 2 -a on > /dev/null
}

force=false
[ "${1:-}" = "--force" ] && force=true

if ! command -v uhubctl > /dev/null; then
    log "uhubctl not installed: cannot recover a missing Xiao (sudo apt install uhubctl)"
    wait_for_xiao "$WAIT_AT_BOOT_S"
    exit $?
fi

if ! $force && wait_for_xiao "$WAIT_AT_BOOT_S"; then
    log "Xiao present; others:$(others)"
    exit 0
fi

if $force; then
    log "forced USB power cycle (Xiao present: $(xiao_present && echo yes || echo no))"
else
    log "Xiao missing after ${WAIT_AT_BOOT_S} s; others:$(others); cycling USB power"
fi
cycle_usb

if wait_for_xiao "$WAIT_AFTER_CYCLE_S"; then
    log "Xiao present after USB power cycle; others:$(others)"
    exit 0
fi
log "Xiao still missing after USB power cycle; others:$(others); replug it by hand"
exit 1
