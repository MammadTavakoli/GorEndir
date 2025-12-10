import re
import os
import time
import random
import copy
import logging
import yt_dlp
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple
from requests.exceptions import HTTPError
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import SRTFormatter
from .utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder
from .vtt_to_srt import process_directory
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs
import json

DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080
MAX_WORKERS = 3  # برای دانلود همزمان چند ویدیو

# تنظیمات پیشرفته logging
def setup_logger():
    """تنظیم پیشرفته logger"""
    for h in logging.root.handlers[:]:
        logging.root.removeHandler(h)
    
    logger = logging.getLogger("gorendir")
    logger.setLevel(logging.INFO)
    
    # جلوگیری از duplicate handlers
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        "%H:%M:%S"
    )
    console.setFormatter(console_format)
    logger.addHandler(console)
    
    # File handler
    log_file = Path("gorendir.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logger()

class DownloadError(Exception):
    """Custom exception for download failures."""
    pass

class RateLimitExceeded(Exception):
    """Exception for rate limiting."""
    pass

class YouTubeDownloader:
    """A professional class to download YouTube videos and their subtitles."""
    
    def __init__(
        self,
        save_directory: Union[str, Path],
        subtitle_languages: Optional[List[str]] = None,
        max_resolution: int = DEFAULT_MAX_RESOLUTION,
        max_workers: int = MAX_WORKERS,
        retry_attempts: int = 3,
        timeout: int = 30
    ):
        self.save_directory = Path(save_directory).resolve()
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution
        self.max_workers = max_workers
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.downloaded_urls = self._load_downloaded_urls()
        
    def _load_downloaded_urls(self) -> set:
        """Load already downloaded URLs from log file."""
        log_file = self.save_directory / "_urls.txt"
        if log_file.exists():
            try:
                return set(log_file.read_text(encoding='utf-8').splitlines())
            except Exception as e:
                logger.warning(f"Could not read URL log: {e}")
        return set()
    
    def _save_url_to_log(self, url: str):
        """Save URL to log file."""
        log_file = self.save_directory / "_urls.txt"
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(url + "\n")
            self.downloaded_urls.add(url)
        except Exception as e:
            logger.error(f"Failed to save URL to log: {e}")
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats."""
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([^&#]+)',
            r'(?:youtu\.be\/)([^&#]+)',
            r'(?:youtube\.com\/embed\/)([^&#]+)',
            r'(?:youtube\.com\/v\/)([^?#]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # Try to extract from query parameters
        parsed = urlparse(url)
        if parsed.netloc in ['youtube.com', 'www.youtube.com']:
            query_params = parse_qs(parsed.query)
            if 'v' in query_params:
                return query_params['v'][0]
        
        return None
    
    def _get_video_info_with_retry(self, url: str) -> dict:
        """Retrieve video info with retry mechanism."""
        for attempt in range(self.retry_attempts):
            try:
                ydl_opts = {
                    'ignoreerrors': True,
                    'quiet': True,
                    'no_warnings': True,
                    'socket_timeout': self.timeout,
                    'extract_flat': False
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                
                if not info:
                    raise DownloadError(f"Could not extract info from: {url}")
                
                if info.get("live_status") == "is_upcoming":
                    raise DownloadError(f"Video is upcoming/live: {url}")
                
                return info
                
            except Exception as e:
                if attempt == self.retry_attempts - 1:
                    raise DownloadError(f"Failed to get video info after {self.retry_attempts} attempts: {e}")
                
                wait_time = (2 ** attempt) + random.random()
                logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time:.1f}s: {e}")
                time.sleep(wait_time)
    
    def _create_folder(self, info: dict, url: str, force: bool) -> Path:
        """Create per-video folder with improved naming."""
        if not force and url in self.downloaded_urls:
            raise DownloadError(f"URL already downloaded: {url}")
        
        title = info.get("title", "Unknown_Title")[:100]  # Limit title length
        uploader = info.get("uploader", "Unknown_Uploader")[:50]
        video_id = info.get("id", "")[:20]
        
        # Create safe folder name
        folder_name = sanitize_filename(f"{video_id}_{title}_{uploader}")
        folder = self.save_directory / "Download_video" / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        
        # Save metadata
        self._save_metadata(info, folder)
        self._save_url_to_log(url)
        
        (folder / "_url.txt").write_text(url, encoding="utf-8")
        
        logger.info(f"Created folder: {folder}")
        return folder
    
    def _save_metadata(self, info: dict, folder: Path):
        """Save video metadata as JSON."""
        metadata = {
            'title': info.get('title'),
            'uploader': info.get('uploader'),
            'upload_date': info.get('upload_date'),
            'duration': info.get('duration'),
            'view_count': info.get('view_count'),
            'like_count': info.get('like_count'),
            'description': info.get('description'),
            'categories': info.get('categories'),
            'tags': info.get('tags'),
            'webpage_url': info.get('webpage_url')
        }
        
        try:
            metadata_file = folder / "metadata.json"
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not save metadata: {e}")
    
    def _get_ydl_options(self, start: int, reverse: bool, write_subs: bool) -> dict:
        """Get optimized yt-dlp options."""
        opts = {
            # Quality selection
            'format': f'bestvideo[height<={self.max_resolution}][ext=mp4]+bestaudio[ext=m4a]/best[height<={self.max_resolution}]/best',
            'outtmpl': {
                'default': '%(autonumber)02d_%(title)s.%(ext)s',
                'thumbnail': '%(autonumber)02d_%(title)s.%(ext)s'
            },
            
            # Output configuration
            'writedescription': True,
            'writeinfojson': True,
            'writethumbnail': True,
            
            # Playlist handling
            'autonumber_start': start,
            'playliststart': start,
            'ignoreerrors': True,
            'no_overwrites': True,
            'continue_dl': True,
            
            # Subtitle configuration
            'writesubtitles': write_subs,
            'writeautomaticsub': write_subs,
            'subtitleslangs': self.subtitle_languages,
            'subtitlesformat': 'srt',
            
            # Network settings
            'socket_timeout': self.timeout,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            
            # Progress hooks
            'progress_hooks': [self._progress_hook],
            
            # Other optimizations
            'no_part': True,
            'no_check_certificate': True,
            'prefer_free_formats': True,
            'keepvideo': False,
        }
        
        if reverse:
            opts['playlistreverse'] = True
            
        return opts
    
    def _progress_hook(self, d):
        """Progress hook for yt-dlp."""
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            
            if total:
                percent = (downloaded / total) * 100
                speed = d.get('speed', 0)
                eta = d.get('eta', 0)
                
                logger.info(f"Downloading: {percent:.1f}% | Speed: {self._format_bytes(speed)}/s | ETA: {eta}s")
        elif d['status'] == 'finished':
            logger.info("Download completed, processing...")
    
    @staticmethod
    def _format_bytes(size):
        """Format bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"
    
    def download_video(
        self,
        video_urls: Union[str, List[str], Dict[str, int]],
        playlist_start: int = 1,
        skip_download: bool = False,
        force_download: bool = False,
        reverse_download: bool = False,
        yt_dlp_write_subs: bool = False,
        download_subtitles: bool = True
    ) -> Dict[str, any]:
        """Download videos with enhanced error handling and reporting."""
        
        results = {
            'success': [],
            'failed': [],
            'skipped': []
        }
        
        # Parse input URLs
        tasks = self._parse_url_input(video_urls, playlist_start)
        
        if not tasks:
            logger.warning("No valid URLs provided")
            return results
        
        self._print_ascii_art()
        
        # Process tasks
        for url, start in tasks:
            try:
                result = self._process_single_url(
                    url, start, skip_download, force_download,
                    reverse_download, yt_dlp_write_subs, download_subtitles
                )
                
                if result.get('skipped'):
                    results['skipped'].append(url)
                elif result.get('success'):
                    results['success'].append(url)
                else:
                    results['failed'].append({'url': url, 'error': result.get('error')})
                    
            except Exception as e:
                logger.error(f"Critical error processing {url}: {e}")
                results['failed'].append({'url': url, 'error': str(e)})
        
        # Post-processing
        if not skip_download:
            try:
                process_directory(self.save_directory)
                convert_all_srt_to_text(self.save_directory, '*******')
            except Exception as e:
                logger.error(f"Post-processing failed: {e}")
        
        # Summary
        self._print_summary(results)
        return results
    
    def _parse_url_input(self, video_urls, playlist_start):
        """Parse various URL input formats."""
        tasks = []
        
        if isinstance(video_urls, dict):
            for url, start in video_urls.items():
                tasks.append((url, start))
        elif isinstance(video_urls, str):
            tasks.append((video_urls, playlist_start))
        elif isinstance(video_urls, list):
            for item in video_urls:
                if isinstance(item, dict):
                    for url, start in item.items():
                        tasks.append((url, start))
                else:
                    tasks.append((item, playlist_start))
        
        return tasks
    
    def _process_single_url(
        self, url, start, skip_download, force_download,
        reverse_download, yt_dlp_write_subs, download_subtitles
    ):
        """Process a single URL."""
        vid_id = self._extract_video_id(url)
        if not vid_id:
            return {'error': 'Invalid YouTube URL', 'success': False}
        
        canonical = f"https://www.youtube.com/watch?v={vid_id}"
        logger.info(f"Processing: {canonical}")
        
        try:
            info = self._get_video_info_with_retry(canonical)
            folder = self._create_folder(info, canonical, force_download)
            
            opts = self._get_ydl_options(start, reverse_download, yt_dlp_write_subs)
            if skip_download:
                opts['simulate'] = True
                opts['skip_download'] = True
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                try:
                    ydl.cache.remove()
                except:
                    pass
                
                playlist_info = ydl.extract_info(canonical, download=not skip_download) or {}
            
            # Process subtitles
            if download_subtitles:
                entries = playlist_info.get("entries") or [playlist_info]
                videos = self._process_playlist_entries(entries, start, reverse_download)
                self.download_subtitles(videos, reverse_download)
            
            return {'success': True, 'folder': str(folder)}
            
        except DownloadError as e:
            if "already downloaded" in str(e):
                return {'skipped': True, 'message': str(e)}
            raise
        except Exception as e:
            return {'error': str(e), 'success': False}
    
    def _process_playlist_entries(self, entries, start, reverse_download):
        """Process playlist entries."""
        results = []
        cnt = start
        
        for e in entries or []:
            if not e:
                continue
            
            vid = e.get("id")
            name = sanitize_filename(e.get("title", ""))
            results.append({
                'id': vid,
                'filename': f"{cnt:02d}_{name}",
                'title': e.get("title", "")
            })
            cnt += 1
        
        return results
    
    def download_subtitles(self, video_info_list: List[Dict[str, str]], reverse_download: bool = False):
        """Download subtitles with improved error handling and parallel processing."""
        
        if not video_info_list:
            logger.warning("No videos to download subtitles for")
            return
        
        if reverse_download:
            video_info_list = list(reversed(video_info_list))
        
        total_videos = len(video_info_list)
        
        # Use ThreadPoolExecutor for parallel subtitle downloading
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            
            for idx, video_info in enumerate(video_info_list, start=1):
                future = executor.submit(
                    self._download_single_subtitle,
                    video_info,
                    idx,
                    total_videos,
                    reverse_download
                )
                futures.append(future)
            
            # Wait for all futures to complete
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=60)
                    if result.get('success'):
                        logger.info(f"Subtitle download completed: {result['filename']}")
                    else:
                        logger.warning(f"Subtitle download failed: {result.get('error')}")
                except Exception as e:
                    logger.error(f"Subtitle download thread failed: {e}")
    
    def _download_single_subtitle(self, video_info, idx, total_videos, reverse_download):
        """Download subtitles for a single video."""
        video_id = video_info.get('id')
        filename = sanitize_filename(video_info.get('filename'))
        title = video_info.get('title', 'Unknown')
        
        if not video_id:
            return {'success': False, 'error': 'No video ID', 'filename': filename}
        
        try:
            # Get available transcripts
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Download available languages
            downloaded_langs = set()
            sublangs = copy.deepcopy(self.subtitle_languages)
            
            for transcript in transcript_list:
                lang = transcript.language_code
                
                if lang in sublangs:
                    try:
                        srt = transcript.fetch()
                        formatter = SRTFormatter()
                        srt_content = formatter.format_transcript(srt)
                        
                        # Calculate correct index for reverse download
                        numbered_idx = total_videos - idx + 1 if reverse_download else idx
                        srt_filename = f"{numbered_idx:02d}_{title}.{lang}.srt"
                        srt_filename = sanitize_filename(srt_filename)
                        
                        with open(srt_filename, "w", encoding="utf-8") as f:
                            f.write(srt_content)
                        
                        downloaded_langs.add(lang)
                        sublangs.remove(lang)
                        logger.info(f"Downloaded {lang} subtitles for: {title}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to download {lang} subtitles for {title}: {e}")
            
            # Try to get first transcript for translation
            if sublangs:  # If there are still languages we need
                first_transcript = next((t for t in transcript_list), None)
                
                if first_transcript:
                    for lang in sublangs:
                        try:
                            translated = first_transcript.translate(lang)
                            srt = translated.fetch()
                            formatter = SRTFormatter()
                            srt_content = formatter.format_transcript(srt)
                            
                            numbered_idx = total_videos - idx + 1 if reverse_download else idx
                            srt_filename = f"{numbered_idx:02d}_{title}.{lang}.srt"
                            srt_filename = sanitize_filename(srt_filename)
                            
                            with open(srt_filename, "w", encoding="utf-8") as f:
                                f.write(srt_content)
                            
                            logger.info(f"Downloaded translated {lang} subtitles for: {title}")
                            
                        except Exception as e:
                            logger.debug(f"Could not translate to {lang} for {title}: {e}")
            
            return {'success': True, 'filename': filename, 'downloaded': downloaded_langs}
            
        except TranscriptsDisabled:
            logger.warning(f"Subtitles disabled for: {title}")
            return {'success': False, 'error': 'Subtitles disabled', 'filename': filename}
        except NoTranscriptFound:
            logger.warning(f"No subtitles found for: {title}")
            return {'success': False, 'error': 'No subtitles found', 'filename': filename}
        except Exception as e:
            logger.error(f"Error downloading subtitles for {title}: {e}")
            return {'success': False, 'error': str(e), 'filename': filename}
    
    def _print_ascii_art(self):
        """Display ASCII art."""
        ascii_art = r"""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║   ██████╗  ██████╗ ██████╗ ███████╗███╗   ██╗██████╗ ██╗██████╗   ║
║  ██╔═══██╗██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║██╔══██╗  ║
║  ██║   ██║██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║  ██║██║██████╔╝  ║
║  ██║   ██║██║   ██║██╔══██╗██╔══╝  ██║╚██╗██║██║  ██║██║██╔══██╗  ║
║  ╚██████╔╝╚██████╔╝██║  ██║███████╗██║ ╚████║██████╔╝██║██║  ██║  ║
║   ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚═╝╚═╝  ╚═╝  ║
║                                                                   ║
║  Welcome to GÖRENDİR - Professional YouTube Downloader v2.0      ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
"""
        logger.info("\n" + ascii_art)
    
    def _print_summary(self, results):
        """Print download summary."""
        logger.info("\n" + "="*60)
        logger.info("DOWNLOAD SUMMARY:")
        logger.info(f"  Success: {len(results['success'])}")
        logger.info(f"  Failed:  {len(results['failed'])}")
        logger.info(f"  Skipped: {len(results['skipped'])}")
        
        if results['failed']:
            logger.info("\nFailed URLs:")
            for fail in results['failed']:
                logger.info(f"  - {fail['url']}: {fail.get('error', 'Unknown error')}")
        logger.info("="*60)