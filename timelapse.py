import os, time, cv2, re, subprocess, math, platform
from datetime import datetime, timedelta

# ================== USER TOGGLES ==================
KEEP_FRAMES       = False     # False = delete seq_*.jpg after video render; True = keep them
EXTRA_CAPTURE_SEC = 600       # extra time (seconds) to keep capturing after the planned window (e.g., 600 = 10 min)
OPEN_FOLDER_ON_FINISH = True
# ==================================================

# ==== FIXED PRINT SETTINGS (GKTwo / ChiTuBox-like) ====
# Counts
BOTTOM_LAYERS     = 10
TRANSITION_LAYERS = 7                   # layers between bottom & normal
TRANSITION_TYPE   = "linear"            # only "linear" modeled

# Exposures
NORMAL_EXPOSURE_S = 1.7
BOTTOM_EXPOSURE_S = 50.0

# Rests (Waiting mode: Resting time)
REST_BEFORE_LIFT_S   = 0.5
REST_AFTER_LIFT_S    = 0.0
REST_AFTER_RETRACT_S = 2.0

# ---------- Two-stage MOTION (distances in mm, speeds in mm/min) ----------
# Bottom motion (from your screenshot)
B_LIFT_MM_1,   B_LIFT_MM_2   = 5.0, 5.0
B_LIFT_V_1,    B_LIFT_V_2    = 50.0, 100.0
B_RETR_MM_1,   B_RETR_MM_2   = 9.0, 1.0
B_RETR_V_1,    B_RETR_V_2    = 100.0, 50.0   # you set 50; keep as-is

# Normal motion (from your screenshot)
N_LIFT_MM_1,   N_LIFT_MM_2   = 1.8, 2.4
N_LIFT_V_1,    N_LIFT_V_2    = 135.0, 230.0
N_RETR_MM_1,   N_RETR_MM_2   = 2.2, 2.0
N_RETR_V_1,    N_RETR_V_2    = 230.0, 90.0

# Small fixed overhead per layer to account for controller/accel/settle latencies
FIRMWARE_OVERHEAD_S = 1.4

# ---- Manual overrides for real-world per-layer time ----
# Normal
USE_MEASURED_NORMAL = False
MEASURED_NORMAL_S   = 9.03

# Bottom (optional, mirrors normal override)
USE_MEASURED_BOTTOM = False
MEASURED_BOTTOM_S   = 126.9

# Camera & output defaults
CAM_INDEX     = 0
RES_W, RES_H  = 1920, 1080
JPEG_QUALITY  = 90
ROOT_OUT_DIR  = "captures"

# ---------------- Helpers ----------------
def two_stage_time_s(d1, d2, v1, v2):
    """Two-stage motion time in seconds (distances in mm, speeds in mm/min)."""
    if v1 <= 0 or v2 <= 0:
        raise ValueError("Speeds must be > 0.")
    return 60.0 * ((d1 / v1) + (d2 / v2))

def normal_motion_time_s():
    lift    = two_stage_time_s(N_LIFT_MM_1,  N_LIFT_MM_2,  N_LIFT_V_1,  N_LIFT_V_2)
    retract = two_stage_time_s(N_RETR_MM_1,  N_RETR_MM_2,  N_RETR_V_1,  N_RETR_V_2)
    return lift, retract

def bottom_motion_time_s():
    lift    = two_stage_time_s(B_LIFT_MM_1,  B_LIFT_MM_2,  B_LIFT_V_1,  B_LIFT_V_2)
    retract = two_stage_time_s(B_RETR_MM_1,  B_RETR_MM_2,  B_RETR_V_1,  B_RETR_V_2)
    return lift, retract

def layer_time_s(exposure_s, lift_s, retract_s):
    """Full per-layer time with rests + motion + exposure."""
    return (
        exposure_s
        + REST_BEFORE_LIFT_S
        + lift_s
        + REST_AFTER_LIFT_S
        + retract_s
        + REST_AFTER_RETRACT_S
    )

def transition_interval_s():
    """ChiTuBox linear: (bottom - normal) / (N + 1)."""
    if TRANSITION_LAYERS <= 0:
        return 0.0
    return (BOTTOM_EXPOSURE_S - NORMAL_EXPOSURE_S) / (TRANSITION_LAYERS + 1.0)

def transition_exposures():
    """List of exposure seconds for each transition layer (1..N), linear ramp."""
    n = TRANSITION_LAYERS
    if n <= 0:
        return []
    step = transition_interval_s()
    return [BOTTOM_EXPOSURE_S - (i * step) for i in range(1, n + 1)]

