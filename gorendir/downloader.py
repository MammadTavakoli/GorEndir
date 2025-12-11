import re
import os
import time
import random
import copy
import logging
import json
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple
from urllib.parse import urlparse, parse_qs

# Third-party imports
import yt_dlp
try:
    from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
    from youtube_transcript_api.formatters import SRTFormatter
except ImportError:
    YouTubeTranscriptApi = None

# Local imports
try:
    from .utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder
    from .vtt_to_srt import process_directory
except ImportError:
    from utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder
    from vtt_to_srt import process_directory

DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080

def setup_logger():
    """تنظیمات پیشرفته لاگینگ"""
    logger = logging.getLogger("gorendir")
    if logger.hasHandlers():
        logger.handlers.clear()
        
    logger.setLevel(logging.INFO)
    log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    
    console = logging.StreamHandler()
    console.setFormatter(log_formatter)
    logger.addHandler(console)
    
    try:
        log_file = Path("gorendir.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='a')
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"))
        logger.addHandler(file_handler)
    except Exception:
        pass
    return logger

logger = setup_logger()

class DownloadError(Exception):
    pass

class YouTubeDownloader:
    """کلاس حرفه‌ای برای دانلود ویدیو و زیرنویس از یوتوب."""
    
    def __init__(
        self,
        save_directory: Union[str, Path],
        subtitle_languages: Optional[List[str]] = None,
        max_resolution: int = DEFAULT_MAX_RESOLUTION,
        retry_attempts: int = 3,
        timeout: int = 30,
        cookies_path: Optional[str] = None
    ):
        self.save_directory = Path(save_directory).resolve()
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution
        # حذف MAX_WORKERS: برای جلوگیری از 429 همیشه سریال دانلود می‌کنیم
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.cookies_path = cookies_path
        self.downloaded_urls = self._load_downloaded_urls()
        
        # بررسی نسخه کتابخانه
        if YouTubeTranscriptApi and not hasattr(YouTubeTranscriptApi, 'list_transcripts'):
            logger.critical("Your 'youtube-transcript-api' library is too old. Please run: pip install --upgrade youtube-transcript-api")
        
    def _load_downloaded_urls(self) -> set:
        log_file = self.save_directory / "_urls.txt"
        if log_file.exists():
            try:
                return set(log_file.read_text(encoding='utf-8').splitlines())
            except Exception:
                return set()
        return set()
    
    def _save_url_to_log(self, url: str):
        log_file = self.save_directory / "_urls.txt"
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(url + "\n")
            self.downloaded_urls.add(url)
        except Exception as e:
            logger.error(f"Failed to save URL to log: {e}")
    
    def _extract_video_id(self, url: str) -> Optional[str]:
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
        
        parsed = urlparse(url)
        if parsed.netloc in ['youtube.com', 'www.youtube.com']:
            query = parse_qs(parsed.query)
            if 'v' in query:
                return query['v'][0]
        return None
    
    def _get_video_info_with_retry(self, url: str) -> dict:
        for attempt in range(self.retry_attempts):
            try:
                ydl_opts = {
                    'ignoreerrors': True,
                    'quiet': True,
                    'no_warnings': True,
                    'socket_timeout': self.timeout,
                    'extract_flat': True,
                    'cookiefile': self.cookies_path
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
                    raise DownloadError(f"Failed after {self.retry_attempts} attempts: {e}")
                time.sleep(2 + attempt) # افزایش تاخیر در صورت خطا
    
    def _create_folder(self, info: dict, url: str, force: bool) -> Path:
        if not force and url in self.downloaded_urls:
            raise DownloadError(f"URL already downloaded: {url}")
        
        title = info.get("title", "Unknown_Title")[:100]
        uploader = info.get("uploader", "Unknown_Uploader")[:50]
        
        folder_name = sanitize_filename(f"{title}_{uploader}")
        folder = self.save_directory / "Download_video" / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        
        try:
            (folder / "metadata.json").write_text(
                json.dumps(info, indent=2, ensure_ascii=False), encoding='utf-8'
            )
            (folder / "_url.txt").write_text(url, encoding="utf-8")
        except Exception:
            pass
            
        self._save_url_to_log(url)
        return folder
    
    def _get_ydl_options(self, start: int, reverse: bool, write_subs: bool, folder: Path = None) -> dict:
        opts = {
            'format': f'bestvideo[height<={self.max_resolution}][ext=mp4]+bestaudio[ext=m4a]/best[height<={self.max_resolution}]/best',
            'paths': {'home': str(folder)} if folder else {},
            'outtmpl': '%(autonumber)02d_%(title)s.%(ext)s',
            'writedescription': True,
            'writeinfojson': True,
            'writethumbnail': True,
            'autonumber_start': start,
            'playliststart': start,
            'ignoreerrors': True,
            'no_overwrites': True,
            'continue_dl': True,
            
            'writesubtitles': write_subs,
            'writeautomaticsub': True,
            'subtitleslangs': self.subtitle_languages, 
            'subtitlesformat': 'srt', 
            
            'socket_timeout': self.timeout,
            'retries': 10,
            'no_check_certificate': True,
            'prefer_free_formats': True,
            'cookiefile': self.cookies_path,
            # کاهش سرعت دانلود برای جلوگیری از بلاک شدن در صورت نیاز
            # 'ratelimit': 5000000, 
        }
        
        if reverse:
            opts['playlistreverse'] = True
            
        return opts

    def download_video(
        self,
        video_urls: Union[str, List[str], Dict[str, int]],
        playlist_start: int = 1,
        skip_download: bool = False,
        force_download: bool = False,
        reverse_download: bool = False,
        yt_dlp_write_subs: bool = True,
        download_subtitles: bool = True
    ) -> Dict[str, any]:
        
        results = {'success': [], 'failed': [], 'skipped': []}
        tasks = self._parse_url_input(video_urls, playlist_start)
        
        if not tasks:
            logger.warning("No valid URLs provided")
            return results
        
        logger.info(f"Starting batch download of {len(tasks)} items...")
        
        for url, start in tasks:
            try:
                # تاخیر تصادفی بین ویدیوها برای جلوگیری از 429
                if len(results['success']) > 0 or len(results['failed']) > 0:
                    sleep_time = random.uniform(3, 7)
                    logger.info(f"Sleeping for {sleep_time:.1f}s to avoid rate limits...")
                    time.sleep(sleep_time)

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
        
        if not skip_download:
            try:
                logger.info("Running post-processing...")
                process_directory(self.save_directory)
                convert_all_srt_to_text(self.save_directory, '*******')
            except Exception as e:
                logger.error(f"Post-processing failed: {e}")
        
        self._print_summary(results)
        return results
    
    def _parse_url_input(self, video_urls, playlist_start):
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
    
    def _process_single_url(self, url, start, skip_download, force_download, reverse, write_subs, download_subs_api):
        vid_id = self._extract_video_id(url)
        if not vid_id and "list=" not in url:
             return {'error': 'Invalid YouTube URL', 'success': False}

        canonical = url if "list=" in url else f"https://www.youtube.com/watch?v={vid_id}"
        
        logger.info(f"Processing: {canonical}")
        
        try:
            info = self._get_video_info_with_retry(canonical)
            folder = self._create_folder(info, canonical, force_download)
            
            opts = self._get_ydl_options(start, reverse, write_subs, folder=folder)
            
            if skip_download:
                opts['simulate'] = True
                opts['skip_download'] = True
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                try: ydl.cache.remove()
                except: pass
                playlist_info = ydl.extract_info(canonical, download=not skip_download) or {}
            
            if download_subs_api:
                entries = playlist_info.get("entries")
                if not entries:
                    entries = [playlist_info]
                
                videos = self._process_playlist_entries(entries)
                self.download_subtitles(videos, folder, reverse, start)
            
            return {'success': True, 'folder': str(folder)}
            
        except DownloadError as e:
            if "already downloaded" in str(e):
                return {'skipped': True, 'message': str(e)}
            raise
        except Exception as e:
            return {'error': str(e), 'success': False}
    
    def _process_playlist_entries(self, entries):
        results = []
        for e in entries or []:
            if not e: continue
            results.append({
                'id': e.get("id"),
                'title': e.get("title", ""),
                'original_title': e.get("title", "")
            })
        return results

    def download_subtitles(self, video_info_list: List[Dict], folder: Path, reverse_download: bool, start_index: int):
        if not video_info_list: return
        if not YouTubeTranscriptApi:
             logger.error("youtube_transcript_api not installed. Cannot download extra subtitles.")
             return

        if reverse_download:
            video_info_list = list(reversed(video_info_list))
        
        # استفاده از حلقه ساده به جای ThreadPoolExecutor برای جلوگیری از 429
        for idx, video_info in enumerate(video_info_list):
            current_number = start_index + idx
            
            # تاخیر بین درخواست‌های زیرنویس
            if idx > 0:
                time.sleep(random.uniform(2, 5))
                
            self._download_single_subtitle(video_info, current_number, folder)

    def _download_single_subtitle(self, video_info, number, folder):
        video_id = video_info.get('id')
        title = video_info.get('title', 'Unknown')
        if not video_id: return
        
        base_filename = sanitize_filename(f"{number:02d}_{title}")
        
        try:
            # چک کردن وجود متد جدید
            if not hasattr(YouTubeTranscriptApi, 'list_transcripts'):
                 logger.error("Error: youtube-transcript-api version is too old. Cannot fetch auto-translations.")
                 return

            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, cookies=self.cookies_path)
            
            needed_langs = set(self.subtitle_languages)
            
            # --- گام ۱: دانلود مستقیم ---
            for transcript in transcript_list:
                lang_code = transcript.language_code
                is_match = False
                matched_req_lang = None
                
                for req_lang in needed_langs:
                    if lang_code == req_lang or lang_code.startswith(req_lang + '-'):
                        is_match = True
                        matched_req_lang = req_lang
                        break
                
                if is_match and matched_req_lang:
                    self._save_transcript(transcript, folder, base_filename, matched_req_lang)
                    if matched_req_lang in needed_langs:
                        needed_langs.remove(matched_req_lang)

            # --- گام ۲: ترجمه ---
            if needed_langs:
                source_transcript = None
                # تلاش برای پیدا کردن سورس مناسب
                try: source_transcript = transcript_list.find_manually_created_transcript(['en', 'en-US'])
                except: pass
                
                if not source_transcript:
                    try: source_transcript = transcript_list.find_generated_transcript(['en', 'en-US'])
                    except: pass
                
                if not source_transcript:
                    try: source_transcript = next(iter(transcript_list))
                    except: pass
                
                if source_transcript:
                    for req_lang in list(needed_langs):
                        try:
                            if source_transcript.is_translatable:
                                logger.info(f"Translating to {req_lang}...")
                                translated_transcript = source_transcript.translate(req_lang)
                                self._save_transcript(translated_transcript, folder, base_filename, req_lang)
                                time.sleep(1) # تاخیر کوچک برای هر ترجمه
                        except Exception as e:
                            logger.warning(f"Translation failed for {req_lang}: {e}")

        except Exception as e:
            if "Too Many Requests" in str(e):
                logger.error(f"Rate limit hit for subtitles on {title}. Waiting 60s...")
                time.sleep(60)
            elif "list_transcripts" in str(e):
                 logger.error("Library version error: Update youtube_transcript_api")
            else:
                logger.warning(f"Subtitle API error for {title}: {e}")

    def _save_transcript(self, transcript, folder, base_filename, lang):
        try:
            srt_content = SRTFormatter().format_transcript(transcript.fetch())
            suffix = ".auto" if transcript.is_generated else ""
            filename = f"{base_filename}.{lang}{suffix}.srt"
            file_path = folder / filename
            
            if not file_path.exists() or file_path.stat().st_size < 10:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                logger.info(f"API Saved subtitle: {filename}")
        except Exception as e:
            logger.debug(f"Failed to save transcript {lang}: {e}")

    def _print_summary(self, results):
        logger.info("\n" + "="*60)
        logger.info(f"Summary: Success={len(results['success'])}, Failed={len(results['failed'])}, Skipped={len(results['skipped'])}")
        if results['failed']:
            for f in results['failed']:
                logger.info(f"Fail: {f['url']} -> {f['error']}")
        logger.info("="*60)
