import os
import re
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
from youtube_transcript_api.formatters import SRTFormatter
from typing import List, Dict, Optional, Union
from .utils import sanitize_filename, convert_all_srt_to_text, rename_files_in_folder
import copy

try:
    from IPython import get_ipython
    from IPython.display import display, HTML
    IN_COLAB = 'google.colab' in str(get_ipython())
except:
    IN_COLAB = False

if not IN_COLAB:
    from colorama import Fore, Style, init
    init(autoreset=True)

DEFAULT_SUBTITLE_LANGUAGES = ["az", "en", "fa", "tr"]
DEFAULT_MAX_RESOLUTION = 1080

class YouTubeDownloader:
    """A class to download YouTube videos and their subtitles."""

    def __init__(
        self,
        save_directory: str,
        subtitle_languages: Optional[List[str]] = None,
        max_resolution: int = DEFAULT_MAX_RESOLUTION
    ):
        """
        Initialize the YouTubeDownloader.

        Args:
            save_directory: Directory to save downloaded videos and subtitles.
            subtitle_languages: List of subtitle languages to download.
            max_resolution: Maximum resolution for video downloads.
        """
        self.save_directory = save_directory
        self.subtitle_languages = subtitle_languages or DEFAULT_SUBTITLE_LANGUAGES
        self.max_resolution = max_resolution

    def _print_colored(self, text: str, color: str = "white", emoji: str = ""):
        """Print colored text to the console."""
        if IN_COLAB:
            color_map = {
                "purple": "#6A5ACD", "orange": "#FF8C00", "pink": "#FF1493",
                "alizarin": "#DC143C", "red": "#B22222", "green": "#228B22",
                "blue": "#4169E1", "dark_magenta": "#4B0082", "maroon": "#8B0000",
                "lotus_green": "#2E8B57", "black_blue": "#191970",
            }
            html_text = f"<span style='color:{color_map.get(color, 'white')};'>{emoji} {text}</span>"
            display(HTML(html_text))
        else:
            color_map = {
                "purple": Fore.MAGENTA, "orange": Fore.YELLOW, "pink": Fore.MAGENTA,
                "alizarin": Fore.RED, "red": Fore.RED, "green": Fore.GREEN,
                "blue": Fore.BLUE, "dark_magenta": Fore.MAGENTA, "maroon": Fore.RED,
                "lotus_green": Fore.GREEN, "black_blue": Fore.BLUE,
            }
            color_code = color_map.get(color, Fore.WHITE)
            lines = text.splitlines()
            for line in lines:
                print(f"{color_code}{emoji} {line}{Style.RESET_ALL}")

    def _print_ascii_art(self):
        """Print the ASCII art for the package GÖRENDİR."""
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
        if IN_COLAB:
            display(HTML(f'<pre style="color: #6A5ACD; font-family: monospace;">{ascii_art}</pre>'))
        else:
            self._print_colored(ascii_art, color="purple")

    def _create_video_folder(self, video_url: str, force_download: bool = False) -> Optional[str]:
        """Create a folder for the video and return its path if successful."""
        try:
            with yt_dlp.YoutubeDL({"ignoreerrors": True, "quiet": True}) as ydl:
                video_info = ydl.extract_info(video_url, download=False)
                if not video_info or not video_info.get("title") or not video_info.get("uploader"):
                    self._print_colored(f"Invalid or incomplete video info: {video_url}", color="orange", emoji="⏭️")
                    return None
                if video_info.get("live_status") == "is_upcoming":
                    self._print_colored(f"Video is upcoming: {video_url}", color="orange", emoji="⏭️")
                    return None
                self._print_colored(video_info["title"], color="purple", emoji="🎬")
                os.makedirs(self.save_directory, exist_ok=True)
                url_file_path = os.path.join(self.save_directory, "_urls.txt")
                if not force_download and self._is_url_already_saved(url_file_path, video_url):
                    self._print_colored("URL already saved. Skipping.", color="orange", emoji="⏭️")
                    return None
                self._save_url_to_file(url_file_path, video_url)
                folder_name = sanitize_filename(f"{video_info['title']}_{video_info['uploader']}")
                folder_path = os.path.join(self.save_directory, "Download_video", folder_name)
                os.makedirs(folder_path, exist_ok=True)
                self._print_colored(f"Working directory: {folder_path}", color="green", emoji="📂")
                self._print_colored("Folder created successfully.", color="lotus_green", emoji="✅")
                return folder_path
        except Exception as e:
            self._print_colored(f"Folder creation failed: {e}", color="maroon", emoji="❌")
            return None

    def _is_url_already_saved(self, url_file_path: str, video_url: str) -> bool:
        """Check if a URL is already saved."""
        if os.path.exists(url_file_path):
            with open(url_file_path, "r", encoding="utf-8") as f:
                return video_url in f.read().splitlines()
        return False

    def _save_url_to_file(self, url_file_path: str, video_url: str):
        """Save a URL to the tracking file."""
        with open(url_file_path, "a+", encoding="utf-8") as f:
            f.write(f"{video_url}\n")

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from a URL."""
        match = re.search(r'(?<=v=)[^&#]+', url)
        return match.group() if match else None

    def _get_ydl_options(self, start_index: int) -> Dict:
        """Return yt-dlp options with numbering starting from start_index."""
        return {
            "format": f"(bestvideo[height<={self.max_resolution}]+bestvideo[height<=720][vcodec^=avc1]+bestaudio/best)",
            "outtmpl": "%(autonumber)02d_%(title)s.%(ext)s",
            "autonumber_start": start_index,
            "restrictfilenames": False,
            "nooverwrites": True,
            "writedescription": True,
            "writeinfojson": False,
            "writeannotations": True,
            "writethumbnail": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "ignoreerrors": True,
            "noplaylist": True,  # We'll handle playlists manually
        }

    def _process_entries(self, entries: List[Dict], start_index: int) -> List[Dict[str, str]]:
        """Process playlist entries into a list of video info dictionaries."""
        video_info_list = []
        counter = start_index
        for entry in entries:
            if entry:
                video_id = entry.get("id")
                title = sanitize_filename(entry.get("title"))
                filename = f"{str(counter).zfill(2)}_{title}"
                video_info_list.append({"id": video_id, "filename": filename})
                counter += 1
            else:
                self._print_colored("Skipping invalid entry", color="orange", emoji="⏭️")
        return video_info_list

    def _download_subtitles(self, video_info_list: List[Dict[str, str]], reverse: bool = False):
        """Download subtitles for a list of videos."""
        if reverse:
            video_info_list = list(reversed(video_info_list))
        total = len(video_info_list)
        for idx, info in enumerate(video_info_list, 1):
            video_id, filename = info["id"], info["filename"]
            try:
                sublangs = copy.deepcopy(self.subtitle_languages)
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                for transcript in transcript_list:
                    lng = transcript.language_code
                    if lng in sublangs:
                        srt = YouTubeTranscriptApi.get_transcript(video_id, languages=[lng])
                        srt_content = SRTFormatter().format_transcript(srt)
                        self._print_colored(f"Downloading {lng} subtitles for: {filename}", color="blue", emoji="📄")
                        with open(f"{filename}.{lng}.srt", "w", encoding="utf-8") as f:
                            f.write(srt_content)
                        sublangs.remove(lng)
                first_transcript = next((t for t in transcript_list if t.language_code), None)
                if first_transcript:
                    for lng in sublangs:
                        try:
                            translated = first_transcript.translate(lng)
                            srt_content = SRTFormatter().format_transcript(translated.fetch())
                            self._print_colored(f"Translating to {lng} for: {filename}", color="dark_magenta", emoji="🌐")
                            with open(f"{filename}.{lng}.srt", "w", encoding="utf-8") as f:
                                f.write(srt_content)
                        except Exception as e:
                            self._print_colored(f"Translation to {lng} failed: {e}", color="alizarin", emoji="❌")
            except TranscriptsDisabled:
                self._print_colored(f"Subtitles disabled for: {filename}", color="orange", emoji="🚫")
            except Exception as e:
                self._print_colored(f"Subtitle download failed: {e}", color="maroon", emoji="❌")

    def download_video(
        self,
        video_urls: Union[str, List[str], Dict[str, int]],
        playlist_start: int = 1,
        skip_download: bool = False,
        force_download: bool = False,
        reverse_download: bool = False
    ):
        """
        Download videos or playlists with custom start and reverse options.

        Args:
            video_urls: Single URL, list of URLs, or dict of URLs with start indices.
            playlist_start: Starting index for playlists (1-based).
            skip_download: Skip actual video download.
            force_download: Force download even if URL is saved.
            reverse_download: Download in reverse order from start point.
        """
        self._print_ascii_art()
        if isinstance(video_urls, str):
            self._download_single(video_urls, playlist_start, skip_download, force_download, reverse_download)
        elif isinstance(video_urls, list):
            for url in video_urls:
                self._download_single(url, playlist_start, skip_download, force_download, reverse_download)
        elif isinstance(video_urls, dict):
            for url, start in video_urls.items():
                self._download_single(url, start, skip_download, force_download, reverse_download)
        else:
            raise ValueError("video_urls must be str, list, or dict")
        convert_all_srt_to_text(self.save_directory, '*******')
        rename_files_in_folder(self.save_directory)

    def _download_single(
        self,
        video_url: str,
        playlist_start: int,
        skip_download: bool,
        force_download: bool,
        reverse_download: bool
    ):
        """Handle downloading a single video or playlist."""
        video_id = self._extract_video_id(video_url)
        if video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        folder_path = self._create_video_folder(video_url, force_download)
        if not folder_path and not force_download:
            return
        os.chdir(folder_path)

        # Extract info
        try:
            with yt_dlp.YoutubeDL({"ignoreerrors": True, "quiet": True}) as ydl:
                info = ydl.extract_info(video_url, download=False)
                if not info:
                    self._print_colored(f"Failed to extract info: {video_url}", color="orange", emoji="⏭️")
                    return
                if info.get("live_status") == "is_upcoming":
                    self._print_colored(f"Video is upcoming: {video_url}", color="orange", emoji="⏭️")
                    return

            # Handle playlist or single video
            if "entries" in info:
                entries = [e for e in info["entries"] if e]
                if not entries:
                    self._print_colored(f"No valid entries in playlist: {video_url}", color="orange", emoji="⏭️")
                    return
                start_idx = max(0, playlist_start - 1)  # Convert to 0-based
                filtered_entries = entries[start_idx:]
                if reverse_download:
                    filtered_entries = filtered_entries[::-1]
                urls = [entry["webpage_url"] for entry in filtered_entries]
                video_info_list = self._process_entries(filtered_entries, playlist_start)
            else:
                urls = [video_url]
                video_info_list = [{"id": info["id"], "filename": f"01_{sanitize_filename(info['title'])}"}]

            # Download
            ydl_opts = self._get_ydl_options(playlist_start)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.cache.remove()
                if not skip_download:
                    ydl.download(urls)
                self._download_subtitles(video_info_list, reverse_download)
                self._print_colored("Download completed.", color="green", emoji="✅")
        except yt_dlp.DownloadError as e:
            self._print_colored(f"Download error: {e}", color="alizarin", emoji="❌")
        except Exception as e:
            self._print_colored(f"Unexpected error: {e}", color="maroon", emoji="❌")