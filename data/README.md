# data/

Runtime model and data artifacts go here. They are **not committed**: they are
large and derived from a third-party dataset. `.gitignore` excludes `*.onnx`,
`*.onnx.data`, `*.csv` and `*.db` in this directory.

Required files, their purpose and checksums are listed in
[`configs/artifacts.json`](../configs/artifacts.json); see
[docs/artifacts.md](../docs/artifacts.md) for how they are used.

## Getting the files

The models were trained by the original Streamora team. Ask the
[upstream maintainers](https://github.com/RP-1106/Streamora-Recommendation-System)
for the files, copy them here and verify:

```bash
python scripts/check_artifacts.py            # presence (and checksums, once recorded)
python scripts/check_artifacts.py --record   # first time: record sha256 and size
```

## Licensing and redistribution

The feature tables and models are derived from Netflix UK interaction data.
Before publishing them anywhere (GitHub Releases, Git LFS, cloud storage),
confirm the dataset's licence permits redistribution, and record the source
and licence of each file in `configs/artifacts.json`. Until then, share them
only privately.
