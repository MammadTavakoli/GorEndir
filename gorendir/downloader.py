import re
import os
import time
import random
import copy
import logging
import yt_dlp
from pathlib import Path
from typing import List, Dict, Optional, Union
from requests.exceptions import HTTPError
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
from youtube_transcript_api.formatters import SRTFormatter
from .utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder
from .vtt_to_srt import process_directory

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
        os.chdir(folder)
        logger.info(f"Folder ready: {folder}")
        return folder

    def _get_ydl_options(
        self,
        start: int,
        reverse: bool,
        write_subs: bool
    ) -> dict: 
        opts = {
            # --- Quality and Formatting ---
            # Simplified and more robust format selector.
            # It selects the best video with the specified resolution (in MP4 container if available)
            # and the best audio, merging them. Falls back to a complete best-quality file if merging fails.
            "format": f"bestvideo[height<={self.max_resolution}][ext=mp4]+bestaudio[ext=m4a]/best[height<={self.max_resolution}][ext=mp4]/best",
            "outtmpl": "%(autonumber)02d_%(title)s.%(ext)s",
            "writedescription": True,  # Download the video's description to a .description file.

            # --- Playlist Handling ---
            "autonumber_start": start,
            "playliststart": start,
            "ignoreerrors": True, # Good for downloading playlists where some videos might be unavailable.

            # --- Subtitle Configuration ---
            # This is the core of the improvement.
            "writesubtitles": write_subs,      # Main switch to enable downloading of manual subtitles.
            "writeautomaticsub": write_subs,  # Main switch to enable downloading of automatic subtitles as a fallback.

            # Specifies a prioritized LIST of languages. yt-dlp will try them in order.
            # It will first look for a manual subtitle for the first language, then an automatic one (if writeautomaticsub is True).
            # If not found, it moves to the next language in the list.
            "subtitleslangs": self.subtitle_languages,

            # --- Deprecated / Redundant Options Removed ---
            # "write_auto_sub": write_subs, # Incorrect key, the correct one is 'writeautomaticsub'.
            # "sub_lang": "en",             # Redundant when using the more flexible 'subtitleslangs'.
            # "writeannotations": True,     # Annotations were discontinued by YouTube in 2019. This option does nothing.
            # "simulate": False,            # False is the default, so this line is not needed unless you toggle it programmatically.
        }      
 
        if reverse:
            opts["playlistreverse"] = True
        print(opts)
        return opts

    def _process_playlist_entries(
        self,
        entries: List[dict],
        start: int,
        reverse_download: bool = False
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
            tasks = [(list(video_urls.keys())[0], list(video_urls.values())[0])]
        elif isinstance(video_urls, str):
            tasks = [(video_urls, playlist_start)]
        else:
            tasks = [
                (list(u.keys())[0], list(u.values())[0]) if isinstance(u, dict) and len(u) == 1
                else (u, playlist_start)
                for u in video_urls
            ]

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

                print("*"*10,"download subtitles", "*"*10)
                entries = playlist_info.get("entries") or [playlist_info]
                videos = self._process_playlist_entries(entries, start, reverse_download)
                self.download_subtitles(videos, reverse_download)
            except DownloadError as e:
                logger.warning(e)
            except Exception as e:
                logger.error(f"Unexpected error for {canonical}: {e}")
        
        process_directory(self.save_directory)    
        convert_all_srt_to_text(self.save_directory, '*******')
        
        # rename_files_in_folder(self.save_directory)

    def download_subtitles(self, video_info_list: List[Dict[str, str]], reverse_download: bool = False):
        """
        Download subtitles for the videos in the list.

        Args:
            video_info_list: List of video information dictionaries.
            reverse_download: Whether to download subtitles in reverse order.
        """
        ytt_api = YouTubeTranscriptApi()

        if reverse_download:
            video_info_list = list(reversed(video_info_list))

        total_videos = len(video_info_list)
        for idx, video_info in enumerate(video_info_list, start=1):
            try:
                sublangs = copy.deepcopy(self.subtitle_languages)
                video_id = video_info.get('id')
                filename = sanitize_filename(video_info.get('filename'))
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                
                for transcript in transcript_list:
                    lng = transcript.language_code                       
                    srt = transcript.fetch()
                    formatter = SRTFormatter()
                    srt_content = formatter.format_transcript(srt)
                    numbered_idx = total_videos - idx + 1 if reverse_download else idx
                    logger.info(f"Downloading {lng} subtitles for: {filename}")
                    with open(rf"{filename}.{lng}.srt", "w", encoding="utf-8") as subtitle_file:
                        subtitle_file.write(srt_content)
                    if lng in sublangs:
                        sublangs.remove(lng)

                first_transcript = next((t for t in transcript_list if t.language_code), None)
                if first_transcript:
                    for tr_lang in sublangs:
                        try:
                            translated_transcript = first_transcript.translate(tr_lang)
                            formatter = SRTFormatter()
                            srt_content = formatter.format_transcript(translated_transcript.fetch())
                            numbered_idx = total_videos - idx + 1 if reverse_download else idx
                            logger.info(f"Downloading translated subtitles to {tr_lang} for: {filename}")
                            with open(rf"{filename}.{tr_lang}.srt", "w", encoding="utf-8") as subtitle_file:
                                subtitle_file.write(srt_content)
                        except Exception as e:
                            logger.error(f"Error downloading translated subtitles to {tr_lang} for: {filename}. Error: {e}")
            except TranscriptsDisabled:
                logger.error(f"Subtitles are disabled for: {filename}")
            except Exception as e:
                logger.error(f"Error downloading subtitles for: {filename}. Error: {e}")