def compute_times():
    # Motion times
    n_lift, n_retr = normal_motion_time_s()
    b_lift, b_retr = bottom_motion_time_s()

    # Theoretical per-layer times (+ firmware overhead)
    t_normal_theoretical = layer_time_s(NORMAL_EXPOSURE_S, n_lift, n_retr) + FIRMWARE_OVERHEAD_S
    t_bottom_theoretical = layer_time_s(BOTTOM_EXPOSURE_S, b_lift, b_retr) + FIRMWARE_OVERHEAD_S

    # Apply measured overrides if enabled
    t_normal = MEASURED_NORMAL_S if USE_MEASURED_NORMAL else t_normal_theoretical
    t_bottom = MEASURED_BOTTOM_S if USE_MEASURED_BOTTOM else t_bottom_theoretical

    # Transition layers use NORMAL motion, stepped exposures, + overhead per layer
    t_transition_each = [layer_time_s(exp, n_lift, n_retr) + FIRMWARE_OVERHEAD_S
                         for exp in transition_exposures()]

    return (
        round(t_bottom_theoretical, 3),
        round(t_normal_theoretical, 3),
        round(t_bottom, 3),
        round(t_normal, 3),
        [round(x, 3) for x in t_transition_each],
        round(transition_interval_s(), 4),
    )

def ask(prompt, default=None, cast=str):
    s = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
    if s == "" and default is not None:
        return cast(default)
    return cast(s)

def sanitize(name: str) -> str:
    name = name.strip().replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9_\-]", "", name) or "session"

def allocate_session_dir(root: str, session_name: str) -> str:
    base = os.path.join(root, session_name)
    if not os.path.exists(base):
        os.makedirs(base, exist_ok=True)
        return base
    i = 1
    while True:
        candidate = f"{base}-{i:03d}"
        if not os.path.exists(candidate):
            os.makedirs(candidate, exist_ok=True)
            return candidate
        i += 1

def capture_frame(cap, out_dir, idx):
    path = os.path.join(out_dir, f"seq_{idx:05d}.jpg")
    ok, frame = cap.read()
    if not ok or frame is None:
        return None
    cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    return path

def reveal_in_file_manager(target_path: str):
    """
    Reveal a file in the OS file manager if possible; otherwise open the folder.
    - Windows: Explorer with the file pre-selected.
    - macOS: Finder 'reveal'.
    - Linux: Opens the containing folder.
    """
    target_path = os.path.realpath(target_path)
    folder = os.path.dirname(target_path)
    try:
        system = platform.system()
        if system == "Windows":
            try:
                subprocess.run(["explorer", "/select,", target_path], check=True)
            except Exception:
                os.startfile(folder)  # type: ignore[attr-defined]
        elif system == "Darwin":
            try:
                subprocess.run(["open", "-R", target_path], check=True)
            except Exception:
                subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)
    except Exception as e:
        print(f"⚠️ Could not open folder: {e}")

def _monotonic_sleep(seconds: float):
    """Sleep using monotonic time as a reference (immune to wall-clock jumps)."""
    end = time.monotonic() + max(0.0, seconds)
    while True:
        remain = end - time.monotonic()
        if remain <= 0:
            break
        time.sleep(min(1.0, remain))

