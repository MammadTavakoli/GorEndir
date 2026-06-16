import os
import time
import json
import random
import logging
import http.cookiejar
import requests
import re
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple
from urllib.parse import urlparse, parse_qs

# Suppress InsecureRequestWarning when verify_ssl=False
try:
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

# Third-party imports
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import SRTFormatter, TextFormatter

# Local imports fallback
try:
    from .utils import sanitize_filename, convert_all_srt_to_text
    from .vtt_to_srt import process_directory
except ImportError:
    def sanitize_filename(name: str) -> str:
        return "".join([c for c in name if c.isalpha() or c.isdigit() or c in " ._-"]).strip()[:200]
    def process_directory(path): pass
    def convert_all_srt_to_text(path, sep): pass

# Constants
DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080
LOG_FILE = "gorendir.log"
RATE_LIMIT_INITIAL_SLEEP = 45
RATE_LIMIT_MAX_RETRIES = 3

def setup_logger():
    """Configures a professional logger without duplicate printing."""
    logger = logging.getLogger("gorendir")
    logger.propagate = False 
    
    if logger.hasHandlers():
        logger.handlers.clear()
        
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    try:
        fh = logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a')
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"))
        logger.addHandler(fh)
    except Exception:
        pass
        
    return logger

logger = setup_logger()

class DownloadError(Exception):
    pass

class _YtdlpQuietLogger:
    """Custom logger for yt-dlp that suppresses [download] progress lines.
    
    yt-dlp writes download progress to its internal logger even when quiet=True.
    We intercept and drop those messages so only our tqdm progress bar is shown.
    """
    def debug(self, msg):
        pass  # Suppress [download] progress and other debug messages
    def warning(self, msg):
        # Only forward important warnings, skip routine download noise
        msg_str = str(msg).lower()
        if any(kw in msg_str for kw in ['error', 'fail', 'sign in', 'bot', 'age-restrict', 'unavailable']):
            logger.warning(f"[yt-dlp] {msg}")
    def error(self, msg):
        logger.error(f"[yt-dlp] {msg}")

class YouTubeDownloader:
    
    def __init__(
        self,
        save_directory: Union[str, Path],
        subtitle_languages: Optional[List[str]] = None,
        max_resolution: int = DEFAULT_MAX_RESOLUTION,
        retry_attempts: int = 3,
        timeout: int = 30,
        cookies_path: Optional[str] = None,
        verify_ssl: bool = True
    ):
        self.save_directory = Path(save_directory).resolve()
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.main_root = self.save_directory / "Download_video"
        self.main_root.mkdir(parents=True, exist_ok=True)

        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.cookies_path = cookies_path
        self.verify_ssl = verify_ssl

        # Base options for all yt-dlp calls
        # - remote_components: solve YouTube's JS n-challenge via EJS
        # - nocheckcertificate: disable SSL verification when verify_ssl=False
        #   (needed on local machines behind corporate proxies / antivirus SSL
        #    inspection that inject self-signed certificates into the chain)
        self._ydl_base_opts = {
            'cookiefile': self.cookies_path,
            'remote_components': ['ejs:github'],
            'nocheckcertificate': not self.verify_ssl,
        }

        if not self.verify_ssl:
            logger.warning(
                "⚠️ SSL certificate verification is DISABLED. "
                "This is insecure on public networks. Use only on trusted local "
                "machines where a corporate proxy or antivirus performs SSL inspection."
            )

        self.downloaded_urls = self._load_downloaded_urls()
        
        # Initialize API Session
        self.api_session = self._setup_api_session()
        self.ytt_api = YouTubeTranscriptApi(http_client=self.api_session)
        
        self._print_ascii_art()

    def _print_ascii_art(self):
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

    def _print_video_separator(self, title: str, url: str, index: int, total: int, file_prefix: str, playlist_name: str):
        safe_title = (title[:55] + '..') if len(title) > 55 else title
        safe_pl = (playlist_name[:55] + '..') if len(playlist_name) > 55 else playlist_name
        
        sep = r"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ PROCESSING VIDEO [{:>3}/{:>3}]                                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Collection: {:<66} ║
