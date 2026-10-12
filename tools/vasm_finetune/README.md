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

2. `extract_crops.py`: crops for labelling and the benchmark. It samples both sides at 4 Hz and saves the daemon's
   exact model input (its own `_run_inference` blob) as a 352×352 PNG. Every PNG is checked to reload bit-identical to
   that blob. `crops/manifest.csv` holds the shipped model's three probabilities, radar on that car side, the real
   D-118 pass-hold state, speed, blinker, crop brightness, a proposed label, and why the row needs review.
   Run `tools/vasm_replay/rlog_extract.py` first for the `ex_*.json` files. It is resumable per segment.
   **Test-split crops must all be labelled by hand.** Model proposals there would bias the benchmark toward the shipped
   model. Proposals are only a shortcut for training crops.
   Result on 00000321 s30/31/41/42 + 00000323 s3/4: 2,582 crops (164 MB). `p_car` matches the earlier
   `conf_replay` run within 5e-05. 1,272 were flagged for review: 1,091 uncertain (<0.98), 174 where the pass hold says
   occupied but the camera says clear, 14 where radar is within 8 m but the camera says clear.

3. `labeler.py`: a local labelling page, stdlib only, on 127.0.0.1. Start it with
   `python3 tools/vasm_finetune/labeler.py`, then open `http://127.0.0.1:8765/?split=test`.
   - **Keys:** 0 no car, 1 car, 2 distant or rear, x unsure, arrow keys to move.
   - **Context:** each crop is shown with the same side 0.25 s and 0.5 s before and after it, plus radar and the pass-hold state.
   - **Blind test labelling:** test crops are labelled blind (the model's probabilities and proposal are hidden). `?split=train`
     shows only the flagged crops, with the model's view.
   - **Saving:** labels go to `<crops>/labels.json` after every key press. Reopening resumes at the first unlabelled crop.
   - **Verified with headless Chromium:** five rapid key presses land five labels, on five crops, in order. The first version lost
     fast presses to a save race. A path-traversal request returns 404.
