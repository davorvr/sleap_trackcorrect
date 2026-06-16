#!/usr/bin/env python3
"""
SLEAP Social Track Corrector — server + review UI.

Usage:
    uv run python serve.py \
        --labels-dir /path/to/predictions/files \
        --video-dir /path/to/video/files \
        [--port 8500]

Opens a browser at localhost:8500.  Select a social .slp file, review the
tracked instances overlaid on video, reassign tracks with bidirectional
distance-based propagation, and save corrected labels to a :file:`corrected/`
subdirectory next to the input file.
"""

import argparse
import io
import json
import logging
import math
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import sleap_io as sio
from flask import Flask, Response, jsonify, render_template, request, send_file

log = logging.getLogger("sleap_review")

# ---------------------------------------------------------------------------
# Optional imports (only needed to open the browser)
# ---------------------------------------------------------------------------
try:
    import webbrowser

    HAS_WEB = True
except Exception:
    HAS_WEB = False


# =============================================================================
# App factory
# =============================================================================


def create_app(labels_dir: Path, video_dir: Path) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
    )
    app.config["LABELS_DIR"] = labels_dir.resolve()
    app.config["VIDEO_DIR"] = video_dir.resolve()
    app.config["CORRECTED_DIR"] = labels_dir.resolve() / "corrected"
    app.config["SOCIAL_FILE_MAP"] = _build_social_file_map(labels_dir, video_dir)
    app.config["SKELETON"] = _extract_skeleton(app.config["SOCIAL_FILE_MAP"])
    app.config["LABEL_CACHE"] = {}
    app.config["DISTANCE_CACHE"] = {}

    _register_routes(app)
    return app


# =============================================================================
# Social file index
# =============================================================================

ANIMAL_PAIR_RE = re.compile(r"__([a-zA-Z0-9]+)-([a-zA-Z0-9]+)__")


def _parse_animal_pair(filename: str) -> list[str]:
    m = ANIMAL_PAIR_RE.search(filename)
    if m:
        return [m.group(1), m.group(2)]
    return ["", ""]


