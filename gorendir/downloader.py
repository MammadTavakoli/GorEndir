import os
import time
import json
import random
import logging
import http.cookiejar
import requests
import re
from pathlib import Path
from typing import List, Dict, Optional, Union
from urllib.parse import urlparse, parse_qs

# Third-party imports
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import SRTFormatter, TextFormatter

# Local imports fallback
try:
    from .utils import sanitize_filename, convert_all_srt_to_text
    from .vtt_to_srt import process_directory
except ImportError:
    def sanitize_filename(name):
        return "".join([c for c in name if c.isalpha() or c.isdigit() or c in " ._-"]).strip()[:200]
    def process_directory(path): pass
    def convert_all_srt_to_text(path, sep): pass

# Constants
DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080
LOG_FILE = "gorendir.log"

def setup_logger():
    """Configures a professional logger."""
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

class YouTubeDownloader:
    
    def __init__(
        self,
        save_directory: Union[str, Path],
        subtitle_languages: Optional[List[str]] = None,
        max_resolution: int = DEFAULT_MAX_RESOLUTION,
        retry_attempts: int = 3,
        cookies_path: Optional[str] = None
    ):
        self.save_directory = Path(save_directory).resolve()
        self.save_directory.mkdir(parents=True, exist_ok=True)
        self.main_root = self.save_directory / "Download_video"
        self.main_root.mkdir(parents=True, exist_ok=True)
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution
        self.retry_attempts = retry_attempts
        self.cookies_path = cookies_path if cookies_path and Path(cookies_path).exists() else None
        
        self.downloaded_urls = self._load_downloaded_urls()
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

    def _print_video_separator(self, title, url, index, total, file_prefix, playlist_name):
        safe_title = (title[:60] + '..') if len(title) > 60 else title
        safe_pl = (playlist_name[:60] + '..') if len(playlist_name) > 60 else playlist_name
        sep = r"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ PROCESSING VIDEO [{current}/{total}]                                       
