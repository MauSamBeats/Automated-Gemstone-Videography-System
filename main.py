import os
import sys
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import subprocess
import cv2
import threading
import shutil
import queue
from PIL import Image, ImageTk

DEFAULTS = {
    "exposure": 0.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "hue": 0.0,
    "sharpness": 1.0,
    "warmth": 0.0,
    "tint": 0.0,
    "shadows": 0.0,
    "highlights": 0.0,
    "vibrance": 0.0,
    "denoise": 0.0
}


USER_PRESETS_FILE = "user_presets.json"
USER_MUSIC_FILE = "user_music.json"
USER_MUSIC_DIR = "music"
DEFAULT_MUSIC_NAME = "MistyMountains"

def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def exposure_to_brightness_gamma(exposure):
    brightness = exposure
    gamma = 1
    return brightness, gamma

def map_shadows_highlights(shadows, highlights):
    rimin = max(0.0, min(0.5, 0.15 * shadows))
    rimax = max(0.5, min(1.0, 1.0 - 0.15 * highlights))
    return rimin, rimax

def build_eq_filter(exposure, contrast, saturation, gamma=1.0):
    eq_params = []
    if abs(exposure - DEFAULTS["exposure"]) > 1e-6:
        eq_params.append(f"brightness={exposure:.2f}")
    if abs(contrast - DEFAULTS["contrast"]) > 1e-6:
        eq_params.append(f"contrast={contrast:.2f}")
    if abs(saturation - DEFAULTS["saturation"]) > 1e-6:
        eq_params.append(f"saturation={saturation:.2f}")
    if abs(gamma - 1.0) > 1e-6:
        eq_params.append(f"gamma={gamma:.2f}")
    return "eq=" + ":".join(eq_params) if eq_params else None

def build_denoise_filter(denoise):
    if denoise <= 0:
        return None
    ls = max(1.0, denoise)
    cs = max(1.0, denoise * 0.75)
    return f"hqdn3d=luma_spatial={ls:.2f}:chroma_spatial={cs:.2f}:luma_tmp=0:chroma_tmp=0"


def build_hue_filter(hue):
    if abs(hue - DEFAULTS["hue"]) > 1e-6:
        return f"hue=h={hue:.1f}"
    return None

def build_colorbalance_filter(warmth, tint):
    if abs(warmth - DEFAULTS["warmth"]) > 1e-6 or abs(tint - DEFAULTS["tint"]) > 1e-6:
        return f"colorbalance=rs={warmth:.2f}:gs={tint:.2f}:bs={-warmth:.2f}"
    return None

def build_colorlevels_filter(shadows, highlights):
    if abs(shadows - DEFAULTS["shadows"]) > 1e-6 or abs(highlights - DEFAULTS["highlights"]) > 1e-6:
        rimin = gimin = bimin = max(0.0, 0.15 * shadows)
        rimax = gimax = bimax = min(1.0, 1.0 - 0.15 * highlights)
        return (f"colorlevels=rimin={rimin:.3f}:gimin={gimin:.3f}:bimin={bimin:.3f}:"
                f"rimax={rimax:.3f}:gimax={gimax:.3f}:bimax={bimax:.3f}")
    return None

def build_unsharp_filter(sharpness):
    if abs(sharpness - DEFAULTS["sharpness"]) > 1e-6:
        return f"unsharp=5:5:{sharpness:.1f}:5:5:{sharpness/2:.1f}"
    return None

def build_vibrance_filter(vibrance):
    if abs(vibrance - 0.0) > 1e-6:
        return f"vibrance={vibrance:.2f}"
    return None

def build_colorlevels_filter(shadows, highlights):
    rimin, rimax = map_shadows_highlights(shadows, highlights)
    return f"colorlevels=rimin={rimin:.3f}:gimin={rimin:.3f}:bimin={rimin:.3f}:rimax={rimax:.3f}:gimax={rimax:.3f}:bimax={rimax:.3f}"

