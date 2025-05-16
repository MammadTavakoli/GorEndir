import re
import time
import random
import logging
import yt_dlp
from pathlib import Path
from typing import List, Dict, Optional, Union
from requests.exceptions import HTTPError
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
from youtube_transcript_api.formatters import SRTFormatter
from .utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder

DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080

# تنظیم لاگر برای نمایش در کنسول (بدون ذخیره فایل)
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)
logger = logging.getLogger("gorendir")
logger.setLevel(logging.INFO)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
logger.addHandler(console)

class DownloadError(Exception):
    """Custom exception for download failures."""

class YouTubeDownloader:
    """A class to download YouTube videos and their subtitles."""

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
        """نمایش ASCII Art"""
        ascii_art = r"""
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
        logger.info("\n" + ascii_art)

    def _extract_video_id(self, url: str) -> Optional[str]:
        match = re.search(r"(?:v=|youtu\.be/)([^&#]+)", url)
        return match.group(1) if match else None

    def _get_video_info(self, url: str) -> dict:
        """Retrieve video info without downloading."""
        with yt_dlp.YoutubeDL({"ignoreerrors": True, "quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or info.get("live_status") == "is_upcoming":
            raise DownloadError(f"Cannot extract or video not live: {url}")
        return info

    def _create_folder(self, info: dict, url: str, force: bool) -> Path:
        """Create per-video folder and record URL if needed."""
        title = info.get("title", "")
        uploader = info.get("uploader", "")
        folder = self.save_directory / "Download_video" / sanitize_filename(f"{title}_{uploader}")
        folder.mkdir(parents=True, exist_ok=True)

        log_file = self.save_directory / "_urls.txt"
        if not force and url in log_file.read_text(encoding="utf-8").splitlines():
            raise DownloadError("URL already saved; skipping.")
        log_file.open("a+", encoding="utf-8").write(url + "\n")
        (folder / "_url.txt").write_text(url, encoding="utf-8")
        logger.info(f"Folder ready: {folder}")
        return folder

    def _get_ydl_options(
        self,
        start: int,
        reverse: bool,
        write_subs: bool
    ) -> dict:
        opts = {
            "format": f"(bestvideo[height<={self.max_resolution}]+bestaudio/best)",
            "outtmpl": "%(autonumber)02d_%(title)s.%(ext)s",
            "autonumber_start": start,
            "writesubtitles": write_subs,
            "writeautomaticsub": write_subs,
            "write_auto_sub": write_subs,
            "sub_lang": "en",
            "subtitleslangs": self.subtitle_languages,
            "ignoreerrors": True,
            "simulate": False,
        }
        if reverse:
            opts["playlistreverse"] = True
        return opts

    def _process_playlist_entries(
        self,
        entries: List[dict],
        start: int
    ) -> List[Dict[str, str]]:
        results, cnt = [], start
        for e in entries or []:
            if not e:
                logger.warning("Skipping empty entry")
                continue
            vid = e.get("id")
            name = sanitize_filename(e.get("title", ""))
            results.append({"id": vid, "filename": f"{cnt:02d}_{name}"})
            cnt += 1
        return results

    def _fetch_with_retry(self, transcript, max_retries: int = 5, base_delay: float = 1.0):
        """
        Fetch transcript with retry on HTTP 429 using exponential backoff.
        """
        for attempt in range(max_retries):
            try:
                return transcript.fetch()
            except HTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status == 429:
                    delay = base_delay * (2 ** attempt) + random.random()
                    logger.warning(f"Rate limited (429). retrying after {delay:.1f}s …")
                    time.sleep(delay)
                else:
                    raise
        raise DownloadError("Rate limited after multiple retries.")

    def download_video(
        self,
        video_urls: Union[str, List[str], Dict[str, int]],
        playlist_start: int = 1,
        skip_download: bool = False,
        force_download: bool = False,
        reverse_download: bool = False,
        yt_dlp_write_subs: bool = False
    ) -> None:
        """Download videos (single, list, or dict) and their subtitles."""
        if isinstance(video_urls, dict):
            tasks = list(video_urls.items())
        elif isinstance(video_urls, str):
            tasks = [(video_urls, playlist_start)]
        else:
            tasks = [(u, playlist_start) for u in video_urls]

        self._print_ascii_art()

        for url, start in tasks:
            vid_id = self._extract_video_id(url)
            canonical = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else url
            logger.info(f"Starting download: {canonical}")
            try:
                info = self._get_video_info(canonical)
                folder = self._create_folder(info, canonical, force_download)
                opts = self._get_ydl_options(start, reverse_download, yt_dlp_write_subs)
                if skip_download:
                    opts["simulate"] = True

                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.cache.remove()  # پاک‌سازی کش yt_dlp
                    playlist_info = ydl.extract_info(canonical, download=not skip_download) or {}

                entries = playlist_info.get("entries") or [playlist_info]
                videos = self._process_playlist_entries(entries, start)
                self.download_subtitles(videos, reverse_download, folder)

            except DownloadError as e:
                logger.warning(e)
            except Exception as e:
                logger.error(f"Unexpected error for {canonical}: {e}")

        convert_all_srt_to_text(self.save_directory, '*******')
        rename_files_in_folder(self.save_directory)

    def download_subtitles(
        self,
        video_list: List[Dict[str, str]],
        reverse: bool,
        folder: Path
    ) -> None:
        """Download existing and translated subtitles to پوشهٔ مشخص."""
        api = YouTubeTranscriptApi()
        vids = list(reversed(video_list)) if reverse else video_list

        for idx, info in enumerate(vids, 1):
            vid, fname = info["id"], info["filename"]
            base = folder / fname
            try:
                time.sleep(0.5 + random.random() * 0.5)
                transcripts = api.list_transcripts(vid)

                # زیرنویس‌های اصلی
                for t in transcripts.transcripts:
                    raw = self._fetch_with_retry(t)
                    srt = SRTFormatter().format_transcript(raw)
                    (base.with_suffix(f".{t.language_code}.srt")).write_text(srt, encoding="utf-8")
                    logger.info(f"[{idx}] Saved subs {t.language_code} for {fname}")

                # ترجمه زیرنویس‌ها
                existing = {t.language_code for t in transcripts.transcripts}
                to_translate = set(self.subtitle_languages) - existing
                default_transcript = (
                    transcripts.find_manually_created_transcript
                    if transcripts.manually_created_transcripts else
                    transcripts.find_generated_transcript
                )
                for lang in to_translate:
                    try:
                        tr = default_transcript([lang]).translate(lang)
                        raw = self._fetch_with_retry(tr)
                        srt = SRTFormatter().format_transcript(raw)
                        (base.with_suffix(f".{lang}.srt")).write_text(srt, encoding="utf-8")
                        logger.info(f"[{idx}] Translated subs to {lang} for {fname}")
                    except Exception as e:
                        logger.error(f"Translate error ({lang}) for {fname}: {e}")

            except TranscriptsDisabled:
                logger.warning(f"[{idx}] Subtitles disabled for {fname}")
            except Exception as e:
                logger.error(f"[{idx}] Error fetching subs for {fname}: {e}")
