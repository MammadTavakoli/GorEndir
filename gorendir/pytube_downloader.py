import os
import logging
from pathlib import Path
from typing import List, Union, Optional, Dict

from pytube import YouTube, Playlist
from pytube.exceptions import VideoUnavailable

DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080

# لاگر
logger = logging.getLogger("gorendir")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)

class DownloadError(Exception):
    pass

class YouTubeDownloader:
    def __init__(
        self,
        save_directory: Union[str, Path],
        subtitle_languages: Optional[List[str]] = None,
        max_resolution: int = DEFAULT_MAX_RESOLUTION
    ):
        self.save_directory = Path(save_directory)
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution

    def _print_banner(self):
        banner = r"""
╔═══════════════════════════════════════════════════════════════════╗
║   GÖRENDİR - Your Ultimate YouTube Video & Playlist Downloader    ║
╚═══════════════════════════════════════════════════════════════════╝
"""
        logger.info(banner)

    def _create_folder(self, title: str, author: str, url: str, force: bool) -> Path:
        folder_name = f"{title}_{author}".replace("/", "_")
        folder = self.save_directory / "Download_video" / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        url_log = self.save_directory / "_urls.txt"
        if not force and url_log.exists() and url in url_log.read_text(encoding="utf-8").splitlines():
            raise DownloadError("URL already downloaded. Skipping...")

        with open(url_log, "a", encoding="utf-8") as f:
            f.write(url + "\n")
        (folder / "_url.txt").write_text(url, encoding="utf-8")

        logger.info(f"Created folder: {folder}")
        return folder

    def _download_single_video(self, url: str, index: int, force: bool):
        try:
            yt = YouTube(url)
            title = yt.title
            author = yt.author
            folder = self._create_folder(title, author, url, force)

            stream = yt.streams.filter(progressive=True, file_extension="mp4") \
                               .order_by("resolution").desc() \
                               .filter(res=f"{self.max_resolution}p").first()

            if not stream:
                stream = yt.streams.get_highest_resolution()

            filename = f"{str(index).zfill(2)} - {title}.mp4"
            logger.info(f"Downloading: {filename}")
            stream.download(output_path=str(folder), filename=filename)

            self._download_captions(yt, folder, filename.replace(".mp4", ""))

        except VideoUnavailable:
            logger.warning(f"Video unavailable: {url}")
        except DownloadError as skip:
            logger.info(skip)
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")

    def _download_captions(self, yt: YouTube, folder: Path, filename_prefix: str):
        for lang in self.subtitle_languages:
            try:
                caption = yt.captions.get_by_language_code(lang)
                if caption:
                    srt = caption.generate_srt_captions()
                    path = folder / f"{filename_prefix}.{lang}.srt"
                    path.write_text(srt, encoding="utf-8")
                    logger.info(f"Saved subtitles: {path}")
            except Exception as e:
                logger.error(f"Error saving subtitles for {lang}: {e}")

    def _is_playlist(self, url: str) -> bool:
        return "list=" in url and "watch?v=" not in url

    def download(
        self,
        video_input: Union[str, List[Union[str, Dict[str, int]]], Dict[str, int]],
        force_download: bool = False,
        reverse_download: bool = False
    ):
        self._print_banner()

        tasks = []

        if isinstance(video_input, str):
            if self._is_playlist(video_input):
                try:
                    playlist = Playlist(video_input)
                    urls = list(playlist.video_urls)
                    if reverse_download:
                        urls.reverse()
                    tasks.extend([(url, idx + 1) for idx, url in enumerate(urls)])
                except Exception as e:
                    logger.error(f"Failed to process playlist: {e}")
            else:
                tasks.append((video_input, 1))

        elif isinstance(video_input, dict):
            for k, v in video_input.items():
                tasks.append((k, v))

        elif isinstance(video_input, list):
            for item in video_input:
                if isinstance(item, dict):
                    for k, v in item.items():
                        tasks.append((k, v))
                else:
                    tasks.append((item, 0))

        if reverse_download:
            tasks.reverse()

        for index, (url, _) in enumerate(tasks, 1):
            self._download_single_video(url, index, force=force_download)
