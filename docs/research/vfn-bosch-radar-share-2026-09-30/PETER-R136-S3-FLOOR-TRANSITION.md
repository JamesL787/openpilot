# Peter R136 S3 Floor Transition

FLOOR CREATED BY: ACC-mode MPC trajectory → `get_accel_from_plan()` returned `-4.388995 m/s²`; the later `np.clip(..., output_accel_min=-3.5)` produced the exact published `-3.5 m/s²` floor.

FIRST CAUSAL CHANGE: lead0 refreshed from `7.39584` to `7.16736 m`. At MPC horizon row 1, `params[1,2]` therefore switched from the cruise obstacle `7.227025` to the lead0 obstacle `7.167540`. The MPC-derived action target then moved from `-3.049340` to `-4.388995 m/s²`; model action stayed mild (`-0.609062` → `-0.612907`).

MPC SOLVER REQUESTED FLOOR: YES

POST-MPC LOGIC CREATED FLOOR: YES — the vehicle-minimum clip set the exact numeric floor; it did not originate the under-floor request

RADAR LEAD CONTRIBUTED: YES — although source remains cruise at row 0, lead0 is the active minimum obstacle from horizon row 1 onward at floor entry

WHY SOURCE=CRUISE: The v15 MLSIM branch leaves the solver in `acc` mode even while the planner is Experimental/blended. ACC source is chosen from the *time-zero* minimum of lead0/lead1/cruise obstacles; `cruise` wins that one label. It does not mean lead0 is absent from later solver constraints.

NEXT STEP: With this replay baseline, isolate the intended lead-constraint response from the abrupt action-time interpolation response before considering any tuning change.

## Exact before/floor diff

| value | before 226.838976 | floor 226.900485 |
|---|---:|---:|
| replay aTarget | `-3.04934` | `-3.5` |
| MPC-derived action target | `-3.04934` | `-4.388995` |
| model action desiredAcceleration | `-0.609062` | `-0.612907` |
| merged min(MPC, model) | `-3.04934` | `-4.388995` |
| MPC source | `cruise` | `cruise` |
| planner mode / MPC mode | `['blended', 'acc']` | `['blended', 'acc']` |
| MPC tracking_lead argument | `True` | `True` |
| MPC vCruise | `20.111111` | `20.111111` |
| MPC cruise min/max accel | `[0.0, 0.0]` | `[0.0, 0.0]` |
| vehicle output accel minimum | `-3.5` | `-3.5` |
| full MPC / constraint costs | `[[3.0, 0.0, 0.0, 0.0, 0.0, 0.0], [1000000.0, 1000000.0, 1000000.0, 0.0]]` | `[[3.0, 0.0, 0.0, 0.0, 0.0, 0.0], [1000000.0, 1000000.0, 1000000.0, 0.0]]` |
| lead0 dRel | `7.39584` | `7.16736` |
| lead0 aLeadK | `0.064037` | `0.037058` |
| model x[1] / cruise x[1] | `[0.142865, 1.396605]` | `[0.142381, 1.396605]` |
| solver a_solution[:5] | `[0.0, -0.562755, -1.764232, -2.472262, -0.69011]` | `[0.0, -2.377271, -2.620994, -1.814919, -0.208094]` |
| solver v_solution[:5] | `[2.079802, 2.060262, 1.817868, 1.082365, 0.313733]` | `[2.069586, 1.987042, 1.466389, 0.696265, 0.204561]` |
| solver x_solution[:5] | `[0.0, 0.143978, 0.552296, 1.062922, 1.367157]` | `[0.0, 0.14181, 0.502424, 0.869787, 1.057096]` |
| MPC min obstacle constraint[:5] | `[7.082594, 7.227025, 7.399851, 7.413002, 7.441972]` | `[7.07284, 7.16754, 7.169666, 7.177224, 7.193888]` |
| lead0 / cruise obstacle[:5] | `[[7.39584, 7.396152, 7.399851, 7.413002, 7.441972], [7.082594, 7.227025, 7.660317, 8.382471, 9.393486]]` | `[[7.16736, 7.16754, 7.169666, 7.177224, 7.193888], [7.07284, 7.216561, 7.647725, 8.366331, 9.37238]]` |
| solver yref first 3 rows | `[[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]` | `[[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]` |
| solver params first 3 rows | `[[-3.5, 0.0, 7.082594, -0.464064, 0.104567, 0.75], [-3.5, 0.0, 7.227025, -0.900837, 0.104567, 0.75], [-3.5, 0.0, 7.399851, -1.832064, 0.104567, 0.75]]` | `[[-3.5, 0.0, 7.07284, -0.405184, 0.104467, 0.75], [-3.5, 0.0, 7.16754, -0.85111, 0.104467, 0.75], [-3.5, 0.0, 7.169666, -1.866188, 0.104467, 0.75]]` |
| post-MPC follow target | `-3.04934` | `-4.388995` |
| far-follow slew result | `-3.04934` | `-3.5` |

