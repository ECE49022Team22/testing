# GPS (DATAGNSS GEM1305): configuring it from the Pi

How to check and change the GPS receiver's settings without Satrack (DATAGNSS's Windows-only tool), to get RTK working.
Last updated 2026-11-05. Script: [`gem1305_cfg.py`](gem1305_cfg.py). RTK client: [`ntrip_rtk.py`](ntrip_rtk.py).

---

## 1. Background (read this first)

- **The receiver is a DATAGNSS GEM1305** (Allystar chip), not a UM982. The code and docs still say "UM982" in
  `bench/w_gps.py`, `demo/d_gps.py`, `demo/README.md`, `demo/static/index.html` and `ntrip_rtk.py`. Its 230400 baud and
  5 Hz output are the GEM1305's factory defaults. The UM982 is a different chip (Unicore), so don't use its manuals.
- **Where RTK stands (from `ntrip_rtk.py`, 2026-11-05):**
  - The first test sent corrections on UART0, but the Pi's UART0 TX (pin 8) never drives, so nothing reached the
    receiver (`motor_cal/ntrip_test1.log`: ~950 B/s of RTCM for 150 s, fix stuck at plain GPS, no correction age).
  - Corrections now go out on UART4 TX (pin 32). The receiver reportedly gets them but still doesn't use them.
- **Most likely cause:** a receiver setting.
  - **CFG-DGNSS** chooses what the receiver does with corrections: none, SBAS only, code DGPS, RTK float or RTK fixed.
    Anything below RTK float means it never computes RTK.
  - A **fixed base position** (the receiver set up as a base station) also blocks it.
  - `gem1305_cfg.py info` shows both; `rover` fixes both.
- There is **no "enable RTCM input" setting**: this receiver's port configuration only holds the baud rate.

## 2. Before you start

**Wiring** (GEM1305 5-pin connector: GND / PPS / RX / TX / 5V):

| GEM1305 | Pi header | Linux device | Used for |
|---|---|---|---|
| TX | pin 10 (GPIO15, UART0 RX) | `/dev/ttyAMA0` | NMEA and replies **from** the receiver |
| RX | pin 32 (GPIO12, UART4 TX) | `/dev/ttyAMA4` | commands and RTCM **to** the receiver |
| PPS | pin 12 (GPIO18) | `pps@12` | timing (demo only) |
| GND, 5V | GND, 5V | | |

Pin 8 (UART0 TX) is not used: it doesn't drive its pin on this Pi.

**Checklist:**
- **Stop everything else reading `/dev/ttyAMA0`:** the demo (`run_demo.py`, its GPS worker) and `ntrip_rtk.py`. Two
  readers split the bytes between them and the replies get lost. `sudo fuser -v /dev/ttyAMA0` shows who has it open.
- **UART4 must exist:** `ls /dev/ttyAMA4`. If it's missing, add `dtoverlay=uart4-pi5` to `/boot/firmware/config.txt`
  and reboot.
- **Run from the repo root with the venv:** `.venv/bin/python` (needs pyserial, same as `ntrip_rtk.py`).
- **Check the script itself first** (no hardware needed): `.venv/bin/python gem1305_cfg.py selftest` should print
  `selftest ok`.

## 3. Steps

