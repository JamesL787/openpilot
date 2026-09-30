# Peter R136 S3 Dual-Lead Freeze

LEAD1/LEAD2 SAME PHYSICAL TRACK: YES

PREVIOUS SINGLE-LEAD FREEZE VALID: NO

NORMAL PRECLIP: `-4.388995 m/s²`

SINGLE FREEZE PRECLIP: `-4.388995 m/s²`

ALL-SAME-TRACK FREEZE PRECLIP: `-3.038732 m/s²`

FOUR-COUNT RANGE UPDATE ACTUALLY NECESSARY FOR FLOOR: YES

ACTION EXTRACTION STILL AMPLIFIES: YES

## Floor-cycle leads

| field | leadOne | leadTwo |
|---|---:|---:|
| status | `True` | `True` |
| radar | `True` | `True` |
| radarTrackId | `57.0` | `57.0` |
| dRel | `7.16736` | `7.16736` |
| vRel | `-2.296875` | `-2.296875` |
| vLead | `-0.206974` | `-0.206974` |
| aLeadK | `0.037058` | `0.037058` |
| modelProb | `0.998121` | `0.998651` |

Both visible lead objects have the same nonzero radar track identity only if the top-line answer is YES.

## Three stateful floor-cycle runs

All runs begin at the same five-second sequential pre-roll. B changes only leadOne distance; C changes distance on both visible copies of the same track.

| quantity | A normal | B leadOne frozen | C both copies frozen |
|---|---:|---:|---:|
| leadOne snapshot | `{'status': True, 'radar': True, 'radarTrackId': 57.0, 'dRel': 7.16736, 'vRel': -2.296875, 'vLead': -0.206974, 'aLeadK': 0.037058, 'modelProb': 0.998121}` | `{'status': True, 'radar': True, 'radarTrackId': 57.0, 'dRel': 7.39584, 'vRel': -2.296875, 'vLead': -0.206974, 'aLeadK': 0.037058, 'modelProb': 0.998121}` | `{'status': True, 'radar': True, 'radarTrackId': 57.0, 'dRel': 7.39584, 'vRel': -2.296875, 'vLead': -0.206974, 'aLeadK': 0.037058, 'modelProb': 0.998121}` |
| leadTwo snapshot | `{'status': True, 'radar': True, 'radarTrackId': 57.0, 'dRel': 7.16736, 'vRel': -2.296875, 'vLead': -0.206974, 'aLeadK': 0.037058, 'modelProb': 0.998651}` | `{'status': True, 'radar': True, 'radarTrackId': 57.0, 'dRel': 7.16736, 'vRel': -2.296875, 'vLead': -0.206974, 'aLeadK': 0.037058, 'modelProb': 0.998651}` | `{'status': True, 'radar': True, 'radarTrackId': 57.0, 'dRel': 7.39584, 'vRel': -2.296875, 'vLead': -0.206974, 'aLeadK': 0.037058, 'modelProb': 0.998651}` |
| mpc.lead_xv_0[:3] (x/v) | `[[7.16736, 7.167538, 7.169645], [0.0, 0.00257, 0.010113]]` | `[[7.39584, 7.396019, 7.398126], [0.0, 0.00257, 0.010113]]` | `[[7.39584, 7.396019, 7.398126], [0.0, 0.00257, 0.010113]]` |
| mpc.lead_xv_1[:3] (x/v) | `[[7.16736, 7.167538, 7.169645], [0.0, 0.00257, 0.010113]]` | `[[7.16736, 7.167538, 7.169645], [0.0, 0.00257, 0.010113]]` | `[[7.39584, 7.396019, 7.398126], [0.0, 0.00257, 0.010113]]` |
| lead0 obstacle[:5] | `[7.16736, 7.16754, 7.169666, 7.177224, 7.193888]` | `[7.39584, 7.39602, 7.398146, 7.405704, 7.422368]` | `[7.39584, 7.39602, 7.398146, 7.405704, 7.422368]` |
| lead1 obstacle[:5] | `[7.16736, 7.16754, 7.169666, 7.177224, 7.193888]` | `[7.16736, 7.16754, 7.169666, 7.177224, 7.193888]` | `[7.39584, 7.39602, 7.398146, 7.405704, 7.422368]` |
| cruise obstacle[:5] | `[7.07284, 7.216561, 7.647725, 8.366331, 9.37238]` | `[7.07284, 7.216561, 7.647725, 8.366331, 9.37238]` | `[7.07284, 7.216561, 7.647725, 8.366331, 9.37238]` |
| solver min obstacle[:5] | `[7.07284, 7.16754, 7.169666, 7.177224, 7.193888]` | `[7.07284, 7.16754, 7.169666, 7.177224, 7.193888]` | `[7.07284, 7.216561, 7.398146, 7.405704, 7.422368]` |
| solver a_solution[:5] | `[0.0, -2.377271, -2.620994, -1.814919, -0.208094]` | `[0.0, -2.377271, -2.620994, -1.814919, -0.208094]` | `[0.0, -0.53871, -1.713829, -2.564343, -0.695574]` |
| solver v_solution[:5] | `[2.069586, 1.987042, 1.466389, 0.696265, 0.204561]` | `[2.069586, 1.987042, 1.466389, 0.696265, 0.204561]` | `[2.069586, 2.050881, 1.816241, 1.073503, 0.281162]` |
| direct accel at action_t | `-1.989031` | `-1.989031` | `-2.380632` |
| get_accel_from_plan | `-4.388995` | `-4.388995` | `-3.038732` |
| final published target | `-3.5` | `-3.5` | `-3.038732` |

Only `mpc.params[:,2]` is the solver-authoritative min-obstacle trajectory; the individual obstacle rows are independently reconstructed as a consistency aid.