╠══════════════════════════════════════════════════════════════════════════════╣
║ Collection: {:<66} ║
║ Title:      {:<66} ║
║ File Index: {:<66} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""".format(safe_pl, safe_title, f"{file_prefix}_...", current=index, total=total)
        logger.info(sep)
    
    def _print_summary(self, results):
        success_count = len(results['success'])
        failed_count = len(results['failed'])
        skipped_count = len(results['skipped'])
        summary_box = r"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                 JOB COMPLETE                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║   ✅ Success:   {:<56} ║
║   ❌ Failed:    {:<56} ║
║   ⏭️ Skipped:   {:<56} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""".format(success_count, failed_count, skipped_count)
        logger.info(summary_box)

    def _setup_api_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        if self.cookies_path:
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
        except Exception:
            pass
    
    def _save_collection_url(self, folder: Path, url: str):
        try:
            url_file = folder / "_url.txt"
            if not url_file.exists():
                url_file.write_text(url, encoding='utf-8')
                logger.info(f"Saved collection URL to: {url_file.name}")
        except Exception as e:
            logger.warning(f"Could not save collection URL: {e}")

    def _extract_video_id(self, url: str) -> Optional[str]:
        patterns = [r'(?:youtube\.com\/watch\?v=)([^&#]+)', r'(?:youtu\.be\/)([^&#]+)']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match: return match.group(1)
        parsed = urlparse(url)
        if 'youtube.com' in parsed.netloc:
            query = parse_qs(parsed.query)
            if 'v' in query: return query['v'][0]
        return None

    def _save_metadata(self, info: dict, url: str, assigned_number: int, folder: Path):
        try:
            title = info.get("title", "Unknown")[:100]
            base_name = sanitize_filename(f"{assigned_number:02d}_{title}")
            json_path = folder / f"{base_name}.info.json"
            json_path.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    def download_video(self, video_urls: Union[str, List[str], Dict[str, int]], playlist_start: int = 1, skip_download: bool = False, force_download: bool = False, reverse_download: bool = False, yt_dlp_write_subs: bool = True, download_subtitles: bool = True):
        results = {'success': [], 'failed': [], 'skipped': []}
        inputs = []
        if isinstance(video_urls, str): inputs.append((video_urls, playlist_start))
        elif isinstance(video_urls, list):
            for item in video_urls:
                if isinstance(item, dict):
                    for u, s in item.items(): inputs.append((u, s))
                else: inputs.append((item, playlist_start))
        
        for url, start_num in inputs:
            logger.info(f"Analyzing input: {url}")
            try:
                with yt_dlp.YoutubeDL({'extract_flat': True, 'quiet': True, 'cookiefile': self.cookies_path}) as ydl:
                    info = ydl.extract_info(url, download=False)
                
                tasks_to_run = []
                collection_name = "Unknown"
                title = info.get('title', 'Unknown')
                uploader = info.get('uploader', 'Unknown_Uploader')
                folder_name = sanitize_filename(f"{title}_{uploader}")
                target_folder = self.main_root / folder_name
                target_folder.mkdir(parents=True, exist_ok=True)
                
                self._save_collection_url(target_folder, url)

                if 'entries' in info and info['entries']:
                    collection_name = f"Playlist: {title}"
                    logger.info(f"Detected Playlist: {collection_name}")
                    entries = list(info['entries'])
                    if reverse_download: entries.reverse()
                    for i, entry in enumerate(entries):
                        if entry:
                            v_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                            tasks_to_run.append((v_url, start_num + i))
                else:
                    collection_name = f"Single: {title}"
                    logger.info(f"Detected Single Video: {collection_name}")
                    tasks_to_run.append((url, start_num))

                total_in_batch = len(tasks_to_run)
                for idx, (v_url, assigned_num) in enumerate(tasks_to_run):
                    if idx > 0:
                        sleep_time = random.uniform(5, 8)
                        logger.info(f"Waiting {sleep_time:.1f}s...")
                        time.sleep(sleep_time)
                    
                    res = self._process_single_task(v_url, assigned_num, target_folder, skip_download, force_download, yt_dlp_write_subs, download_subtitles, idx + 1, total_in_batch, collection_name)
                    if res.get('skipped'): results['skipped'].append(v_url)
                    elif res.get('success'): results['success'].append(v_url)
                    else: results['failed'].append({'url': v_url, 'error': res.get('error')})
                
                if not skip_download:
                    process_directory(target_folder)
            except Exception as e:
                logger.error(f"Error processing input {url}: {e}")
                results['failed'].append({'url': url, 'error': str(e)})
        
        self._print_summary(results)
        return results

    def _detect_original_language(self, info: dict) -> Optional[str]:
        if not info: return None
        lang = info.get('language') or info.get('audio_lang')
        if lang: return lang
        formats = info.get('formats', [])
        for f in formats:
            if f.get('language') and f.get('language') != 'und': return f.get('language')
        return None

    def _process_single_task(self, url, assigned_number, target_folder, skip, force, write_subs, dl_subs, idx, total, playlist_name):
        vid_id = self._extract_video_id(url)
        canonical = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else url
        
        if not force and canonical in self.downloaded_urls:
            return {'skipped': True, 'message': 'Already downloaded'}
        
        video_title = "Unknown Video"
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'cookiefile': self.cookies_path}) as ydl:
                pre_info = ydl.extract_info(canonical, download=False)
                video_title = pre_info.get('title', canonical)
        except Exception:
            video_title = canonical

        self._print_video_separator(video_title, canonical, idx, total, f"{assigned_number:02d}", playlist_name)
        
        try:
            ydl_opts = {
                'format': f'bestvideo[height<={self.max_resolution}][ext=mp4]+bestaudio[ext=m4a]/best',
                'paths': {'home': str(target_folder)},
                'outtmpl': f'{assigned_number:02d}_%(title)s.%(ext)s', 
                'noplaylist': True,
                'ignoreerrors': False,
                'no_overwrites': not force,
                'continue_dl': True,
                'quiet': True,
                'no_warnings': True,
                'cookiefile': self.cookies_path,
                'writesubtitles': write_subs,
                'writeautomaticsub': True,
                'subtitleslangs': self.subtitle_languages,
            }
            if skip:
                ydl_opts.update({'simulate': True, 'skip_download': True})

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(canonical, download=not skip)
                if not info: raise DownloadError("yt-dlp failed to return info dictionary.")

            self._save_metadata(info, canonical, assigned_number, target_folder)
            
            detected_lang = self._detect_original_language(info)
            if detected_lang: logger.info(f"Detected Original Audio Language: {detected_lang}")
                
            if dl_subs:
                videos = [{'id': info.get('id'), 'title': info.get('title', 'Unknown'), 'detected_lang': detected_lang}]
                self._download_subtitles_api(videos, target_folder, assigned_number)
            
            self._save_url_to_log(canonical)
            return {'success': True}

        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download failed for '{video_title}': {e}")
            return {'error': str(e), 'success': False}
        except Exception as e:
            logger.error(f"An unexpected error occurred for '{url}': {e}")
            return {'error': str(e), 'success': False}

    def _get_best_translation_source(self, transcript_list):
        try:
            return transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
        except:
            pass
        try:
            return transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
        except:
            pass
        for t in transcript_list:
            if t.is_translatable: return t
        return None

    def _download_subtitles_api(self, videos: List[Dict], folder: Path, assigned_number: int):
        for video in videos:
            vid_id, title, detected_lang = video.get('id'), video.get('title'), video.get('detected_lang')
            if not vid_id: continue
            
            base_filename = sanitize_filename(f"{assigned_number:02d}_{title}")
            try:
                transcript_list = self.ytt_api.list_transcripts(vid_id)
                processed_langs = set()

                try:
                    original_transcript = transcript_list.find_transcript([detected_lang]) if detected_lang else next(iter(transcript_list))
                    lang = original_transcript.language_code
                    logger.info(f"Downloading Original Subtitle ({lang})...")
                    self._save_transcript(original_transcript, folder, base_filename, lang)
                    processed_langs.add(lang.split('-')[0])
                    time.sleep(1)
                except Exception:
                    pass

                for req_lang in self.subtitle_languages:
                    if req_lang in processed_langs: continue
                    try:
                        transcript = transcript_list.find_transcript([req_lang])
                        self._save_transcript(transcript, folder, base_filename, req_lang)
                        processed_langs.add(req_lang)
                        time.sleep(random.uniform(1, 2))
                    except (NoTranscriptFound, ValueError):
                        pass

                missing_langs = [lang for lang in self.subtitle_languages if lang not in processed_langs]
                if missing_langs:
                    source = self._get_best_translation_source(transcript_list)
                    if source:
                        for req_lang in missing_langs:
                            try:
                                logger.info(f"Translating {source.language_code} -> {req_lang}...")
                                translated = source.translate(req_lang)
                                self._save_transcript(translated, folder, base_filename, req_lang)
                                time.sleep(random.uniform(2, 4))
                            except Exception as e:
                                if "blocking" in str(e).lower() or "too many requests" in str(e).lower():
                                    logger.warning("⚠️ Rate Limit Hit. Sleeping 45s...")
                                    time.sleep(45)
                                else:
                                    logger.warning(f"Translation failed for {req_lang}")
            except (TranscriptsDisabled, NoTranscriptFound):
                logger.warning(f"No transcripts available for: {title}")
            except Exception as e:
                logger.warning(f"Subtitle API Error on {title}: {e}")

    def _save_transcript(self, transcript, folder, base_filename, lang_code):
        try:
            fetched = transcript.fetch()
            suffix = ".auto" if transcript.is_generated else ""
            
            srt_content = SRTFormatter().format_transcript(fetched)
            srt_path = folder / f"{base_filename}.{lang_code}{suffix}.srt"
            if not srt_path.exists() or srt_path.stat().st_size < 10:
                with open(srt_path, "w", encoding="utf-8") as f: f.write(srt_content)
                logger.info(f"Saved SRT: {srt_path.name}")
                
            txt_content = TextFormatter().format_transcript(fetched)
            txt_path = folder / f"{base_filename}.{lang_code}{suffix}.txt"
            if not txt_path.exists() or txt_path.stat().st_size < 10:
                with open(txt_path, "w", encoding="utf-8") as f: f.write(txt_content)
                logger.info(f"Saved TXT: {txt_path.name}")
        except Exception as e:
            logger.error(f"Failed to save {lang_code}: {e}")

# if __name__ == '__main__':
#     DOWNLOAD_PATH = "."
#     COOKIES_FILE = None
    
#     urls_to_process = [
#         "https://www.youtube.com/watch?v=V3JQjXra7D0",
#         "https://www.youtube.com/watch?v=5JoSryGwRy0",
#     ]
    
#     downloader = YouTubeDownloader(
#         save_directory=DOWNLOAD_PATH,
#         cookies_path=COOKIES_FILE
#     )
    
#     downloader.download_video(urls_to_process)
