"""Filesystem and runtime path constants used across the app."""

import os

STATIC_DIR = "static"
VIDEOS_DIR = os.path.join(STATIC_DIR, "videos")
RESULTS_DIR = os.path.join(STATIC_DIR, "results")
TEMP_DIR = os.path.join(STATIC_DIR, "temp")
CLIPS_DIR = os.path.join(STATIC_DIR, "clips")

TEMPLATES_DIR = "templates"
INDEX_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "index.html")

TASKS_PERSISTENCE_FILE = "tasks.json"
