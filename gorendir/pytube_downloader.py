from pytube import YouTube, Playlist
from pytube.exceptions import VideoUnavailable, RegexMatchError, LiveStreamError
try:
    from pytube.exceptions import AgeRestrictedError
except ImportError:
    class AgeRestrictedError(Exception):
        pass

import os
import logging
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple
import re
import time
import random

DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080

# Logger setup - proper handler management
logger = logging.getLogger("gorendir")

if not logger.handlers:
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(console_handler)

# Custom exception
class DownloadError(Exception):
    pass

class pytube_YouTubeDownloader:
    def __init__(
        self,
        save_directory: Union[str, Path],
        subtitle_languages: Optional[List[str]] = None,
        max_resolution: int = DEFAULT_MAX_RESOLUTION,
        retry_attempts: int = 3,
    ):
        self.save_directory = Path(save_directory)
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution
        self.retry_attempts = retry_attempts
        self.downloaded_urls = self._load_downloaded_urls()

    def _load_downloaded_urls(self) -> set:
        log_file = self.save_directory / "_urls.txt"
        if log_file.exists():
            try:
                return set(log_file.read_text(encoding='utf-8').splitlines())
            except Exception:
                return set()
        return set()

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
        return "playlist" in url.lower() or "list=" in url.lower()

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitizes a string to be used as a filename."""
        if not isinstance(filename, str):
            filename = str(filename)

        # Remove invalid characters for filenames
        filename = re.sub(r'[\\/:*?"<>|]', '', filename)
        # Normalize spaces (keep spaces, don't replace with underscore for readability)
        filename = re.sub(r'\s+', ' ', filename).strip()
        # Limit length
        return filename[:200].strip() or "untitled"

    def _create_folder(self, title: str, uploader: str, url: str, force: bool) -> Optional[Path]:
        """
        Creates a folder for a single video download and logs the URL.
        Returns the folder path, or None if the URL was already downloaded.
        """
        sanitized_title = self._sanitize_filename(title)
        sanitized_uploader = self._sanitize_filename(uploader)
        folder_name = f"{sanitized_title}_{sanitized_uploader}"
        folder = self.save_directory / "Download_video" / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        log_file = self.save_directory / "_urls.txt"
        if not force and url in self.downloaded_urls:
            raise DownloadError(f"URL '{url}' already saved; skipping.")

        self._save_url_to_log(url)
        (folder / "_url.txt").write_text(url, encoding='utf-8')
        logger.info(f"Folder ready: {folder}")
        return folder

    def _save_url_to_log(self, url: str):
        try:
            with open(self.save_directory / "_urls.txt", 'a', encoding='utf-8') as f:
                f.write(url + "\n")
            self.downloaded_urls.add(url)
        except Exception as e:
            logger.warning(f"Failed to save URL to log: {e}")

    def _on_progress(self, stream, chunk, bytes_remaining):
        total_size = stream.filesize
        if total_size <= 0:
            return
        bytes_downloaded = total_size - bytes_remaining
        percentage = bytes_downloaded / total_size * 100
        # Only log every 10% to reduce log spam
        if int(percentage) % 10 == 0 and int(percentage) != getattr(self, '_last_progress_log', -1):
            self._last_progress_log = int(percentage)
            logger.info(f"Downloading: {percentage:.1f}% complete")

    def _on_complete(self, stream, file_path):
        logger.info(f"Download complete: {file_path}")

    def _normalize_inputs(
        self,
        video_urls: Union[str, Dict[str, int], List[Union[str, Dict[str, int]]]]
    ) -> List[Tuple[str, int]]:
        """Normalize all input formats into a list of (url, start_num) tuples."""
        tasks = []
        
        if isinstance(video_urls, dict):
            for k, v in video_urls.items():
                tasks.append((k, v if v > 0 else 1))
        elif isinstance(video_urls, str):
            tasks.append((video_urls, 1))
        elif isinstance(video_urls, list):
            for item in video_urls:
                if isinstance(item, dict):
                    for k, v in item.items():
                        tasks.append((k, v if v > 0 else 1))
                elif isinstance(item, str):
                    tasks.append((item, 1))
                else:
                    logger.warning(f"Skipping unsupported item type: {type(item)}")
        else:
            logger.error("Unsupported video_urls format. Please provide a string, dict, or list of strings/dicts.")
        
        return tasks

    def download_video(
        self,
        video_urls: Union[str, Dict[str, int], List[Union[str, Dict[str, int]]]],
        force_download: bool = False,
        reverse_download: bool = False,
        playlist_end: int = 0,
    ) -> Dict[str, list]:
        """
        Download videos from YouTube using pytube.
        
        Args:
            video_urls: URL(s) to download. Can be:
                - str: Single URL
                - Dict[str, int]: URL -> start number mapping
                - List[Union[str, Dict[str, int]]]: Mixed list
            force_download: If True, re-download even if already downloaded
            reverse_download: If True, reverse playlist order
            playlist_end: If > 0, stop downloading after this many videos
        """
        self._print_ascii_art()

        tasks = self._normalize_inputs(video_urls)
        if not tasks:
            logger.error("No valid inputs provided")
            return {'success': [], 'failed': [], 'skipped': []}

        if reverse_download:
            tasks.reverse()

        results: Dict[str, list] = {'success': [], 'failed': [], 'skipped': []}

        for index, (url, start_num) in enumerate(tasks, 1):
            logger.info(f"Processing URL {index}/{len(tasks)}: {url} (start_num={start_num})")
            if self._is_playlist(url):
                res = self._download_playlist(url, force_download, reverse_download, start_num, playlist_end)
                results['success'].extend(res['success'])
                results['failed'].extend(res['failed'])
                results['skipped'].extend(res['skipped'])
            else:
                res = self._download_single_video(url, force_download, start_num)
                if res.get('skipped'):
                    results['skipped'].append(url)
                elif res.get('success'):
                    results['success'].append(url)
                else:
                    results['failed'].append({'url': url, 'error': res.get('error', 'Unknown error')})
            # Delay between downloads
            time.sleep(random.uniform(1, 2))

        self._print_summary(results)
        return results

    def _download_playlist(
        self,
        url: str,
        force: bool,
        reverse: bool,
        start_num: int = 1,
        playlist_end: int = 0
    ) -> Dict[str, list]:
        """Download a YouTube playlist with start number and end limit support."""
        results: Dict[str, list] = {'success': [], 'failed': [], 'skipped': []}
        
        try:
            playlist = Playlist(url)

            # Get playlist title safely
            title = playlist.title
            if not isinstance(title, str) or not title.strip():
                logger.warning(f"Playlist title for {url} is invalid. Defaulting to 'Untitled_Playlist'.")
                title = "Untitled_Playlist"

            sanitized_playlist_title = self._sanitize_filename(title)
            playlist_folder = self.save_directory / "Download_video" / f"Playlist_{sanitized_playlist_title}"
            playlist_folder.mkdir(parents=True, exist_ok=True)

            # Check if playlist already downloaded
            if not force and url in self.downloaded_urls:
                logger.info(f"Playlist URL '{url}' already saved; skipping playlist download.")
                return results

            self._save_url_to_log(url)
            (playlist_folder / "_playlist_url.txt").write_text(url, encoding='utf-8')
            logger.info(f"Playlist folder ready: {playlist_folder}")

            # Get video URLs from playlist (more reliable than .videos)
            #
            # PLAYLIST PROCESSING LOGIC:
            # In normal mode:  V1→01, V2→02, ... V20→20
            # In reverse mode: V20→01, V19→02, ... V1→20
            # start_num always means "skip N videos from the start of DOWNLOAD order"
            #   normal:  skip from beginning of playlist
            #   reverse: skip from end of playlist (which is start of reversed order)
            #
            # Order of operations:
            #   1) Get URLs
            #   2) Reverse (if reverse mode) — transforms download order
            #   3) Skip by start_num (based on DOWNLOAD order, not original)
            #   4) Apply playlist_end limit
            #   5) Number from start_num based on download order
            
            try:
                video_urls = list(playlist.video_urls)
            except Exception:
                video_urls = [yt.watch_url for yt in playlist.videos]
            
            total_original = len(video_urls)
            
            # Step 2: Reverse FIRST so skip/numbering work on download order
            if reverse:
                video_urls.reverse()
            
            # Step 3: Skip videos before start_num (in DOWNLOAD order)
            skip_count = max(0, start_num - 1)
            video_urls = video_urls[skip_count:]
            
            # Step 4: Apply playlist_end limit
            if playlist_end > 0:
                video_urls = video_urls[:playlist_end]
            
            logger.info(f"Downloading playlist: '{title}' (skipping first {skip_count} in download order, downloading {len(video_urls)}/{total_original} remaining, reverse={reverse})")

            # Step 5: Number from start_num based on download order
            for i, video_url in enumerate(video_urls):
                assigned_num = start_num + i
                logger.info(f"Processing video #{assigned_num} ({i+1}/{len(video_urls)} in download order): {video_url}")
                
                res = self._download_single_video(video_url, force, assigned_num, playlist_folder, is_playlist_item=True)
                if res.get('skipped'):
                    results['skipped'].append(video_url)
                elif res.get('success'):
                    results['success'].append(video_url)
                else:
                    results['failed'].append({'url': video_url, 'error': res.get('error', 'Unknown error')})
                
                # Delay between playlist videos
                time.sleep(random.uniform(0.5, 1.5))

        except RegexMatchError:
            error_msg = f"Failed to parse playlist URL '{url}'. Try updating pytube."
            logger.error(error_msg)
            results['failed'].append({'url': url, 'error': error_msg})
        except Exception as e:
            error_msg = f"Failed to download playlist {url}: {e}"
            logger.error(error_msg, exc_info=True)
            results['failed'].append({'url': url, 'error': str(e)})
        
        return results

    def _download_single_video(
        self,
        url: str,
        force: bool,
        index: int = 1,
        base_folder: Optional[Path] = None,
        is_playlist_item: bool = False
    ) -> Dict[str, any]:
        """Download a single video. Returns a result dict."""
        try:
            yt = YouTube(url, on_progress_callback=self._on_progress, on_complete_callback=self._on_complete)

            try:
                title = yt.title
                author = yt.author or "Unknown_Author"
            except Exception as e:
                logger.warning(f"Could not fetch title/author for {url}: {e}. Skipping.")
                return {'error': f'Could not fetch title/author: {e}'}

            # Create folder if not part of a playlist download
            folder = base_folder
            if not folder and not is_playlist_item:
                try:
                    folder = self._create_folder(title, author, url, force)
                except DownloadError as skip:
                    logger.info(str(skip))
                    return {'skipped': True, 'message': str(skip)}

            if not folder:
                logger.error(f"Could not determine save folder for {url}. Skipping.")
                return {'error': 'No save folder determined'}

            # Select stream with retry
            stream = self._select_stream(yt, url)

            if not stream:
                return {'error': f'No suitable stream found'}

            # Prepare filename
            sanitized_title = self._sanitize_filename(title)
            numbered_filename = f"{str(index).zfill(2)} - {sanitized_title}.mp4"
            full_file_path = folder / numbered_filename

            if not force and full_file_path.exists():
                logger.info(f"File '{numbered_filename}' already exists; skipping download.")
                return {'skipped': True, 'message': 'File already exists'}

            logger.info(f"Starting download: '{numbered_filename}' to '{folder}'")
            
            # Download with retry
            for attempt in range(self.retry_attempts):
                try:
                    stream.download(output_path=str(folder), filename=numbered_filename)
                    break
                except Exception as e:
                    if attempt == self.retry_attempts - 1:
                        raise e
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Download attempt {attempt + 1} failed. Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)

            self.download_captions(yt, folder, sanitized_title)
            return {'success': True}

        except VideoUnavailable:
            msg = f"Video unavailable: {url}"
            logger.warning(msg)
            return {'error': msg}
        except AgeRestrictedError:
            msg = f"Video is age-restricted: {url}"
            logger.warning(msg)
            return {'error': msg}
        except LiveStreamError:
            msg = f"Video is a live stream: {url}"
            logger.warning(msg)
            return {'error': msg}
        except RegexMatchError:
            msg = f"Failed to parse video URL '{url}'"
            logger.warning(msg)
            return {'error': msg}
        except DownloadError as skip:
            logger.info(str(skip))
            return {'skipped': True, 'message': str(skip)}
        except Exception as e:
            error_msg = f"Unexpected error downloading {url}: {e}"
            logger.error(error_msg, exc_info=True)
            return {'error': str(e)}

    def _select_stream(self, yt: YouTube, url: str):
        """Select the best stream for download with fallback logic."""
        try:
            # Try exact resolution first
            stream = yt.streams.filter(
                progressive=True, file_extension="mp4"
            ).order_by("resolution").desc().filter(
                res=f"{self.max_resolution}p"
            ).first()
            
            if stream:
                return stream
            
            # Try any resolution up to max
            stream = yt.streams.filter(
                progressive=True, file_extension="mp4"
            ).order_by("resolution").desc().first()
            
            if stream:
                logger.info(f"Using best available resolution instead of {self.max_resolution}p")
                return stream
            
            # Try DASH streams as last resort
            stream = yt.streams.filter(
                file_extension="mp4"
            ).order_by("resolution").desc().first()
            
            if stream:
                logger.warning("Using DASH stream (video only, no audio). Consider using yt-dlp instead.")
                return stream
            
            return None
        except Exception as e:
            logger.error(f"Error selecting stream for {url}: {e}")
            return None

    def download_captions(self, yt: YouTube, folder: Path, title: str):
        """Download captions for a video in requested languages."""
        try:
            if not yt.captions:
                logger.info(f"No captions available for '{title}'.")
                return

            for lang in self.subtitle_languages:
                caption = yt.captions.get_by_language_code(lang)
                if caption:
                    try:
                        srt = caption.generate_srt_captions()
                        sanitized_caption_title = self._sanitize_filename(title)
                        filename = folder / f"{sanitized_caption_title}.{lang}.srt"
                        with open(filename, "w", encoding="utf-8") as f:
                            f.write(srt)
                        logger.info(f"Saved subtitles: {filename}")
                    except Exception as caption_e:
                        logger.warning(f"Could not generate SRT for '{lang}' on '{title}': {caption_e}")
                else:
                    logger.debug(f"No captions found for language '{lang}' for '{title}'.")
        except Exception as e:
            logger.error(f"Error downloading captions for '{title}': {e}", exc_info=True)

    def _print_summary(self, results: Dict[str, list]):
        """Print a summary of download results."""
        success_count = len(results['success'])
        failed_count = len(results['failed'])
        skipped_count = len(results['skipped'])
        
        summary_box = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                JOB COMPLETE                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║   ✅ Success:   {success_count:<56} ║
║   ❌ Failed:    {failed_count:<56} ║
║   ⏭️ Skipped:   {skipped_count:<56} ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
        logger.info(summary_box)
        
        if results['failed']:
            logger.warning("Failed downloads:")
            for fail in results['failed']:
                logger.warning(f"  - {fail.get('url', 'Unknown')}: {fail.get('error', 'Unknown error')}")
