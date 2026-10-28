# Set-speed override

Only a qualified driver set-speed change can create an SLC override. Either an
increase or decrease qualifies when the resulting speed differs from the most
recently applied set speed. Card's qualified application receipt records the
rounded value; only a 0.001 m/s transport tolerance applies. The causal ledger
excludes automatic changes, consumed
confirmation presses, duplicated effects and foreign or obsolete contexts.

Override is presentation state; it never adds another planner target. Card's set
speed remains the sole cruise target. The widget crosses out its latest source
limit while override is active. A new limit is adopted immediately in automatic mode
or follows the ten-second manual confirmation policy. Acceptance clears the old override. Returning
the selected speed to the adopted adjusted limit also clears it.

Accelerator use neither creates an override nor cancels a preexisting set-speed
choice. Authority transitions still suppress commands and invalidate action origins;
reversed clocks and malformed evidence remain fail-closed. See [README](README.md).
