import re
import os
import time
import random
import copy
import logging
import json
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs

# Third-party imports
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import SRTFormatter

# Local imports (handle both module and script usage)
try:
    from .utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder
    from .vtt_to_srt import process_directory
except ImportError:
    from utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder
    from vtt_to_srt import process_directory

DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080
MAX_WORKERS = 3

def setup_logger():
    """تنظیمات پیشرفته لاگینگ"""
    logger = logging.getLogger("gorendir")
    if logger.hasHandlers():
        logger.handlers.clear()
        
    logger.setLevel(logging.INFO)
    
    # فرمت خروجی
    log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    
    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(log_formatter)
    logger.addHandler(console)
    
    # File handler
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
        log_file = self.save_directory / "_urls.txt"
        if log_file.exists():
            try:
                return set(log_file.read_text(encoding='utf-8').splitlines())
            except Exception as e:
                logger.warning(f"Could not read URL log: {e}")
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
                    'extract_flat': True  # فقط اطلاعات اولیه را بگیریم
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
                time.sleep(2 ** attempt)
    
    def _create_folder(self, info: dict, url: str, force: bool) -> Path:
        if not force and url in self.downloaded_urls:
            raise DownloadError(f"URL already downloaded: {url}")
        
        title = info.get("title", "Unknown_Title")[:100]
        uploader = info.get("uploader", "Unknown_Uploader")[:50]
        video_id = info.get("id", "")[:20]
        
        folder_name = sanitize_filename(f"{title}_{uploader}")
        folder = self.save_directory / "Download_video" / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        
        # ذخیره متادیتا
        try:
            (folder / "metadata.json").write_text(
                json.dumps(info, indent=2, ensure_ascii=False), encoding='utf-8'
            )
            (folder / "_url.txt").write_text(url, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not save metadata: {e}")
            
        self._save_url_to_log(url)
        return folder
    
    def _get_ydl_options(self, start: int, reverse: bool, write_subs: bool, folder: Path = None) -> dict:
        """تنظیمات بهینه‌شده yt-dlp با پشتیبانی از مسیر خروجی."""
        opts = {
            'format': f'bestvideo[height<={self.max_resolution}][ext=mp4]+bestaudio[ext=m4a]/best[height<={self.max_resolution}]/best',
            # استفاده از paths برای تعیین دقیق محل ذخیره
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
            
            # تنظیمات زیرنویس
            'writesubtitles': write_subs,
            'writeautomaticsub': write_subs,
            'subtitleslangs': self.subtitle_languages,
            'subtitlesformat': 'srt', # تلاش برای دانلود مستقیم srt
            
            'socket_timeout': self.timeout,
            'retries': 10,
            'no_check_certificate': True,
            'prefer_free_formats': True,
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
        yt_dlp_write_subs: bool = True, # پیش‌فرض روشن برای عملکرد بهتر
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
        
        # پردازش نهایی (تبدیل VTT و تمیزکاری)
        if not skip_download:
            try:
                logger.info("Running post-processing...")
                process_directory(self.save_directory) # تبدیل VTTهای دانلود شده توسط yt-dlp
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
        if not vid_id:
            return {'error': 'Invalid YouTube URL', 'success': False}
        
        canonical = f"https://www.youtube.com/watch?v={vid_id}"
        logger.info(f"Processing: {canonical}")
        
        try:
            info = self._get_video_info_with_retry(canonical)
            folder = self._create_folder(info, canonical, force_download)
            
            # ارسال folder به تنظیمات yt-dlp
            opts = self._get_ydl_options(start, reverse, write_subs, folder=folder)
            
            if skip_download:
                opts['simulate'] = True
                opts['skip_download'] = True
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                # حذف کش برای جلوگیری از مشکلات احتمالی
                try:
                    ydl.cache.remove()
                except:
                    pass
                playlist_info = ydl.extract_info(canonical, download=not skip_download) or {}
            
            # دانلود تکمیلی زیرنویس با API (اگر yt-dlp موفق نبود یا برای اطمینان بیشتر)
            if download_subs_api:
                entries = playlist_info.get("entries")
                if not entries:
                    entries = [playlist_info]
                    
                # آماده‌سازی لیست ویدیوها برای دانلود زیرنویس
                videos = self._process_playlist_entries(entries, start)
                self.download_subtitles(videos, folder, reverse, start)
            
            return {'success': True, 'folder': str(folder)}
            
        except DownloadError as e:
            if "already downloaded" in str(e):
                return {'skipped': True, 'message': str(e)}
            raise
        except Exception as e:
            return {'error': str(e), 'success': False}
    
    def _process_playlist_entries(self, entries, start):
        """لیست کردن ویدیوها بدون تغییر نام، چون yt-dlp نام‌گذاری را انجام داده است."""
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
        """دانلود زیرنویس با استفاده از API و ذخیره در پوشه صحیح."""
        if not video_info_list:
            return

        # اگر yt-dlp به صورت reverse دانلود کرده، ما هم لیست را معکوس می‌کنیم تا شماره‌گذاری درست باشد
        if reverse_download:
            video_info_list = list(reversed(video_info_list))
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for idx, video_info in enumerate(video_info_list):
                # محاسبه شماره فایل برای هماهنگی با نام‌گذاری yt-dlp
                # yt-dlp همیشه از start_index شروع به شمارش می‌کند (چه معمولی چه معکوس)
                current_number = start_index + idx
                
                future = executor.submit(
                    self._download_single_subtitle,
                    video_info,
                    current_number,
                    folder,
                    reverse_download
                )
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Subtitle thread error: {e}")

    def _download_single_subtitle(self, video_info, number, folder, reverse_download):
        video_id = video_info.get('id')
        title = video_info.get('title', 'Unknown')
        
        if not video_id: return
        
        # نام پایه فایل (بدون پسوند زبان)
        # 01_VideoTitle
        base_filename = sanitize_filename(f"{number:02d}_{title}")
        
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # لیست زبان‌های مورد نظر که هنوز دانلود نشده‌اند
            # (ما فرض می‌کنیم yt-dlp ممکن است دانلود کرده باشد، اما اینجا دوباره چک/دانلود می‌کنیم)
            langs_to_check = copy.deepcopy(self.subtitle_languages)
            
            for transcript in transcript_list:
                lang = transcript.language_code
                if lang in langs_to_check:
                    self._save_transcript(transcript, folder, base_filename, lang)
                    if lang in langs_to_check:
                        langs_to_check.remove(lang)
            
            # تلاش برای ترجمه خودکار برای زبان‌های باقی‌مانده
            if langs_to_check:
                try:
                    first_transcript = next(iter(transcript_list))
                    for lang in langs_to_check:
                        try:
                            translated = first_transcript.translate(lang)
                            self._save_transcript(translated, folder, base_filename, lang)
                        except Exception:
                            pass 
                except Exception:
                    pass

        except (TranscriptsDisabled, NoTranscriptFound):
            logger.warning(f"No subtitles available via API for: {title}")
        except Exception as e:
            logger.warning(f"Error fetching subtitles via API for {title}: {e}")

    def _save_transcript(self, transcript, folder, base_filename, lang):
        """ذخیره ترنسکریپت در فایل."""
        try:
            srt_content = SRTFormatter().format_transcript(transcript.fetch())
            filename = f"{base_filename}.{lang}.srt"
            file_path = folder / filename
            
            # اگر فایل وجود دارد و خالی نیست، بازنویسی نکن (مگر اینکه خیلی قدیمی باشد)
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