def _json_float(value):
    """Return a JSON-safe float or None for missing/non-finite values."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _extract_skeleton(file_map: list[dict]) -> dict:
    """Extract skeleton node names and edge pairs from the first readable file."""
    for entry in file_map:
        try:
            labels = sio.load_slp(entry["path"], lazy=True)
            skel = labels.skeletons[0]
            nodes = [n.name for n in skel.nodes]
            edges = [(e.source.name, e.destination.name) for e in skel.edges]
            return {"nodes": nodes, "edges": edges}
        except Exception:
            continue
    return {"nodes": [], "edges": []}


def _resolve_video_path(video_filename: str, video_dir: Path) -> Path:
    """Resolve a SLEAP-stored video path against the user-provided video dir."""
    video_name = Path(video_filename).name
    direct = video_dir / video_name
    if direct.exists():
        return direct.resolve()

    matches = sorted(video_dir.rglob(video_name))
    if matches:
        return matches[0].resolve()

    # Return expected path so UI/server errors show the filename being sought.
    return direct.resolve()


def _build_social_file_map(labels_dir: Path, video_dir: Path) -> list[dict]:
    files = sorted(labels_dir.glob("*.slp"))
    result = []
    for f in files:
        animal_ids = _parse_animal_pair(f.name)
        try:
            labels = sio.load_slp(str(f), lazy=True)
            n_frames = len(labels.labeled_frames)
            video_path = _resolve_video_path(labels.videos[0].filename, video_dir) if labels.videos else Path("")
            fps = labels.videos[0].fps if labels.videos else 50.0
            tracks = [t.name for t in labels.tracks]
        except Exception:
            log.warning("Skipping unreadable file: %s", f.name)
            continue
        result.append(
            {
                "path": str(f),
                "filename": f.name,
                "animal_ids": animal_ids,
                "n_frames": n_frames,
                "video_path": str(video_path),
                "video_exists": bool(video_path.exists()),
                "fps": fps,
                "tracks": tracks,
            }
        )
    return result


def _get_lazy_labels(app: Flask, file_path: Path):
    """Load labels once per file for responsive frame overlay requests."""
    cache = app.config["LABEL_CACHE"]
    key = str(file_path)
    if key not in cache:
        # Keep the cache tiny; users typically review one file at a time.
        if len(cache) >= 3:
            cache.pop(next(iter(cache)))
        cache[key] = sio.load_slp(key, lazy=True)
    return cache[key]


def _get_frame_distances(app: Flask, file_path: Path) -> list[float | None]:
    """Return centroid-centroid distance for every labeled frame in a file."""
    cache = app.config["DISTANCE_CACHE"]
    key = str(file_path)
    if key in cache:
        return cache[key]

    labels = _get_lazy_labels(app, file_path)
    distances = []
    for lf in labels.labeled_frames:
        if len(lf.instances) < 2:
            distances.append(None)
            continue
        c0 = _inst_centroid(lf.instances[0])
        c1 = _inst_centroid(lf.instances[1])
        if c0 is None or c1 is None:
            distances.append(None)
        else:
            distances.append(float(math.hypot(c0[0] - c1[0], c0[1] - c1[1])))

    if len(cache) >= 3:
        cache.pop(next(iter(cache)))
    cache[key] = distances
    return distances


# =============================================================================
# Route registration
# =============================================================================


def _register_routes(app: Flask):
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/files")
    def api_files():
        return jsonify(
            {
                "files": app.config["SOCIAL_FILE_MAP"],
                "skeleton": app.config.get("SKELETON", {}),
            }
        )

    @app.route("/api/frame")
    def api_frame():
        rel = request.args.get("file", "")
        frame_idx = int(request.args.get("frame", 0))
        labels_dir: Path = app.config["LABELS_DIR"]
        file_path = (labels_dir / rel).resolve()

        # Basic safety
        if labels_dir not in file_path.parents or file_path != file_path.resolve():
            return jsonify({"error": "file not in labels directory"}), 403

        labels = _get_lazy_labels(app, file_path)
        if frame_idx < 0 or frame_idx >= len(labels.labeled_frames):
            return jsonify({"error": "frame out of range"}), 400

        lf = labels.labeled_frames[frame_idx]
        instances = []
        for inst in lf.instances:
            pts_data = []
            for pt in inst.points:
                xy = pt["xy"]
                pts_data.append(
                    {
                        "x": float(xy[0]) if np.isfinite(xy[0]) else None,
                        "y": float(xy[1]) if np.isfinite(xy[1]) else None,
                        "visible": bool(pt["visible"]),
                        "score": float(pt["score"]) if np.isfinite(pt["score"]) else None,
                        "name": str(pt["name"]),
                    }
                )
            instances.append(
                {
                    "track": inst.track.name if inst.track else "",
                    "score": _json_float(inst.score),
                    "points": pts_data,
                }
            )

        return jsonify(
            {
                "frame_idx": int(lf.frame_idx) if hasattr(lf, "frame_idx") else frame_idx,
                "instances": instances,
            }
        )

    @app.route("/api/distances")
    def api_distances():
        rel = request.args.get("file", "")
        labels_dir: Path = app.config["LABELS_DIR"]
        file_path = (labels_dir / rel).resolve()

        if labels_dir not in file_path.parents or file_path != file_path.resolve():
            return jsonify({"error": "file not in labels directory"}), 403

        distances = _get_frame_distances(app, file_path)
        return jsonify({"distances": distances})

    @app.route("/api/video_frame")
    def api_video_frame():
        file_path = request.args.get("file", "")
        frame_idx = int(request.args.get("frame", 0))

        # Find the video path from the file map
        for entry in app.config["SOCIAL_FILE_MAP"]:
            if entry["path"] == file_path:
                video_path = entry["video_path"]
                break
        else:
            return jsonify({"error": "file not found"}), 404

        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return jsonify({"error": "cannot read video frame"}), 500

        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(buf.tobytes(), mimetype="image/jpeg")

    @app.route("/api/video")
    def api_video():
        file_path = request.args.get("file", "")

        for entry in app.config["SOCIAL_FILE_MAP"]:
            if entry["path"] == file_path:
                video_path = Path(entry["video_path"])
                break
        else:
            return jsonify({"error": "file not found"}), 404

        if not video_path.exists():
            return jsonify({"error": f"video not found: {video_path}"}), 404

        # Werkzeug handles HTTP Range requests for browser-native seeking.
        return send_file(video_path, mimetype="video/mp4", conditional=True)

    @app.route("/api/save", methods=["POST"])
    def api_save():
        data = request.get_json(force=True)
        rel = data.get("file", "")
        editing = data.get("edits", [])
        track_labels = data.get("track_labels", {})  # e.g. {"track_0": "crni10", "track_1": "crveni1"}
        propagate_cfg = data.get("propagation", {"enabled": False, "distance_px": 50, "max_frames": 500})

        labels_dir: Path = app.config["LABELS_DIR"]
        file_path = (labels_dir / rel).resolve()
        if labels_dir not in file_path.parents:
            return jsonify({"error": "file not in labels directory"}), 403

        out_dir: Path = app.config["CORRECTED_DIR"]
        out_dir.mkdir(parents=True, exist_ok=True)

        labels = sio.load_slp(str(file_path))
        n_frames = len(labels.labeled_frames)
        tracks = {t.name: t for t in labels.tracks}

        # Apply instant (clicked) reassignments
        for edit in editing:
            fi = edit["frame_idx"]
            if fi < 0 or fi >= n_frames:
                continue
            lf = labels.labeled_frames[fi]
            old_name = edit["old_track"]
            new_name = edit["new_track"]
            _swap_tracks_in_frame(lf, old_name, new_name, tracks)

            # Propagation (server-side, bidirectional)
            if propagate_cfg.get("enabled", False):
                mode = propagate_cfg.get("mode", "distance")
                dist_px = propagate_cfg.get("distance_px", 50)
                max_frames = propagate_cfg.get("max_frames", 500)
                if max_frames is None:
                    max_frames = n_frames
                else:
                    max_frames = int(max_frames)

                if mode == "smart":
                    _propagate_smart(labels, fi, old_name, new_name, dist_px, max_frames)
                else:
                    _propagate(labels, fi, old_name, new_name, dist_px, max_frames)

        # Attach track_labels to provenance
        prov = getattr(labels, "provenance", {}) or {}
        prov["track_labels"] = track_labels
        labels.provenance = prov

        out_path = out_dir / file_path.name
        sio.save_slp(labels, str(out_path))
        log.info("Saved corrected labels to %s", out_path)
        return jsonify({"saved": str(out_path), "edits_applied": len(editing)})


# =============================================================================
# Propagation engine
# =============================================================================


def _centroid(pts):
    """Mean of finite x,y points."""
    xs = [p["x"] for p in pts if p["x"] is not None]
    ys = [p["y"] for p in pts if p["y"] is not None]
    if not xs:
        return None
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _centroid_dist(inst_a, inst_b):
    ca, cb = _centroid(inst_a), _centroid(inst_b)
    if ca is None or cb is None:
        return float("inf")
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1])


def _inst_centroid(inst):
    pts = []
    for pt in inst.points:
        xy = pt["xy"]
        if np.isfinite(xy[0]) and np.isfinite(xy[1]):
            pts.append((float(xy[0]), float(xy[1])))
    if not pts:
        return None
    return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))


def _track_instances(lf, first_track_name, second_track_name):
    instances = {first_track_name: None, second_track_name: None}
    for inst in lf.instances:
        if inst.track and inst.track.name in instances:
            instances[inst.track.name] = inst
    return instances[first_track_name], instances[second_track_name]


def _inst_points(inst):
    pts = {}
    for pt in inst.points:
        xy = pt["xy"]
        if np.isfinite(xy[0]) and np.isfinite(xy[1]):
            score = _json_float(pt["score"])
            pts[str(pt["name"])] = (float(xy[0]), float(xy[1]), score if score is not None else 1.0)
    return pts


def _inst_mean_score(inst):
    scores = []
    for pt in inst.points:
        score = _json_float(pt["score"])
        if score is not None:
            scores.append(score)
    return sum(scores) / len(scores) if scores else 1.0


def _pose_distance(inst_a, inst_b):
    """Distance between two predicted poses, combining centroid and named points."""
    ca = _inst_centroid(inst_a)
    cb = _inst_centroid(inst_b)
    if ca is None or cb is None:
        return float("inf")

    cost = math.hypot(ca[0] - cb[0], ca[1] - cb[1])
    pts_a = _inst_points(inst_a)
    pts_b = _inst_points(inst_b)
    shared = sorted(set(pts_a) & set(pts_b))
    if not shared:
        return cost

    weighted = []
    weights = []
    for name in shared:
        ax, ay, ascore = pts_a[name]
        bx, by, bscore = pts_b[name]
        weight = max(0.05, min(ascore, bscore))
        weighted.append(math.hypot(ax - bx, ay - by) * weight)
        weights.append(weight)
    return 0.45 * cost + 0.55 * (sum(weighted) / sum(weights))


def _pair_centroid_distance(inst_a, inst_b):
    ca = _inst_centroid(inst_a)
    cb = _inst_centroid(inst_b)
    if ca is None or cb is None:
        return None
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1])


def _too_close_instances(inst_a, inst_b, dist_px):
    distance = _pair_centroid_distance(inst_a, inst_b)
    return distance is not None and distance < dist_px


def _propagate(labels, start_frame, old_track_name, new_track_name, dist_px, max_frames):
    n = len(labels.labeled_frames)
    tracks = {t.name: t for t in labels.tracks}

    def _too_close(lf):
        instances_with_centroids = [(inst, _inst_centroid(inst)) for inst in lf.instances]
        finite = [(inst, c) for inst, c in instances_with_centroids if c is not None]
        if len(finite) < 2:
            return False
        for i in range(len(finite)):
            for j in range(i + 1, len(finite)):
                ci, cj = finite[i][1], finite[j][1]
                if math.hypot(ci[0] - cj[0], ci[1] - cj[1]) < dist_px:
                    return True
        return False

    # Forward
    for f in range(start_frame + 1, min(start_frame + max_frames + 1, n)):
        lf = labels.labeled_frames[f]
        if _too_close(lf):
            break
        _swap_tracks_in_frame(lf, old_track_name, new_track_name, tracks)

    # Backward
    for f in range(start_frame - 1, max(start_frame - max_frames - 1, -1), -1):
        lf = labels.labeled_frames[f]
        if _too_close(lf):
            break
        _swap_tracks_in_frame(lf, old_track_name, new_track_name, tracks)


def _propagate_smart(labels, start_frame, old_track_name, new_track_name, dist_px, max_frames):
    """Propagate only while swapped identities improve pose/motion continuity.

    The edit frame has already been swapped. Moving away from it, each frame is
    tested under its current assignment and under the swapped assignment. We only
    keep swapping while the swapped assignment is clearly cheaper, and we stop at
    close interactions where identities are intrinsically ambiguous.
    """
    n = len(labels.labeled_frames)
    tracks = {t.name: t for t in labels.tracks}
    start_lf = labels.labeled_frames[start_frame]
    start_old, start_new = _track_instances(start_lf, old_track_name, new_track_name)
    if start_old is None or start_new is None:
        return

    def _walk(direction):
        ref_old, ref_new = start_old, start_new
        last_current_cost = 0.0
        stop = min(start_frame + max_frames, n - 1) if direction > 0 else max(start_frame - max_frames, 0)
        frame_range = range(start_frame + direction, stop + direction, direction)

        for frame_idx in frame_range:
            lf = labels.labeled_frames[frame_idx]
            cand_old, cand_new = _track_instances(lf, old_track_name, new_track_name)
            if cand_old is None or cand_new is None:
                break
            if _too_close_instances(cand_old, cand_new, dist_px):
                break

            current_cost = _pose_distance(ref_old, cand_old) + _pose_distance(ref_new, cand_new)
            swapped_cost = _pose_distance(ref_old, cand_new) + _pose_distance(ref_new, cand_old)
            if not math.isfinite(current_cost) or not math.isfinite(swapped_cost):
                break

            confidence = min(_inst_mean_score(cand_old), _inst_mean_score(cand_new))
            margin_px = max(8.0, 18.0 * (1.0 - confidence))
            large_jump = last_current_cost > 0 and min(current_cost, swapped_cost) > max(75.0, last_current_cost * 4.0)
            if large_jump:
                break

            if swapped_cost + margin_px < current_cost:
                _swap_tracks_in_frame(lf, old_track_name, new_track_name, tracks)
                ref_old, ref_new = cand_new, cand_old
                last_current_cost = swapped_cost
            else:
                break

    _walk(1)
    _walk(-1)


def _swap_tracks_in_frame(lf, old_track_name, new_track_name, tracks):
    """Swap two track assignments in a frame, preserving exactly two identities."""
    old_track = tracks.get(old_track_name)
    new_track = tracks.get(new_track_name)
    if old_track is None or new_track is None:
        return
    for inst in lf.instances:
        if not inst.track:
            continue
        if inst.track.name == old_track_name:
            inst.track = new_track
        elif inst.track.name == new_track_name:
            inst.track = old_track


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="SLEAP Social Track Corrector")
    parser.add_argument(
        "--labels-dir",
        "--input",
        dest="labels_dir",
        required=True,
        help="Directory containing social .slp prediction files",
    )
    parser.add_argument(
        "--video-dir",
        required=True,
        help="Directory containing matching MP4 videos. The SLP video basename is resolved inside this directory.",
    )
    parser.add_argument("--port", type=int, default=8500, help="HTTP port (default: 8500)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    labels_dir = Path(args.labels_dir).resolve()
    if not labels_dir.is_dir():
        sys.exit(f"Error: labels directory does not exist: {labels_dir}")

    video_dir = Path(args.video_dir).resolve()
    if not video_dir.is_dir():
        sys.exit(f"Error: video directory does not exist: {video_dir}")

    app = create_app(labels_dir, video_dir)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    url = f"http://localhost:{args.port}"
    if not args.no_browser and HAS_WEB:
        webbrowser.open(url)

    log.info("Serving labels from %s", labels_dir)
    log.info("Resolving SLP video basenames under %s", video_dir)
    log.info("Open %s in your browser", url)
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