## Focused cycle trace

Only the 226.70–227.00 s cycles are retained. Arrays are truncated to the first five horizon points.

### t=226.740790 s

- Logged/replay aTarget: `-2.45595` / `-2.44966`; source: `cruise`; shouldStop: `False`.
- Pre-MPC: planner/MPC mode=`blended`/`acc`, trackingLead=`True`, effective lead-control=`True`, x0=`[0.0, 2.095043, 0.0]`, vCruise=`20.111111`, cruise min/max=`0.0`/`0.0`, output min=`-3.5`, limits=`[0.0, 0.0]`, full/constraint costs=`[3.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[1000000.0, 1000000.0, 1000000.0, 0.0]`.
- Lead/model/cruise: lead0=`{'status': True, 'dRel': 7.5672, 'vLead': -0.170498, 'aLeadK': 0.076074, 'radar': True}`, lead xv=`{'x': [7.5672, 7.567567, 7.571892, 7.587258, 7.621184], 'v': [0.0, 0.005275, 0.020761, 0.044255, 0.069789], 'input_status': True, 'tracking_arg': True}`, model x/v/a/j=`[0.0, 0.143955, 0.558821, 1.19188, 1.947291]` / `[2.095043, 2.056771, 1.933385, 1.702151, 1.351658]` / `[-0.579682, -0.596701, -0.63471, -0.685061, -0.721126]` / `[0.0, 0.0, 0.0, 0.0, 0.0]`, cruise x=`[0.0, 1.396605, 5.58642, 12.569444, 22.345679]`.
- Solver: a/v/x=`[0.0, -0.000461, -1.32181, -2.615444, -0.936619]` / `[2.095043, 2.095027, 1.957291, 1.27374, 0.410391]` / `[0.0, 0.145489, 0.572384, 1.146324, 1.522602]`; obstacles=`{'lead0': [7.5672, 7.567572, 7.571978, 7.58765, 7.622158], 'lead1': [7.5672, 7.567572, 7.571978, 7.58765, 7.622158], 'cruise': [7.096548, 7.242037, 7.678505, 8.40595, 9.424374], 'reconstructed_min': [7.096548, 7.242037, 7.571978, 7.58765, 7.622158], 'matches_solver_params': True}`; min obstacle=`[7.096548, 7.242037, 7.571978, 7.58765, 7.622158]`; yref/params first 3=`[[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]` / `[[-3.5, 0.0, 7.096548, -0.074542, 0.104392, 0.75], [-3.5, 0.0, 7.242037, -0.229524, 0.104392, 0.75], [-3.5, 0.0, 7.571978, -0.967537, 0.104392, 0.75]]`; cost scalars=`{'x_ego': 3.0, 'j_ego': 4.966525, 'a_change': 199.330503, 'filter_factor': 0.0}`; source=`cruise`.
- Output stages: MPC target=`{'a_target_mpc': -2.44966, 'should_stop_mpc': False, 'speeds': [2.095043, 2.095041, 2.095034, 2.082832, 2.037637], 'accels': [0.0, -6.5e-05, -0.00026, -0.117456, -0.551023]}`, model action=`{'desired_accel': -0.591046, 'should_stop': False}`, follow=`{'raw_target': -2.44966, 'target': -2.44966, 'lead_present': False}`, slew=`{'previous': -2.07782, 'raw': -2.44966, 'result': -2.44966}`, final=`{'a_desired': -0.639121, 'v_filter': 2.094381, 'published': -2.44966}`.

