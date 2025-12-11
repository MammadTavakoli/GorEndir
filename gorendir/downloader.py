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
        return "".join([c for c in name if c.isalpha() or c.isdigit() or c in " ._-"]).strip()
    def process_directory(path): pass
    def convert_all_srt_to_text(path, sep): pass

# Constants
DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080
LOG_FILE = "gorendir.log"

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

class YouTubeDownloader:
    
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
        self.main_root = self.save_directory / "Download_video"
        self.main_root.mkdir(parents=True, exist_ok=True)

        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.cookies_path = cookies_path
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

    def _print_video_separator(self, title, url, index, total, file_prefix, playlist_name):
        safe_title = (title[:60] + '..') if len(title) > 60 else title
        safe_pl = (playlist_name[:60] + '..') if len(playlist_name) > 60 else playlist_name
        
        sep = r"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ PROCESSING VIDEO [{current}/{total}]                                                 
╠══════════════════════════════════════════════════════════════════════════════╣
║ Playlist:   {:<66} ║
║ Title:      {:<66} ║
║ File Index: {:<66} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""".format(
            safe_pl,
            safe_title, 
            f"{file_prefix}_...", 
            current=index, 
            total=total
        )
        logger.info(sep)
    
    def _print_summary(self, results):
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

    def _setup_api_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })

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
        except Exception:
            pass

    def _extract_video_id(self, url: str) -> Optional[str]:
        patterns = [r'(?:youtube\.com\/watch\?v=)([^&#]+)', r'(?:youtu\.be\/)([^&#]+)']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match: return match.group(1)
        parsed = urlparse(url)
        if parsed.netloc in ['youtube.com', 'www.youtube.com']:
            query = parse_qs(parsed.query)
            if 'v' in query: return query['v'][0]
        return None

    def _save_metadata(self, info: dict, url: str, assigned_number: int, folder: Path):
        try:
            title = info.get("title", "Unknown")[:100]
            base_name = sanitize_filename(f"{assigned_number:02d}_{title}")
            json_path = folder / f"{base_name}.info.json"
            json_path.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding='utf-8')
            self._save_url_to_log(url)
        except Exception: pass

    def download_video(
        self,
        video_urls: Union[str, List[str], Dict[str, int]],
        playlist_start: int = 1,
        skip_download: bool = False,
        force_download: bool = False,
        reverse_download: bool = False,
        yt_dlp_write_subs: bool = True,
        download_subtitles: bool = True
    ):
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
                playlist_title = "Unknown"

                if 'entries' in info:
                    # PLAYLIST
                    playlist_title = info.get('title', 'Unknown_Playlist')
                    logger.info(f"Detected Playlist: {playlist_title}")
                    
                    target_folder = self.main_root / sanitize_filename(playlist_title)
                    target_folder.mkdir(parents=True, exist_ok=True)
                    
                    entries = list(info['entries'])
                    if reverse_download: entries.reverse()
                        
                    for i, entry in enumerate(entries):
                        if entry:
                            v_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                            tasks_to_run.append((v_url, start_num + i))
                else:
                    # SINGLE VIDEO
                    video_title = info.get('title', 'Single_Video')
                    playlist_title = f"Single: {video_title}"
                    logger.info(f"Detected Single Video: {video_title}")
                    
                    # Create Folder named after the video
                    target_folder = self.main_root / sanitize_filename(video_title)
                    target_folder.mkdir(parents=True, exist_ok=True)
                    
                    tasks_to_run.append((url, start_num))

                total_in_batch = len(tasks_to_run)
                
                for idx, (v_url, assigned_num) in enumerate(tasks_to_run):
                    if results['success']: 
                        sleep_time = random.uniform(5, 8)
                        logger.info(f"Waiting {sleep_time:.1f}s...")
                        time.sleep(sleep_time)

                    res = self._process_single_task(
                        v_url, assigned_num, target_folder,
                        skip_download, force_download, yt_dlp_write_subs, download_subtitles,
                        idx + 1, total_in_batch, playlist_title
                    )

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
        lang = info.get('language')
        if lang: return lang
        audio_languages = info.get('audio_languages')
        if audio_languages:
            if isinstance(audio_languages, list) and len(audio_languages) > 0:
                return audio_languages[0]
            elif isinstance(audio_languages, str):
                return audio_languages
        formats = info.get('formats', [])
        for f in formats:
            if f.get('language') and f.get('language') != 'und':
                return f.get('language')
        return None

    def _process_single_task(self, url, assigned_number, target_folder, skip, force, write_subs, dl_subs, idx, total, playlist_name):
        vid_id = self._extract_video_id(url)
        canonical = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else url
        
        if not force and canonical in self.downloaded_urls:
             return {'skipped': True, 'message': 'Already downloaded'}

        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'cookiefile': self.cookies_path}) as ydl:
                pre_info = ydl.extract_info(canonical, download=False)
                video_title = pre_info.get('title', canonical)
        except:
            video_title = canonical

        self._print_video_separator(video_title, canonical, idx, total, f"{assigned_number:02d}", playlist_name)
        
        try:
            info = self._fetch_info(canonical)
            self._save_metadata(info, canonical, assigned_number, target_folder)
            
            detected_lang = self._detect_original_language(info)
            if detected_lang:
                logger.info(f"Detected Original Audio Language: {detected_lang}")
            
            ydl_opts = {
                'format': f'bestvideo[height<={self.max_resolution}][ext=mp4]+bestaudio[ext=m4a]/best',
                'paths': {'home': str(target_folder)},
                'outtmpl': f'{assigned_number:02d}_%(title)s.%(ext)s', 
                'noplaylist': True,
                'ignoreerrors': True,
                'no_overwrites': True,
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
                try: ydl.cache.remove() 
                except: pass
                playlist_info = ydl.extract_info(canonical, download=not skip) or {}
            
            if dl_subs:
                videos = [{
                    'id': playlist_info.get('id'), 
                    'title': playlist_info.get('title', 'Unknown'),
                    'detected_lang': detected_lang
                }]
                self._download_subtitles_api(videos, target_folder, assigned_number)
                
            return {'success': True}
            
        except DownloadError as e:
            if "already downloaded" in str(e): return {'skipped': True, 'message': str(e)}
            raise
        except Exception as e:
            return {'error': str(e), 'success': False}

    def _fetch_info(self, url):
        for attempt in range(self.retry_attempts):
            try:
                opts = {'extract_flat': True, 'quiet': True, 'cookiefile': self.cookies_path, 'noplaylist': True}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                if not info: raise DownloadError("No info extracted")
                return info
            except Exception as e:
                if attempt == self.retry_attempts - 1: raise e
                time.sleep(2 + attempt)

    def _get_best_translation_source(self, transcript_list):
        try: return transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
        except: pass
        try: return transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
        except: pass
        for t in transcript_list:
            if t.is_translatable: return t
        return None

    def _download_subtitles_api(self, videos: List[Dict], folder: Path, assigned_number: int):
        for video in videos:
            vid_id = video.get('id')
            title = video.get('title')
            detected_lang = video.get('detected_lang')
            
            if not vid_id: continue
            base_filename = sanitize_filename(f"{assigned_number:02d}_{title}")
            
            try:
                transcript_list = self.ytt_api.list(vid_id)
                processed_langs = set()

                # 1. Original
                try:
                    original_transcript = None
                    if detected_lang:
                        try: original_transcript = transcript_list.find_transcript([detected_lang])
                        except: pass
                    if not original_transcript:
                        for t in transcript_list:
                            if not t.is_generated:
                                original_transcript = t
                                break
                    if not original_transcript: original_transcript = next(iter(transcript_list))
                    
                    if original_transcript:
                        lang = original_transcript.language_code
                        logger.info(f"Downloading Original Subtitle ({lang})...")
                        self._save_transcript(original_transcript, folder, base_filename, lang)
                        processed_langs.add(lang)
                        time.sleep(1)
                except Exception: pass

                # 2. Direct Match
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

                # 3. Translation
                missing_langs = []
                for req in self.subtitle_languages:
                    if not any(l == req or l.startswith(req + '-') for l in processed_langs):
                        missing_langs.append(req)

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
                                err = str(e).lower()
                                if "blocking" in err or "too many requests" in err:
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