1. **Look, don't touch:** `.venv/bin/python gem1305_cfg.py info`
   - If the first line shows the receiver's software and hardware version, commands are reaching it over pin 32.
     That alone settles whether the receiver can hear the corrections.
   - It then prints the DGNSS mode, any fixed base position, survey-in settings, both ports' baud rates and the latest
     GGA, and a `PROBLEM:` line for each setting that blocks RTK.
   - No version line: see [Troubleshooting](#5-troubleshooting).
2. **If there are `PROBLEM:` lines:** `.venv/bin/python gem1305_cfg.py rover`
   - Sets DGNSS mode to RTK fixed (keeping the pre-filter as it was) and clears any fixed base position, then reads
     both back.
   - Nothing is saved yet: a power cycle undoes it, which is what you want until RTK is shown to work.
3. **Test RTK outdoors, clear sky:** `.venv/bin/python ntrip_rtk.py --rtcm-port /dev/ttyAMA4`
   - Watch the fix column go GPS → DGPS / RTK float → RTK FIXED, and the `age` column stop being `-`.
   - A non-blank correction age is the first sign the receiver is using the corrections.
4. **Once RTK works, make it stick:** `.venv/bin/python gem1305_cfg.py save`, then power-cycle the receiver and run
   `info` again to check the DGNSS mode is still RTK (see the save caveat in [section 7](#7-how-this-was-worked-out-and-what-isnt-known)).
5. **If `info` shows no problems but RTK still doesn't come:** use DATAGNSS's own rover setup file.
   - Download [`config_rover_5hz.cmd`](https://docs.datagnss.com/assets/config/config_rover_5hz.cmd) (or
     [`config_rover_5hz_all.cmd`](https://docs.datagnss.com/assets/config/config_rover_5hz_all.cmd) for all
     constellations). Both are linked from DATAGNSS's
     [base/rover setup page](https://docs.datagnss.com/common/common_setup_base_rover/).
   - `.venv/bin/python gem1305_cfg.py decode config_rover_5hz.cmd` lists what it sends, by name, without opening a port.
   - `.venv/bin/python gem1305_cfg.py send-cmd config_rover_5hz.cmd` sends it and checks each setting is
     acknowledged. Add `--save` to save afterwards if every setting was.
6. **Commit the `ntrip_rtk.py` output** from the run that works (or doesn't), like `motor_cal/ntrip_test1.log`.

What `info` looks like when something is wrong (this is from a simulated receiver; real values differ):

```
Receiver:     software 3.018.2564030c, hardware HD9510.6484af35b  (commands are reaching it)
DGNSS mode:   0 = none: corrections are ignored  (pre-filter 0)
Fixed ECEF:   none
Fixed LLA:    none
Survey-in:    minimum 0 s, accuracy limit 0 mm
UART0:        230400 baud
UART1:        230400 baud
NMEA GGA:     fix GPS, 14 sats, HDOP 1.09, correction age -, base -

PROBLEM: DGNSS mode is 0 (none: corrections are ignored), so it won't compute RTK from the corrections. `rover` sets it to RTK.
```

## 4. Command reference

All commands take `--port` (read, default `/dev/ttyAMA0`), `--tx-port` (write, default `/dev/ttyAMA4`), `--baud`
(default 230400) and `--dry-run` (print the frames that would be sent, open no port). Options go before the command:
`.venv/bin/python gem1305_cfg.py --dry-run rover`.

| Command | Does | Changes the receiver? |
|---|---|---|
| `selftest` | Checks the frame encoder/decoder against Satrack's own output | No (no port) |
| `info` | Version, DGNSS mode, fixed base position, survey-in, port baud rates, latest GGA, problems | No |
| `rover [--dgnss fixed\|float\|rtd] [--save]` | Sets the DGNSS mode (default RTK fixed), clears any fixed base position | Yes, until power off unless `--save` |
| `save` | Saves the baud, message and nav settings to flash | Yes |
| `decode FILE.cmd` | Lists the commands in a DATAGNSS `.cmd` file (hex text or binary) | No (no port) |
| `send-cmd FILE.cmd [--save] [--allow-reset]` | Sends a `.cmd` file, checks each setting is acknowledged | Yes |
| `poll CLASS ID [PAYLOAD]` | Polls any message by class and id (hex), prints the raw reply | No |

- `send-cmd` refuses a file that loads or clears the saved configuration (CFG-CFG load/clear, including Satrack's
  "Factory Reset") unless you add `--allow-reset`.
- With a USB-serial adapter instead of the two UARTs, pass the same device for both: `--port /dev/ttyUSB0 --tx-port /dev/ttyUSB0`.

## 5. Troubleshooting

**No reply to MON-VER (the version poll).** The commands aren't reaching the receiver, or its replies aren't being read:
- **TX wire:** Pi pin 32 must go to the GEM1305's RX on the **same connector** whose TX goes to pin 10. The GEM1305 has two
  UARTs (UART0 on J7, UART1 on J2); replies come back on the UART the command went in on.
- **Another program has `/dev/ttyAMA0` open:** `sudo fuser -v /dev/ttyAMA0`.
- **Baud:** both ports run at `--baud`. If the receiver was changed from 230400, NMEA would also be garbled.
- **Is UART4 really transmitting?** `pinctrl get 12` should show GPIO12 on a UART4 TX function.
  `pinctrl get 14` is also worth a look: if GPIO14 isn't on its UART0 TX function, the "dead" pin 8 was a pin setting,
  not broken hardware.

**`rover` gets a NAK on CFG-DGNSS.** This firmware doesn't accept that setting; use DATAGNSS's rover `.cmd` file (step 5).

**DGNSS mode is RTK but the fix stays GPS.**
- Check the `age` column in `ntrip_rtk.py`: blank means the receiver isn't using the corrections at all; a number with
  no RTK means it is, and the problem is sky view or the base.
- Test outdoors with a clear view; RTK float can take a minute, fixed longer.
- Try `rover --dgnss float` in case the firmware won't fix ambiguities with this base.
- The mountpoint is `MSM4_NEAR` (MSM4 for GPS, GLONASS, Galileo, BeiDou plus station messages 1006/1008/1033/1230).

**Settings gone after a power cycle.** `save` didn't cover the section the DGNSS mode is stored in (see the caveat in
section 7). Try `send-cmd` with the vendor file and `--save`, or save once from Satrack ([section 8](#8-fallback-satrack-under-wine)).

## 6. Protocol details

Reverse-engineered from Satrack (see section 7). Allystar's binary protocol is laid out like u-blox UBX.

**Frame:** `F1 D9 | class | id | length (u16, little-endian) | payload | checksum (2 bytes)`. The checksum is the
8-bit Fletcher sum over class, id, length and payload (same as UBX). Binary frames and NMEA lines arrive interleaved
on the same port.

**Replies:**
- A **set** (payload filled in) is answered with **ACK-ACK `05 01`** or **ACK-NAK `05 00`**, whose payload is the
  `[class, id]` being answered.
- A **poll** is the same message with an empty payload (CFG-PRT: just the port number), answered with the message.

| Message | Class Id | Payload (little-endian) |
|---|---|---|
| MON-VER | `0A 04` | reply: software version (16 bytes) + hardware version (16 bytes), ASCII, NUL-padded |
| CFG-DGNSS | `06 F1` | `mode u8`, `pre-filter u8`. Modes: 0 none, 1 SBAS, 2 RTD (code), 3 RTK float, 4 RTK fixed |
| CFG-FIXEDECEF | `06 14` | `X, Y, Z` as `i32` cm. All zero clears it (what Satrack's Clear button sends) |
| CFG-FIXEDLLA | `06 13` | `lat, lon` as `i32` 1e-7 deg, `alt` as `i32` cm |
| CFG-SURVEY | `06 12` | `min duration u32` s, `accuracy limit u32` mm (survey-in, for base stations) |
| CFG-PRT | `06 00` | poll: `port u8` (0 or 1). Reply and set: `port u8`, 3 reserved bytes, `baud u32` |
| CFG-MSG | `06 01` | poll: `class, id`. Set: `class, id, rate u8, port mask u8` (`FF` = all ports) |
| CFG-CFG | `06 09` | `action u32` (0 save, 1 load, 2 clear), `sections u32` (1 baud, 2 messages, 4 nav, 8/0x20 reserved, 0x100 IMU start, 0x200 IMU remap). `0xFFFFFFFF` is Satrack's "Factory Reset" |
| NAV-PVT | `01 C2` | position fix, including fix type up to "Float RTK" / "Fix RTK" (not decoded by the script; it reads GGA) |

Satrack's own saves, for comparison: "Set RTK rate" saves with sections `3`; "Factory reset" is clear (2) with `0xFFFFFFFF`.
The script's `decode` knows the names of all 121 messages Satrack has panels for.

## 7. How this was worked out, and what isn't known

**Source:** Satrack v1.31.007 (`satrack_latest.zip` from docs.datagnss.com).
- It's a 32-bit .NET Framework 4.0 program written in C++/CLI, so most of it disassembles to .NET bytecode.
- Each message's panel fills in a payload and calls a native function that adds the header and checksum. A table in
  the native code maps Satrack's internal message numbers to class/id pairs.
- That native function was run in an x86 emulator to produce reference frames; those are the test vectors in
  `gem1305_cfg.py selftest`.
- The frame format and checksum also match a MON-VER reply recorded from a real Allystar receiver, which happened to be
  in the zip's log folder (software `3.018.2564030c`, hardware `HD9510.6484af35b`).

**Testing so far:** the script ran end-to-end against a simulated receiver on virtual serial ports, both with separate
read/write ports and with a single port. **It has not been run on the GEM1305 yet.**

**Not known:**
- **Which saved section holds the DGNSS mode.** `save` writes baud + messages + nav (`7`), on the guess that DGNSS is a
  nav setting. Check by power-cycling and running `info` (step 4).
- **What CFG-SURVEY's values do on their own.** They are survey-in settings for a base station; the script only shows
  them. The vendor's rover `.cmd` is the way to reset them if they turn out to matter.
- **CFG-RTKCHOSEMODE (`06 66`, "Module0 / Module1")** exists in Satrack, meaning unknown; the script never sends it.
- **Whether this GEM1305's firmware answers every poll.** Anything it doesn't support shows as "no reply" or NAK.

## 8. Fallback: Satrack under Wine

If the script can't do something, Satrack can run on an Ubuntu laptop with a 3.3 V USB-serial adapter wired to the
GEM1305. Unplug the GEM1305 from the Pi first, so the Pi's pin 32 doesn't fight the adapter's TX.

```bash
sudo dpkg --add-architecture i386 && sudo apt update
sudo apt install wine wine32:i386 winetricks
sudo usermod -aG dialout $USER                      # then log out and back in
export WINEPREFIX=~/.wine-satrack WINEARCH=win32
wineboot -i
winetricks -q dotnet40                              # Satrack is .NET 4.0 (mixed-mode C++/CLI)
ln -sf /dev/ttyUSB0 $WINEPREFIX/dosdevices/com5     # the adapter shows up as COM5
cd Satrack_client_V1.31.007 && WINEPREFIX=~/.wine-satrack wine Satrack.exe
```

Connect to COM5 at 230400 baud. The settings in section 6 are under the same names in Satrack's message view, and the
rover `.cmd` files go through Tools → Send Command.