### t=226.793627 s

- Logged/replay aTarget: `-3.089109` / `-3.080427`; source: `cruise`; shouldStop: `False`.
- Pre-MPC: planner/MPC mode=`blended`/`acc`, trackingLead=`True`, effective lead-control=`True`, x0=`[0.0, 2.088146, 0.0]`, vCruise=`20.111111`, cruise min/max=`0.0`/`0.0`, output min=`-3.5`, limits=`[0.0, 0.0]`, full/constraint costs=`[3.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[1000000.0, 1000000.0, 1000000.0, 0.0]`.
- Lead/model/cruise: lead0=`{'status': True, 'dRel': 7.39584, 'vLead': -0.211627, 'aLeadK': 0.064037, 'radar': True}`, lead xv=`{'x': [7.39584, 7.396149, 7.399789, 7.412724, 7.441282], 'v': [0.0, 0.004441, 0.017476, 0.037253, 0.058747], 'input_status': True, 'tracking_arg': True}`, model x/v/a/j=`[0.0, 0.143366, 0.556253, 1.186065, 1.931881]` / `[2.088146, 2.048625, 1.924517, 1.690305, 1.326289]` / `[-0.585431, -0.602955, -0.641293, -0.704451, -0.74839]` / `[0.0, 0.0, 0.0, 0.0, 0.0]`, cruise x=`[0.0, 1.396605, 5.58642, 12.569444, 22.345679]`.
- Solver: a/v/x=`[0.0, -0.644534, -1.712466, -2.543006, -0.646482]` / `[2.088146, 2.065766, 1.820245, 1.081448, 0.306225]` / `[0.0, 0.144492, 0.553148, 1.065258, 1.365194]`; obstacles=`{'lead0': [7.39584, 7.396152, 7.399851, 7.413002, 7.441972], 'lead1': [7.39584, 7.396152, 7.399851, 7.413002, 7.441972], 'cruise': [7.09054, 7.23555, 7.67058, 8.395631, 9.410701], 'reconstructed_min': [7.09054, 7.23555, 7.399851, 7.413002, 7.441972], 'matches_solver_params': True}`; min obstacle=`[7.09054, 7.23555, 7.399851, 7.413002, 7.441972]`; yref/params first 3=`[[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]` / `[[-3.5, 0.0, 7.09054, -0.000332, 0.104623, 0.75], [-3.5, 0.0, 7.23555, -0.317585, 0.104623, 0.75], [-3.5, 0.0, 7.399851, -1.508093, 0.104623, 0.75]]`; cost scalars=`{'x_ego': 3.0, 'j_ego': 4.966635, 'a_change': 199.332707, 'filter_factor': 0.0}`; source=`cruise`.
- Output stages: MPC target=`{'a_target_mpc': -3.080427, 'should_stop_mpc': False, 'speeds': [2.088146, 2.084999, 2.075557, 2.044027, 1.963466], 'accels': [0.0, -0.090638, -0.36255, -0.73909, -1.089505]}`, model action=`{'desired_accel': -0.603511, 'should_stop': False}`, follow=`{'raw_target': -3.080427, 'target': -3.080427, 'lead_present': False}`, slew=`{'previous': -2.44966, 'raw': -3.080427, 'result': -3.080427}`, final=`{'a_desired': -0.690766, 'v_filter': 2.076973, 'published': -3.080427}`.

### t=226.838976 s

