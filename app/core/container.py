"""Dependency container for shared runtime objects."""

import asyncio

from services.clipper import VideoClipper
from services.downloader import VideoDownloader
from services.premiere_exporter import PremiereExporter
from services.refiner import TextRefiner
from services.shorts_maker import ShortsMaker
from services.summarizer import VideoSummarizer
from services.task_manager import TaskManager
from services.transcriber import VideoTranscriber

from app.core.paths import RESULTS_DIR, TASKS_PERSISTENCE_FILE, TEMP_DIR, VIDEOS_DIR


class AppContainer:
    """Holds service instances and shared async primitives."""

    def __init__(self) -> None:
        self.job_queue: asyncio.Queue = asyncio.Queue()
        self.resource_semaphore = asyncio.Semaphore(1)

        self.downloader = VideoDownloader(download_dir=VIDEOS_DIR)
        self.transcriber = VideoTranscriber(output_dir=RESULTS_DIR)
        self.summarizer = VideoSummarizer(output_dir=RESULTS_DIR)
        self.refiner = TextRefiner()
        self.task_manager = TaskManager(persistence_file=TASKS_PERSISTENCE_FILE)
        self.clipper = VideoClipper(temp_dir=TEMP_DIR)
        self.shorts_maker = ShortsMaker()
        self.premiere_exporter = PremiereExporter(output_dir=TEMP_DIR)

        # Placeholder to keep references for lifecycle-managed objects.
        self.worker = None
        self.worker_task = None
