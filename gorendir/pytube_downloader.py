from pytube import YouTube, Playlist
from pytube.exceptions import VideoUnavailable, RegexMatchError, LiveStreamError, AgeRestrictedError
import os
import logging
from pathlib import Path
from typing import List, Dict, Optional, Union
import re # Import regex module
import time # For potential delays

DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080

# Logger setup
# Ensure handlers are cleared only once if this script might be run multiple times in a session
if not logging.root.handlers:
    logger = logging.getLogger("gorendir")
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(console_handler)
else:
    logger = logging.getLogger("gorendir") # Get existing logger if already configured

# Custom exception
class DownloadError(Exception):
    pass

class pytube_YouTubeDownloader:
    def __init__(self, save_directory: Union[str, Path],
                 subtitle_languages: Optional[List[str]] = None,
                 max_resolution: int = DEFAULT_MAX_RESOLUTION):
        self.save_directory = Path(save_directory)
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution

    def _print_ascii_art(self):
        art = r"""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║  ██████╗  ██████╗ ██████╗ ███████╗███╗   ██╗██████╗ ██╗██████╗   ║
║ ██╔════╝ ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║██╔══██╗  ║
║ ██║  ███╗██║  ██║██████╔╝█████╗  ██╔██╗ ██║██║  ██║██║██████╔╝  ║
║ ██║   ██║██║  ██║██╔══██╗██╔══╝  ██║╚██╗██║██║  ██║██║██╔══██╗  ║
║ ╚██████╔╝╚██████╔╝██║  ██║███████╗██║ ╚████║██████╔╝██║██║  ██║  ║
║  ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚═╝╚═╝  ╚═╝  ║
║                                                                   ║
║  Welcome to GÖRENDİR - Your Ultimate YouTube Video Downloader!    ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
"""
        logger.info("\n" + art)

    def _is_playlist(self, url: str) -> bool:
        # More robust check for playlist URLs
        return "playlist" in url.lower() or "list=" in url.lower()

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitizes a string to be used as a filename."""
        # Remove invalid characters for filenames
        filename = re.sub(r'[\\/:*?"<>|]', '', filename)
        # Replace spaces with underscores, or keep spaces if preferred
        filename = filename.replace(' ', '_')
        # Limit length to avoid OS issues (e.g., 255 chars for Windows)
        return filename[:200].strip()

    def _create_folder(self, title: str, uploader: str, url: str, force: bool, is_playlist_item: bool = False) -> Path:
        """
        Creates a folder for the video/playlist and logs the URL.
        If it's a playlist item, the folder is created by the playlist handler.
        """
        if is_playlist_item:
            # For playlist items, the base_folder is passed directly
            # This function is primarily for single video downloads
            pass
        else:
            # Sanitize folder name
            sanitized_title = self._sanitize_filename(title)
            sanitized_uploader = self._sanitize_filename(uploader)
            folder_name = f"{sanitized_title}_{sanitized_uploader}"
            folder = self.save_directory / "Download_video" / folder_name
            folder.mkdir(parents=True, exist_ok=True)

            log_file = self.save_directory / "_urls.txt"
            if not force and log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    downloaded_urls = f.read().splitlines()
                if url in downloaded_urls:
                    raise DownloadError(f"URL '{url}' already saved; skipping.")

            with open(log_file, "a+", encoding="utf-8") as f:
                f.write(url + "\n")

            (folder / "_url.txt").write_text(url, encoding="utf-8")
            logger.info(f"Folder ready: {folder}")
            return folder

    def _on_progress(self, stream, chunk, bytes_remaining):
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        percentage_of_completion = bytes_downloaded / total_size * 100
        logger.info(f"Downloading: {percentage_of_completion:.2f}% complete")

    def _on_complete(self, stream, file_path):
        logger.info(f"Download complete: {file_path}")

    def download_video(
        self,
        video_urls: Union[str, Dict[str, int], List[Union[str, Dict[str, int]]]],
        force_download: bool = False,
        reverse_download: bool = False
    ) -> None:
        self._print_ascii_art()

        # Normalize input
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
            logger.error("Unsupported video_urls format. Please provide a string, dict, or list of strings/dicts.")
            return

        if reverse_download:
            tasks.reverse()

        for index, (url, _) in enumerate(tasks, 1):
            logger.info(f"Processing URL {index}/{len(tasks)}: {url}")
            if self._is_playlist(url):
                self._download_playlist(url, force_download, reverse_download)
            else:
                self._download_single_video(url, force_download, index)
            # Optional: Add a small delay between downloads to avoid rate limiting
            # time.sleep(1)

    def _download_playlist(self, url: str, force: bool, reverse: bool):
        try:
            playlist = Playlist(url)
            # Removing playlist._video_regex as it might cause issues with newer pytube versions
            # and YouTube's changing HTML. Rely on pytube's internal parsing.

            title = playlist.title or "Untitled_Playlist"
            sanitized_playlist_title = self._sanitize_filename(title)
            playlist_folder = self.save_directory / "Download_video" / f"Playlist_{sanitized_playlist_title}"
            playlist_folder.mkdir(parents=True, exist_ok=True)

            # Log playlist URL
            log_file = self.save_directory / "_urls.txt"
            if not force and log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    downloaded_urls = f.read().splitlines()
                if url in downloaded_urls:
                    logger.info(f"Playlist URL '{url}' already saved; skipping playlist download.")
                    return # Skip entire playlist if already logged

            with open(log_file, "a+", encoding="utf-8") as f:
                f.write(url + "\n")

            (playlist_folder / "_playlist_url.txt").write_text(url, encoding="utf-8")
            logger.info(f"Playlist folder ready: {playlist_folder}")

            # Iterate through playlist.videos for more reliable parsing
            videos = list(playlist.videos) # Convert to list to allow reverse()
            if reverse:
                videos.reverse()

            logger.info(f"Downloading playlist: '{title}' ({len(videos)} videos)")

            for idx, yt_obj in enumerate(videos, 1):
                video_url = yt_obj.watch_url # Get the URL for the individual video
                logger.info(f"Processing video {idx}/{len(videos)} in playlist: {video_url}")
                self._download_single_video(video_url, force, idx, playlist_folder, is_playlist_item=True)
                # Optional: Add a small delay between videos in a playlist
                # time.sleep(0.5)

        except RegexMatchError:
            logger.error(f"Failed to parse playlist URL '{url}'. This often means pytube needs an update or YouTube changed its layout. Try 'pip install --upgrade pytube'.")
        except Exception as e:
            logger.error(f"Failed to download playlist {url}: {e}", exc_info=True) # exc_info=True to print traceback

    def _download_single_video(self, url: str, force: bool, index: int = 1, base_folder: Optional[Path] = None, is_playlist_item: bool = False):
        try:
            # Initialize YouTube object with callbacks
            yt = YouTube(url, on_progress_callback=self._on_progress, on_complete_callback=self._on_complete)

            # Fetch video info (title, author)
            # This can sometimes fail, so wrap it
            try:
                title = yt.title
                author = yt.author or "Unknown_Author" # Handle cases where author might be None
            except Exception as e:
                logger.warning(f"Could not fetch title/author for {url}: {e}. Skipping this video.")
                return

            # Create folder if not part of a playlist download
            folder = base_folder
            if not folder: # Only create folder if it's a standalone video download
                try:
                    folder = self._create_folder(title, author, url, force, is_playlist_item)
                except DownloadError as skip:
                    logger.info(str(skip))
                    return # Skip this video if already downloaded/logged

            if not folder: # Fallback if folder creation failed for some reason
                logger.error(f"Could not determine save folder for {url}. Skipping.")
                return

            # Select stream
            stream = yt.streams.filter(progressive=True, file_extension="mp4") \
                               .order_by("resolution").desc() \
                               .filter(res=f"{self.max_resolution}p").first()

            if not stream:
                logger.warning(f"No progressive MP4 stream found for {self.max_resolution}p. Trying highest resolution.")
                stream = yt.streams.get_highest_resolution()

            if not stream:
                logger.warning(f"No suitable stream found for {url}. Skipping video.")
                return

            # Sanitize filename for the video itself
            sanitized_title = self._sanitize_filename(title)
            numbered_filename = f"{str(index).zfill(2)} - {sanitized_title}.mp4"
            full_file_path = folder / numbered_filename

            if not force and full_file_path.exists():
                logger.info(f"File '{numbered_filename}' already exists in '{folder}'; skipping download.")
                return

            logger.info(f"Starting download: '{numbered_filename}' to '{folder}'")
            stream.download(output_path=str(folder), filename=numbered_filename)

            self.download_captions(yt, folder, sanitized_title)

        except VideoUnavailable:
            logger.warning(f"Video unavailable: {url}")
        except AgeRestrictedError:
            logger.warning(f"Video is age-restricted and cannot be downloaded: {url}")
        except LiveStreamError:
            logger.warning(f"Video is a live stream and cannot be downloaded: {url}")
        except RegexMatchError:
            logger.warning(f"Failed to parse video URL '{url}'. Try updating pytube.")
        except DownloadError as skip:
            logger.info(str(skip))
        except Exception as e:
            logger.error(f"An unexpected error occurred while downloading {url}: {e}", exc_info=True)

    def download_captions(self, yt: YouTube, folder: Path, title: str):
        try:
            if not yt.captions:
                logger.info(f"No captions available for '{title}'.")
                return

            for lang in self.subtitle_languages:
                caption = yt.captions.get_by_language_code(lang)
                if caption:
                    try:
                        srt = caption.generate_srt_captions()
                        # Sanitize filename for captions as well
                        sanitized_caption_title = self._sanitize_filename(title)
                        filename = folder / f"{sanitized_caption_title}.{lang}.srt"
                        with open(filename, "w", encoding="utf-8") as f:
                            f.write(srt)
                        logger.info(f"Saved subtitles: {filename}")
                    except Exception as caption_e:
                        logger.warning(f"Could not generate SRT for language '{lang}' for '{title}': {caption_e}")
                else:
                    logger.info(f"No captions found for language '{lang}' for '{title}'.")
        except Exception as e:
            logger.error(f"Error downloading captions for '{title}': {e}", exc_info=True)
