import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional, Union

from pytube import YouTube
from pytube.exceptions import VideoUnavailable

# تنظیمات پیش‌فرض
DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080

# تنظیمات لاگر
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logger = logging.getLogger("gorendir")
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
logger.addHandler(console_handler)


# کلاس خطای سفارشی
class DownloadError(Exception):
    pass


# پاکسازی نام فایل‌ها
def sanitize_filename(name: str) -> str:
    return re.sub(r"[\\/*?\"<>|]", "_", name)


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

    def _print_ascii_art(self):
        art = r"""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║   ██████╗  ██████╗ ██████╗ ███████╗███╗   ██╗██████╗ ██╗██████╗   ║
║  ██╔════╝ ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║██╔══██╗  ║
║  ██║  ███╗██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║  ██║██║██████╔╝  ║
║  ██║   ██║██║   ██║██╔══██╗██╔══╝  ██║╚██╗██║██║  ██║██║██╔══██╗  ║
║  ╚██████╔╝╚██████╔╝██║  ██║███████╗██║ ╚████║██████╔╝██║██║  ██║  ║
║   ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚═╝╚═╝  ╚═╝  ║
║                                                                   ║
║  Welcome to GÖRENDİR - Your Ultimate YouTube Video Downloader!    ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
"""
        logger.info("\n" + art)

    def _create_folder(self, title: str, uploader: str, url: str, force: bool) -> Path:
        folder_name = sanitize_filename(f"{title}_{uploader}")
        folder = self.save_directory / "Download_video" / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        log_file = self.save_directory / "_urls.txt"
        if not force and log_file.exists() and url in log_file.read_text(encoding="utf-8").splitlines():
            raise DownloadError("URL already saved; skipping.")

        with open(log_file, "a+", encoding="utf-8") as f:
            f.write(url + "\n")

        (folder / "_url.txt").write_text(url, encoding="utf-8")
        os.chdir(folder)
        logger.info(f"Folder ready: {folder}")
        return folder

    def download_video(
        self,
        video_urls: Union[str, Dict[str, int], List[Union[str, Dict[str, int]]]],
        force_download: bool = False,
        reverse_download: bool = False
    ) -> None:
        self._print_ascii_art()

        # تبدیل ورودی به لیست وظایف دانلود
        if isinstance(video_urls, dict):
            tasks = [(k, v) for k, v in video_urls.items()]
        elif isinstance(video_urls, str):
            tasks = [(video_urls, 0)]
        elif isinstance(video_urls, list):
            tasks = []
            for item in video_urls:
                if isinstance(item, dict) and len(item) == 1:
                    k, v = list(item.items())[0]
                    tasks.append((k, v))
                else:
                    tasks.append((item, 0))
        else:
            logger.error("Unsupported video_urls format.")
            return

        if reverse_download:
            tasks.reverse()

        for index, (url, _) in enumerate(tasks, 1):
            try:
                yt = YouTube(url)
                title = yt.title
                author = yt.author
                folder = self._create_folder(title, author, url, force_download)

                stream = yt.streams.filter(progressive=True, file_extension="mp4") \
                                   .order_by("resolution").desc() \
                                   .filter(res=f"{self.max_resolution}p").first()

                if not stream:
                    stream = yt.streams.get_highest_resolution()

                numbered_title = f"{str(index).zfill(2)} - {title}"
                logger.info(f"Downloading: {numbered_title}")
                stream.download(output_path=str(folder), filename=sanitize_filename(numbered_title) + ".mp4")

                self.download_captions(yt, folder, numbered_title)

            except VideoUnavailable:
                logger.warning(f"Video unavailable: {url}")
            except DownloadError as skip:
                logger.info(str(skip))
            except Exception as e:
                logger.error(f"Error downloading {url}: {e}")

    def download_captions(self, yt: YouTube, folder: Path, title: str):
        try:
            for lang in self.subtitle_languages:
                caption = yt.captions.get_by_language_code(lang)
                if caption:
                    srt = caption.generate_srt_captions()
                    filename = folder / f"{sanitize_filename(title)}.{lang}.srt"
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(srt)
                    logger.info(f"Saved subtitles: {filename}")
        except Exception as e:
            logger.error(f"Error downloading captions for {title}: {e}")
