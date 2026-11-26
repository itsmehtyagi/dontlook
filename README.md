# dontlook

Webcam privacy guard for Windows. It learns your face and hides your screen when anyone else looks at it.

- Blanks the screen when a face that isn't yours appears in the webcam.
- Locks Windows when you haven't been seen for 20 seconds.
- `Ctrl+Alt+P` hides or shows the screen manually. `Ctrl+Alt+Q` quits.
- Runs fully offline. No images are saved or sent anywhere. Only a numeric face signature (`owner.npy`) is stored locally.

> Software can only react after it sees someone. For real protection from side viewing, use a physical privacy filter on your screen as well.

## Setup

1. Install Python 3.10+.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Download the face models into a `models` folder (PowerShell):
   ```powershell
   mkdir models
   $b = "https://github.com/opencv/opencv_zoo/raw/main/models"
   Invoke-WebRequest "$b/face_detection_yunet/face_detection_yunet_2023mar.onnx" -OutFile models\yunet.onnx
   Invoke-WebRequest "$b/face_recognition_sface/face_recognition_sface_2021dec.onnx" -OutFile models\sface.onnx
   ```

## Usage

1. Run `enroll.bat` and look at the camera while slowly moving your head. Only you should be in view.
2. Run `run.bat` to start the guard.

Run `enroll.bat` again any time to re-learn your face.

## Tuning

Edit the settings at the top of `screengone.py`:

| Setting | Effect |
|---|---|
| `MATCH_THRESHOLD` | Lower (e.g. `0.30`) if it blanks on you; raise (e.g. `0.42`) if it misses others |
| `LOCK_AFTER_SECONDS` | Seconds before locking when you're away (`0` disables locking) |
| `MIN_FACE_FRACTION` | Lower to detect faces farther away |
| `CLEAR_SECONDS` | How long a stranger must be gone before the screen returns |

## Limitations

Faces in profile, in dim light, or far away can be missed. Occasional false detections may briefly blank the screen.
