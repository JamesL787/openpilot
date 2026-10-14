"""ONNX -> PyTorch (onnx2torch); prove the converted model matches cv2.dnn on real V-ASM crops."""

import json
import os
import av
import numpy as np
import torch
import onnx
from onnx2torch import convert
from openpilot.starpilot.system.adj_spot_monitor_vision_inference import VASMInference, V_ASM_UPSTREAM_MODEL_PATH
from onnx import shape_inference, helper, numpy_helper

WORK = os.environ.get("VASM_WORK", "/work")  # scratch dir; /work in docker

g = shape_inference.infer_shapes(onnx.load(str(V_ASM_UPSTREAM_MODEL_PATH)))
# opset-18 Split(num_outputs=k) -> opset-13 Split with explicit sizes, so onnx2torch can convert it
shapes = {vi.name: [d.dim_value for d in vi.type.tensor_type.shape.dim] for vi in list(g.graph.value_info) + list(g.graph.input)}
for n in g.graph.node:
  if n.op_type == "Split":
    attrs = {a.name: helper.get_attribute_value(a) for a in n.attribute}
    k = attrs.get("num_outputs")
    if k and len(n.input) < 2:
      axis = attrs.get("axis", 0)
      dim = shapes[n.input[0]][axis]
      sizes = numpy_helper.from_array(np.array([dim // k] * k, dtype=np.int64), n.name + "_sizes")
      g.graph.initializer.append(sizes)
      n.input.append(sizes.name)
      del n.attribute[:]
      n.attribute.append(helper.make_attribute("axis", axis))
for o in g.opset_import:
  if o.domain in ("", "ai.onnx"):
    o.version = 17
# batch=1 is baked into Reshape shape constants: make the batch dim -1 so training can use batches
inits = {t.name: t for t in g.graph.initializer}
consts = {n.output[0]: n for n in g.graph.node if n.op_type == "Constant"}
patched = 0
for n in g.graph.node:
  if n.op_type == "Reshape":
    src = n.input[1]
    if src in inits:
      arr = numpy_helper.to_array(inits[src]).copy()
      if arr[0] == 1 and -1 not in arr[1:]:
        arr[0] = -1
        inits[src].CopyFrom(numpy_helper.from_array(arr, src))
        patched += 1
    elif src in consts:
      at = consts[src].attribute[0]
      arr = numpy_helper.to_array(at.t).copy()
      if arr[0] == 1 and -1 not in arr[1:]:
        arr[0] = -1
        at.t.CopyFrom(numpy_helper.from_array(arr, at.t.name))
        patched += 1
print("reshape batch dims patched:", patched, "of", sum(n.op_type == "Reshape" for n in g.graph.node))
onnx.checker.check_model(g)
m = convert(g).eval()
torch.save(m, f"{WORK}/ft/vasm_converted.pt")
inf = VASMInference(V_ASM_UPSTREAM_MODEL_PATH)
assert inf.load()
ex = json.load(open(f"{WORK}/dm/ex_00000321--67540f4492_42.json"))
inf.load_config(json.loads(ex["params"]["VASMAnnotationConfig"]))
blobs = []
for i, fr in enumerate(av.open(f"{WORK}/dm/00000321--67540f4492/42/dcamera.hevc").decode(video=0)):
  if i % 25:
    continue
  nv = fr.to_ndarray(format="nv12")
  inf._prepare_geometry(fr.height, fr.width)
  for side in ("left", "right"):
    # same preprocessing as the daemon: capture the blob it feeds cv2.dnn via a proxy net
    class Proxy:
      def __init__(self, net):
        self.net, self.blob = net, None

      def setInput(self, b):
        self.blob = b.copy()
        self.net.setInput(b)

      def forward(self):
        return self.net.forward()

    real = inf.net
    inf.net = Proxy(real)
    inf._run_inference(nv, fr.height, side)
    got = {"b": inf.net.blob}
    inf.net = real
    real.setInput(got["b"])
    blobs.append((got["b"], inf.net.forward().squeeze()))
x = torch.from_numpy(np.concatenate([b for b, _ in blobs]))
with torch.no_grad():
  y = m(x).numpy()
ref = np.stack([r for _, r in blobs])
d = np.abs(y - ref)
print(
  f"n={len(ref)} max_abs_diff={d.max():.2e} mean={d.mean():.2e} argmax_agree={np.mean(y.argmax(1) == ref.argmax(1)):.4f}",
  f"car>=0.8 agree={np.mean((y[:, 1] >= 0.8) == (ref[:, 1] >= 0.8)):.4f}",
)
print("trainable params:", sum(p.numel() for p in m.parameters()), "row sums ~1:", np.allclose(y.sum(1), 1, atol=1e-4))
