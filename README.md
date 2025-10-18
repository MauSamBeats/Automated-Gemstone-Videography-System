# Automated-Gemstone-Videography-System
Automated gemstone showcase system with Arduino-controlled stepper motor, custom 3D-printed attachments, and user-friendly drag-and-drop motor code UI. Includes Python-based video editor for interval cropping, effect filters, screenshot capture, and image-sequenced 3D interactive gemstone viewing.

# Project Report: Automated Gemstone Videography & Post-Processing Pipeline

## 1. Project Objective
This project's primary objective is to automate the complete workflow for creating web-ready gemstone product videos. It replaces a manual, inconsistent, and time-consuming process with a high-precision automated system.

### The system is designed to:

- Standardize physical capture of gemstone footage using a stepper motor.

- Fully automate post-processing, including motion detection, precise-time video cropping, color grading, and batch-exporting of web-optimized assets (videos, seamless loops, and 3D-spin image sequences).

- The main benefit is speeding up video creation while making sure every video looks consistently professional, which is crucial for a high-end web store.

## 2. System Architecture
The solution is comprised of two distinct, interconnected components:

### Component 1: 
This is a web-based tool (MotorCodeMaker.html) that functions as the control interface for the motor. It allows non-technical users, like photographers, to program complex rotation patterns by generate Arduino IDE code without writing a single line of code.

### Component 2: 
Automated Post-Processing Engine (Python/FFmpeg) A desktop application (main.py) that takes raw video footage Folder as input. It uses computer vision to synchronize with the motor's actions and then automatically performs all batch-processing tasks based on user-defined settings.

## 3. Core Technical Implementation & Automation

Development Note: AI-assisted development was used as a productivity tool to streamline the creation of both the Tkinter application and the MotorCodeMaker interface bringing the workflow Idea to Reality.

### Component 1: Motion Control Interface (MotorCodeMaker.html)
Technology Stack: Vanilla HTML, CSS, and JavaScript.

#### Dynamic Sequence Builder: 
The UI allows users to add, remove, and reorder rotation(degrees, direction) and delay(seconds) commands.

#### Runtime Calculation: 
A key function, calculateRuntime(), iterates through the sequence of stepsData. It uses the configured Steps per Revolution and Step Delay (μs) to precisely calculate the total execution time of the entire sequence in seconds. This runtime is the critical data point that links the physical world to the software.

#### Arduino Code Generation: 
The generateCode() function dynamically builds a complete Arduino (.ino) sketch. It iterates through the stepsData array and popula th setup() loop with the corresponding rotateStepper() and delay() commands, ready for direct upload.

#### 3D Visualization: 
A CSS-based 3D gemstone model provides immediate visual feedback of the programmed sequence, preventing errors in the code generation.

### Component 2: Automated Post-Processing Engine (main.py)
Technology Stack: Python, Tkinter (GUI), OpenCV (cv2), subprocess, and threading.

#### Core Automation Feature: 
- Automated Time-Synchronization is the system's most critical innovation i.e its ability to sync post-processing with the physical motor. The detect_motion_start() function is called for each input video, it uses OpenCV (cv2) to load the video, convert frames to grayscale, and apply Gaussian blur now by comparing consecutive frames using cv2.absdiff and cv2.threshold, it performs contour detection (cv2.findContours) to find the first frame with significant motion (i.e., when the gemstone starts to turn). The timestamp of this frame is captured (e.g., 2.31s) and established as the absolute time-zero datum (t=0) for all subsequent operations. When the user requests a video clip from 1.0s to 3.5s, the system knows this actually means (t=0 + 1.0s) to (t=0 + 3.5s). This allows the app to extract the exact desired rotation (e.g., "front-face-loop") with sub-second precision, which is impossible to do efficiently by hand. This is the key to creating perfectly seamless loops, as the start and end times are known from the motor code.

- The system does not use static ffmpeg commands. Instead, it features a set of modular "builder" functions (build_eq_filter, build_unsharp_filter, build_colorlevels_filter, etc.). These functions dynamically construct a complex ffmpeg filter chain (-vf) string, adding filters only if their values deviate from the default, the puprose behind this functionality is that, say for a process which doesnt involve any saturation tweaks originally the system will add a {-vf "eq=saturation=1.0"} to the final ffmpeg string, this will ruin the videos raw pre possesed saturation and set it to 1.0 even when it wasnt tweaked by the user, that is why the filters parameters are only added to the final string when the user changes them from their default positions. This creates highly efficient and customized processing for each batch.

- Multi-Threaded Batch Processing is used. Meaning, The entire processing logic (_process_videos) is executed in a separate thread (threading.Thread). This ensures the Tkinter GUI remains responsive, allowing the user to monitor progress or even stop the job. The application processes an entire input folder, applying the same set of precise intervals and filters to every video, enabling true automation.

- Multi-Asset Generation From a single input video, the engine autonomously generates three distinct asset types:

  - Cropped Videos: Upto 5 user-defined intervals, with all filters, zoom, and rotation applied at one time.
  - Photo Stills: Extracts high-quality still frames at specific user-defined timestamps (e.g., t=0 + 1.5s).
  - 3D-Spin Sequences: Automatically generates specified number of equidistant images (e.g., 72 frames) over a user specified time interval, ready for use in a sirv.com-style 3D-spin web viewer.

## 4. Automation Outcomes & Business Value
### Efficiency: 
Reduces a multi-hour manual editing task (per gemstone) to a few minutes of automated batch processing.
### Consistency: 
Eliminates human error. Every video is perfectly centered, identically color-graded (due to presets), and cropped with programmatic precision.
### Advanced Assets: 
Enables the creation of "seamless loop" videos and 3D-spin sequences at scale, features that are technically complex and cost-prohibitive to create manually.
### Optimized Workflow: 
The entire pipeline, from motor control to final file, is designed as a single, cohesive system. The calculateRuntime feature in the HTML app directly informs the time intervals entered into the Python app, creating a perfect, data-driven workflow.
### Server-Space Reduction: 
By generating tiny, seamless-loop videos (e.g., <500kb), the system allows the e-commerce site to host thousands of product videos without incurring massive server or CDN costs.