class PreviewThread(threading.Thread):
    def __init__(self, cmd, output_path, target_width, target_height):
        threading.Thread.__init__(self)
        self.cmd = cmd
        self.output_path = output_path
        self.target_width = target_width
        self.target_height = target_height
        self.result_queue = queue.Queue()
        self.daemon = True

    def run(self):
        try:
            subprocess.run(
                self.cmd, 
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.result_queue.put(("success", self.output_path, self.target_width, self.target_height))
        except Exception as e:
            self.result_queue.put(("error", str(e)))

class VideoEditorApp:
    def __init__(self, root):
        self.root = root
        self.ffmpeg_path = resource_path("bin/ffmpeg.exe")
        self.default_audio_path = resource_path("assets/misty_mountains.mpeg")
        self.builtin_presets = {
            "Original": {
                "exposure": 0.0, "contrast": 1.0, "saturation": 1.0, "hue": 0.0,
                "sharpness": 1.0, "crf": 20.0, "warmth": 0.0, "tint": 0.0,
                "shadows": 0.0, "highlights": 0.0, "vibrance": 0.0, "denoise": 0.0,
                "zoom": "100%", "aspect": "1:1", "spin_start": 0.0, "spin_end": 0.0,
                "spin_count": 72, "spin_enabled": False, "rotation_step": 0, "img_compression": 15,
                "videos": [
                    {"start": 0, "end": 0, "enabled": False, "audio": "None"},
                    {"start": 0, "end": 0, "enabled": False, "audio": "None"},
                    {"start": 0, "end": 0, "enabled": False, "audio": "None"}
                ]
            }
        }
        self.user_presets = self.load_user_presets()
        self.user_music = self.load_user_music()
        self.selected_preset_name = tk.StringVar()
        self.selected_preset_name.set("Original")
        self.exposure_var = tk.DoubleVar(value=0.0)
        self.shadows_var = tk.DoubleVar(value=0.0)
        self.highlights_var = tk.DoubleVar(value=0.0)
        self.contrast_var = tk.DoubleVar(value=1.0)
        self.saturation_var = tk.DoubleVar(value=1.0)
        self.hue_var = tk.DoubleVar(value=0.0)
        self.sharpness_var = tk.DoubleVar(value=1.0)
        self.crf_var = tk.DoubleVar(value=20.0)
        self.warmth_var = tk.DoubleVar(value=0.0)
        self.tint_var = tk.DoubleVar(value=0.0)
        self.vibrance_var = tk.DoubleVar(value=0.0)
        self.denoise_var = tk.DoubleVar(value=0.0)
        self.rotation_steps = 0  # Track clockwise rotations (0-3)
        self.rotation_label = None  # Will be set in setup_gui
        self.img_compression_var = tk.IntVar(value=15)
        self.stop_event = threading.Event()
        self.spin_rotation_steps = 0  # 0-3, for 0/90/180/270 degrees
        self.spin_rotation_label = None  # Will be set in setup_gui

        self.video_settings = []
        for _ in range(5):
            self.video_settings.append({
                "start_var": tk.DoubleVar(value=0.0),
                "end_var": tk.DoubleVar(value=0.0),
                "enabled_var": tk.BooleanVar(value=False),
                "audio_var": tk.StringVar(value="None")
            })
        self.music_list = self.get_sorted_music_list()
        if DEFAULT_MUSIC_NAME in self.music_list:
            self.selected_music = tk.StringVar(value=DEFAULT_MUSIC_NAME)
        else:
            self.selected_music = tk.StringVar(value="None")
        self.aspect_ratios = {
            "1:1": (1080, 1080),
            "16:9": (1920, 1080),
            "9:16": (1080, 1920),
            "4:3": (1440, 1080),
            "3:4": (1080, 1440)
        }
        self.selected_aspect = tk.StringVar(value="1:1")
        self.preview_image = None
        self.preview_label = None
        self.preview_thread = None
        self.preview_timer = None
        self.setup_gui()
        self.update_preset_list()
        self.apply_preset(self.selected_preset_name.get())

    def update_preset_dropdown_values(self):
        """Sort user presets alphabetically and update the preset dropdown in real time."""
        builtin = list(self.builtin_presets.keys())
        user_presets = sorted(self.user_presets.keys(), key=lambda x: x.lower())
        if user_presets:
            values = builtin + ["──────────────"] + user_presets
        else:
            values = builtin
        self.preset_dropdown['values'] = values

    def get_sorted_music_list(self):
        """Return music list with 'None' at top, rest alphabetically sorted."""
        music = ["None"]
        music_names = []
        if os.path.exists(self.default_audio_path):
            music_names.append(DEFAULT_MUSIC_NAME)
        music_names += [
            name for name in self.user_music
            if name != DEFAULT_MUSIC_NAME and name != "None"
        ]
        return music + sorted(music_names, key=lambda x: x.lower())

    def load_user_presets(self):
        if os.path.exists(USER_PRESETS_FILE):
            with open(USER_PRESETS_FILE, "r") as f:
                return json.load(f)
        return {}

    def save_user_presets(self):
        with open(USER_PRESETS_FILE, "w") as f:
            json.dump(self.user_presets, f, indent=2)

    def load_user_music(self):
        if os.path.exists(USER_MUSIC_FILE):
            with open(USER_MUSIC_FILE, "r") as f:
                return json.load(f)
        return {}

    def save_user_music(self):
        with open(USER_MUSIC_FILE, "w") as f:
            json.dump(self.user_music, f, indent=2)

    def get_music_list(self):
        music = ["None"]
        music_names = []
        if os.path.exists(self.default_audio_path):
            music_names.append(DEFAULT_MUSIC_NAME)
        music_names += [name for name in self.user_music if name not in (DEFAULT_MUSIC_NAME, "None")]
        music_names = sorted(music_names, key=lambda x: x.lower())
        music.extend(music_names)
        return music

    def update_music_list(self):
        self.music_list = self.get_music_list()
        for vs in self.video_settings:
            if vs["audio_var"].get() not in self.music_list:
                vs["audio_var"].set("None")
            vs["audio_dropdown"]["values"] = self.music_list
        if self.selected_music.get() not in self.music_list:
            self.selected_music.set("None")
        self.music_dropdown["values"] = self.music_list

    def update_preset_list(self):
        user_preset_names = sorted(self.user_presets.keys(), key=lambda x: x.lower())
        if user_preset_names:
            self.preset_names = (
                list(self.builtin_presets.keys()) +
                ["──────────────"] +
                user_preset_names
            )
        else:
            self.preset_names = list(self.builtin_presets.keys())
        self.preset_dropdown["values"] = self.preset_names

    def setup_gui(self):
        self.root.title("VideoEditor")
        self.root.geometry("1100x800")
        container = ttk.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(container)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.main_frame = ttk.Frame(self.canvas)
        self.main_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        folders_frame = ttk.Frame(self.main_frame)
        folders_frame.pack(fill=tk.X, pady=5)
        ttk.Label(folders_frame, text="Input Folder:").grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.input_entry = ttk.Entry(folders_frame, width=40)
        self.input_entry.grid(row=0, column=1, padx=5, pady=5, sticky='w')
        ttk.Button(folders_frame, text="Browse", command=self.browse_input).grid(row=0, column=2, padx=2)
        ttk.Label(folders_frame, text="Presets:").grid(row=0, column=3, padx=(40, 5), sticky='e')
        self.preset_dropdown = ttk.Combobox(
            folders_frame, textvariable=self.selected_preset_name, values=[], state="readonly", width=18,
            postcommand=self.update_preset_dropdown_values  # Add this
        )
        self.preset_dropdown.grid(row=0, column=4, padx=(0, 2), pady=5, sticky='w')
        self.preset_dropdown.bind("<<ComboboxSelected>>", lambda e: self.apply_preset(self.selected_preset_name.get()))
        self.save_preset_btn = ttk.Button(folders_frame, text="Save Preset", command=self.save_preset_dialog)
        self.save_preset_btn.grid(row=0, column=5, padx=(5, 0), pady=5, sticky='w')
        self.delete_preset_btn = ttk.Button(
            folders_frame, text="Delete Preset", command=self.delete_selected_preset
        )
        self.delete_preset_btn.grid(row=0, column=6, padx=(5, 0), pady=5, sticky='w')
        ttk.Label(folders_frame, text="Output Folder:").grid(row=1, column=0, padx=5, pady=5, sticky='w')
        self.output_entry = ttk.Entry(folders_frame, width=40)
        self.output_entry.grid(row=1, column=1, padx=5, pady=5, sticky='w')
        ttk.Button(folders_frame, text="Browse", command=self.browse_output).grid(row=1, column=2, padx=2)
        music_frame = ttk.Frame(self.main_frame)
        music_frame.pack(fill=tk.X, pady=5)
        music_frame.grid_columnconfigure(0, weight=1)
        ttk.Label(music_frame, text="Music:").grid(row=0, column=0, padx=5, sticky='e')
        self.music_dropdown = ttk.Combobox(
            music_frame, textvariable=self.selected_music, values=self.music_list, state="readonly", width=24,
            postcommand=lambda: self.music_dropdown.configure(values=self.get_sorted_music_list())
        )
        self.music_dropdown.grid(row=0, column=1, padx=5, sticky='w')
        self.music_dropdown.bind("<<ComboboxSelected>>", lambda e: None)
        ttk.Button(music_frame, text="Add Music", command=self.add_music_dialog).grid(row=0, column=2, padx=5, sticky='w')
        ttk.Button(music_frame, text="Delete Music", command=self.delete_selected_music).grid(row=0, column=3, padx=5, sticky='w')
        adj_frame = ttk.LabelFrame(self.main_frame, text="Video Adjustments")
        adj_frame.pack(fill=tk.X, pady=5)
        preview_frame = ttk.Frame(adj_frame)
        preview_frame.grid(row=0, column=6, rowspan=5, padx=20, sticky='nsew')
        ttk.Label(preview_frame, text="Aspect Ratio:").pack(pady=5)
        self.aspect_dropdown = ttk.Combobox(
            preview_frame, textvariable=self.selected_aspect,
            values=list(self.aspect_ratios.keys()), state="readonly", width=8
        )
        self.aspect_dropdown.pack(pady=5)
        self.aspect_dropdown.bind("<<ComboboxSelected>>", lambda e: self.schedule_preview())

        self.preview_label = ttk.Label(preview_frame)
        self.preview_label.pack(pady=10)
        
        ttk.Label(preview_frame, text="Zoom:").pack(pady=(10, 5))
        self.zoom_var = tk.StringVar(value="100%")
        self.zoom_dropdown = ttk.Combobox(
            preview_frame, textvariable=self.zoom_var,
            values=["100%", "125%", "150%", "175%", "200%"], 
            state="readonly", width=8
        )
        self.zoom_dropdown.pack(pady=5)
        self.zoom_dropdown.bind("<<ComboboxSelected>>", lambda e: self.schedule_preview())

        # Rotation Controls Frame
        rotation_frame = ttk.Frame(adj_frame)
        rotation_frame.grid(row=5, column=6, sticky='e', pady=5, padx=(0, 20))

        ttk.Label(rotation_frame, text="Rotation:").grid(row=0, column=0, padx=5)

        self.rotate_ccw_btn = ttk.Button(rotation_frame, text="↺", width=3, command=lambda: self.rotate_image(-1))
        self.rotate_ccw_btn.grid(row=0, column=1, padx=2)

        self.rotate_cw_btn = ttk.Button(rotation_frame, text="↻", width=3, command=lambda: self.rotate_image(1))
        self.rotate_cw_btn.grid(row=0, column=2, padx=2)

        self.rotation_label = ttk.Label(rotation_frame, text="0°")
        self.rotation_label.grid(row=0, column=3, padx=5)

                
        def validate_float_with_minus(new_value, slider_min, slider_max):
            if new_value == "" or new_value == "-":
                return True  # Allow empty or just minus (user typing negative)
            try:
                val = float(new_value)
                return slider_min <= val <= slider_max
            except ValueError:
                return False
        def validate_time_input(new_value):
            if new_value == "":
                return True  # Allow empty input
            try:
                val = float(new_value)
                return val >= 0  # Allow only positive numbers
            except ValueError:
                return False
        def validate_int(new_value, min_val, max_val):
            if new_value == "":
                return True
            try:
                val = int(new_value)
                return min_val <= val <= max_val
            except:
                return False


        #vcmd = (self.root.register(lambda new_value, min_val, max_val: validate_float_with_minus(new_value, min_val, max_val)), '%P', min_val, max_val)

        # Left column (as before)
        left_labels = ["Exposure:", "Contrast:", "Saturation:", "Hue:", "Sharpness:"]
        left_vars = [self.exposure_var, self.contrast_var, self.saturation_var, self.hue_var, self.sharpness_var]
        left_from = [-10.0, 0.0, 0.0, -180.0, 0.0]
        left_to = [10.0, 2.0, 3.0, 180.0, 5.0]
        left_res = [0.01, 0.01, 0.01, 1.0, 0.1]

        # Middle column (formerly right)
        middle_labels = ["CRF:", "Warmth:", "Tint:", "Shadows:", "Highlights:"]
        middle_vars = [self.crf_var, self.warmth_var, self.tint_var, self.shadows_var, self.highlights_var]
        middle_from = [0.0, -1.0, -1.0, -1.0, -1.0]
        middle_to = [50.0, 1.0, 1.0, 1.0, 1.0]
        middle_res = [1.0, 0.01, 0.01, 0.01, 0.01]

        # New right column (for vibrance)
        right_labels = ["Vibrance:", "Denoise:", "IMG Compression:", "", ""]  # Only last row has vibrance, or add more if you want
        right_vars = [self.vibrance_var, self.denoise_var, self.img_compression_var, tk.DoubleVar(), tk.DoubleVar()]
        right_from = [-2.0, 0.0, 1.0, 0.0, 0.0]  # Only vibrance slider uses this
        right_to = [2.0, 4.0, 31.0, 0.0, 0.0]
        right_res = [0.01, 0.01, 1.0, 0.0, 0.0]

        num_sliders = max(len(left_labels), len(middle_labels), len(right_labels))

        for i in range(num_sliders):
            # Left column
            if i < len(left_labels):
                ttk.Label(adj_frame, text=left_labels[i]).grid(row=i, column=0, padx=5, sticky='w')
                left_row_frame = ttk.Frame(adj_frame)
                left_row_frame.grid(row=i, column=1, sticky='w', pady=2)
                vcmd = (
                    self.root.register(
                        lambda new_value, slider_min=left_from[i], slider_max=left_to[i]: validate_float_with_minus(new_value, slider_min, slider_max)
                    ),
                    '%P'
                )
                left_entry = ttk.Entry(left_row_frame, textvariable=left_vars[i], width=8, validate='key', validatecommand=vcmd)
                left_entry.pack(side=tk.LEFT, padx=(0, 5))
                left_scale = tk.Scale(left_row_frame, from_=left_from[i], to=left_to[i], resolution=left_res[i],
                                      orient="horizontal", variable=left_vars[i], length=180)
                left_scale.pack(side=tk.LEFT)
                left_vars[i].trace_add('write', lambda *args, var=left_vars[i], scale=left_scale, from_=left_from[i], to=left_to[i]: self.on_slider_change(var, scale, from_, to))

            # Middle column
            if i < len(middle_labels) and middle_labels[i]:
                ttk.Label(adj_frame, text=middle_labels[i]).grid(row=i, column=2, padx=5, sticky='w')
                middle_row_frame = ttk.Frame(adj_frame)
                middle_row_frame.grid(row=i, column=3, sticky='w', pady=2)
                vcmd = (
                    self.root.register(
                        lambda new_value, slider_min=middle_from[i], slider_max=middle_to[i]: validate_float_with_minus(new_value, slider_min, slider_max)
                    ),
                    '%P'
                )
                middle_entry = ttk.Entry(middle_row_frame, textvariable=middle_vars[i], width=8, validate='key', validatecommand=vcmd)
                middle_entry.pack(side=tk.LEFT, padx=(0, 5))
                middle_scale = tk.Scale(middle_row_frame, from_=middle_from[i], to=middle_to[i], resolution=middle_res[i],
                                        orient="horizontal", variable=middle_vars[i], length=180)
                middle_scale.pack(side=tk.LEFT)
                middle_vars[i].trace_add('write', lambda *args, var=middle_vars[i], scale=middle_scale, from_=middle_from[i], to=middle_to[i]: self.on_slider_change(var, scale, from_, to))

            # New right column (only vibrance for now)
            if i < len(right_labels) and right_labels[i]:
                ttk.Label(adj_frame, text=right_labels[i]).grid(row=i, column=4, padx=5, sticky='w')
                right_row_frame = ttk.Frame(adj_frame)
                right_row_frame.grid(row=i, column=5, sticky='w', pady=2)
                if i == 2:  # IMG Compression row
                    vcmd = (self.root.register(lambda new_value: validate_int(new_value, 1, 31)), '%P')
                else:
                    vcmd = (
                        self.root.register(
                            lambda new_value, slider_min=right_from[i], slider_max=right_to[i]: validate_float_with_minus(new_value, slider_min, slider_max)
                        ),
                        '%P'
                    )
                right_entry = ttk.Entry(right_row_frame, textvariable=right_vars[i], width=8, validate='key', validatecommand=vcmd)
                right_entry.pack(side=tk.LEFT, padx=(0, 5))
                right_scale = tk.Scale(right_row_frame, from_=right_from[i], to=right_to[i], resolution=right_res[i],
                                        orient="horizontal", variable=right_vars[i], length=180)
                right_scale.pack(side=tk.LEFT)
                right_vars[i].trace_add('write', lambda *args, var=right_vars[i], scale=right_scale, from_=right_from[i], to=right_to[i]: self.on_slider_change(var, scale, from_, to))        
        output_frame = ttk.LabelFrame(self.main_frame, text="Video Outputs")
        output_frame.pack(fill=tk.X, pady=10)

        # --- Photo Output Section ---
        photo_frame = ttk.LabelFrame(self.main_frame, text="Photo Outputs")
        photo_frame.pack(fill=tk.X, pady=10)

        self.photo_settings = []
        vcmd_time = (self.root.register(lambda v: v == "" or (v.replace('.', '', 1).isdigit() and float(v) >= 0)), '%P')
        for i in range(5):
            row = i
            ttk.Label(photo_frame, text=f"Photo {i+1} (s):").grid(row=row, column=0, padx=5, pady=5, sticky='w')
            ts_var = tk.DoubleVar(value=0.0)
            cb_var = tk.BooleanVar(value=False)
            entry = ttk.Entry(photo_frame, textvariable=ts_var, width=8, validate='key', validatecommand=vcmd_time)
            entry.grid(row=row, column=1, padx=2)
            cb = ttk.Checkbutton(photo_frame, variable=cb_var)
            cb.grid(row=row, column=2, padx=5)
            self.photo_settings.append({"ts_var": ts_var, "cb_var": cb_var})


        self.stop_btn = ttk.Button(output_frame, text="Stop Processing", command=self.stop_processing)
        self.stop_btn.grid(row=0, column=8, rowspan=3, padx=10, pady=10, sticky='ns')
        self.stop_btn.config(state=tk.DISABLED)  # Initially disabled
        
        vcmd_time = (self.root.register(validate_time_input), '%P')
        for i, vs in enumerate(self.video_settings):
            row = i
            ttk.Label(output_frame, text=f"Video {i+1} (s):").grid(row=row, column=0, padx=5, pady=5, sticky='w')
            ttk.Entry(output_frame, textvariable=vs["start_var"], width=6, validate='key', validatecommand=vcmd_time).grid(row=row, column=1, padx=2)
            ttk.Label(output_frame, text="-").grid(row=row, column=2)
            ttk.Entry(output_frame, textvariable=vs["end_var"], width=6, validate='key', validatecommand=vcmd_time).grid(row=row, column=3, padx=2)
            ttk.Checkbutton(output_frame, variable=vs["enabled_var"]).grid(row=row, column=4, padx=5)
            ttk.Label(output_frame, text="Audio:").grid(row=row, column=5, padx=2)
            vs["audio_dropdown"] = ttk.Combobox(
                output_frame, textvariable=vs["audio_var"], values=self.music_list, state="readonly", width=18,
                postcommand=lambda v=vs: v["audio_dropdown"].configure(values=self.get_sorted_music_list())
            )
            vs["audio_dropdown"].grid(row=row, column=6, padx=2)
        self.start_btn = ttk.Button(output_frame, text="Start Processing", command=self.start_processing)
        self.start_btn.grid(row=0, column=7, rowspan=3, padx=30, pady=10, sticky='ns')

        # --- Place this code right after the output_frame section and before progress bar/log ---

        spin_frame = ttk.LabelFrame(self.main_frame, text="Spin Settings")
        spin_frame.pack(fill=tk.X, pady=10)

        # --- Spin Rotation Controls ---
        spin_rot_frame = ttk.Frame(spin_frame)
        spin_rot_frame.grid(row=1, column=0, columnspan=6, sticky='w', pady=(5, 0))

        ttk.Label(spin_rot_frame, text="Spin Rotation:").grid(row=0, column=0, padx=5)

        self.spin_rotate_ccw_btn = ttk.Button(
            spin_rot_frame, text="↺", width=3,
            command=lambda: self.spin_rotate_image(-1)
        )
        self.spin_rotate_ccw_btn.grid(row=0, column=1, padx=2)

        self.spin_rotate_cw_btn = ttk.Button(
            spin_rot_frame, text="↻", width=3,
            command=lambda: self.spin_rotate_image(1)
        )
        self.spin_rotate_cw_btn.grid(row=0, column=2, padx=2)

        self.spin_rotation_label = ttk.Label(spin_rot_frame, text="0°")
        self.spin_rotation_label.grid(row=0, column=3, padx=5)


        ttk.Label(spin_frame, text="Spin:").grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.spin_start_var = tk.DoubleVar(value=0.0)
        self.spin_end_var = tk.DoubleVar(value=0.0)
        ttk.Entry(spin_frame, textvariable=self.spin_start_var, width=6).grid(row=0, column=1, padx=2)
        ttk.Label(spin_frame, text="-").grid(row=0, column=2)
        ttk.Entry(spin_frame, textvariable=self.spin_end_var, width=6).grid(row=0, column=3, padx=2)

        self.spin_count_var = tk.StringVar()
        self.spin_count_combo = ttk.Combobox(
            spin_frame, 
            textvariable=self.spin_count_var,
            values=["18", "36", "72", "108", "144", "288", "576"],
            state="readonly",
            width=6
        )
        self.spin_count_combo.grid(row=0, column=4, padx=5)
        self.spin_count_combo.set("72")  # Default value

        self.spin_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(spin_frame, variable=self.spin_enabled_var).grid(row=0, column=5, padx=5)

        
        self.progress = ttk.Progressbar(self.main_frame, orient="horizontal", mode="determinate")
        self.progress.pack(fill=tk.X, pady=5)
        self.log = tk.Text(self.main_frame, height=10, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))


    def on_slider_change(self, var, scale, from_, to):
        try:
            value = float(var.get())
            if value < from_:
                var.set(from_)
            elif value > to:
                var.set(to)
            else:
                scale.set(value)
        except Exception:
            pass
        self.schedule_preview()

    def schedule_preview(self):
        if self.preview_timer is not None:
            self.root.after_cancel(self.preview_timer)
        self.preview_timer = self.root.after(500, self.generate_preview)

    def apply_preset(self, preset):
        if preset == "──────────────":
            return
        if preset in self.builtin_presets:
            vals = self.builtin_presets[preset]
        elif preset in self.user_presets:
            vals = self.user_presets[preset]
        else:
            return
        
        # Cancel any pending preview timer
        if hasattr(self, 'preview_timer') and self.preview_timer is not None:
            self.root.after_cancel(self.preview_timer)
            self.preview_timer = None
        
        # Stop active preview thread if running
        if hasattr(self, 'preview_thread') and self.preview_thread and self.preview_thread.is_alive():
            # Allow thread to terminate gracefully
            self.preview_thread = None
        
        # Apply preset values
        self.exposure_var.set(vals.get("exposure", 0.0))
        self.shadows_var.set(vals.get("shadows", 0.0))
        self.highlights_var.set(vals.get("highlights", 0.0))
        self.contrast_var.set(vals["contrast"])
        self.saturation_var.set(vals["saturation"])
        self.hue_var.set(vals["hue"])
        self.sharpness_var.set(vals["sharpness"])
        self.crf_var.set(vals["crf"])
        self.warmth_var.set(vals["warmth"])
        self.tint_var.set(vals["tint"])
        self.vibrance_var.set(vals.get("vibrance", 0.0))
        self.denoise_var.set(vals.get("denoise", 0.0))
        self.zoom_var.set(vals.get("zoom", "100%"))
        # Apply aspect ratio and folder paths from preset
        self.selected_aspect.set(vals.get("aspect", "1:1"))  # NEW
        self.rotation_steps = vals.get("rotation_steps", 0)
        degrees = self.rotation_steps * 90
        self.rotation_label.config(text=f"{degrees}°")
        #self.input_entry.delete(0, tk.END)  # NEW
        #self.input_entry.insert(0, vals.get("input_folder", ""))  # NEW
        #self.output_entry.delete(0, tk.END)  # NEW
        #self.output_entry.insert(0, vals.get("output_folder", ""))  # NEW
        self.spin_start_var.set(vals.get("spin_start", 0.0))
        self.spin_end_var.set(vals.get("spin_end", 0.0))
        self.spin_count_var.set(vals.get("spin_count", "72"))
        self.spin_enabled_var.set(vals.get("spin_enabled", False))
        self.img_compression_var.set(vals.get("img_compression", 15))
        self.spin_rotation_steps = vals.get("spin_rotation_steps", 0)
        if self.spin_rotation_label:
            self.spin_rotation_label.config(text=f"{self.spin_rotation_steps * 90}°")


        
        for i, vs in enumerate(self.video_settings):
            vinfo = vals.get("videos", [{}]*5)
            if i < len(vinfo):
                vs["start_var"].set(vinfo[i].get("start", 0.0))
                vs["end_var"].set(vinfo[i].get("end", 0.0))
                vs["enabled_var"].set(vinfo[i].get("enabled", False))
                audio = vinfo[i].get("audio", "None")
                if audio not in self.music_list:
                    audio = "None"
                vs["audio_var"].set(audio)
        photo_list = vals.get("photos", [{}]*5)
        for i, ps in enumerate(self.photo_settings):
            if i < len(photo_list):
                ps["ts_var"].set(photo_list[i].get("timestamp", 0.0))
                ps["cb_var"].set(photo_list[i].get("enabled", False))
        
        self.log_message(f"✨ Applied {preset} preset")
        self.schedule_preview()  # Schedule new preview after applying preset


    def save_preset_dialog(self):
        name = simpledialog.askstring("Save Preset", "Enter a name for your preset:")
        if not name: return
        if name in self.builtin_presets:
            messagebox.showerror("Error", "Cannot overwrite a built-in preset.")
            return
        if name in self.user_presets:
            if not messagebox.askyesno("Replace Preset", f"Preset '{name}' already exists. Replace it?"):
                return
        preset_data = {
            "exposure": self.exposure_var.get(),
            "shadows": self.shadows_var.get(),
            "highlights": self.highlights_var.get(),
            "contrast": self.contrast_var.get(),
            "saturation": self.saturation_var.get(),
            "hue": self.hue_var.get(),
            "sharpness": self.sharpness_var.get(),
            "crf": self.crf_var.get(),
            "warmth": self.warmth_var.get(),
            "tint": self.tint_var.get(),
            "vibrance": self.vibrance_var.get(),
            "denoise": self.denoise_var.get(),
            "zoom": self.zoom_var.get(),
            "aspect": self.selected_aspect.get(),  # NEW
            #"input_folder": self.input_entry.get(),  # NEW
            #"output_folder": self.output_entry.get(),  # NEW
            "spin_start": self.spin_start_var.get(),
            "spin_end": self.spin_end_var.get(),
            "spin_count": self.spin_count_var.get(),
            "spin_enabled": self.spin_enabled_var.get(),
            "rotation_steps": self.rotation_steps,
            "img_compression": self.img_compression_var.get(),
            "spin_rotation_steps": self.spin_rotation_steps,
            "photos": [
                {"timestamp": ps["ts_var"].get(), "enabled": ps["cb_var"].get()}
                for ps in self.photo_settings
            ],


            "videos": []
        }
        for vs in self.video_settings:
            preset_data["videos"].append({
                "start": vs["start_var"].get(),
                "end": vs["end_var"].get(),
                "enabled": vs["enabled_var"].get(),
                "audio": vs["audio_var"].get()
            })
        self.user_presets[name] = preset_data
        self.save_user_presets()
        self.update_preset_list()
        self.selected_preset_name.set(name)
        self.log_message(f"✅ Saved preset '{name}'")

    def delete_selected_preset(self):
        preset = self.selected_preset_name.get()
        if preset in self.builtin_presets:
            messagebox.showerror("Error", "Cannot delete a built-in preset.")
            return
        if preset in self.user_presets:
            if messagebox.askyesno("Delete Preset", f"Delete user preset '{preset}'?"):
                del self.user_presets[preset]
                self.save_user_presets()
                self.update_preset_list()
                self.selected_preset_name.set("Original")
                self.apply_preset("Original")
                self.log_message(f"🗑️ Deleted preset '{preset}'")
        else:
            messagebox.showinfo("Info", "No user preset selected to delete.")

    def add_music_dialog(self):
        filetypes = [("Audio Files", "*.mp3 *.wav *.aac *.flac *.mpeg *.ogg *.m4a"), ("All Files", "*.*")]
        path = filedialog.askopenfilename(title="Select Audio File", filetypes=filetypes)
        if not path: return
        name = simpledialog.askstring("Add Music", "Enter a name for this music file:")
        if not name: return
        if name in self.user_music or name in [DEFAULT_MUSIC_NAME, "None"]:
            messagebox.showerror("Error", "Music name already exists or is reserved.")
            return
        if not os.path.exists(USER_MUSIC_DIR):
            os.makedirs(USER_MUSIC_DIR)
        ext = os.path.splitext(path)[1]
        dest = os.path.join(USER_MUSIC_DIR, f"{name}{ext}")
        shutil.copy2(path, dest)
        self.user_music[name] = dest
        self.save_user_music()
        self.update_music_list()
        self.log_message(f"🎵 Added music '{name}'")

    def delete_selected_music(self):
        music = self.selected_music.get()
        if music in ["None", DEFAULT_MUSIC_NAME]:
            messagebox.showerror("Error", f"Cannot delete '{music}'.")
            return
        if music in self.user_music:
            if messagebox.askyesno("Delete Music", f"Delete music '{music}'?"):
                try: os.remove(self.user_music[music])
                except Exception: pass
                del self.user_music[music]
                self.save_user_music()
                self.update_music_list()
                self.selected_music.set(DEFAULT_MUSIC_NAME if DEFAULT_MUSIC_NAME in self.music_list else "None")
                self.log_message(f"🗑️ Deleted music '{music}'")
        else:
            messagebox.showinfo("Info", "No user music selected to delete.")

    def browse_input(self):
        folder = filedialog.askdirectory()
        self.input_entry.delete(0, tk.END)
        self.input_entry.insert(0, folder)
        self.schedule_preview()

    def browse_output(self):
        folder = filedialog.askdirectory()
        self.output_entry.delete(0, tk.END)
        self.output_entry.insert(0, folder)

    def log_message(self, message):
        # This method is thread-safe - can be called from any thread
        if self.root:
            self.root.after(0, self._log_message, message)

    def _log_message(self, message):
        # This runs in the main thread only
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)


    def detect_motion_start(self, video_path, threshold=30, min_contour_area=500):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): return None
        ret, prev_frame = cap.read()
        if not ret: return None
        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        prev_gray = cv2.GaussianBlur(prev_gray, (21, 21), 0)
        motion_start = None
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            current_frame_time = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            frame_diff = cv2.absdiff(prev_gray, gray)
            _, thresh = cv2.threshold(frame_diff, threshold, 255, cv2.THRESH_BINARY)
            thresh = cv2.dilate(thresh, None, iterations=2)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                if cv2.contourArea(contour) > min_contour_area:
                    motion_start = current_frame_time
                    break
            if motion_start is not None: break
            prev_gray = gray
        cap.release()
        return motion_start

    def get_crop_params(self, input_path):
        cmd_probe = [self.ffmpeg_path, '-i', input_path]
        result_probe = subprocess.run(cmd_probe, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        import re
        match = re.search(r'Stream.*Video:.* (\d+)x(\d+)', result_probe.stderr)
        if not match: return None
        width, height = int(match.group(1)), int(match.group(2))
        cmd = [
            self.ffmpeg_path,
            '-i', input_path,
            '-vf', 'cropdetect=24:16:0',
            '-t', '2',
            '-f', 'null', '-'
        ]
        result = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        crop_matches = re.findall(r'crop=(\d+:\d+:\d+:\d+)', result.stderr)
        if not crop_matches: return None
        crop_w, crop_h, _, _ = map(int, crop_matches[-1].split(':'))
        if crop_w > width or crop_h > height: return None
        return crop_matches[-1]

    def generate_spin_screenshots(self, input_path, output_folder, filename, motion_start, spin_start, spin_end, spin_count, settings, crop_params):
        if self.stop_event.is_set():
            self.log_message("🛑 Spin processing stopped")
            return
        try:
            aspect = settings["aspect"]
            target_width, target_height = self.aspect_ratios[aspect]
            zoom_factor = float(settings["zoom"].rstrip('%')) / 100.0
            scaled_width = int(target_width * zoom_factor)
            scaled_height = int(target_height * zoom_factor)
            
            # CORRECT: Call top-level function
            brightness, gamma = exposure_to_brightness_gamma(settings["exposure"])
            contrast = settings["contrast"]
            saturation = settings["saturation"]
            hue = settings["hue"]
            sharpness = settings["sharpness"]
            warmth = settings["warmth"]
            tint = settings["tint"]
            shadows = settings["shadows"]
            highlights = settings["highlights"]
            vibrance = settings["vibrance"]
            denoise = settings["denoise"]

            filters = []
            filters.append(f"crop={crop_params}")
            filters.append(f"scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=increase:flags=lanczos")
            filters.append(f"crop={target_width}:{target_height}:(iw-ow)/2:(ih-oh)/2")
            filters.append("setsar=1:1")
            filters.append(f"setdar={target_width/target_height:.2f}")
            
            # CORRECT: Call top-level functions
            eq_filter = build_eq_filter(brightness, contrast, saturation, gamma)
            if eq_filter:
                filters.append(eq_filter)
                
            hue_filter = build_hue_filter(hue)
            if hue_filter:
                filters.append(hue_filter)
                
            colorbalance_filter = build_colorbalance_filter(warmth, tint)
            if colorbalance_filter:
                filters.append(colorbalance_filter)
                
            colorlevels_filter = build_colorlevels_filter(shadows, highlights)
            if colorlevels_filter:
                filters.append(colorlevels_filter)
                
            unsharp_filter = build_unsharp_filter(sharpness)
            if unsharp_filter:
                filters.append(unsharp_filter)
                
            vibrance_filter = build_vibrance_filter(vibrance)
            if vibrance_filter:
                filters.append(vibrance_filter)
                
            denoise_filter = build_denoise_filter(denoise)
            if denoise_filter:
                filters.append(denoise_filter)
            # Add rotation filter
            # Add spin-specific rotation filter (independent from main rotation)
            spin_rotation_filter = self.get_rotation_filter(settings.get("spin_rotation_steps", 0))
            if spin_rotation_filter:
                filters.append(spin_rotation_filter)


                
            filter_str = ",".join([f for f in filters if f])
            actual_start = motion_start + spin_start
            duration = spin_end - spin_start
            spin_folder = os.path.join(output_folder, f"{os.path.splitext(filename)[0]}_spin")
            os.makedirs(spin_folder, exist_ok=True)
            intervals = [spin_start + i*(duration/(spin_count-1)) 
                        for i in range(spin_count)] if spin_count > 1 else [spin_start]

            # Announce start
            self.log_message(f"⏳ Generating {spin_count} frames for '{filename}'...")

            for i, timestamp in enumerate(intervals):
                if self.stop_event.is_set():
                    self.log_message("🛑 Spin processing stopped")
                    break  # or return, if you want to exit immediately
                output_path = os.path.join(spin_folder, f"frame_{i+1:04d}.jpg")
                cmd = [
                    self.ffmpeg_path,
                    '-ss', str(motion_start + timestamp),
                    '-i', input_path,
                    '-vf', filter_str,
                    '-vframes', '1',
                    '-q:v', str(settings["img_compression"]),
                    '-map_metadata', '-1',
                    output_path
                ]
                try:
                    subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                except Exception as e:
                    self.log_message(f"❌ Frame {i+1} failed: {str(e)}")
                    continue

            # Announce completion
            self.log_message(f"✅ Completed generating {spin_count} frames for '{filename}'")
            return True
        except Exception as e:
            self.log_message(f"❌ Spin screenshot error: {str(e)}")
            return False

    def spin_rotate_image(self, direction):
        """Rotate spin images by 90° steps (direction: 1=CW, -1=CCW)"""
        self.spin_rotation_steps = (self.spin_rotation_steps + direction) % 4
        degrees = self.spin_rotation_steps * 90
        self.spin_rotation_label.config(text=f"{degrees}°")
        # No need to update preview, as spin rotation does NOT affect preview

    
    def rotate_image(self, direction):
        """Rotate image by 90° steps (direction: 1=CW, -1=CCW)"""
        self.rotation_steps = (self.rotation_steps + direction) % 4
        degrees = self.rotation_steps * 90
        self.rotation_label.config(text=f"{degrees}°")
        self.schedule_preview()
        
    def get_rotation_filter(self, steps):
        """Generate FFmpeg rotation filter string"""
        steps = steps % 4
        if steps == 0:
            return None
        elif steps == 1:  # 90° CW
            return "transpose=1"
        elif steps == 2:  # 180°
            return "transpose=1,transpose=1"
        elif steps == 3:  # 270° CW (90° CCW)
            return "transpose=2"


    def generate_preview(self):
        if self.preview_thread and self.preview_thread.is_alive():
            return
        input_folder = self.input_entry.get()
        if not input_folder:
            return
        video_files = [f for f in os.listdir(input_folder)
                      if f.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.flv'))]
        if not video_files:
            return
        input_path = os.path.join(input_folder, video_files[0])
        output_path = "preview_output.jpg"
        exposure = self.exposure_var.get()
        brightness, gamma = exposure_to_brightness_gamma(exposure)
        contrast = self.contrast_var.get()
        saturation = self.saturation_var.get()
        hue = self.hue_var.get()
        sharpness = self.sharpness_var.get()
        warmth = self.warmth_var.get()
        tint = self.tint_var.get()
        shadows = self.shadows_var.get()
        highlights = self.highlights_var.get()
        vibrance = self.vibrance_var.get()
        #denoise = self.denoise_var.get()
        aspect = self.selected_aspect.get()
        target_width, target_height = self.aspect_ratios[aspect]
        zoom_factor = float(self.zoom_var.get().rstrip('%')) / 100.0
        scaled_width = int(target_width * zoom_factor)
        scaled_height = int(target_height * zoom_factor)
        colorbalance = f"colorbalance=rs={warmth:.2f}:gs={tint:.2f}:bs={-warmth:.2f}"
        colorlevels = build_colorlevels_filter(shadows, highlights)
        filters = [
            f"scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=increase:flags=lanczos",
            f"crop={target_width}:{target_height}:(iw-ow)/2:(ih-oh)/2",  # Fixed
            "setsar=1:1",
            f"eq=brightness={brightness:.2f}:gamma={gamma:.2f}:contrast={contrast:.2f}:saturation={saturation:.2f}",
            f"hue=h={hue:.1f}",
            colorbalance,
            colorlevels,
            f"unsharp=5:5:{sharpness:.1f}:5:5:{sharpness/2:.1f}"
        ]
        if abs(vibrance - 0.0) > 1e-6:
            filters.append(f"vibrance={vibrance:.2f}")
        rotation_filter = self.get_rotation_filter(self.rotation_steps)
        if rotation_filter:
            filters.append(rotation_filter)
        
        cmd = [
            self.ffmpeg_path, '-y', '-ss', '0', '-i', input_path,
            '-vf', ','.join(filters), '-vframes', '1', output_path
        ]
        self.aspect_dropdown.config(state='disabled')
        self.preview_label.config(text="Generating preview...")
        self.preview_thread = PreviewThread(cmd, output_path, target_width, target_height)
        self.preview_thread.start()
        self.root.after(100, self.monitor_preview_thread)


    def monitor_preview_thread(self):
        if self.preview_thread.is_alive():
            self.root.after(100, self.monitor_preview_thread)
        else:
            self.aspect_dropdown.config(state='readonly')
            self.preview_label.config(text="")
            if not self.preview_thread.result_queue.empty():
                result_type, content, target_width, target_height = self.preview_thread.result_queue.get()
                if result_type == "success":
                    try:
                        img = Image.open(content)
                        ratio = min(300 / target_width, 300 / target_height)
                        new_size = (int(target_width * ratio), int(target_height * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                        self.preview_image = ImageTk.PhotoImage(img)
                        self.preview_label.config(image=self.preview_image)
                        os.remove(content)
                    except Exception as e:
                        messagebox.showerror("Preview Error", f"Image display failed: {str(e)}")
                else:
                    messagebox.showerror("Preview Error", content)
    def capture_current_settings(self):
        """Capture all current settings for processing"""
        return {
            "exposure": self.exposure_var.get(),
            "contrast": self.contrast_var.get(),
            "saturation": self.saturation_var.get(),
            "hue": self.hue_var.get(),
            "sharpness": self.sharpness_var.get(),
            "crf": self.crf_var.get(),
            "warmth": self.warmth_var.get(),
            "tint": self.tint_var.get(),
            "shadows": self.shadows_var.get(),
            "highlights": self.highlights_var.get(),
            "vibrance": self.vibrance_var.get(),
            "denoise": self.denoise_var.get(),
            "aspect": self.selected_aspect.get(),
            "zoom": self.zoom_var.get(),
            "spin_start": self.spin_start_var.get(),
            "spin_end": self.spin_end_var.get(),
            "spin_count": self.spin_count_var.get(),
            "spin_enabled": self.spin_enabled_var.get(),
            #"input_folder": self.input_entry.get(),  # NEW
            #"output_folder": self.output_entry.get(),  # NEW
            "rotation_steps": self.rotation_steps,
            "img_compression": self.img_compression_var.get(),
            "spin_rotation_steps": self.spin_rotation_steps,

            "photos": [
                {"timestamp": ps["ts_var"].get(), "enabled": ps["cb_var"].get()}
                for ps in self.photo_settings
            ],


            "video_settings": [
                {
                    "start": vs["start_var"].get(),
                    "end": vs["end_var"].get(),
                    "enabled": vs["enabled_var"].get(),
                    "audio": vs["audio_var"].get()
                }
                for vs in self.video_settings
            ]
        }


    def start_processing(self):
        input_folder = self.input_entry.get()
        output_folder = self.output_entry.get()
        if not input_folder or not output_folder:
            messagebox.showerror("Error", "Please select input and output folders")
            return
        
        # Capture current settings BEFORE processing starts
        current_settings = self.capture_current_settings()
        
        # Get spin settings
        spin_enabled = self.spin_enabled_var.get()
        spin_start = self.spin_start_var.get()
        spin_end = self.spin_end_var.get()
        spin_count = self.spin_count_var.get()
        
        # Validate spin settings if enabled
        if spin_enabled:
            try:
                spin_start = float(spin_start)
                spin_end = float(spin_end)
                spin_count = int(spin_count)
                
                if spin_end <= spin_start:
                    messagebox.showerror("Error", "Spin end time must be greater than start time")
                    return
                if spin_end - spin_start <= 0:
                    messagebox.showerror("Error", "Spin duration must be positive")
                    return
                if spin_count <= 0:
                    messagebox.showerror("Error", "Spin count must be positive")
                    return
            except ValueError:
                messagebox.showerror("Error", "Invalid spin values (times must be numbers)")
                return
        
        # Check if any output is selected
        video_outputs_enabled = any(vs["enabled_var"].get() for vs in self.video_settings)
        photo_outputs_enabled = any(ps["cb_var"].get() for ps in self.photo_settings)
        if not video_outputs_enabled and not spin_enabled and not photo_outputs_enabled:
            messagebox.showerror("Error", "No video, spin, or photo output selected")
            return

        
        # Collect video jobs
        video_jobs = []
        for idx, vs in enumerate(self.video_settings):
            if vs["enabled_var"].get():
                try:
                    start = float(vs["start_var"].get())
                    end = float(vs["end_var"].get())
                    if end <= start:
                        messagebox.showerror("Error", f"End time for Video {idx+1} must be greater than start time.")
                        return
                except Exception:
                    messagebox.showerror("Error", f"Invalid start/end time for Video {idx+1}.")
                    return
                video_jobs.append({
                    "index": idx+1,
                    "start": start,
                    "end": end,
                    "audio": vs["audio_var"].get()
                })
        
        # UI feedback
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)  # Enable stop button
        self.stop_event.clear()  # Reset stop flag
        self.log_message("🚀 Starting processing...")

                
        # Start processing thread with spin parameters
        threading.Thread(
            target=self._process_videos,
            args=(input_folder, output_folder, video_jobs, current_settings, spin_enabled)
        ).start()

    def stop_processing(self):
        self.log_message("🛑 Stop requested. Waiting for current operation to finish...")
        self.stop_event.set()


    def _process_videos(self, input_folder, output_folder, video_jobs, settings, spin_enabled):
        self.log_message(f"Input folder: {input_folder}")
        self.log_message(f"Output folder: {output_folder}")
        self.log_message(f"Video jobs: {video_jobs}")
        self.log_message(f"Spin enabled: {spin_enabled}")

        # --- Default values for all adjustments ---
        DEFAULTS = {
            "exposure": 0.0, "contrast": 1.0, "saturation": 1.0, "hue": 0.0,
            "sharpness": 1.0, "warmth": 0.0, "tint": 0.0, "shadows": 0.0, "highlights": 0.0, "vibrance": 0.0, "denoise": 0.0
        }
        '''
        def build_eq_filter(exposure, contrast, saturation, gamma=1.0):
            eq_params = []
            if abs(exposure - DEFAULTS["exposure"]) > 1e-6:
                eq_params.append(f"brightness={exposure:.2f}")
            if abs(contrast - DEFAULTS["contrast"]) > 1e-6:
                eq_params.append(f"contrast={contrast:.2f}")
            if abs(saturation - DEFAULTS["saturation"]) > 1e-6:
                eq_params.append(f"saturation={saturation:.2f}")
            if abs(gamma - 1.0) > 1e-6:
                eq_params.append(f"gamma={gamma:.2f}")
            return "eq=" + ":".join(eq_params) if eq_params else None

        def build_denoise_filter(denoise):
            if denoise <= 0:
                return None
            ls = max(1.0, denoise)
            cs = max(1.0, denoise * 0.75)
            return f"hqdn3d=luma_spatial={ls:.2f}:chroma_spatial={cs:.2f}:luma_tmp=0:chroma_tmp=0"


        def build_hue_filter(hue):
            if abs(hue - DEFAULTS["hue"]) > 1e-6:
                return f"hue=h={hue:.1f}"
            return None

        def build_colorbalance_filter(warmth, tint):
            if abs(warmth - DEFAULTS["warmth"]) > 1e-6 or abs(tint - DEFAULTS["tint"]) > 1e-6:
                return f"colorbalance=rs={warmth:.2f}:gs={tint:.2f}:bs={-warmth:.2f}"
            return None

        def build_colorlevels_filter(shadows, highlights):
            if abs(shadows - DEFAULTS["shadows"]) > 1e-6 or abs(highlights - DEFAULTS["highlights"]) > 1e-6:
                rimin = gimin = bimin = max(0.0, 0.15 * shadows)
                rimax = gimax = bimax = min(1.0, 1.0 - 0.15 * highlights)
                return (f"colorlevels=rimin={rimin:.3f}:gimin={gimin:.3f}:bimin={bimin:.3f}:"
                        f"rimax={rimax:.3f}:gimax={gimax:.3f}:bimax={bimax:.3f}")
            return None

        def build_unsharp_filter(sharpness):
            if abs(sharpness - DEFAULTS["sharpness"]) > 1e-6:
                return f"unsharp=5:5:{sharpness:.1f}:5:5:{sharpness/2:.1f}"
            return None
        def build_vibrance_filter(vibrance):
            if abs(vibrance - 0.0) > 1e-6:
                return f"vibrance={vibrance:.2f}"
            return None
        '''

        try:
            os.makedirs(output_folder, exist_ok=True)
            video_extensions = ('.mp4', '.mov', '.avi', '.mkv', '.flv')
            video_files = [f for f in os.listdir(input_folder) if f.lower().endswith(video_extensions)]
            total = len(video_files)
            self.progress["maximum"] = total
            total_success = 0
            aspect = settings["aspect"]
            target_width, target_height = self.aspect_ratios[aspect]
            zoom_factor = float(settings["zoom"].rstrip('%')) / 100.0
            scaled_width = int(target_width * zoom_factor)
            scaled_height = int(target_height * zoom_factor)
            
            exposure = settings["exposure"]
            brightness, gamma = exposure_to_brightness_gamma(exposure)
            contrast = settings["contrast"]
            saturation = settings["saturation"]
            hue = settings["hue"]
            sharpness = settings["sharpness"]
            crf = settings["crf"]
            warmth = settings["warmth"]
            tint = settings["tint"]
            shadows = settings["shadows"]
            highlights = settings["highlights"]
            vibrance = settings["vibrance"]
            denoise = settings["denoise"]
            
            for idx, filename in enumerate(video_files, 1):
                if self.stop_event.is_set():
                    self.log_message("🛑 Processing stopped by user")
                    break
                self.progress["value"] = idx - 1
                self.log_message(f"Processing {idx}/{total}: {filename}")
                input_path = os.path.join(input_folder, filename)
                motion_start = self.detect_motion_start(input_path)
                if motion_start is None:
                    self.log_message(f"⚠️ No motion detected in {os.path.basename(input_path)}")
                    continue
                crop_params = self.get_crop_params(input_path)
                if not crop_params:
                    self.log_message(f"⚠️ Valid crop parameters not found for {os.path.basename(input_path)}")
                    continue
                for job in video_jobs:
                    if self.stop_event.is_set():
                        self.log_message("🛑 Stopped during video jobs")
                        break
                    out_name = f"{os.path.splitext(filename)[0]}_v{job['index']}.mp4"
                    output_path = os.path.abspath(os.path.join(output_folder, out_name))
                    start_time = motion_start + job["start"]
                    duration = job["end"] - job["start"]

                    '''
                    # --- Use captured settings ---
                    exposure = settings["exposure"]
                    brightness, gamma = exposure_to_brightness_gamma(exposure)
                    contrast = settings["contrast"]
                    saturation = settings["saturation"]
                    hue = settings["hue"]
                    sharpness = settings["sharpness"]
                    crf = settings["crf"]
                    warmth = settings["warmth"]
                    tint = settings["tint"]
                    shadows = settings["shadows"]
                    highlights = settings["highlights"]
                    vibrance = settings["vibrance"]
                    denoise = settings["denoise"]
                    zoom_factor = float(settings["zoom"].rstrip('%')) / 100.0
                    scaled_width = int(target_width * zoom_factor)
                    scaled_height = int(target_height * zoom_factor)
                    '''

                    # --- Build filter chain conditionally ---
                    filters = []
                    filters.append(f"crop={crop_params}")
                    filters.append(f"scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=increase:flags=lanczos")
                    # CORRECT - centers the crop properly  
                    filters.append(f"crop={target_width}:{target_height}:(iw-ow)/2:(ih-oh)/2")
                    filters.append("setsar=1:1")
                    filters.append(f"setdar={target_width/target_height:.2f}")
                    eq_filter = build_eq_filter(brightness, contrast, saturation, gamma)
                    if eq_filter:
                        filters.append(eq_filter)
                    hue_filter = build_hue_filter(hue)
                    if hue_filter:
                        filters.append(hue_filter)
                    colorbalance_filter = build_colorbalance_filter(warmth, tint)
                    if colorbalance_filter:
                        filters.append(colorbalance_filter)
                    colorlevels_filter = build_colorlevels_filter(shadows, highlights)
                    if colorlevels_filter:
                        filters.append(colorlevels_filter)
                    unsharp_filter = build_unsharp_filter(sharpness)
                    if unsharp_filter:
                        filters.append(unsharp_filter)
                    vibrance_filter = build_vibrance_filter(vibrance)  # Add this line
                    if vibrance_filter:
                        filters.append(vibrance_filter)  # Add this line
                    denoise_filter = build_denoise_filter(denoise)
                    if denoise_filter:
                        filters.append(denoise_filter)
                    rotation_filter = self.get_rotation_filter(settings.get("rotation_steps", 0))
                    if rotation_filter:
                        filters.append(rotation_filter)

                    filter_str = ",".join([f for f in filters if f])
                    ffmpeg_cmd = [
                        self.ffmpeg_path,
                        '-y', '-ss', str(start_time),
                        '-i', os.path.abspath(input_path)
                    ]
                    audio_name = job["audio"]
                    if audio_name == "None":
                        ffmpeg_cmd += [
                            '-vf', filter_str,
                            '-t', str(duration),
                            '-an'
                        ]
                    else:
                        if audio_name == DEFAULT_MUSIC_NAME:
                            audio_path = self.default_audio_path
                        else:
                            audio_path = self.user_music.get(audio_name)
                        if audio_path and os.path.exists(audio_path):
                            ffmpeg_cmd += [
                                '-i', os.path.abspath(audio_path),
                                '-filter_complex',
                                f'[0:v]{filter_str}[v];'
                                f'[1:a]atrim=0:{duration},apad=pad_dur={duration},volume=0.4[audio]',
                                '-map', '[v]',
                                '-map', '[audio]',
                                '-t', str(duration),
                                '-c:a', 'aac',
                                '-b:a', '128k'
                            ]
                        else:
                            ffmpeg_cmd += [
                                '-vf', filter_str,
                                '-t', str(duration),
                                '-an'
                            ]
                    ffmpeg_cmd += [
                        '-c:v', 'libx264',
                        '-crf', str(crf),
                        '-b:v', '1000k',
                        '-maxrate', '1100k',
                        '-bufsize', '2200k',
                        '-preset', 'slow',
                        '-profile:v', 'baseline',
                        '-level', '3.1',
                        '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart',
                        '-colorspace', 'bt709',
                        '-color_primaries', 'bt709',
                        '-color_trc', 'bt709',
                        output_path
                    ]
                    try:
                        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
                        self.log_message(f"✅ Created video: {os.path.basename(output_path)}")
                        total_success += 1
                    except subprocess.CalledProcessError as e:
                        error_msg = e.stderr.decode(errors="replace")
                        self.log_message(f"❌ FFmpeg Error: {error_msg}")
                if self.stop_event.is_set():
                    break  # Skip spin and next videos
                if spin_enabled:
                    if not crop_params:
                        self.log_message(f"⚠️ Skipping spin for {filename}: no crop params")
                    else:
                        self.generate_spin_screenshots(
                            input_path=os.path.abspath(input_path),
                            output_folder=output_folder,
                            filename=filename,
                            motion_start=motion_start,
                            spin_start=settings["spin_start"],
                            spin_end=settings["spin_end"],
                            spin_count=int(settings["spin_count"]),
                            settings=settings,  # ADD THIS
                            crop_params=crop_params  # ADD THIS
                        )

                # --- Photo Outputs ---
                photo_jobs = settings.get("photos", [])
                for photo_idx, photo in enumerate(photo_jobs):
                    if self.stop_event.is_set():
                        self.log_message("🛑 Photo processing stopped by user")
                        break
                    if not photo.get("enabled"):
                        continue
                    ts = photo.get("timestamp", 0.0)
                    if ts < 0:
                        continue
                    out_name = f"{os.path.splitext(filename)[0]}_p{photo_idx+1}.jpg"
                    output_path = os.path.abspath(os.path.join(output_folder, out_name))
                    # Build filter chain (same as video, but quality-focused)
                    filters = []
                    filters.append(f"crop={crop_params}")
                    filters.append(f"scale={scaled_width}:{scaled_height}:force_original_aspect_ratio=increase:flags=lanczos")
                    filters.append(f"crop={target_width}:{target_height}:(iw-ow)/2:(ih-oh)/2")
                    filters.append("setsar=1:1")
                    filters.append(f"setdar={target_width/target_height:.2f}")
                    eq_filter = build_eq_filter(brightness, contrast, saturation, gamma)
                    if eq_filter:
                        filters.append(eq_filter)
                    hue_filter = build_hue_filter(hue)
                    if hue_filter:
                        filters.append(hue_filter)
                    colorbalance_filter = build_colorbalance_filter(warmth, tint)
                    if colorbalance_filter:
                        filters.append(colorbalance_filter)
                    colorlevels_filter = build_colorlevels_filter(shadows, highlights)
                    if colorlevels_filter:
                        filters.append(colorlevels_filter)
                    unsharp_filter = build_unsharp_filter(sharpness)
                    if unsharp_filter:
                        filters.append(unsharp_filter)
                    vibrance_filter = build_vibrance_filter(vibrance)
                    if vibrance_filter:
                        filters.append(vibrance_filter)
                    denoise_filter = build_denoise_filter(denoise)
                    if denoise_filter:
                        filters.append(denoise_filter)
                    rotation_filter = self.get_rotation_filter(settings.get("rotation_steps", 0))
                    if rotation_filter:
                        filters.append(rotation_filter)
                    filter_str = ",".join([f for f in filters if f])

                    # Use -q:v 1 for highest JPEG quality
                    ffmpeg_cmd = [
                        self.ffmpeg_path,
                        '-y',
                        '-ss', str(motion_start + ts),
                        '-i', os.path.abspath(input_path),
                        '-vf', filter_str,
                        '-frames:v', '1',
                        '-q:v', '1',
                        '-map_metadata', '-1',
                        output_path
                    ]
                    try:
                        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
                        self.log_message(f"🖼️ Saved photo: {os.path.basename(output_path)}")
                    except subprocess.CalledProcessError as e:
                        error_msg = e.stderr.decode(errors="replace")
                        self.log_message(f"❌ Photo {photo_idx+1} failed: {error_msg}")

                
                self.progress["value"] = idx
                self.root.update_idletasks()
            self.root.after(0, lambda: messagebox.showinfo(
                "Complete",
                f"Processing finished!\nTotal videos created: {total_success}"
            ))
        except Exception as e:
            import traceback
            self.log_message(f"❌ CRITICAL ERROR: {str(e)}")
            self.log_message(traceback.format_exc())
        finally:
            self.root.after(0, self.start_btn.config, {'state': tk.NORMAL})
            self.root.after(0, self.stop_btn.config, {'state': tk.DISABLED})



if __name__ == "__main__":
    root = tk.Tk()
    app = VideoEditorApp(root)
    root.mainloop()