def main():
    # 1) Session/folder name
    session_raw = ask("Session/folder name", default=datetime.now().strftime("print_%Y%m%d"))
    session_name = sanitize(session_raw)
    out_dir = allocate_session_dir(ROOT_OUT_DIR, session_name)
    print(f"\n📁 Session folder: {os.path.abspath(out_dir)}")

    # 2) Timing summary
    t_bot_theo, t_norm_theo, t_bot, t_norm, t_trans_list, t_step = compute_times()

    print("\nTiming (per layer):")
    print(f"  Bottom (theoretical): {t_bot_theo}s | Using: {t_bot}s "
          f"({'measured' if USE_MEASURED_BOTTOM else 'theoretical'})")
    print(f"  Normal (theoretical): {t_norm_theo}s | Using: {t_norm}s "
          f"({'measured' if USE_MEASURED_NORMAL else 'theoretical'})")
    if TRANSITION_LAYERS > 0:
        print(f"  Transition interval (exposure step): {t_step}s")
        print(f"  Transition layer times: {t_trans_list}\n")
    else:
        print()

    # 3) Inputs
    total_layers = ask("Total layers (from slicer)", default=5000, cast=int)
    fps          = ask("Output video FPS", default=30, cast=int)
    target_sec   = ask("Desired video length (seconds)", default=8.0, cast=float)

    # Count layers we will capture across (post-bottoms & post-transitions)
    normal_layers = max(total_layers - BOTTOM_LAYERS - TRANSITION_LAYERS, 0)
    frames_needed = int(round(fps * target_sec))

    # Delay: wait out bottoms + transitions (by time), then start capturing
    delay_bottoms_s     = BOTTOM_LAYERS * t_bot
    delay_transitions_s = sum(t_trans_list)
    delay_start         = delay_bottoms_s + delay_transitions_s

    if frames_needed <= 0 or normal_layers == 0:
        print("Nothing to do (check inputs: need frames_needed > 0 and some normal layers).")
        return

    # Evenly space frames across the normal-layer window using chosen t_norm
    interval_s = (normal_layers * t_norm) / frames_needed

    # Extra tail frames at the same interval (round up so you always get at least EXTRA_CAPTURE_SEC)
    extra_frames = int(math.ceil(max(0, EXTRA_CAPTURE_SEC) / interval_s))

    total_planned_frames = frames_needed + extra_frames
    total_runtime = delay_start + total_planned_frames * interval_s
    eta = datetime.now() + timedelta(seconds=total_runtime)

    print("Plan:")
    print(f"  Skip bottoms: ~{delay_bottoms_s/60:.1f} min "
          f"(= {BOTTOM_LAYERS} × {t_bot:.2f}s)")
    if TRANSITION_LAYERS > 0:
        print(f"  Skip transitions: ~{delay_transitions_s/60:.1f} min "
              f"(= sum of {TRANSITION_LAYERS} transition layers)")
    print(f"  Capture {frames_needed} frames for the main window + {extra_frames} extra tail frames")
    print(f"  Interval: {interval_s:.1f} s  (≈ every {interval_s/t_norm:.1f} layers)")
    print(f"  Estimated capture window after start: {total_runtime/3600:.2f} h (ETA ~ {eta.strftime('%Y-%m-%d %H:%M')})")
    print(f"  KEEP_FRAMES = {KEEP_FRAMES} | EXTRA_CAPTURE_SEC = {EXTRA_CAPTURE_SEC}\n")

    # 4) Open camera
    cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RES_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RES_H)
    if not cap.isOpened():
        print("❌ Cannot open camera. Check USB / CAM_INDEX.")
        return

    # 5) Wait out bottoms + transitions (monotonic-friendly)
    print(f"Waiting {int(delay_start)} seconds for bottom + transition layers…")
    _monotonic_sleep(delay_start)

    # 6) Interval capture loop (main + tail)
    print("Starting interval capture. Ctrl+C to stop early.")
    start = time.monotonic()  # taken AFTER the delay
    for i in range(total_planned_frames):
        # Capture
        saved = capture_frame(cap, out_dir, i)
        if saved is None:
            print("⚠️ Camera read failed; retrying in 1s…")
            time.sleep(1)
            continue
        print(f"[{i+1}/{total_planned_frames}] Saved {saved}")

        # Pace to next shot — DO NOT add delay_start here (already waited)
        next_time = start + (i+1) * interval_s
        wait = max(0.0, next_time - time.monotonic())
        time.sleep(wait)

    cap.release()

    # 7) Build video with ffmpeg
    out_mp4 = os.path.join(out_dir, f"{session_name}.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate", str(fps),
        "-i", os.path.join(out_dir, "seq_%05d.jpg"),
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        out_mp4
    ]
    print("\n🎬 Running ffmpeg to render video…")
    try:
        subprocess.run(cmd, check=True)
        print(f"✅ Rendered {out_mp4}")
    except Exception as e:
        print(f"ffmpeg failed: {e}")
        return

    # 8) Optionally delete frames
    if not KEEP_FRAMES:
        deleted = 0
        for f in os.listdir(out_dir):
            if f.startswith("seq_") and f.endswith(".jpg"):
                try:
                    os.remove(os.path.join(out_dir, f))
                    deleted += 1
                except OSError:
                    pass
        print(f"🗑️ Deleted {deleted} frame files, kept only {out_mp4}")
    else:
        print("🗂️ KEEP_FRAMES=True → frames preserved alongside the MP4.")

    # 9) Open new folder / reveal the rendered file
    if OPEN_FOLDER_ON_FINISH:
        reveal_in_file_manager(out_mp4)

if __name__ == "__main__":
    main()
