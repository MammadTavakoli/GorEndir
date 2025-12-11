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

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import SRTFormatter

# ایمپورت‌های داخلی
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
    logger = logging.getLogger("gorendir")
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(console)
    return logger

logger = setup_logger()

class DownloadError(Exception): pass

class YouTubeDownloader:
    def __init__(self, save_directory, subtitle_languages=None, max_resolution=1080, max_workers=3, retry_attempts=3, timeout=30):
        self.save_directory = Path(save_directory).resolve()
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution
        self.max_workers = max_workers
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.downloaded_urls = set()

    def _extract_video_id(self, url: str) -> Optional[str]:
        if "v=" in url:
            return url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            return url.split("youtu.be/")[1].split("?")[0]
        return None

    def _create_folder(self, info, url, force):
        title = info.get("title", "Unknown")[:50]
        vid_id = info.get("id", "")
        folder_name = sanitize_filename(f"{vid_id}_{title}")
        folder = self.save_directory / "Download_video" / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def download_video(self, video_urls, playlist_start=1, skip_download=False, force_download=False, reverse_download=False, yt_dlp_write_subs=True, download_subtitles=True):
        if isinstance(video_urls, str): video_urls = [video_urls]
        
        for url in video_urls:
            try:
                vid_id = self._extract_video_id(url)
                if not vid_id: continue
                
                logger.info(f"Processing: {url}")
                
                # تنظیمات yt-dlp
                ydl_opts = {
                    'format': f'bestvideo[height<={self.max_resolution}]+bestaudio/best',
                    'outtmpl': '%(autonumber)02d_%(title)s.%(ext)s',
                    'ignoreerrors': True,
                    'skip_download': skip_download,
                    'writesubtitles': yt_dlp_write_subs,
                    'writeautomaticsub': yt_dlp_write_subs,
                    'subtitleslangs': self.subtitle_languages,
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=not skip_download)
                    folder = self._create_folder(info, url, force_download)
                    
                if download_subtitles:
                    video_info = {'id': vid_id, 'title': info.get('title', 'video')}
                    self._download_single_subtitle_advanced(video_info, 1, folder)
                    
            except Exception as e:
                logger.error(f"Error: {e}")

    # =========================================================================
    #  بخش اصلاح شده و هوشمند برای دانلود تمام زبان‌ها
    # =========================================================================
    def _download_single_subtitle_advanced(self, video_info, number, folder):
        video_id = video_info.get('id')
        title = video_info.get('title', 'Unknown')
        base_filename = sanitize_filename(f"{number:02d}_{title}")
        
        logger.info(f"🔍 Searching subtitles for: {title}")

        try:
            # دریافت لیست کامل زیرنویس‌ها
            transcript_list_obj = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # تبدیل به لیست برای پیمایش چندباره
            all_transcripts = list(transcript_list_obj)
            
            # تفکیک زیرنویس‌های دستی و ماشینی
            manual_transcripts = [t for t in all_transcripts if not t.is_generated]
            generated_transcripts = [t for t in all_transcripts if t.is_generated]
            
            wanted_langs = set(self.subtitle_languages)
            
            # تابع کمکی برای یافتن بهترین تطابق برای یک زبان خاص
            def find_match(lang, transcripts):
                # ۱. جستجوی تطابق دقیق (Exact Match)
                for t in transcripts:
                    if t.language_code == lang:
                        return t
                # ۲. جستجوی پیشوند (مثلاً درخواست 'fa' و پیدا کردن 'fa-IR')
                for t in transcripts:
                    if t.language_code.split('-')[0] == lang:
                        return t
                return None

            # فاز ۱: اولویت با زیرنویس‌های دستی (Manual)
            for lang in list(wanted_langs):
                match = find_match(lang, manual_transcripts)
                if match:
                    try:
                        self._save_sub(match, folder, base_filename, lang)
                        wanted_langs.remove(lang)
                        logger.info(f"   ✅ Found Manual subtitle for: {lang}")
                    except Exception as e:
                        logger.warning(f"   Error downloading manual {lang}: {e}")

            # فاز ۲: استفاده از زیرنویس‌های خودکار (Generated) برای زبان‌های باقی‌مانده
            for lang in list(wanted_langs):
                match = find_match(lang, generated_transcripts)
                if match:
                    try:
                        self._save_sub(match, folder, base_filename, lang)
                        wanted_langs.remove(lang)
                        logger.info(f"   ⚠️ Found Auto-generated subtitle for: {lang}")
                    except Exception as e:
                        logger.warning(f"   Error downloading generated {lang}: {e}")

            # فاز ۳: ترجمه ماشینی برای زبان‌های باقی‌مانده
            if wanted_langs:
                logger.info(f"🌍 Translating to missing languages: {wanted_langs}")
                try:
                    source_transcript = self._find_best_source_transcript(transcript_list_obj)
                    
                    if source_transcript:
                        for lang in list(wanted_langs):
                            try:
                                logger.info(f"   Creating translation: {source_transcript.language_code} -> {lang}")
                                translated_transcript = source_transcript.translate(lang)
                                self._save_sub(translated_transcript, folder, base_filename, lang)
                                wanted_langs.remove(lang)
                            except Exception as e:
                                logger.warning(f"   Translation failed for {lang}: {e}")
                    else:
                        logger.warning("   No suitable transcript found to translate from.")
                
                except Exception as e:
                    logger.error(f"Translation process error: {e}")

        except (TranscriptsDisabled, NoTranscriptFound):
            logger.warning("❌ No subtitles available for this video.")
        except Exception as e:
            logger.error(f"❌ Subtitle error: {e}")

    def _find_best_source_transcript(self, transcript_list):
        """بهترین زیرنویس را برای استفاده به عنوان منبع ترجمه پیدا می‌کند."""
        try:
            return transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
        except:
            try:
                return next(t for t in transcript_list if not t.is_generated)
            except:
                try:
                    return transcript_list.find_generated_transcript(['en', 'en-US'])
                except:
                    try:
                        return next(iter(transcript_list))
                    except:
                        return None

    def _save_sub(self, transcript, folder, base_name, lang_code):
        srt_content = SRTFormatter().format_transcript(transcript.fetch())
        filename = f"{base_name}.{lang_code}.srt"
        file_path = folder / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        # logger.info(f"Saved: {filename}")
