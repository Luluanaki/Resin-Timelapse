# Resin Printer Timelapse Program

A Python script that captures high-quality timelapses of resin printer jobs by
synchronizing camera frames with actual layer timing. Designed for the Resin Printers
and ChiTuBox-style slicer settings.

---

# ✨ Features
- Two-stage motion calculations (ChiTuBox “+” distances).
- Support for bottom layer overrides, normal overrides, and transition layers.
- Firmware overhead calibration for real-world accuracy.
- Monotonic scheduling (immune to system clock changes).
- Automatic MP4 rendering with ffmpeg.
- Optionally opens the finished timelapse folder in Explorer/Finder/Linux.
- Configurable frame spacing, FPS, and video length.

---

# 🖼️ Example
*Timelapse examples soon to come*

---

# 🛠️ Notes
- Tested on Windows 10 with Uniformation GKTwo.
- Should work cross-platform (macOS/Linux) for folder opening and ffmpeg.
- Used a basic logitech webcam for captures.
- This approach isn’t as precise as using a light sensor to detect LCD flashes, but many printers (like the GKTwo) don’t expose direct access to the light, so this script provides a reliable alternative.

---

# Installation
## 1. Install Python
This script requires **Python 3.8+**.  
Download and install from the official site: [Python Downloads](https://www.python.org/downloads/).

On windows, make sure to check **"Add Python to PATH"** during installation.



## 2. Install ffmpeg
This program uses **ffmpeg** to render captured images into an MP4 timelapse video.  
Download ffmpeg from the official site and make sure the `ffmpeg` command is available in your system `PATH`.

- Windows: download the zip build, extract, and add the `bin` folder to PATH.  
- macOS: install with Homebrew → `brew install ffmpeg`.  
- Linux (Debian/Ubuntu): `sudo apt install ffmpeg`.

Confirm installation by running `ffmpeg -version` in a terminal.

## 3. Install dependencies
Clone this repo and install required Python packages:

```bash
git clone https://github.com/<your-username>/resin-timelapse.git
cd resin-timelapse
pip install -r requirements.txt
```
## 4. Set up your camera

- Connect USB webcam (or built-in camera).
- Update CAM_INDEX in timelapse.py if needed (0 = default camera).
- Resolution defaults to 1920×1080, but you can adjust RES_W and RES_H.

## 5. Run the program

From inside the repo folder:

```bash
python timelapse.py
```
You will be prompted for:

- Session/folder name (where captures and video are stored).
- Total layers (from slicer).
- Video FPS.
- Desired video length (seconds).
  
When the print finishes, the script:
- Captures frames during the print.
- Builds an MP4 timelapse with ffmpeg.
- (Optional) Deletes all captured images
- (Optional) Opens the folder in Explorer/Finder/Linux.

---

# 🧪 Tune firmware Overhead

Modern resin printers add small, fixed delays each layer that don’t show up in slicer math (LCD settle time, motion controller latency, acceleration ramps, UI/LED delays, etc.).
This script models that as a single constant: `FIRMWARE_OVERHEAD_S = 1.4`


On the Uniformation GKTwo, the overhead is about 1.4 s per layer.
By including this value, the program aligns theoretical timing more closely with actual print timing.

**The closer the actual print timing, the more smooth the timelapse.**


##  Calibration

To calibrate your printer’s firmware overhead:

1. **Measure your actual normal layer time**
    - Start a print and use a stopwatch to measure start-to-start layer times:
      - Begin timing when the **UV light turns on**.
      - Stop timing when it turns on again.
    - For accuracy, measure multiple layers (e.g., 10) and divide by that count.

2. **Get the theoretical layer time**
   - Run the script once.
   - Look at the startup summary for `Normal (theoretical): X.XX s`

3. **Calculate firmware overhead**
    - `FIRMWARE_OVERHEAD_S = measured_normal - theoretical_normal`

5. **Update the constant**
    - Open **timelapse.py** and set:  `FIRMWARE_OVERHEAD_S = X.X`

5. **Re-run the program**
    - Start your program when beginning a print.
    - Captures should now closely match your printer’s actual cycle time.

