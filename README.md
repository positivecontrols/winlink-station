# winlink-station

Scripts and config for running [Pat](https://getpat.io/) Winlink on a Raspberry Pi with three
radios, plus diagnostics for the problems that made those radios hard to get working.

| Menu entry | Radio | Modem | Pat web UI |
|---|---|---|---|
| Pat (IC-7300) ARDOP | Icom IC-7300 | ardopcf on port 8515 | `localhost:8080` |
| Pat (IC-7300) VARA (XARA) | Icom IC-7300 | XARA on port 8300 | `localhost:8080` |
| Pat (QMX) ARDOP | QRP Labs QMX | ardopcf on port 8615 | `localhost:8081` |
| Pat (QMX) VARA (XARA) | QRP Labs QMX | XARA on port 8400 | `localhost:8081` |
| Pat (UV-82HP) Packet | Baofeng UV-82HP + Digirig Mobile | Direwolf on port 8000 | `localhost:8080` |
| Pat: stop all radios | all | | |

One click stops whatever was running and starts the radio you picked. Transmit power is never
changed, so set it on the radio.

**Status: provided as-is.** This is one station's setup, not a general tool, so expect to edit it.
Issues are welcome, but replies may be slow and support isn't promised.

## Built with AI

This was written by [Claude Code](https://claude.com/claude-code) working with KJ4PRT, who set the
requirements, made the design decisions, and ran the on-air tests as control operator.

## What has been tested

These results came from the original station in 2026:

- **IC-7300, ARDOP:** sent a real Winlink message through a gateway on 80m, 6 September.
- **IC-7300, XARA:** 30 complete VARA Winlink sessions on 40m and 20m at 10% power, 31 October.
- **QMX, ARDOP:** sent a real Winlink message, 6 September.
- **UV-82HP, packet:** sent a real Winlink message on 2m, 8 September.
- **QMX, XARA:** not tested on air.

**This repo is a cleaned-up copy of that station, and the copy hasn't been run against a radio.**
Paths and callsigns became settings, and some scripts gained safety checks. The tests in `tests/`
cover the two control libraries and the safety checks using a fake serial port. The shell scripts
have had a syntax check, and only the launcher's stop path, the QMX start and stop scripts, and the
desktop installer have been run, against stand-in commands.

The diagnostics have only been used on the radios they're named for. CI-V menu numbers change
between firmware versions, so check them on yours.

## Transmitting

You need an amateur license, and you are the control operator for everything these scripts send.
Stay at the radio when you run anything marked as transmitting below.

### IC-7300 (`ic7300/`)

| Script | What it does | Transmits? |
|---|---|---|
| `ic7300.py` | CI-V control library. Run it to print the radio's status. | Only if your code calls `transmit()` |
| `rx_check.py` | Decodes FT8 to prove the receive chain works. Needs `jt9`. | No |
| `ardop_listen.py` | Confirms audio reaches the ARDOP modem. Needs `MYCALL` set. | Only if a station calls you |
| `tx_monitor.py` | Watches power, ALC, and SWR through rigctld. | No |
| `menu_scan.py` | Lists the CI-V menu items your radio answers. | No |
| `find_af_level.py` | Finds the USB AF Output Level menu item by measuring it. Changes settings briefly, then restores them. | No |
| `swr_check.py FREQ_MHZ` | Listens first, then measures SWR. | **Yes**, 2 s at 20% power |
| `calibrate_drive.py --transmit` | Sweeps audio drive against the ALC meter. Doesn't check that the channel is clear. | **Yes** |
| `try_gateways.py CALL:FREQ ...` | Calls a list of ARDOP gateways in turn. | **Yes** |

The serial port has one owner, so scripts that use `ic7300.py` directly need rigctld stopped first.
`tx_monitor.py` goes through rigctld and can run alongside it.

### QMX (`qmx/`)

| Script | What it does | Transmits? |
|---|---|---|
| `qmx.py` | CAT control library. | Only if your code calls `transmit()` |
| `menu_dump.py` | Dumps the radio's whole menu tree to JSON. | No |
| `set_usb_mode.py` | Forces USB mode, which ARDOP needs. | No |
| `qmx_raw_cat.sh` | Sends a raw CAT command through rigctld. | Depends on the command |
| `start_pat_qmx.sh`, `stop_pat_qmx.sh` | Start and stop the QMX stack. | Only when Pat connects |

## Setup

1. Install Pat, [ardopcf](https://github.com/pflarue/ardop), Hamlib, Direwolf, `python3-serial`, and
   `python3-numpy`. `rx_check.py` also needs WSJT-X for `jt9`. For the VARA stacks, also install
   [XARA](https://github.com/x0rro/xara) as `/usr/local/bin/xara`. XARA is a separate project, and
   checking how VARA's license terms apply to your use is up to you.
2. Copy `system/udev/*.rules` to `/etc/udev/rules.d/`, and replace `YOUR_SERIAL` as each file
   explains. Your user needs to be in the `dialout` group.
3. Copy `system/systemd/*.service` to `/etc/systemd/system/`, change `User=pi` if needed, and run
   `sudo systemctl daemon-reload`. Leave `ardopcf` disabled, because the launcher starts it.
4. Set your calibrated audio level in `ardopcf.service` and `xara-ic7300.service`. The `93` there is
   for one station, so find yours with `calibrate_drive.py`. Set `MYCALL` in `xara-ic7300.service`
   too, because it won't start with the placeholder.
5. Install `system/sudoers-pat-launch` as the file explains, so the launcher can control the
   services.
6. Write `~/.config/pat/config.json` for the IC-7300 and UV-82HP, and `config-qmx.json` for the QMX:

   | Setting | `config.json` | `config-qmx.json` |
   |---|---|---|
   | `http_addr` | `localhost:8080` | `localhost:8081` |
   | `hamlib_rigs` | `IC7300` at `localhost:4532` | `QMX` at `localhost:4533` |
   | `ardop.addr` | `localhost:8515` | `localhost:8615` |
   | `ardop.rig` | `IC7300` | `QMX` |
   | `ardop.ptt_ctrl` | `true` | `true` |
   | `varahf.addr` | `localhost:8300` | `localhost:8400` |
   | `varahf.rig` | `IC7300` | `QMX` |
   | `varahf.ptt_ctrl` | `false` | `false` |
   | `agwpe.addr` | `localhost:8000` | not used |

   Those files hold your Winlink password, so never commit them. Pat's web UI has no login, so keep
   it on `localhost` unless you trust your network. The QMX's XARA stack reads your callsign from
   `mycall` in `config-qmx.json`.
7. Set `MYCALL` in `packet/direwolf-digirig.conf`. Direwolf won't start until you do.
8. Run `launcher/install_desktop.sh` to add the menu entries.

## Things that cost us time

- **IC-7300 data mode.** The radio keys on plain USB, but digital audio needs USB-D. The launcher
  sets `PKTUSB` with a 3 kHz passband, because the passband has come back as narrow as 1200 Hz.
- **ARDOP `TRAILER 120` on the IC-7300.** At the default 20 ms the radio unkeys before short frames
  finish, so the gateway fails CRC right after answering. `ardopcf.service` has the details.
- **QMX mode and audio source.** ARDOP needs USB mode and USB audio as the SSB source (`SS0`). FSK
  mode, or the mic as the source, keys up with strong RF that nobody can decode.
- **QMX and carriage returns.** A CR flips its serial port into terminal mode, which once hung the
  firmware. Use `qmx_raw_cat.sh` for raw commands.
- **ALSA levels on USB radios.** `alsa-restore` runs before USB sound cards appear, so saved levels
  don't come back. The services and Direwolf script set them on each start.
- **`pat --listen ardop`.** A listening Pat holds the modem's ports, so a manual connect fights it.
  `pat.service` leaves listening off.
- **One modem per sound card.** ARDOP and XARA can't share a radio's audio. `xara-ic7300.service`
  conflicts with `ardopcf.service`, so starting either one stops the other.
- **Slow VARA logins.** At low power and 18 bps a Winlink login takes minutes, so a short timeout on
  `pat connect` kills a working session. Allow at least 600 seconds.

## License

Public domain, under the [Unlicense](LICENSE). Pat, ardopcf, XARA, Hamlib, and Direwolf are separate
projects with their own licenses, and none of them are included here.
