# SLEAP Social Track Corrector

Standalone local web app for reviewing two-animal social SLEAP `.slp` files and saving corrected track assignments.

## Quick Start

1. Make sure you have `uv` installed
2. Download the repo, unpack it, and `cd` into the dir
3. Populate `videos/` and `predictions/` directories
4. Run `bash ./start_server.sh`

## Detailed instructions

### Data Folders

By default, the launcher uses these folders inside this tool directory:

```text
predictions/   # put social .slp files here
videos/        # put matching .mp4 files here
```

The folders are intentionally empty in git. Their contents are ignored so large data files do not get committed.

### Create The Tool Environment

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

### Direct uv Run

```bash
uv run --project ./ python serve.py \
  --labels-dir predictions/ \
  --video-dir videos/ \
  --port 8500
```

Open `http://localhost:8500` after startup.

## Auto-Propagation Algorithms

When you manually assign a selected animal to the other track, the app can propagate that correction forward and backward from the edited frame. Auto-propagation never changes the original input file directly; changes are applied only when you click `Save to corrected/`.

### Distance Stop (Current)

This is the simpler mode. After the edited frame is swapped, the app keeps swapping the same two track labels in neighboring frames, moving forward and backward.

Propagation stops when one of these happens:

- the two animal centroids are closer than `Min distance`
- the `Limit max frames` cap is enabled and reached
- the video reaches the first or last frame

Use this mode when a track identity swap is obvious and persists across a clear span where the animals remain separated. It is predictable, but it does not check whether the motion or pose continuity actually supports each propagated swap.

### Smart Continuity

This mode still starts from the manually corrected frame, but each neighboring frame is evaluated before it is swapped. For each frame, the app compares two possibilities:

- keep the current track assignment
- swap the two track assignments

It scores both possibilities using pose and motion continuity from the previous accepted frame. The score combines centroid movement and matching named keypoints such as `nose`, `ear_L`, `ear_R`, `tail_base`, and `neck`. Keypoints with higher SLEAP confidence contribute more than low-confidence keypoints.

The frame is swapped only when the swapped assignment is clearly better than the current assignment. Propagation stops when the evidence is ambiguous, when there is a large implausible jump, when either animal is missing, or when the two animals are closer than `Min distance`.

Use this mode when you want safer automatic correction around uncertain regions. It is less aggressive than distance mode and is designed to avoid propagating through crossings, close interactions, or occlusions.

### Controls

`Min distance` applies to both algorithms. In `Distance Stop`, it is the main stop rule. In `Smart Continuity`, it is a hard ambiguity stop: the app will not auto-propagate through frames where animals are closer than this distance.

`Limit max frames` is disabled by default. When disabled, propagation can continue until an algorithm-specific stop condition or the edge of the video. When enabled, propagation is capped to the selected number of frames in each direction.
