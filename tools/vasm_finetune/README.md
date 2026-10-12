# V-ASM fine-tuning on the owner's routes

There is no upstream training code (github.com/prabhaavp/vasm-op has only a route-submission notebook) and no `.pt`
checkpoint. The shipped model's ONNX metadata says it is an Ultralytics YOLO26n-cls classifier: input `images`
[1,3,352,352] RGB/255, output `output0` [1,3] softmax over {0 no car, 1 car, 2 distant or rear}.

1. `convert.py`: ONNX to PyTorch (onnx2torch). It rewrites opset-18 `Split(num_outputs)` to explicit sizes, sets
   opset 17, and frees the batch dim baked into the `Reshape` constants. It then compares the converted model with
   cv2.dnn on the daemon's exact input blobs. The output is already softmax, so train on log-probs.
   Result on 96 crops from 00000321--67540f4492 s42: max abs diff 1.97e-06, class and ≥0.8 agreement 100 %.

Run it the same way as `tools/vasm_replay` (scratch dir mounted at /work), with
`pip install av opencv-python-headless onnx onnx2torch torch --extra-index-url https://download.pytorch.org/whl/cpu`.
