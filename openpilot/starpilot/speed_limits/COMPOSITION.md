# Speed-limit composition

`composition.step` joins current source selection, adoption decisions, configured
offsets, selected cruise coordinates and qualified driver intent. It preserves
validation of sessions, clocks, source observations, current authority and the causal
action ledger. Malformed or contradictory input cannot authorize a command.

The resulting accepted adjusted limit is adoption data. Runtime sends it to card
as a bounded set-speed command, retrying a failed application only while the same
adoption and expected set speed remain current. `Result.ceiling` is always `None`; SLC does
not compose another speed ceiling with the driver's set speed. The planner uses
card's published set speed and its ordinary selected braking profile.

The former lead-relaxation helper is not applied to SLC output. Lead following,
curves, stopping and actuator restrictions retain their independent planner paths.
See the [current controller contract](README.md).
