"""Exact H020 image identities. Generated firmware hashes are not an ECU image readback.

Legacy builds retain their original profile. Rev-b has a distinct queried EPS ID,
so selecting an old profile on new firmware (or vice versa) cannot silently activate.
"""

PTM_BUILDS = {
  "20261011-trk4250": {
    "rwd_sha256": "9fcd18697938a741771aada9f6a1274b7eada6ae3dc3fb1d7d3771c61f97e537",
    "image_sha256": "53427cbcd80e315c237d34f4e41bb7ef62ddedd6166d670e6352acb1d45587a1",
    "tracker": 4250,
    "file": "39990-TEA,H020-20261011-PTM-FF45-Norm1650-Trk4250-P117to265-D737-Pclamp7373-Dclamp1774-Out9000-SpeedClamp0-A280Flat.rwd",
    "fw_version": "39990-TEA,H020",
    "profile": "legacy",
  },
  "20261011-trk3200": {
    "rwd_sha256": "56191940003ee614fe1bd18e0a1a67b946c40db5bf69a08109806eca408ade55",
    "image_sha256": "5b3ba3061d9259abfa622beca1c460aad03b0e8af9422c3199b72a58749bc080",
    "tracker": 3200,
    "file": "39990-TEA,H020-20261011-PTM-FF45-Norm1650-Trk3200-P117to265-D737-Pclamp7373-Dclamp1774-Out9000-SpeedClamp0-A280Flat.rwd",
    "fw_version": "39990-TEA,H020",
    "profile": "legacy",
  },
  "20261022b-tgg-claritylimits-trk4250": {
    "rwd_sha256": "e1ad753e11986b9392fc9a1baca8f46605d25bb538b00ed7bf2bec57f2264261",
    "image_sha256": "a5e87ece9039c820993f0beb3f8f7f9597c09e94ec6518d827be3855cbcb755d",
    "tracker": 4250,
    "file": "39990-TEA,H02B-20261022b-TggResponse-ClarityLimits-Trk4250.rwd",
    "fw_version": "39990-TEA,H02B",
    "profile": "revb-tgg-claritylimits",
  },
  "20261022b-tgg-claritylimits-trk3200": {
    "rwd_sha256": "0289f9178016effd707de92e5d4923254587d771bbca02e203b1ab9aadb2877b",
    "image_sha256": "b330ef7150fbf819bc9764c7795cd63d571e14f964b6f8ed7bbec0c851b40ce3",
    "tracker": 3200,
    "file": "39990-TEA,H02B-20261022b-TggResponse-ClarityLimits-Trk3200.rwd",
    "fw_version": "39990-TEA,H02B",
    "profile": "revb-tgg-claritylimits",
  },
}