- Logged/replay aTarget: `-3.055781` / `-3.04934`; source: `cruise`; shouldStop: `False`.
- Pre-MPC: planner/MPC mode=`blended`/`acc`, trackingLead=`True`, effective lead-control=`True`, x0=`[0.0, 2.079802, 0.0]`, vCruise=`20.111111`, cruise min/max=`0.0`/`0.0`, output min=`-3.5`, limits=`[0.0, 0.0]`, full/constraint costs=`[3.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[1000000.0, 1000000.0, 1000000.0, 0.0]`.
- Lead/model/cruise: lead0=`{'status': True, 'dRel': 7.39584, 'vLead': -0.211627, 'aLeadK': 0.064037, 'radar': True}`, lead xv=`{'x': [7.39584, 7.396149, 7.399789, 7.412724, 7.441282], 'v': [0.0, 0.004441, 0.017476, 0.037253, 0.058747], 'input_status': True, 'tracking_arg': True}`, model x/v/a/j=`[0.0, 0.142865, 0.555056, 1.186801, 1.939632]` / `[2.079802, 2.04227, 1.923726, 1.698953, 1.345677]` / `[-0.563775, -0.577089, -0.614093, -0.682909, -0.732173]` / `[0.0, 0.0, 0.0, 0.0, 0.0]`, cruise x=`[0.0, 1.396605, 5.58642, 12.569444, 22.345679]`.
- Solver: a/v/x=`[0.0, -0.562755, -1.764232, -2.472262, -0.69011]` / `[2.079802, 2.060262, 1.817868, 1.082365, 0.313733]` / `[0.0, 0.143978, 0.552296, 1.062922, 1.367157]`; obstacles=`{'lead0': [7.39584, 7.396152, 7.399851, 7.413002, 7.441972], 'lead1': [7.39584, 7.396152, 7.399851, 7.413002, 7.441972], 'cruise': [7.082594, 7.227025, 7.660317, 8.382471, 9.393486], 'reconstructed_min': [7.082594, 7.227025, 7.399851, 7.413002, 7.441972], 'matches_solver_params': True}`; min obstacle=`[7.082594, 7.227025, 7.399851, 7.413002, 7.441972]`; yref/params first 3=`[[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]` / `[[-3.5, 0.0, 7.082594, -0.464064, 0.104567, 0.75], [-3.5, 0.0, 7.227025, -0.900837, 0.104567, 0.75], [-3.5, 0.0, 7.399851, -1.832064, 0.104567, 0.75]]`; cost scalars=`{'x_ego': 3.0, 'j_ego': 4.966769, 'a_change': 199.335374, 'filter_factor': 0.0}`; source=`cruise`.
- Output stages: MPC target=`{'a_target_mpc': -3.04934, 'should_stop_mpc': False, 'speeds': [2.079802, 2.077054, 2.068811, 2.0388, 1.959264], 'accels': [0.0, -0.079137, -0.31655, -0.669136, -1.063371]}`, model action=`{'desired_accel': -0.609062, 'should_stop': False}`, follow=`{'raw_target': -3.04934, 'target': -3.04934, 'lead_present': False}`, slew=`{'previous': -3.080427, 'raw': -3.04934, 'result': -3.04934}`, final=`{'a_desired': -0.684719, 'v_filter': 2.069914, 'published': -3.04934}`.

### t=226.900485 s

