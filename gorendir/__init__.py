"""
GorEndir - YouTube Video & Subtitle Downloader
===============================================

A comprehensive YouTube downloader supporting:
- Single video and playlist downloads
- Multi-language subtitle extraction (SRT + TXT)
- Playlist start/end control
- Cookie-based authentication for age-restricted content
- VTT to SRT conversion with cleaning
- Resume/skip already downloaded videos
"""

from .downloader import YouTubeDownloader, DownloadError
from .utils import sanitize_filename, convert_srt_to_text, convert_all_srt_to_text
from .vtt_to_srt import process_directory, vtt_to_srt_clean

__version__ = "1.0.0"
__author__ = "Mohammad Tavakoli Heshejin"
__all__ = [
    "YouTubeDownloader",
    "DownloadError",
    "sanitize_filename",
    "convert_srt_to_text",
    "convert_all_srt_to_text",
    "process_directory",
    "vtt_to_srt_clean",
]