║ Title:      {:<66} ║
║ File Index: {:<66} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""".format(
            index, total,
            safe_pl,
            safe_title, 
            f"{file_prefix}_...", 
        )
        logger.info(sep)
    
    def _print_summary(self, results: Dict[str, list]):
        success_count = len(results['success'])
        failed_count = len(results['failed'])
        skipped_count = len(results['skipped'])
        
        summary_box = r"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                JOB COMPLETE                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║   ✅ Success:   {:<56} ║
║   ❌ Failed:    {:<56} ║
║   ⏭️ Skipped:   {:<56} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""".format(success_count, failed_count, skipped_count)
        logger.info(summary_box)
        
        # Log failed URLs details
        if results['failed']:
            logger.warning("Failed downloads:")
            for fail in results['failed']:
                logger.warning(f"  - {fail.get('url', 'Unknown')}: {fail.get('error', 'Unknown error')}")

    def _setup_api_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })

        # Honor verify_ssl for the youtube_transcript_api requests session too.
        # When False, requests will skip certificate verification (same effect
        # as yt-dlp's `nocheckcertificate`).
        if not self.verify_ssl:
            session.verify = False

        if self.cookies_path and os.path.exists(self.cookies_path):
            try:
                cookie_jar = http.cookiejar.MozillaCookieJar(self.cookies_path)
                cookie_jar.load(ignore_discard=True, ignore_expires=True)
                session.cookies = cookie_jar
                logger.info(f"Loaded cookies from {self.cookies_path}")
            except Exception as e:
                logger.warning(f"Failed to load cookies: {e}")
        return session

    def _load_downloaded_urls(self) -> set:
        log_file = self.save_directory / "_urls.txt"
        if log_file.exists():
            try:
                return set(log_file.read_text(encoding='utf-8').splitlines())
            except Exception:
                return set()
        return set()

    def _save_url_to_log(self, url: str):
        try:
            with open(self.save_directory / "_urls.txt", 'a', encoding='utf-8') as f:
                f.write(url + "\n")
            self.downloaded_urls.add(url)
        except Exception as e:
            logger.warning(f"Failed to save URL to log: {e}")

    def _extract_video_id(self, url: str) -> Optional[str]:
        patterns = [r'(?:youtube\.com\/watch\?v=)([^&#]+)', r'(?:youtu\.be\/)([^&#]+)']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match: return match.group(1)
        parsed = urlparse(url)
        if parsed.netloc in ['youtube.com', 'www.youtube.com', 'm.youtube.com']:
            query = parse_qs(parsed.query)
            if 'v' in query: return query['v'][0]
        return None

    def _save_metadata(self, info: dict, url: str, assigned_number: int, folder: Path):
        try:
            title = info.get("title", "Unknown")[:100]
            base_name = sanitize_filename(f"{assigned_number:02d}_{title}")
            json_path = folder / f"{base_name}.info.json"
            
            # Save only essential metadata, not the full info dict (can be very large)
            essential_info = {
                'id': info.get('id'),
                'title': info.get('title'),
                'description': info.get('description', '')[:500],
                'duration': info.get('duration'),
                'upload_date': info.get('upload_date'),
                'uploader': info.get('uploader'),
                'uploader_id': info.get('uploader_id'),
                'channel': info.get('channel'),
                'view_count': info.get('view_count'),
                'like_count': info.get('like_count'),
                'categories': info.get('categories'),
                'tags': info.get('tags', [])[:20],
                'language': info.get('language'),
                'webpage_url': info.get('webpage_url'),
            }
            json_path.write_text(json.dumps(essential_info, indent=2, ensure_ascii=False), encoding='utf-8')
            self._save_url_to_log(url)
        except Exception as e:
            logger.warning(f"Failed to save metadata: {e}")

    def _normalize_inputs(
        self, 
        video_urls: Union[str, List[str], Dict[str, int], List[Union[str, Dict[str, int]]]], 
        playlist_start: int = 1
    ) -> List[Tuple[str, int]]:
        """Normalize all input formats into a list of (url, start_num) tuples."""
        inputs = []
        
        if isinstance(video_urls, str):
            inputs.append((video_urls, playlist_start))
        elif isinstance(video_urls, dict):
            for u, s in video_urls.items():
                inputs.append((u, s if s > 0 else 1))
        elif isinstance(video_urls, list):
            for item in video_urls:
                if isinstance(item, dict):
                    for u, s in item.items():
                        inputs.append((u, s if s > 0 else 1))
                elif isinstance(item, str):
                    inputs.append((item, playlist_start))
                else:
                    logger.warning(f"Skipping unsupported item type in list: {type(item)}")
        else:
            logger.error(f"Unsupported video_urls format: {type(video_urls)}")
        
        return inputs

    def download_video(
        self,
        video_urls: Union[str, List[str], Dict[str, int], List[Union[str, Dict[str, int]]]],
        playlist_start: int = 1,
        skip_download: bool = False,
        force_download: bool = False,
        reverse_download: bool = False,
        yt_dlp_write_subs: bool = True,
        download_subtitles: bool = True,
        playlist_end: int = 0,
    ) -> Dict[str, list]:
        """
        Download videos from YouTube.
        
        Args:
            video_urls: URL(s) to download. Can be:
                - str: Single URL
                - Dict[str, int]: URL -> start number mapping  
                - List[Union[str, Dict[str, int]]]: Mixed list
            playlist_start: Default start number for playlists (1-indexed)
            skip_download: If True, only extract info without downloading
            force_download: If True, re-download even if already downloaded
            reverse_download: If True, reverse playlist order
            yt_dlp_write_subs: If True, yt-dlp writes subtitles
            download_subtitles: If True, download subtitles via API
            playlist_end: If > 0, stop downloading after this many videos
        """
        results: Dict[str, list] = {'success': [], 'failed': [], 'skipped': []}
        
        inputs = self._normalize_inputs(video_urls, playlist_start)
        
        if not inputs:
            logger.error("No valid inputs provided")
            return results

        for url, start_num in inputs:
            logger.info(f"Analyzing input: {url} (start from #{start_num})")
            
            try:
                with yt_dlp.YoutubeDL({**self._ydl_base_opts, 'extract_flat': True, 'quiet': True, 'logger': _YtdlpQuietLogger()}) as ydl:
                    info = ydl.extract_info(url, download=False)

                if info is None:
                    logger.error(f"Failed to extract info from {url}")
                    results['failed'].append({'url': url, 'error': 'No info extracted'})
                    continue

                tasks_to_run = []
                collection_name = "Unknown"

                # Determine Folder Name: Title + Uploader
                title = info.get('title', 'Unknown')
                uploader = info.get('uploader', 'Unknown_Uploader')
                folder_name = sanitize_filename(f"{title}_{uploader}")

                if 'entries' in info:
                    # PLAYLIST
                    collection_name = f"Playlist: {title}"
                    logger.info(f"Detected Playlist: {collection_name} ({info.get('playlist_count', '?')} videos)")
                    
                    target_folder = self.main_root / folder_name
                    target_folder.mkdir(parents=True, exist_ok=True)
                    
                    # PLAYLIST PROCESSING LOGIC:
                    # In normal mode:  V1→01, V2→02, ... V20→20
                    # In reverse mode: V20→01, V19→02, ... V1→20
                    # start_num always means "skip N videos from the start of DOWNLOAD order"
                    #   normal:  skip from beginning of playlist
                    #   reverse: skip from end of playlist (which is start of reversed order)
                    #
                    # Order of operations:
                    #   1) Filter None entries
                    #   2) Reverse (if reverse mode) — transforms download order
                    #   3) Skip by start_num (based on DOWNLOAD order, not original)
                    #   4) Apply playlist_end limit
                    #   5) Number from start_num based on download order
                    
                    entries = [e for e in info['entries'] if e is not None]
                    total_original = len(entries)
                    
                    # Step 2: Reverse FIRST so skip/numbering work on download order
                    if reverse_download:
                        entries.reverse()
                    
                    # Step 3: Skip entries before start_num (in DOWNLOAD order)
                    skip_count = max(0, start_num - 1)
                    entries = entries[skip_count:]
                    
                    # Step 4: Apply playlist_end limit
                    if playlist_end > 0:
                        entries = entries[:playlist_end]
                    
                    logger.info(f"Will process {len(entries)} videos (skipped first {skip_count} in download order, reverse={reverse_download})")
                    
                    # Step 5: Number from start_num based on download order
                    for i, entry in enumerate(entries):
                        v_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                        assigned_num = start_num + i
                        tasks_to_run.append((v_url, assigned_num))
                else:
                    # SINGLE VIDEO
                    collection_name = f"Single: {title}"
                    logger.info(f"Detected Single Video: {collection_name}")
                    
                    target_folder = self.main_root / folder_name
                    target_folder.mkdir(parents=True, exist_ok=True)
                    
                    tasks_to_run.append((url, start_num))
                
                # Only write _url.txt if target_folder exists and tasks exist
                if tasks_to_run and target_folder.exists():
                    with open(target_folder / "_url.txt", 'w', encoding='utf-8') as f:
                        f.write(url)
                    
                total_in_batch = len(tasks_to_run)
                
                if total_in_batch == 0:
                    logger.warning(f"No videos to process for {url} (start_num={start_num} may exceed playlist length)")
                    continue
                    
                # ── Playlist progress ──
                logger.info(f"📥 Starting playlist: {collection_name[:60]} ({total_in_batch} videos)")
                
                for idx, (v_url, assigned_num) in enumerate(tasks_to_run):
                    # Only sleep after a successful download to avoid wasting time on failures/skips
                    if results['success']: 
                        sleep_time = random.uniform(5, 8)
                        logger.info(f"⏳ Waiting {sleep_time:.1f}s...")
                        time.sleep(sleep_time)

                    res = self._process_single_task(
                        v_url, assigned_num, target_folder,
                        skip_download, force_download, yt_dlp_write_subs, download_subtitles,
                        idx + 1, total_in_batch, collection_name
                    )

                    if res.get('skipped'):
                        results['skipped'].append(v_url)
                        logger.info(f"⏭️  Skipped: {v_url}")
                    elif res.get('success'):
                        results['success'].append(v_url)
                    else:
                        results['failed'].append({'url': v_url, 'error': res.get('error', 'Unknown error')})
                        logger.info(f"❌ Failed: {res.get('error', 'Unknown error')[:60]}")

                if not skip_download and target_folder.exists():
                    process_directory(target_folder)

            except Exception as e:
                logger.error(f"Error processing input {url}: {e}")
                results['failed'].append({'url': url, 'error': str(e)})

        self._print_summary(results)
        return results

    def _detect_original_language(self, info: dict) -> Optional[str]:
        """Detect the original language of a video from metadata."""
        if not info:
            return None
        
        lang = info.get('language')
        if lang:
            return lang
        
        audio_languages = info.get('audio_languages')
        if audio_languages:
            if isinstance(audio_languages, list) and len(audio_languages) > 0:
                return audio_languages[0]
            elif isinstance(audio_languages, str):
                return audio_languages
        
        formats = info.get('formats', [])
        for fmt in formats:
            fmt_lang = fmt.get('language')
            if fmt_lang and fmt_lang not in ('und', None):
                return fmt_lang
        return None

    def _process_single_task(
        self,
        url: str,
        assigned_number: int,
        target_folder: Path,
        skip: bool,
        force: bool,
        write_subs: bool,
        dl_subs: bool,
        idx: int,
        total: int,
        playlist_name: str
    ) -> Dict[str, any]:
        vid_id = self._extract_video_id(url)
        canonical = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else url
        
        if not force and canonical in self.downloaded_urls:
            logger.info(f"Skipping (already downloaded): {canonical}")
            return {'skipped': True, 'message': 'Already downloaded'}

        # Get Title for UI display
        video_title = canonical
        try:
            with yt_dlp.YoutubeDL({**self._ydl_base_opts, 'quiet': True, 'extract_flat': True, 'logger': _YtdlpQuietLogger()}) as ydl:
                pre_info = ydl.extract_info(canonical, download=False)
                if pre_info:
                    video_title = pre_info.get('title', canonical)
        except Exception as e:
            logger.warning(f"Could not fetch title for {canonical}: {e}")

        self._print_video_separator(video_title, canonical, idx, total, f"{assigned_number:02d}", playlist_name)
        
        try:
            info = self._fetch_info(canonical)
            self._save_metadata(info, canonical, assigned_number, target_folder)
            
            detected_lang = self._detect_original_language(info)
            if detected_lang:
                logger.info(f"Detected Original Audio Language: {detected_lang}")
            
            ydl_opts = {
                **self._ydl_base_opts,
                'format': f'bestvideo[height<={self.max_resolution}][ext=mp4]+bestaudio[ext=m4a]/best[height<={self.max_resolution}]',
                'paths': {'home': str(target_folder)},
                'outtmpl': f'{assigned_number:02d}_%(title)s.%(ext)s', 
                'noplaylist': True,
                'ignoreerrors': True,
                'no_overwrites': True,
                'continue_dl': True,
                'quiet': True,
                'no_warnings': True,
                'noprogress': True,          # Suppress yt-dlp's own [download] progress
                'logger': _YtdlpQuietLogger(),  # Custom logger to suppress download noise
                'writesubtitles': write_subs,
                'writeautomaticsub': True,
                'subtitleslangs': self.subtitle_languages,
                'progress_hooks': [self._progress_hook],
            }
            
            if skip:
                ydl_opts.update({'simulate': True, 'skip_download': True})
            
            logger.info(f"  ⬇️  Downloading #{assigned_number:02d} — {video_title[:60]}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    ydl.cache.remove()
                except Exception:
                    pass
                playlist_info = ydl.extract_info(canonical, download=not skip) or {}
            
            if dl_subs and playlist_info:
                videos = [{
                    'id': playlist_info.get('id'), 
                    'title': playlist_info.get('title', 'Unknown'),
                    'detected_lang': detected_lang
                }]
                self._download_subtitles_api(videos, target_folder, assigned_number)
            
            logger.info(f"  ✅ Finished #{assigned_number:02d} — {video_title[:60]}")
            return {'success': True}
            
        except DownloadError as e:
            if "already downloaded" in str(e):
                return {'skipped': True, 'message': str(e)}
            return {'error': str(e)}
        except Exception as e:
            logger.error(f"Error processing {canonical}: {e}")
            return {'error': str(e)}

    def _progress_hook(self, d: dict):
        """yt-dlp progress hook — logs progress at key milestones only."""
        if d['status'] == 'downloading':
            # Only log at 25%, 50%, 75% milestones to reduce output noise
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            if total > 0:
                pct = int(downloaded / total * 100)
                milestone = getattr(self, '_last_milestone', 0)
                next_milestone = milestone + 25
                if pct >= next_milestone:
                    self._last_milestone = (pct // 25) * 25
                    speed = d.get('speed', 0)
                    speed_str = f"{speed/1024/1024:.1f}MB/s" if speed else "?"
                    logger.info(f"  ⬇️  {pct}% ({downloaded/1024/1024:.1f}/{total/1024/1024:.1f}MB) [{speed_str}]")
        elif d['status'] == 'finished':
            self._last_milestone = 0
            logger.info("  ✅ Download finished, processing...")

    def _fetch_info(self, url: str) -> dict:
        """Fetch video info with retry logic and exponential backoff."""
        for attempt in range(self.retry_attempts):
            try:
                opts = {
                    **self._ydl_base_opts,
                    'quiet': True,
                    'noplaylist': True,
                    'logger': _YtdlpQuietLogger(),
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                if not info:
                    raise DownloadError("No info extracted")
                return info
            except Exception as e:
                if attempt == self.retry_attempts - 1:
                    raise e
                sleep_time = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Fetch attempt {attempt + 1}/{self.retry_attempts} failed for {url}. Retrying in {sleep_time:.1f}s...")
                time.sleep(sleep_time)

    def _get_best_translation_source(self, transcript_list):
        """Find the best transcript to use as translation source."""
        try:
            return transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
        except Exception:
            pass
        try:
            return transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
        except Exception:
            pass
        for t in transcript_list:
            if t.is_translatable:
                return t
        return None

    def _download_subtitles_api(self, videos: List[Dict], folder: Path, assigned_number: int):
        """Download subtitles using the YouTube Transcript API with improved rate limiting."""
        for video in videos:
            vid_id = video.get('id')
            title = video.get('title')
            detected_lang = video.get('detected_lang')
            
            if not vid_id:
                logger.warning("No video ID provided, skipping subtitle download")
                continue
                
            base_filename = sanitize_filename(f"{assigned_number:02d}_{title}")
            
            try:
                transcript_list = self.ytt_api.list(vid_id)
                processed_langs = set()

                # 1. Download Original transcript
                try:
                    original_transcript = None
                    if detected_lang:
                        try:
                            original_transcript = transcript_list.find_transcript([detected_lang])
                        except Exception:
                            pass
                    if not original_transcript:
                        for t in transcript_list:
                            if not t.is_generated:
                                original_transcript = t
                                break
                    if not original_transcript:
                        original_transcript = next(iter(transcript_list), None)
                    
                    if original_transcript:
                        lang = original_transcript.language_code
                        logger.info(f"Downloading Original Subtitle ({lang})...")
                        self._save_transcript(original_transcript, folder, base_filename, lang)
                        processed_langs.add(lang)
                        time.sleep(random.uniform(1, 2))
                except Exception as e:
                    logger.warning(f"Failed to get original transcript: {e}")

                # 2. Direct Match for requested languages
                for req_lang in self.subtitle_languages:
                    if any(l == req_lang or l.startswith(req_lang + '-') for l in processed_langs):
                        continue
                    try:
                        transcript = transcript_list.find_transcript([req_lang])
                        self._save_transcript(transcript, folder, base_filename, req_lang)
                        processed_langs.add(req_lang)
                        time.sleep(random.uniform(1, 2))
                    except (NoTranscriptFound, ValueError):
                        pass
                    except Exception as e:
                        logger.warning(f"Error finding {req_lang} transcript: {e}")

                # 3. Translate missing languages
                missing_langs = []
                for req in self.subtitle_languages:
                    if not any(l == req or l.startswith(req + '-') for l in processed_langs):
                        missing_langs.append(req)

                if missing_langs:
                    source = self._get_best_translation_source(transcript_list)
                    if source:
                        for req_lang in missing_langs:
                            self._translate_with_retry(source, req_lang, folder, base_filename)

            except (TranscriptsDisabled, NoTranscriptFound):
                logger.warning(f"No transcripts available for: {title}")
            except Exception as e:
                logger.warning(f"Subtitle API Error on {title}: {e}")

    def _translate_with_retry(self, source, req_lang: str, folder: Path, base_filename: str):
        """Translate transcript with exponential backoff on rate limiting."""
        for attempt in range(RATE_LIMIT_MAX_RETRIES):
            try:
                logger.info(f"Translating {source.language_code} -> {req_lang}...")
                translated = source.translate(req_lang)
                self._save_transcript(translated, folder, base_filename, req_lang)
                time.sleep(random.uniform(2, 4))
                return
            except Exception as e:
                err = str(e).lower()
                if "blocking" in err or "too many requests" in err:
                    sleep_time = RATE_LIMIT_INITIAL_SLEEP * (2 ** attempt)
                    logger.warning(f"⚠️ Rate Limit Hit (attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES}). Sleeping {sleep_time}s...")
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"Translation failed for {req_lang}: {e}")
                    return
        
        logger.error(f"❌ Translation to {req_lang} failed after {RATE_LIMIT_MAX_RETRIES} retries")

    def _save_transcript(self, transcript, folder: Path, base_filename: str, lang_code: str):
        """Save transcript as both SRT and TXT formats."""
        try:
            fetched = transcript.fetch()
            suffix = ".auto" if transcript.is_generated else ""
            
            # Save SRT
            srt_content = SRTFormatter().format_transcript(fetched)
            srt_path = folder / f"{base_filename}.{lang_code}{suffix}.srt"
            if not srt_path.exists() or srt_path.stat().st_size < 10:
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                logger.info(f"Saved SRT: {srt_path.name}")
            else:
                logger.info(f"SRT already exists: {srt_path.name}")
                
            # Save TXT
            txt_content = TextFormatter().format_transcript(fetched)
            txt_path = folder / f"{base_filename}.{lang_code}{suffix}.txt"
            if not txt_path.exists() or txt_path.stat().st_size < 10:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(txt_content)
                logger.info(f"Saved TXT: {txt_path.name}")
                
        except Exception as e:
            logger.error(f"Failed to save transcript {lang_code}: {e}")
