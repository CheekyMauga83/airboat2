# Turbidity bring-up

Boat joystick firmware now samples GPIO4 every 25 ms and reports a 20-sample
average about twice per second over boat USB at 115200 baud. Motor controls and
limits are retained. The controller dashboard still has a placeholder; use the
boat serial output for these real readings.

Wiring: sensor board VCC to regulated 5 V, GND to shared ground, analog signal
through 10 kOhm to GPIO4, and 20 kOhm from GPIO4 to ground. Set the board switch
to A. Do not connect its signal directly to GPIO4. Never apply 5 V to GPIO4.

`TURBIDITY` lines report raw ADC, calibrated ADC millivolts, and sensor voltage
estimated by multiplying divided voltage by 1.5. Resistor tolerances and ADC
error affect that estimate. Raw and millivolt readings are consecutive separate
conversions, not the same sample. ADC_RANGE_LIMIT means some samples approached
the measurable range. LOW_SIGNAL_CHECK_POWER_WIRING is a check prompt, not a
diagnosis: the firmware cannot detect an unplugged sensor reliably.

Upload with battery unplugged. For initial sensor power/testing, keep motor
power disconnected and avoid connecting unverified external 5 V and USB sources
together. Confirm the actual power wiring before applying battery power.

Compare sensor response in clear water and a cloudy sample, with the optical
windows submerged consistently, no trapped bubbles, and similar lighting.
Keep the probe top/connector and electronics dry; the probe is not fully
waterproof. Increasing cloudiness should generally decrease analog voltage.
Measure GPIO4-to-GND with a DC voltmeter to compare against adc_mV if readings
look wrong. A 4.5 V sensor signal divides to 3.0 V with these resistor values.

NTU remains explicitly uncalibrated. Do not infer drinkability or quantitative
water quality from these readings. DFRobot describes this as a qualitative
sensor and cautions against treating a generic voltage conversion as standard
NTU measurement.

Sources: https://wiki.dfrobot.com/sen0189 and
https://www.dfrobot.com/forum/topic/315216
