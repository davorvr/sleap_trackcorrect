# SLEAP Social Track Corrector

Standalone local web app for reviewing two-animal social SLEAP `.slp` files and saving corrected track assignments.

## Quick Start

1. Populate `videos/` and `predictions/` directories
2. Run `bash ./start_server.sh`

## Data Folders

By default, the launcher uses these folders inside this tool directory:

```text
predictions/   # put social .slp files here
videos/        # put matching .mp4 files here
```

The folders are intentionally empty in git. Their contents are ignored so large data files do not get committed.

## Create The Tool Environment

From this repository root:

```bash
uv sync
```

Or run directly; uv will create the environment automatically:

```bash
bash explore/sleap_review/start_server.sh
```

Corrected files are saved to `predictions/corrected/` by default.

You can still pass explicit directories:

```bash
bash ./start_server.sh LABELS_DIR VIDEO_DIR 8500
```

`LABELS_DIR` can be relative or absolute. `VIDEO_DIR` can be relative or absolute. Corrected files are saved to `LABELS_DIR/corrected/`.

## Direct uv Run

```bash
uv run --project ./ python serve.py \
  --labels-dir predictions/ \
  --video-dir videos/ \
  --port 8500
```

Open `http://localhost:8500` after startup.
