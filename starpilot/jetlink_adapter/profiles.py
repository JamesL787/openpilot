"""
The external models this fork has validated against Jetlink, and what modeld may assume about each.

Local models carry their behavior generation in the model manifest (``ModelVersion``: v8 ... v16). An external model has no
manifest entry, so its generation must never be inferred from the *local* fallback model that happens to be loaded
beside it: that is how a v15 small model would silently get a v16 plan decoded as v15. Instead each supported external
model is pinned here by the SHA-256 of its ONNX, with the generation, the exact input layout and the exact output heads
it was validated with. Anything else is refused (``require_profile``), the small model keeps driving, and the refusal is
logged and shown.

Cinque Terre V3 is Jetlink's pinned default and the one model that was read from its ONNX and replayed. Its numbers below were read from the ONNX
(``/Library/Caches/jetlink/models/404a18cfd86d2963.onnx``, 766354845 bytes) and the LFS pointer at the pinned comma commit,
not copied from documentation. Adding a model means adding an entry here *after* running it through the local parser and
action path (tests/test_profiles.py shows how) and a replay; ``generation`` is a claim about the action head and has to be
backed by that replay.

Standard library only: the owner and the UI import the package this lives in.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


class UnsupportedModel(RuntimeError):
  """The server's model is not one this fork has validated."""


@dataclass(frozen=True)
class RemoteProfile:
  name: str
  # the comma commit whose LFS pointer names the ONNX (Jetlink's catalog identity)
  ref: str
  # SHA-256 / size of the ONNX: the model's identity everywhere (ModelSpec.sha256, the pointer's oid)
  sha256: str
  nbytes: int
  # behavior generation, in the vocabulary of starpilot.common.model_versions: how modeld reads this model's action head
  generation: str
  frame_skip: int
  # the ONNX inputs and the driving output exactly as the server must report them
  input_shapes: dict[str, tuple[int, ...]]
  output_shapes: dict[str, tuple[int, ...]]
  # head -> (start, stop) into the 18452-float driving output
  output_slices: dict[str, tuple[int, int]]

  @property
  def is_v9(self) -> bool:
    return self.generation == 'v9'

  @property
  def is_v14(self) -> bool:
    return self.generation == 'v14'

  @property
  def is_v15(self) -> bool:
    return self.generation == 'v15'

  @property
  def is_v16(self) -> bool:
    return self.generation == 'v16'

  @property
  def mlsim(self) -> bool:
    # same rule as ModelState: every tinygrad-era generation (v8+) is an mlsim-style model
    from openpilot.starpilot.common.model_versions import is_tinygrad_model_version
    return is_tinygrad_model_version(self.generation)

  @property
  def display(self) -> str:
    return self.name


# Cinque Terre V3 (stateful graph, comma master after openpilot #38916), as Jetlink's default big model
CINQUE_TERRE_V3 = RemoteProfile(
  name='Cinque Terre V3',
  ref='bf3e3631b3f91d92a1020a5e0dd4298b93ff4244',
  sha256='404a18cfd86d29637d20c697dfde245bb47c666ae016730ab674c65f4d1e1aa4',
  nbytes=766354845,
  generation='v16',
  frame_skip=4,
  input_shapes={
    'new_img': (2, 6, 128, 256),
    'desire': (8,),
    'traffic_convention': (1, 2),
    'action_t': (1, 2),
    'state_img_q': (2, 5, 6, 128, 256),
    'state_desire_q': (132, 1, 8),
    'state_feat_q': (128, 1, 16384),
  },
  output_shapes={
    'outputs': (1, 18452),
    'next_state_img_q': (2, 5, 6, 128, 256),
    'next_state_desire_q': (132, 1, 8),
    'next_state_feat_q': (128, 1, 16384),
  },
  output_slices={
    'lane_lines': (0, 528),
    'lane_lines_prob': (528, 536),
    'road_edges': (536, 800),
    'meta': (800, 855),
    'desire_pred': (855, 887),
    'pose': (887, 899),
    'wide_from_device_euler': (899, 905),
    'road_transform': (905, 917),
    'plan': (917, 1907),
    'lead': (1907, 2051),
    'lead_prob': (2051, 2054),
    'desire_state': (2054, 2062),
    'action': (2062, 2066),
    'hidden_state': (2066, 18450),
    'pad': (18450, 18452),
  },
)

