# Lateral Stiction

This optional final-stage torque state machine emulates the breakaway friction of
high-torque EPS units. It is available for NRDR's modified-EPS Hondas through
the off-by-default `NrdrLatStiction` parameter.

In HOLD, output remains at a captured torque while a slow integrator winds against
standing error, preventing steering-command dither from reaching the transparent
modified EPS. In MOVE, the existing PID, feedforward, Clarity scaling, and learned
trim pass through unchanged.

HOLD breaks into MOVE when angle error, desired-angle rate, or accumulated drift
crosses NRDR's calibrated threshold. MOVE parks in HOLD only when error, the model
plan, and measured wheel rate remain quiet for the dwell period. Transitions crossfade
over 80 ms and minimum state times prevent chatter.

The stage bypasses to the live controller output while disengaged, during driver
override, lane changes, controller saturation, or below 3 m/s. The constants match
NRDR nightly's Lexus ES350-based July 2026 calibration; highway behavior has not yet
been independently calibrated for the Clarity.
