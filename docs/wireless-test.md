# ESP-NOW bench test — 2026-11-06

Both boards are USB powered with the boat motor supply unpowered.

| Role | Station MAC | USB port during test | Sketch |
| --- | --- | --- | --- |
| Controller | E0:72:A1:D5:25:90 | /dev/cu.usbmodem101 | controller_link_test |
| Boat | 44:1B:F6:FE:71:A8 | /dev/cu.usbmodem1101 | boat_link_test |

Both sketches compiled with Arduino-ESP32 3.3.11 and uploaded successfully with
flash-data verification. The matching 16-byte protocol uses channel 1 and raw
12-bit joystick readings. This test is unencrypted and does not drive motors.

Initial live results after the corrected uploads:

```text
Controller: TX seq=100 X=1921 Y=1931 BUTTON=released MAC_ACK=100 FAIL=0 pending=0
Boat: LINK OK | seq=100 X=1921 Y=1931 BUTTON=released | MOTORS DISABLED
```

Matching sequence and payload demonstrate radio transmission and application
receipt. This snapshot is not a sustained packet-loss or range measurement.

During setup, Arduino's WiFi.macAddress() returned all zeros immediately after
WiFi.mode(WIFI_STA), which incorrectly blocked the transmitter's identity guard.
Both sketches now read the station MAC using esp_wifi_get_mac(WIFI_IF_STA, ...).
The corrected controller passed its identity check and transmitted successfully.

The boat log also confirmed the directed joystick movements:

| Direction | Example received sequence | X | Y |
| --- | --- | --- | --- |
| Left | 1086 | 3 | 1922 |
| Right | 1098 | 4095 | 1925 |
| Forward | 1114 | 1912 | 0 |
| Backward | 1126 | 1922 | 4095 |

The initial brief press was not captured in diagnostic prints. A subsequent
two-second held press produced 17 PRESSED samples on the boat, followed by
released samples. Matching packet sequence 1800 carried X=1912, Y=1924,
BUTTON=PRESSED on both controller and boat. All four directions and button
press/release have now been observed across the wireless link.

Unplugging only the controller USB changed the boat's output from LINK OK to
`LINK LOST (>500ms) | MOTORS DISABLED`. The last received sequence was 2531.
This confirms loss detection in the diagnostic; elapsed time was not measured
independently, and no powered motor stopping test has been performed.

On the first controller power-cycle, reception did not resume until its USB
serial monitor was opened. Closing that monitor reproduced link loss. The
controller diagnostic was changed to remove the startup wait for Serial, set
its USB transmit timeout to zero, and skip optional prints unless Serial is
connected and has enough free buffer space. The corrected sketch compiled and
uploaded with verification. With the controller monitor closed after upload,
the boat captured 100 LINK OK samples over ten seconds (sequences 172–370),
with zero LINK LOST samples in that observation window.

The repeated physical controller power-cycle passed with the corrected
transmitter and its serial monitor closed: the boat logged 47 LINK LOST samples,
then resumed LINK OK automatically at controller sequence 1. A further 79
received samples were captured through sequence 157, with centered joystick
readings. The elapsed reconnect time was not independently measured.

Pending: range testing. Motor behavior and current protection
remain unverified; this receiver holds GPIO15/16/13/14 LOW while it runs.
