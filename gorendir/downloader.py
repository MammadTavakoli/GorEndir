import os
import re
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
from youtube_transcript_api.formatters import SRTFormatter
from typing import List, Dict, Optional, Union, Tuple
from .utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder
import copy
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

try:
    from IPython import get_ipython
    from IPython.display import display, HTML
    IN_COLAB = 'google.colab' in str(get_ipython())
except ImportError:
    IN_COLAB = False

if not IN_COLAB:
    from colorama import Fore, Style, init
    init(autoreset=True)

# Constants
DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

class YouTubeDownloader:
    """A class to download YouTube videos and subtitles with enhanced features."""

    def __init__(
        self,
        save_directory: str,
        subtitle_languages: Optional[List[str]] = None,
        max_resolution: int = DEFAULT_MAX_RESOLUTION,
        log_level: str = "INFO"
    ):
        """
        Initialize the YouTubeDownloader.

        Args:
            save_directory: Directory to save downloaded content.
            subtitle_languages: List of subtitle languages to download.
            max_resolution: Maximum video resolution.
            log_level: Logging level ("DEBUG", "INFO", "WARNING", "ERROR").
        """
        self.save_directory = Path(save_directory)  # Use Path for cross-platform compatibility
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution
        self._setup_logging(log_level)

    def _setup_logging(self, log_level: str):
        """Configure logging for the class."""
        logging.basicConfig(level=log_level.upper(), format=LOG_FORMAT)
        self.logger = logging.getLogger(__name__)

    def _print_colored(self, text: str, color: str = "white", emoji: str = ""):
        """Print colored text with logging fallback."""
        message = f"{emoji} {text}"
        self.logger.info(text)
        if IN_COLAB:
            color_map = {
                "purple": "#6A5ACD", "orange": "#FF8C00", "pink": "#FF1493",
                "alizarin": "#DC143C", "red": "#B22222", "green": "#228B22",
                "blue": "#4169E1", "dark_magenta": "#4B0082", "maroon": "#8B0000",
                "lotus_green": "#2E8B57", "black_blue": "#191970",
            }
            html_text = f"<span style='color:{color_map.get(color, 'white')};'>{message}</span>"
            display(HTML(html_text))
        else:
            color_map = {
                "purple": Fore.MAGENTA, "orange": Fore.YELLOW, "pink": Fore.MAGENTA,
                "alizarin": Fore.RED, "red": Fore.RED, "green": Fore.GREEN,
                "blue": Fore.BLUE, "dark_magenta": Fore.MAGENTA, "maroon": Fore.RED,
                "lotus_green": Fore.GREEN, "black_blue": Fore.BLUE,
            }
            color_code = color_map.get(color, Fore.WHITE)
            print(f"{color_code}{message}{Style.RESET_ALL}")

    def _print_ascii_art(self):
        """Display ASCII art for the package."""
        ascii_art = r"""
    ╔═══════════════════════════════════════════════════════════════════╗
    ║   ██████╗  ██████╗ ██████╗ ███████╗███╗   ██╗██████╗ ██╗██████╗   ║
    ║  ██╔════╝ ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║██╔══██╗  ║
    ║  ██║  ███╗██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║  ██║██║██████╔╝  ║
    ║  ██║   ██║██║   ██║██╔══██╗██╔══╝  ██║╚██╗██║██║  ██║██║██╔══██╗  ║
    ║  ╚██████╔╝╚██████╔╝██║  ██║███████╗██║ ╚████║██████╔╝██║██║  ██║  ║
    ║   ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚═╝╚═╝  ╚═╝  ║
    ║  Welcome to GÖRENDİR - Your Ultimate YouTube Video Downloader!    ║
    ╚═══════════════════════════════════════════════════════════════════╝
        """
        if IN_COLAB:
            display(HTML(f'<pre style="color: #6A5ACD; font-family: monospace;">{ascii_art}</pre>'))
        else:
            self._print_colored(ascii_art, color="purple")

    @contextmanager
    def _change_directory(self, path: Path):
        """Context manager to temporarily change the working directory."""
        original_dir = os.getcwd()
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(original_dir)

    def _create_video_folder(self, video_url: str, force_download: bool = False) -> Optional[Path]:
        """Create a folder for the video and track the URL."""
        try:
            with yt_dlp.YoutubeDL({"ignoreerrors": True, "quiet": True}) as ydl:
                info = ydl.extract_info(video_url, download=False)
                if not info or not info.get("title") or not info.get("uploader"):
                    self._print_colored(f"Invalid video info: {video_url}", "orange", "⏭️")
                    return None
                if info.get("live_status") == "is_upcoming":
                    self._print_colored(f"Upcoming video: {video_url}", "orange", "⏭️")
                    return None
                self._print_colored(info["title"], "purple", "🎬")
                self.save_directory.mkdir(exist_ok=True)
                url_file = self.save_directory / "_urls.txt"
                if not force_download and self._is_url_already_saved(url_file, video_url):
                    self._print_colored("URL already processed.", "orange", "⏭️")
                    return None
                self._save_url_to_file(url_file, video_url)
                folder_name = sanitize_filename(f"{info['title']}_{info['uploader']}")
                folder_path = self.save_directory / "Download_video" / folder_name
                folder_path.mkdir(parents=True, exist_ok=True)
                self._print_colored(f"Directory: {folder_path}", "green", "📂")
                return folder_path
        except Exception as e:
            self._print_colored(f"Folder creation failed: {e}", "maroon", "❌")
            return None

    def _is_url_already_saved(self, url_file: Path, video_url: str) -> bool:
        """Check if a URL is already tracked."""
        return url_file.exists() and video_url in url_file.read_text(encoding="utf-8").splitlines()

    def _save_url_to_file(self, url_file: Path, video_url: str):
        """Append a URL to the tracking file."""
        with url_file.open("a+", encoding="utf-8") as f:
            f.write(f"{video_url}\n")

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from a URL."""
        match = re.search(r'(?<=v=)[^&#]+', url)
        return match.group() if match else None

    def _get_ydl_options(self, start_index: int) -> Dict:
        """Return yt-dlp configuration options."""
        return {
            "format": f"(bestvideo[height<={self.max_resolution}]+bestvideo[height<=720][vcodec^=avc1]+bestaudio/best)",
            "outtmpl": "%(autonumber)02d_%(title)s.%(ext)s",
            "autonumber_start": start_index,
            "restrictfilenames": False,
            "nooverwrites": True,
            "writedescription": True,
            "writeannotations": True,
            "ignoreerrors": True,
            "noplaylist": True,
        }

    def _process_entries(self, entries: List[Dict], start_index: int) -> List[Dict[str, str]]:
        """Process playlist entries into video info."""
        video_info = []
        counter = start_index
        for entry in entries:
            if entry:
                video_info.append({
                    "id": entry["id"],
                    "filename": f"{str(counter).zfill(2)}_{sanitize_filename(entry['title'])}"
                })
                counter += 1
        return video_info

    def _download_subtitle(self, video_info: Dict[str, str]) -> None:
        """Download subtitles for a single video."""
        video_id, filename = video_info["id"], video_info["filename"]
        try:
            sublangs = copy.deepcopy(self.subtitle_languages)
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            for transcript in transcripts:
                lng = transcript.language_code
                if lng in sublangs:
                    srt = YouTubeTranscriptApi.get_transcript(video_id, languages=[lng])
                    srt_content = SRTFormatter().format_transcript(srt)
                    with open(f"{filename}.{lng}.srt", "w", encoding="utf-8") as f:
                        f.write(srt_content)
                    self._print_colored(f"{lng} subtitles downloaded for: {filename}", "blue", "📄")
                    sublangs.remove(lng)
            if first := next((t for t in transcripts if t.language_code), None):
                for lng in sublangs:
                    try:
                        translated = first.translate(lng)
                        srt_content = SRTFormatter().format_transcript(translated.fetch())
                        with open(f"{filename}.{lng}.srt", "w", encoding="utf-8") as f:
                            f.write(srt_content)
                        self._print_colored(f"Translated {lng} subtitles for: {filename}", "dark_magenta", "🌐")
                    except Exception as e:
                        self._print_colored(f"Translation to {lng} failed: {e}", "alizarin", "❌")
        except TranscriptsDisabled:
            self._print_colored(f"Subtitles disabled for: {filename}", "orange", "🚫")
        except Exception as e:
            self._print_colored(f"Subtitle error: {e}", "maroon", "❌")

    def _download_single(
        self,
        video_url: str,
        playlist_start: int,
        skip_download: bool,
        force_download: bool,
        reverse_download: bool
    ) -> None:
        """Download a single video or playlist."""
        video_id = self._extract_video_id(video_url)
        if video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        folder_path = self._create_video_folder(video_url, force_download)
        if not folder_path and not force_download:
            return

        with self._change_directory(folder_path):
            try:
                with yt_dlp.YoutubeDL({"ignoreerrors": True, "quiet": True}) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    if not info:
                        self._print_colored(f"Info extraction failed: {video_url}", "orange", "⏭️")
                        return
                    if info.get("live_status") == "is_upcoming":
                        self._print_colored(f"Upcoming video: {video_url}", "orange", "⏭️")
                        return

                if "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    if not entries:
                        self._print_colored(f"Empty playlist: {video_url}", "orange", "⏭️")
                        return
                    start_idx = max(0, playlist_start - 1)
                    filtered_entries = entries[start_idx:]
                    if reverse_download:
                        filtered_entries = filtered_entries[::-1]
                    urls = [entry["webpage_url"] for entry in filtered_entries]
                    video_info_list = self._process_entries(filtered_entries, playlist_start)
                else:
                    urls = [video_url]
                    video_info_list = [{"id": info["id"], "filename": f"01_{sanitize_filename(info['title'])}"}]

                ydl_opts = self._get_ydl_options(playlist_start)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    if not skip_download:
                        ydl.download(urls)
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        executor.map(self._download_subtitle, video_info_list if not reverse_download else reversed(video_info_list))
                self._print_colored("Download completed.", "green", "✅")
            except yt_dlp.DownloadError as e:
                self._print_colored(f"Download failed: {e}", "alizarin", "❌")
            except Exception as e:
                self._print_colored(f"Error: {e}", "maroon", "❌")

    def download_video(
        self,
        video_urls: Union[str, List[str], Dict[str, int]],
        playlist_start: int = 1,
        skip_download: bool = False,
        force_download: bool = False,
        reverse_download: bool = False,
        max_videos: Optional[int] = None
    ) -> None:
        """
        Download videos or playlists with enhanced options.

        Args:
            video_urls: URL, list of URLs, or dict with start indices.
            playlist_start: Starting index (1-based).
            skip_download: Skip video download.
            force_download: Force re-download.
            reverse_download: Reverse order from start point.
            max_videos: Limit the number of videos to download.
        """
        self._print_ascii_art()
        inputs = (
            [(url, start) for url, start in video_urls.items()] if isinstance(video_urls, dict) else
            [(url, playlist_start) for url in video_urls] if isinstance(video_urls, list) else
            [(video_urls, playlist_start)]
        )
        for url, start in inputs:
            self._download_single(url, start, skip_download, force_download, reverse_download)
        convert_all_srt_to_text(self.save_directory, '*******')
        rename_files_in_folder(self.save_directory)