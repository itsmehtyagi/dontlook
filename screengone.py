"""
ScreenGone - webcam shoulder-surf guard for Windows.

- Learns YOUR face (first run, or `python screengone.py --enroll`).
- Blanks the screen when any face that isn't yours is seen.
- Locks the PC when you haven't been seen for a while.
- Ctrl+Alt+P : manually blank / unblank the screen
- Ctrl+Alt+Q : quit

Everything runs locally. Only a numeric face signature (owner.npy) is saved.
"""

import ctypes
import os
import sys
import threading
import time
from collections import deque

import cv2
import numpy as np
import tkinter as tk

# ---------------- settings (tweak these) ----------------
CAMERA_INDEX = 0          # 0 = built-in webcam
MATCH_THRESHOLD = 0.36    # face similarity needed to count as "you" (higher = stricter)
STRANGER_FRAMES = 3       # frames (out of last 5) with a stranger before blanking
CLEAR_SECONDS = 1.5       # how long the stranger must be gone before unblanking
LOCK_AFTER_SECONDS = 20   # lock PC if you're not seen this long (0 = never lock)
MIN_FACE_FRACTION = 0.06  # ignore faces smaller than this fraction of frame width
CHECK_INTERVAL = 0.15     # seconds between camera checks
ENROLL_SAMPLES = 25       # face samples captured during enrollment
# --------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
DET_MODEL = os.path.join(HERE, "models", "yunet.onnx")
REC_MODEL = os.path.join(HERE, "models", "sface.onnx")
OWNER_FILE = os.path.join(HERE, "owner.npy")

user32 = ctypes.windll.user32
VK_CONTROL, VK_MENU = 0x11, 0x12
VK_P, VK_Q = 0x50, 0x51


def key_down(vk):
    return user32.GetAsyncKeyState(vk) & 0x8000


class FaceEngine:
    def __init__(self):
        self.det = cv2.FaceDetectorYN.create(DET_MODEL, "", (640, 480), 0.85)
        self.rec = cv2.FaceRecognizerSF.create(REC_MODEL, "")

    def faces(self, frame):
        h, w = frame.shape[:2]
        self.det.setInputSize((w, h))
        _, faces = self.det.detect(frame)
        if faces is None:
            return []
        return [f for f in faces if f[2] >= w * MIN_FACE_FRACTION]

    def embed(self, frame, face):
        aligned = self.rec.alignCrop(frame, face)
        e = self.rec.feature(aligned).flatten()
        return e / np.linalg.norm(e)


def open_camera():
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        sys.exit("ERROR: could not open webcam.")
    return cap


def enroll(engine):
    """Capture the owner's face from a few angles and save signatures."""
    cap = open_camera()
    samples = []
    last = 0.0
    win = "ScreenGone - enrolling (look at camera, slowly move your head)"
    while len(samples) < ENROLL_SAMPLES:
        ok, frame = cap.read()
        if not ok:
            continue
        faces = engine.faces(frame)
        view = frame.copy()
        if len(faces) == 1:
            x, y, w, h = map(int, faces[0][:4])
            cv2.rectangle(view, (x, y), (x + w, y + h), (0, 200, 0), 2)
            if time.time() - last > 0.25:
                samples.append(engine.embed(frame, faces[0]))
                last = time.time()
            msg = f"Captured {len(samples)}/{ENROLL_SAMPLES}"
        elif len(faces) > 1:
            msg = "Only you should be in view"
        else:
            msg = "No face found - face the camera"
        cv2.putText(view, msg, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 255, 255), 2)
        cv2.imshow(win, view)
        if cv2.waitKey(1) == 27:  # Esc cancels
            cap.release()
            cv2.destroyAllWindows()
            sys.exit("Enrollment cancelled.")
    cap.release()
    cv2.destroyAllWindows()
    np.save(OWNER_FILE, np.array(samples))
    print(f"Saved your face signature to {OWNER_FILE}")


class Guard:
    def __init__(self, engine, owner):
        self.engine = engine
        self.owner = owner                 # (N, 128) normalized embeddings
        self.lock = threading.Lock()
        self.intruder = False
        self.manual = False
        self.running = True

    def is_owner(self, frame, face):
        sim = float(np.max(self.owner @ self.engine.embed(frame, face)))
        return sim >= MATCH_THRESHOLD

    def camera_loop(self):
        cap = open_camera()
        history = deque(maxlen=5)
        last_owner = time.time()
        last_stranger = 0.0
        locked_once = False

        while self.running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.5)
                continue

            now = time.time()
            owner_seen = stranger_seen = False
            for f in self.engine.faces(frame):
                if self.is_owner(frame, f):
                    owner_seen = True
                else:
                    stranger_seen = True

            history.append(stranger_seen)
            if sum(history) >= STRANGER_FRAMES:
                last_stranger = now
            if owner_seen:
                last_owner = now
                locked_once = False

            with self.lock:
                self.intruder = (now - last_stranger) < CLEAR_SECONDS

            if (LOCK_AFTER_SECONDS and not locked_once
                    and now - last_owner > LOCK_AFTER_SECONDS):
                user32.LockWorkStation()
                locked_once = True

            time.sleep(CHECK_INTERVAL)

        cap.release()


class Overlay:
    def __init__(self, guard):
        self.guard = guard
        self.root = tk.Tk()
        self.root.withdraw()
        # cover all monitors (virtual screen)
        x, y = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        w, h = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.configure(bg="black")
        self.win.attributes("-topmost", True)
        self.label = tk.Label(self.win, text="", fg="#555", bg="black",
                              font=("Segoe UI", 20))
        self.label.place(relx=0.5, rely=0.5, anchor="center")
        self.win.withdraw()
        self.shown = False
        self.hotkey_held = False

    def tick(self):
        if not self.guard.running:
            self.root.destroy()
            return

        ctrl_alt = key_down(VK_CONTROL) and key_down(VK_MENU)
        if ctrl_alt and key_down(VK_Q):
            self.guard.running = False
        p = ctrl_alt and key_down(VK_P)
        if p and not self.hotkey_held:
            self.guard.manual = not self.guard.manual
        self.hotkey_held = p

        with self.guard.lock:
            intruder = self.guard.intruder
        show = intruder or self.guard.manual

        if show and not self.shown:
            self.label.config(text="Someone else is looking - screen hidden"
                              if intruder else "Screen hidden (Ctrl+Alt+P)")
            self.win.deiconify()
            self.win.lift()
            self.shown = True
        elif not show and self.shown:
            self.win.withdraw()
            self.shown = False
        if self.shown:
            self.win.attributes("-topmost", True)

        self.root.after(50, self.tick)

    def run(self):
        self.root.after(50, self.tick)
        self.root.mainloop()


if __name__ == "__main__":
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    engine = FaceEngine()
    if "--enroll" in sys.argv or not os.path.exists(OWNER_FILE):
        enroll(engine)
        if "--enroll" in sys.argv:
            sys.exit(0)
    owner = np.load(OWNER_FILE)
    g = Guard(engine, owner)
    threading.Thread(target=g.camera_loop, daemon=True).start()
    print("ScreenGone running. Ctrl+Alt+P = hide/show, Ctrl+Alt+Q = quit.")
    Overlay(g).run()
