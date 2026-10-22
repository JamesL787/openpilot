# Response to the H020 implementation audit

The audit identified real omissions in the first port. This follow-up fixes the code-level press/dropout and startup-consistency issues. It remains a disabled-by-default offline prototype: no C3XL installation, EPS flash, vehicle test, push or Discord message was performed.

The pasted audit describes the original `7ebaf7a572c47b64245596a494e380a61f1af686` port (31 tests, C020 donor). The intervening `7001d79291f6dfc08588a47f2b541a0960e99f72` already transferred the requested TGG-A120 baseline (37 tests). This follow-up retains TGG and H020's original firmware constants. Source controller: `92428ab490b3085ea523f79cc6a32d392a057b56`; target res base: `01e22f5921d9dfd49235f5867f54d9ec0bdccbaf`.

| Audit finding | Disposition and evidence |
|---|---|
| 1. Raw press drops FF | Fixed. `honda_eps_h020_override.py` carries the source detector; the wrapper uses it for FF/integrator only. A five-frame same-direction press retains full FF, opposing torque acts immediately, and sustained same-direction torque is recognized after the source 0.28-second interval. Existing res driver/safety gates remain in charge of actuation. |
| 2. Single-frame inactive resets | Fixed. The wrapper retains core state for up to 0.1 second, integrating nothing and returning zero output during inactive frames. Tests use controlsd's actual reset-before-update ordering, then verify recovery and long-dropout hard reset. |
| 3. setup_interfaces overwrites PID | Guarded after final initialization. Actual setup code reproduces both torque/NNLC overwrites. card refuses activation before CarParams publication with an explicit error; no silent torque fallback on the port map. |
| 4. Repeated config reads/race | Fixed with a startup snapshot. card reads once, shares it with get_params_sp, validates the final tune, and atomically publishes a config/CarParams-hash record before CarParams. controlsd reads the record once and passes that same snapshot to selection and construction. Missing/corrupt/mismatched records on the port map block startup; old prototype/overwritten tunes do too. Tests remove the config/record between startup stages. |
| 5a. Cached firmware reuse | Fixed for enabled startup: no cached CP is deserialized/passed to get_car, and the platform bundle is ignored. Final checks require an exact firmware-source Bosch fingerprint, exact H020 modified EPS response, no fuzzy match and no dashcam mode. Environment-forced identification is rejected by the firmware-source check. This verifies the startup contract offline, not a physical ECU response. |
| 5b. Installed build identity | Still unverified. The supported image/RWD hashes are documented, but Trk3200/4250 use the same EPS version string. The config's build remains an owner declaration, not an ECU image/hash readback. |
| 5c. Bosch versus Nidec | Still physically unverified. The code refuses activation if the actual exact full-car fingerprint is not Civic Bosch. It does not force the candidate or add a speculative Nidec controller adaptation. No actual CarParams from LiMing's car has been supplied. |
| 6. Stock-H020 matching change | Fixed by removing the added stock `39990-TEA-H020` entry. Only the modified version remains added. That modified entry intentionally changes identification for the modified EPS and is not described as having no fingerprint effect. |
| 7. Wrapper/docs differences | Corrected. LPF is now the source wrapper default 0.1/0.1/0.1 s. Wheel-angle initialization of the 300 deg/s slew is explicitly a deliberate res adaptation. Unsupported telemetry/live settings/delay/fade are documented. |
| 8. Unity shaping assumption | Open. Firmware tables/code similarity do not establish runtime blend gates. Unity pre-table shaping remains an explicit assumption in calibration provenance and inspection output; no live telemetry evidence is claimed. |
| 9. Text-only wiring tests | Replaced by execution tests of real params, setup, CarController/packer, and the actual card/controlsd initializer AST bodies with host I/O/unrelated services substituted. These are offline tests, not a complete daemon boot. |

## Calibration conclusions

The earlier C020-only description no longer applies. The current load coefficients, rack map and effective base PID/trims come from the pinned TGG-A120 source calibration as requested. H020/TGG A/B arrays and rate-estimator code similarity support that donor choice; they do not make its bias, roll coefficient, gearing or trims measured on H020. TGG's fit provenance and source routes are preserved in `h020_tgg_donor.json`; no fresh raw-log replay is claimed here.

The command-map finding is valid and remains unresolved. From the H020 binary row:

- Keys: `0,226,311,495,656,887,1108,1552,1774`.
- R5: `0,1926,4938,8455,12036,15926,20138,26955,30000`.
- Incremental slopes: `8.522,35.435,19.114,22.242,16.840,19.059,15.354,13.716` R5/key.

The steep segment is approximately 1.96 times the 18.04 linear reference. Static FF inversion accounts for the map; the residual angle PID does not thereby acquire a uniform plant gain. This follow-up does not alter EPS firmware or invent a compensating gain schedule without evidence. It retains the supplied PTM map and flags this limit.

R6 arithmetic and the supplied static tables remain as audited. The motor-to-angle constant, runtime live row/gates and res plan timing remain unverified on H020. Existing TGG calibration is usable as a provisional donor baseline, not evidence resolving those H020-specific questions. A real full CarParams/carFw and installed image identity remain necessary before representing the port as ready for vehicle testing; H020 route/telemetry evidence would validate/refine the transfer and firmware model.

## Validation and scope

**66 tests pass** on Python 3.12 using the actual res capnp schemas. The four fitting/timing CLIs pass import/`--help` smoke checks. The new production activation/override/wrapper/inspection modules and new startup tests pass Ruff. `git diff --check` passes. The numerical core remains source-identical except two imports, private PID is source-identical, and res's global PID remains unchanged. The original ns-bosch-radar-testing tracked checkout is untouched.

The fitting algorithms were not re-audited as part of this implementation follow-up. There was no C3XL build/boot, ECU query/readback, vehicle CAN capture, road validation or change to supplied firmware images. Archive/dependency coverage remains the documented 443 common source paths; omitted device-local dependencies remain outside that comparison.

Review `h020-res-port.patch` for all three local commits from res, or `audit-fixes-followup.patch` against the TGG commit. The bundle requires the res base above; the overlay is not an installable full image. All prior packages are retained as historical versions. Use the HEAD in the new package README/manifest when requesting another Claude audit.
