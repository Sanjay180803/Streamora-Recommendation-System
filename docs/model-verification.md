# Model verification and evaluation status

This page records what is and is not verified about the recommendation models.
Nothing here has been changed by guessing; open items need the original
training code.

## Status

| Item | Status |
|---|---|
| ONNX models load and run | Verified only by the original authors; this repository's tests use a fake session |
| Input format (padding, mask, offsets) | Inferred from `recommender.py`; not checked against training code |
| BERT4Rec output position | **Unverified — possible bug** (below) |
| SASRec output position | Consistent with standard next-item prediction |
| User features at inference | Always a zero vector (the population mean after standardisation) |
| Published HR / NDCG / MRR | **Not reproducible** from this repository |
| Train/validation/test split | Undocumented; leakage cannot be checked |

## BERT4Rec: which position holds the next-item prediction?

BERT4Rec is trained with masked-item prediction. The usual way to predict the
*next* item is to append a `[MASK]` token after the history and read the logits
at that masked position.

`recommender._run_inference` does **not** append a mask token. It left-pads the
history and reads the logits at the last position, which holds the most
recently watched item. Unless the exported model was trained or wrapped
differently, those logits mostly reconstruct an item the user already watched
(which is then filtered out), so the remaining ranking may be weak.

**Do not change this without evidence.** To resolve it:

1. Obtain the training code and confirm whether a mask token is appended at
   inference time and which output position was used for evaluation.
2. Confirm the vocabulary layout (PAD = 0, MASK = 1, item *i* = token *i* + 2)
   and that `item_idx` in `item_features_final.csv` matches training.
3. Confirm left padding and the `pad_mask` semantics (true = real token).
4. Add a parity test: for a few fixed sequences, run the original PyTorch model
   and the ONNX export and assert the top-k lists (or logits within tolerance)
   match.
5. Only then adjust `_run_inference` if needed, and re-run the evaluation.

## Restoring evaluation reproducibility

The README's metric tables come from the original team's notebooks, which are
not in this repository (`*.ipynb` is gitignored). To make them reproducible:

- [ ] Add the training and evaluation code (scripts, not only notebooks)
- [ ] Document the dataset source, preprocessing and the train/validation/test
      split, including whether splitting is per user (leave-last-out) or
      global by time
- [ ] Check that no user's held-out interactions appear in training sequences
- [ ] Fix random seeds and commit the training configuration
- [ ] Write evaluation results as machine-readable files (e.g. JSON with the
      metric, k, split and artifact checksums)
- [ ] Document the ONNX export (framework version, opset, export script)
- [ ] Record artifact checksums in `configs/artifacts.json` and reference them
      from the results

Until these are done, the README presents the numbers as reported by the
original authors, not as results reproduced here.
