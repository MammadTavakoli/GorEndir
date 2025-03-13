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
            # Use HTML for rendering in Colab
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
            # Handle multi-line strings
            lines = text.splitlines()
            for line in lines:
                print(f"{color_code}{emoji} {line}{Style.RESET_ALL}")

    def _print_ascii_art(self):
        """Print the ASCII art for the package GÖRENDİR."""
        if IN_COLAB:
            # Use HTML for rendering in Colab
            ascii_art_html = """
            <pre style="color: #6A5ACD; font-family: monospace;">
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
            </pre>
            """
            display(HTML(ascii_art_html))
        else:
            # Use regular ASCII art for non-Colab environments
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
            self._print_colored(ascii_art, color="purple")

    def create_video_folder(self, video_url: str, force_download: bool = False) -> bool:
        """
        Create a folder for the video and save the URL.

        Args:
            video_url: URL of the video.
            force_download: Whether to force download even if the URL is already saved.

        Returns:
            bool: True if the folder was created successfully, False otherwise.
        """
        try:
            with yt_dlp.YoutubeDL({"ignoreerrors": True, "quiet": True}) as ydl:
                video_info = ydl.extract_info(video_url, download=False)
                if video_info is None:
                    self._print_colored(f"Unable to extract video info. Skipping: {video_url}", color="orange", emoji="⏭️")
                    return False
                if video_info.get('live_status') == 'is_upcoming':
                    self._print_colored(f"Video is a premiere and not yet live. Skipping: {video_url}", color="orange", emoji="⏭️")
                    return False
                if not video_info.get('title') or not video_info.get('uploader'):
                    self._print_colored(f"Video metadata is incomplete. Skipping: {video_url}", color="orange", emoji="⏭️")
                    return False
                self._print_colored(video_info['title'], color="purple", emoji="🎬")
                os.makedirs(self.save_directory, exist_ok=True)
                url_file_path = os.path.join(self.save_directory, "_urls.txt")
                if not force_download and self._is_url_already_saved(url_file_path, video_url):
                    self._print_colored("This URL has already been saved. Skipping download.", color="orange", emoji="⏭️")
                    return False
                self._save_url_to_file(url_file_path, video_url)
                folder_name = sanitize_filename(f"{video_info['title']}_{video_info['uploader']}")
                folder_path = os.path.join(self.save_directory, "Download_video", folder_name)
                if not os.path.exists(folder_path):
                    os.makedirs(folder_path)
                os.chdir(folder_path)
                self._print_colored(f"Current working directory: {os.getcwd()}", color="green", emoji="📂")
                
                self._print_colored("Folder created and URL saved successfully.", color="lotus_green", emoji="✅")
                return True
        except yt_dlp.DownloadError as e:
            self._print_colored(f"Error downloading video info: {e}", color="alizarin", emoji="❌")
            return False
        except Exception as e:
            self._print_colored(f"Error creating folder: {e}", color="maroon", emoji="❌")
            return False

    def _is_url_already_saved(self, url_file_path: str, video_url: str) -> bool:
        """Check if the URL is already saved in the file."""
        if os.path.exists(url_file_path):
            with open(url_file_path, "r", encoding="utf-8") as url_file:
                saved_urls = url_file.read().splitlines()
                return video_url in saved_urls
        return False

    def _save_url_to_file(self, url_file_path: str, video_url: str):
        """Save the URL to a file."""
        with open(url_file_path, "a+", encoding="utf-8") as url_file:
            url_file.write(video_url + "\n")

    def download_subtitles(self, video_info_list: List[Dict[str, str]], reverse_download: bool = False):
        """
        Download subtitles for the videos in the list.

        Args:
            video_info_list: List of video information dictionaries.
            reverse_download: Whether to download subtitles in reverse order.
        """
        if reverse_download:
            video_info_list = list(reversed(video_info_list))

        total_videos = len(video_info_list)
        for idx, video_info in enumerate(video_info_list, start=1):
            # try:
                sublangs = copy.deepcopy(self.subtitle_languages)
                video_id = video_info.get('id')
                filename = sanitize_filename(video_info.get('filename'))
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                print("******** transcript_list ***"*10)
                print(transcript_list)

                for transcript in transcript_list:
                    lng = transcript.language_code
                    if lng in sublangs:
                        srt = YouTubeTranscriptApi.get_transcript(video_id, languages=[lng])
                        formatter = SRTFormatter()
                        srt_content = formatter.format_transcript(srt)
                        numbered_idx = total_videos - idx + 1 if reverse_download else idx
                        self._print_colored(f"Downloading {lng} subtitles for: {filename}", color="blue", emoji="📄")
                        with open(rf"{filename}.{lng}.srt", "w", encoding="utf-8") as subtitle_file:
                            subtitle_file.write(srt_content)
                        sublangs.remove(lng)
                first_transcript = next((t for t in transcript_list if t.language_code), None)
                print("******* first_transcript ****"*10)
                print(first_transcript)
                
                if first_transcript:
                    for tr_lang in sublangs:
                        try:
                            translated_transcript = first_transcript.translate(tr_lang)
                            formatter = SRTFormatter()
                            srt_content = formatter.format_transcript(translated_transcript.fetch())
                            numbered_idx = total_videos - idx + 1 if reverse_download else idx
                            self._print_colored(f"Downloading translated subtitles to {tr_lang} for: {filename}", color="dark_magenta", emoji="🌐")
                            with open(rf"{filename}.{tr_lang}.srt", "w", encoding="utf-8") as subtitle_file:
                                subtitle_file.write(srt_content)
                        except Exception as e:
                            self._print_colored(f"Error downloading translated subtitles to {tr_lang} for: {filename}. Error: {e}", color="alizarin", emoji="❌")
            # except TranscriptsDisabled:
            #     self._print_colored(f"Subtitles are disabled for: {filename}", color="orange", emoji="🚫")
            # except Exception as e:
            #     self._print_colored(f"Error downloading subtitles for: {filename}. Error: {e}", color="maroon", emoji="❌")

    def download_video(
        self,
        video_urls: Union[str, List[str], Dict[str, int]],
        playlist_start: int = 1,
        skip_download: bool = False,
        force_download: bool = False,
        reverse_download: bool = False
    ):
        """
        Download a single video, a list of videos, or a playlist of videos.

        Args:
            video_urls: A single video URL, a list of video URLs, or a dictionary of URLs with start indices.
            playlist_start: The starting index for playlist downloads.
            skip_download: Whether to skip the actual download.
            force_download: Whether to force download even if the URL is already saved.
            reverse_download: Whether to download in reverse order.
        """

        # Print the ASCII art before starting the download
        self._print_ascii_art()

        if isinstance(video_urls, dict):
            # Handle dictionary of URLs with start indices
            for url, start_index in video_urls.items():
                self._print_colored(f"Downloading: {url} from video {start_index}", color="blue", emoji="📥")
                self._download_video_internal(
                    url,
                    playlist_start=start_index,
                    skip_download=skip_download,
                    force_download=force_download,
                    reverse_download=reverse_download
                )
        elif isinstance(video_urls, str):
            # Handle single video URL
            self._print_colored(f"Downloading: {video_urls}", color="blue", emoji="📥")
            self._download_video_internal(
                video_urls,
                playlist_start=playlist_start,
                skip_download=skip_download,
                force_download=force_download,
                reverse_download=reverse_download
            )
        elif isinstance(video_urls, list):
            # Handle list of video URLs
            for video_url in video_urls:
                self._print_colored(f"Downloading: {video_url}", color="blue", emoji="📥")
                self._download_video_internal(
                    video_url,
                    playlist_start=playlist_start,
                    skip_download=skip_download,
                    force_download=force_download,
                    reverse_download=reverse_download
                )
        else:
            raise ValueError("Invalid input type for video_urls. Expected str, list, or dict.")

        # Convert subtitles to text and sanitize filenames after all downloads are complete
        convert_all_srt_to_text(self.save_directory, '*******')
        rename_files_in_folder(self.save_directory)

    def _download_video_internal(
        self,
        video_url: str,
        playlist_start: int,
        skip_download: bool,
        force_download: bool,
        reverse_download: bool
    ):
        """
        Internal method to handle the download of a single video or playlist.

        Args:
            video_url: URL of the video or playlist.
            playlist_start: The starting index for playlist downloads.
            skip_download: Whether to skip the actual download.
            force_download: Whether to force download even if the URL is already saved.
            reverse_download: Whether to download in reverse order.
        """
        if isinstance(video_url, dict) and len(video_url) == 1:
            playlist_start = list(video_url.values())[0]
            video_url = list(video_url.keys())[0]
        
        video_id = self._extract_video_id(video_url)
        if video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        if not self.create_video_folder(video_url, force_download) and not force_download:
            return
        ydl_options = self._get_ydl_options(playlist_start, reverse_download)
        video_info_list = []
        try:
            with yt_dlp.YoutubeDL(ydl_options) as ydl:
                ydl.cache.remove()
                playlist_info = ydl.extract_info(video_url, download=False)
                if playlist_info is None:
                    self._print_colored(f"Unable to extract playlist info. Skipping: {video_url}", color="orange", emoji="⏭️")
                    return False
                if playlist_info.get('live_status') == 'is_upcoming':
                    self._print_colored(f"Video is a premiere and not yet live. Skipping: {video_url}", color="orange", emoji="⏭️")
                    return False
                print('*' * 50)
                ydl.prepare_filename(playlist_info)
                if not skip_download:
                    ydl.download([video_url])
                video_info_list = self._process_playlist_info(playlist_info, playlist_start, reverse_download)
                self.download_subtitles(video_info_list, reverse_download)
                self._print_colored("-" * 50, color="green")
                self._print_colored("", color="green")
                return True
        except yt_dlp.DownloadError as e:
            self._print_colored(f"Download error: {e}", color="alizarin", emoji="❌")
        except Exception as e:
            self._print_colored(f"Unexpected error: {e}", color="orange", emoji="⚠️")
        self._print_colored("-" * 50, color="red")
        self._print_colored("", color="red")

    def _extract_video_id(self, video_url: str) -> Optional[str]:
        """Extract the video ID from the URL."""
        video_id_match = re.search(r'(?<=v=)[^&#]+', video_url)
        return video_id_match.group() if video_id_match else None

    def _get_ydl_options(self, playlist_start: int, reverse_download: bool = False) -> Dict:
        """Get the options for youtube-dl."""
        options = {
            "format": f"(bestvideo[height<={self.max_resolution}]+bestvideo[height<=720][vcodec^=avc1]+bestaudio/best)",
            "outtmpl": "%(autonumber)02d_%(title)s.%(ext)s",
            "autonumber_start": playlist_start,
            "playliststart": playlist_start,
            "restrictfilenames": False,
            "nooverwrites": True,
            "writedescription": True,
            "writeinfojson": False,
            "writeannotations": True,
            "writethumbnail": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "ignoreerrors": True,           
        }
        if reverse_download:
            options["playlistreverse"] = True
        return options

    def _process_playlist_info(self, playlist_info: Dict, playlist_start: int, reverse_download: bool = False) -> List[Dict[str, str]]:
        """Process the playlist info to extract video information."""
        video_info_list = []
        if "entries" in playlist_info:
            entries = playlist_info["entries"]
            downloadable_counter = playlist_start
            for entry in entries:
                if entry is not None:
                    entry_video_id = entry.get("id")
                    entry_title = sanitize_filename(entry.get("title"))
                    entry_filename = f"{str(downloadable_counter).zfill(2)}_{entry_title}"
                    video_info_list.append({"id": entry_video_id, "filename": entry_filename})
                    downloadable_counter += 1
                else:
                    self._print_colored("Skipping a None entry", color="orange", emoji="⏭️")
        else:
            video_id = playlist_info.get("id")
            title = sanitize_filename(playlist_info.get("title"))
            filename = f"01_{title}"
            video_info_list.append({"id": video_id, "filename": filename})
        return video_info_list