- Logged/replay aTarget: `-3.5` / `-3.5`; source: `cruise`; shouldStop: `False`.
- Pre-MPC: planner/MPC mode=`blended`/`acc`, trackingLead=`True`, effective lead-control=`True`, x0=`[0.0, 2.069586, 0.0]`, vCruise=`20.111111`, cruise min/max=`0.0`/`0.0`, output min=`-3.5`, limits=`[0.0, 0.0]`, full/constraint costs=`[3.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[1000000.0, 1000000.0, 1000000.0, 0.0]`.
- Lead/model/cruise: lead0=`{'status': True, 'dRel': 7.16736, 'vLead': -0.206974, 'aLeadK': 0.037058, 'radar': True}`, lead xv=`{'x': [7.16736, 7.167538, 7.169645, 7.177131, 7.193657], 'v': [0.0, 0.00257, 0.010113, 0.021558, 0.033996], 'input_status': True, 'tracking_arg': True}`, model x/v/a/j=`[0.0, 0.142381, 0.554762, 1.191996, 1.959061]` / `[2.069586, 2.036587, 1.93061, 1.722902, 1.37765]` / `[-0.496812, -0.511151, -0.559958, -0.650211, -0.726358]` / `[0.0, 0.0, 0.0, 0.0, 0.0]`, cruise x=`[0.0, 1.396605, 5.58642, 12.569444, 22.345679]`.
- Solver: a/v/x=`[0.0, -2.377271, -2.620994, -1.814919, -0.208094]` / `[2.069586, 1.987042, 1.466389, 0.696265, 0.204561]` / `[0.0, 0.14181, 0.502424, 0.869787, 1.057096]`; obstacles=`{'lead0': [7.16736, 7.16754, 7.169666, 7.177224, 7.193888], 'lead1': [7.16736, 7.16754, 7.169666, 7.177224, 7.193888], 'cruise': [7.07284, 7.216561, 7.647725, 8.366331, 9.37238], 'reconstructed_min': [7.07284, 7.16754, 7.169666, 7.177224, 7.193888], 'matches_solver_params': True}`; min obstacle=`[7.07284, 7.16754, 7.169666, 7.177224, 7.193888]`; yref/params first 3=`[[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]` / `[[-3.5, 0.0, 7.07284, -0.405184, 0.104467, 0.75], [-3.5, 0.0, 7.16754, -0.85111, 0.104467, 0.75], [-3.5, 0.0, 7.169666, -1.866188, 0.104467, 0.75]]`; cost scalars=`{'x_ego': 3.0, 'j_ego': 4.966932, 'a_change': 199.338638, 'filter_factor': 0.0}`; source=`cruise`.
- Output stages: MPC target=`{'a_target_mpc': -4.388995, 'should_stop_mpc': False, 'speeds': [2.069586, 2.057978, 2.023155, 1.940942, 1.770103], 'accels': [0.0, -0.334304, -1.337215, -2.398851, -2.478822]}`, model action=`{'desired_accel': -0.612907, 'should_stop': False}`, follow=`{'raw_target': -4.388995, 'target': -4.388995, 'lead_present': False}`, slew=`{'previous': -3.04934, 'raw': -3.5, 'result': -3.5}`, final=`{'a_desired': -1.575022, 'v_filter': 2.03021, 'published': -3.5}`.

### t=226.942151 s

- Logged/replay aTarget: `-3.5` / `-3.5`; source: `cruise`; shouldStop: `False`.
- Pre-MPC: planner/MPC mode=`blended`/`acc`, trackingLead=`True`, effective lead-control=`True`, x0=`[0.0, 2.061758, 0.0]`, vCruise=`20.111111`, cruise min/max=`0.0`/`0.0`, output min=`-3.5`, limits=`[0.0, 0.0]`, full/constraint costs=`[3.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[1000000.0, 1000000.0, 1000000.0, 0.0]`.
- Lead/model/cruise: lead0=`{'status': True, 'dRel': 7.16736, 'vLead': -0.217073, 'aLeadK': 0.037058, 'radar': True}`, lead xv=`{'x': [7.16736, 7.167538, 7.169645, 7.177131, 7.193657], 'v': [0.0, 0.00257, 0.010113, 0.021558, 0.033996], 'input_status': True, 'tracking_arg': True}`, model x/v/a/j=`[0.0, 0.142042, 0.554896, 1.196853, 1.975641]` / `[2.061758, 2.032353, 1.934759, 1.742037, 1.411491]` / `[-0.458022, -0.471104, -0.52068, -0.614604, -0.698162]` / `[0.0, 0.0, 0.0, 0.0, 0.0]`, cruise x=`[0.0, 1.396605, 5.58642, 12.569444, 22.345679]`.
- Solver: a/v/x=`[0.0, -1.52082, -2.449718, -2.360821, -0.131055]` / `[2.061758, 2.008952, 1.595354, 0.760191, 0.154527]` / `[0.0, 0.141955, 0.520764, 0.928819, 1.107238]`; obstacles=`{'lead0': [7.16736, 7.16754, 7.169666, 7.177224, 7.193888], 'lead1': [7.16736, 7.16754, 7.169666, 7.177224, 7.193888], 'cruise': [7.065586, 7.208764, 7.638297, 8.354185, 9.356428], 'reconstructed_min': [7.065586, 7.16754, 7.169666, 7.177224, 7.193888], 'matches_solver_params': True}`; min obstacle=`[7.065586, 7.16754, 7.169666, 7.177224, 7.193888]`; yref/params first 3=`[[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]` / `[[-3.5, 0.0, 7.065586, -1.711635, 0.104482, 0.75], [-3.5, 0.0, 7.16754, -2.435765, 0.104482, 0.75], [-3.5, 0.0, 7.169666, -2.504919, 0.104482, 0.75]]`; cost scalars=`{'x_ego': 3.0, 'j_ego': 4.967057, 'a_change': 199.34114, 'filter_factor': 0.0}`; source=`cruise`.
- Output stages: MPC target=`{'a_target_mpc': -4.076988, 'should_stop_mpc': False, 'speeds': [2.061758, 2.054332, 2.032055, 1.972331, 1.836619], 'accels': [0.0, -0.213865, -0.855461, -1.603067, -1.907861]}`, model action=`{'desired_accel': -0.620906, 'should_stop': False}`, follow=`{'raw_target': -4.076988, 'target': -4.076988, 'lead_present': False}`, slew=`{'previous': -3.5, 'raw': -3.5, 'result': -3.5}`, final=`{'a_desired': -1.022925, 'v_filter': 2.036185, 'published': -3.5}`.

