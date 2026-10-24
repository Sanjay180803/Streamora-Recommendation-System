# Model and data artifacts

The backend cannot start without trained models and feature tables. These files
are **not stored in git** (they are large and were produced outside this
repository), and they are **not baked into the Docker image**.

## Required files

The authoritative list is [`configs/artifacts.json`](../configs/artifacts.json).

| File | Required | Purpose |
|---|---|---|
| `data/bert4rec_v3.onnx` | yes | BERT4Rec model graph |
| `data/bert4rec_v3.onnx.data` | yes | BERT4Rec weights (ONNX external data; must sit beside the `.onnx`) |
| `data/sasrec_v3.onnx` | no | SASRec model graph; without it every request uses BERT4Rec |
| `data/sasrec_v3.onnx.data` | no | SASRec weights |
| `data/item_features_final.csv` | yes | Catalogue: `item_id`, `item_idx`, `title`, `release_year`, `click_count`, `log_popularity`, `genre_*` columns |
| `data/user_features_final.csv` | yes | User features; loaded at startup, but inference currently passes a zero user vector |

## Obtaining them

The files were produced by the original Streamora team's training pipeline,
which is not in this repository. Request them from the
[upstream project](https://github.com/RP-1106/Streamora-Recommendation-System)
maintainers and place them in `data/`.

Once you have them, record their checksums so later copies can be verified:

```bash
python scripts/check_artifacts.py --record   # writes sha256 values into configs/artifacts.json
python scripts/check_artifacts.py            # verifies presence and checksums
```

Commit the updated manifest. Until checksums are recorded, the checker can only
confirm that the files exist.

## How they are used

- **Local run:** the backend reads `DATA_DIR` (default `../data` relative to
  `backend/`). `MODEL_PATH` and `SASREC_MODEL_PATH` override the model paths.
- **Docker:** `docker-compose.yml` mounts `./data` read-only at `/app/data`.
- **Missing files:** startup fails with a message listing every missing file
  instead of a stack trace from pandas or ONNX Runtime.
- **Tests and CI** never need these files; they use a small generated
  catalogue and a fake ONNX session (`backend/tests/fakes.py`).

## Model interface the backend assumes

From `backend/recommender.py`. These assumptions have **not** been verified
against the training code; see [model-verification.md](model-verification.md).

| | BERT4Rec | SASRec |
|---|---|---|
| `input_ids` | int64 `[1, 50]`, left-padded with 0 | same |
| `pad_mask` | bool `[1, 50]`, true for real tokens | same |
| `user_feats` | float32 `[1, n_user_features]` | same |
| Token for item `i` | `i + 2` (0 = PAD, 1 = MASK) | `i + 1` (0 = PAD) |
| Logits read from | last sequence position | last sequence position |

## Unknowns

- How the ONNX files were exported (framework, opset, export script) is not
  documented anywhere in the repository.
- There are no recorded checksums, so it is not yet possible to prove that a
  given set of files is the one the published metrics were computed with.