# The 766 MB family of Jetlink's catalog: models whose ONNX is within 0.4 MB of Cinque Terre V3's. Their identity (ref, SHA-256,
# size) is read from the LFS pointer at each catalog commit. Their layout and generation are ASSUMED to be V3's: nobody has
# read these ONNX files or replayed them. require_profile still compares the server's reported inputs, outputs and every head
# slice with V3's exactly, so a model that really differs is refused at the join and the small model keeps driving; what
# that cannot check is the action head's behavior (generation v16 comes from this fork's manifest tagging for the same models).
# Move one up to a fully validated entry by running host_bench.py and route_feed.py against it.
def _v3_family(name, ref, sha256, nbytes):
  return replace(CINQUE_TERRE_V3, name=name, ref=ref, sha256=sha256, nbytes=nbytes)


SAD = _v3_family('Sad', '30de303d5ffb63957f8acbdb256fd4c7d360455a',
                 '3913109713cc782bdb001550a519f1fc6b36dbc7ade1cf6126622f044ff6adfb', 766082665)
BMRLNAP_V4 = _v3_family('BMRLNAP v4', 'f877d7a0ccc3cce943c76e285214c020cd65c899',
                        'a086d5249fc308bb73993d1e64630c669d4c7df5bde85f42ad61902543648525', 765953504)
BMRLNAP_V6 = _v3_family('BMRLNAP v6', '9d683c06518c0358fb402f38468a7030700c38ac',
                        'f3669cb7c8a9a8a13fcd6a8575958dd09a9ec76d9c9072ccdc76fad7cfa3a28d', 765955335)
CINQUE_TERRE = _v3_family('Cinque Terre', '68b5f8e48602f4f88041efd7de6c99e97fda454e',
                          'e8d821733be15ebe9e27498bc27ad8bbbd741980ece37d77f377294010b8ff28', 765950064)
CINQUE_TERRE_V2 = _v3_family('Cinque Terre V2', '37bfa1413edcdc2e8844984b83727c33f81d8f46',
                             '09d080f36965bb2a0790500452bd328aa03c484d0222aa79d1ad9f021a522aec', 766040736)

PROFILES: dict[str, RemoteProfile] = {p.sha256: p for p in (CINQUE_TERRE_V3, CINQUE_TERRE_V2, CINQUE_TERRE, BMRLNAP_V6, BMRLNAP_V4, SAD)}


def _tuples(d) -> dict[str, tuple[int, ...]]:
  return {str(k): tuple(int(x) for x in v) for k, v in d.items()}


def match_profile(spec) -> RemoteProfile | None:
  """The profile whose ONNX `spec` describes, or None. Identity is the SHA-256; the layout is checked separately by
  require_profile, so a spec of the right model with a surprising layout is an error and not a silent miss."""
  return PROFILES.get(str(getattr(spec, 'sha256', '')))


def require_profile(spec) -> RemoteProfile:
  """The profile for `spec`, or raise UnsupportedModel saying what differs. Checks identity, size, frame skip, every
  input and output shape, and every output head's exact slice, so a model whose layout changed under a reused hash (or a
  server that reports another model) cannot reach the parser."""
  sha = str(getattr(spec, 'sha256', ''))
  profile = PROFILES.get(sha)
  if profile is None:
    known = ', '.join(f"{p.name} ({p.sha256[:12]})" for p in PROFILES.values())
    raise UnsupportedModel(f"the server runs an unvalidated model ({sha[:12] or 'unknown'}); validated: {known}")

  nbytes = getattr(spec, 'nbytes', None)
  if nbytes != profile.nbytes:
    raise UnsupportedModel(f"{profile.name}: server reports {nbytes} bytes, expected {profile.nbytes}")
  if getattr(spec, 'frame_skip', None) != profile.frame_skip:
    raise UnsupportedModel(f"{profile.name}: frame_skip {getattr(spec, 'frame_skip', None)}, expected {profile.frame_skip}")

  for what, got, want in (('input', _tuples(spec.input_shapes), profile.input_shapes),
                          ('output', _tuples(spec.output_shapes), profile.output_shapes)):
    if got != want:
      differing = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
      raise UnsupportedModel(f"{profile.name}: {what} shapes differ from the validated model at {differing}")

  slices = {str(k): (int(v.start), int(v.stop)) for k, v in spec.output_slices.items()}
  if slices != profile.output_slices:
    differing = sorted(k for k in set(slices) | set(profile.output_slices) if slices.get(k) != profile.output_slices.get(k))
    raise UnsupportedModel(f"{profile.name}: output heads differ from the validated model at {differing}")
  return profile