### t=226.990951 s

- Logged/replay aTarget: `-3.5` / `-3.5`; source: `lead0`; shouldStop: `False`.
- Pre-MPC: planner/MPC mode=`blended`/`acc`, trackingLead=`True`, effective lead-control=`True`, x0=`[0.0, 2.052302, 0.0]`, vCruise=`20.111111`, cruise min/max=`0.0`/`0.0`, output min=`-3.5`, limits=`[0.0, 0.0]`, full/constraint costs=`[3.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[1000000.0, 1000000.0, 1000000.0, 0.0]`.
- Lead/model/cruise: lead0=`{'status': True, 'dRel': 7.05312, 'vLead': -0.223883, 'aLeadK': 0.023114, 'radar': True}`, lead xv=`{'x': [7.05312, 7.053231, 7.054546, 7.059214, 7.069522], 'v': [0.0, 0.001603, 0.006308, 0.013446, 0.021204], 'input_status': True, 'tracking_arg': True}`, model x/v/a/j=`[0.0, 0.141251, 0.55082, 1.183631, 1.945723]` / `[2.052302, 2.020674, 1.916761, 1.71193, 1.368747]` / `[-0.48522, -0.499814, -0.552351, -0.639443, -0.71643]` / `[0.0, 0.0, 0.0, 0.0, 0.0]`, cruise x=`[0.0, 1.396605, 5.58642, 12.569444, 22.345679]`.
- Solver: a/v/x=`[0.0, -3.033526, -3.049786, -1.453628, -0.089735]` / `[2.052302, 1.946971, 1.313293, 0.53145, 0.156327]` / `[0.0, 0.140083, 0.479752, 0.783984, 0.924294]`; obstacles=`{'lead0': [7.05312, 7.053232, 7.054554, 7.059251, 7.069612], 'lead1': [7.05312, 7.053232, 7.054554, 7.059251, 7.069612], 'cruise': [7.056781, 7.199302, 7.626865, 8.339469, 9.337116], 'reconstructed_min': [7.05312, 7.053232, 7.054554, 7.059251, 7.069612], 'matches_solver_params': True}`; min obstacle=`[7.05312, 7.053232, 7.054554, 7.059251, 7.069612]`; yref/params first 3=`[[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]` / `[[-3.5, 0.0, 7.05312, -1.094991, 0.104464, 0.75], [-3.5, 0.0, 7.053232, -1.743756, 0.104464, 0.75], [-3.5, 0.0, 7.054554, -2.436917, 0.104464, 0.75]]`; cost scalars=`{'x_ego': 3.0, 'j_ego': 4.967208, 'a_change': 199.344162, 'filter_factor': 0.0}`; source=`lead0`.
- Output stages: MPC target=`{'a_target_mpc': -4.916268, 'should_stop_mpc': False, 'speeds': [2.052302, 2.03749, 1.993053, 1.890864, 1.682938], 'accels': [0.0, -0.42659, -1.706358, -3.034965, -3.040301]}`, model action=`{'desired_accel': -0.630993, 'should_stop': False}`, follow=`{'raw_target': -4.916268, 'target': -4.916268, 'lead_present': False}`, slew=`{'previous': -3.5, 'raw': -3.5, 'result': -3.5}`, final=`{'a_desired': -2.003966, 'v_filter': 2.002203, 'published': -3.5}`.

