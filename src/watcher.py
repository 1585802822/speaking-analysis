"""文件夹监控."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .pipeline import Pipeline


class AudioEventHandler(FileSystemEventHandler):
    def __init__(self, config: dict[str, Any], pipeline: Pipeline) -> None:
        self.config = config
        self.pipeline = pipeline
        self.formats = set(config["audio_formats"])

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in self.formats:
            return
        # 等待文件写入完成
        time.sleep(1.0)
        self.pipeline.process(str(path))


class Watcher:
    def __init__(self, config: dict[str, Any], pipeline: Pipeline) -> None:
        self.config = config
        self.pipeline = pipeline
        self.observer = Observer()

    def start(self) -> None:
        handler = AudioEventHandler(self.config, self.pipeline)
        self.observer.schedule(handler, self.config["input_dir"], recursive=False)
        self.observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.observer.stop()
        self.observer.join()
