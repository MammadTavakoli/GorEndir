# 🎥 GörEndir: YouTube Video and Subtitle Downloader

**GörEndir** is a powerful and user-friendly Python package designed to simplify the process of downloading YouTube videos and subtitles. Whether you're archiving content, studying with subtitles, or conducting research, GörEndir provides a seamless experience with a wide range of features.

---

## ✨ Key Features

- **📥 Download YouTube Videos**: Save videos in your preferred resolution, including up to 4K.
- **📜 Download Subtitles**: Automatically fetch subtitles in multiple languages.
- **📝 Convert Subtitles to Text**: Easily convert `.srt` subtitle files to plain text for convenient reading and analysis.
- **🔄 Rename Files**: Sanitize filenames by replacing invalid characters for better organization.
- **💾 Flexible Storage Options**: Save downloaded files to Google Drive or local storage.
- **🌍 Multi-Language Support**: Supports subtitles in **Azerbaijani (az)**, **English (en)**, **Farsi (fa)**, **Turkish (tr)**, and more.
- **🖥️ User-Friendly Interface**: Simple API and command-line interface for easy integration into your projects.
- **🔧 Customizable Options**: Control download resolution, subtitle languages, and more.
- **🔄 Reverse Download**: Download playlists in reverse order.
- **🚫 Skip Existing Downloads**: Avoid re-downloading videos that are already saved.

---

## 🛠️ Installation

### Using pip
Install **GörEndir** directly from GitHub using pip:

```bash
pip install -q git+https://github.com/MammadTavakoli/gorendir.git
```

### Manual Installation
1. Clone the repository:

    ```bash
    git clone https://github.com/MammadTavakoli/gorendir.git
    ```

2. Navigate to the project directory:

    ```bash
    cd gorendir
    ```

3. Install the dependencies:

    ```bash
    pip install -q -r requirements.txt
    ```

---

## 🚀 Quick Start

### Using GörEndir in Google Colab

```python
# Install GörEndir and mount Google Drive
!pip install -q --upgrade --force-reinstall git+https://github.com/MammadTavakoli/gorendir.git

from google.colab import drive
drive.mount('/content/drive')

# Import GörEndir's YouTubeDownloader and initialize it
from gorendir.downloader import YouTubeDownloader

# Set the path to save the downloaded videos (Google Drive)
save_directory = "/content/drive/MyDrive/YouTube/"  # Change this path if needed

# Initialize the downloader with subtitle languages
downloader = YouTubeDownloader(
    save_directory=save_directory,
    subtitle_languages=["az", "fa", "en", "tr"]
)

# Define your video URLs (can be a single video URL, a list of URLs, or a playlist dictionary)
video_urls = [
    # Corey Schafer's Python Tutorials Playlist
    "https://www.youtube.com/playlist?list=PL-osiE80TeTt2d9bfVyTiXJA-UTHn6WwU",

    # Real Python Tutorials Playlist
    "https://www.youtube.com/playlist?list=PL-osiE80TeTt2d9bfVyTiXJA-UTHn6WwU",

    # Tech With Tim - Python Programming (start downloading from the 3rd video)
    {"https://www.youtube.com/playlist?list=PLzMcBGfZo4-lSq2IDrA6vpZEV92AmQfJK": 3},

    # FreeCodeCamp Python Playlist
    "https://www.youtube.com/watch?v=rfscVS0vtbw",

    # Çok Güzel Hareketler Video
    "https://www.youtube.com/watch?v=E9rMSlMxqIk"
]

# Download all videos (force download even if already downloaded)
downloader.download_video(video_urls, force_download=True)
```

### Download a Single Video

```python
from gorendir.downloader import YouTubeDownloader

# Initialize downloader
downloader = YouTubeDownloader(save_directory="/path/to/save/videos", subtitle_languages=["fa", "ar"])

# Download a video
downloader.download_video("https://www.youtube.com/watch?v=example", force_download=True)
```

---

## 🛠️ Methods

### `YouTubeDownloader`

The `YouTubeDownloader` class is the core interface for downloading YouTube videos and subtitles.

#### Parameters:
- **`save_directory`** (**`str`**): Path to save downloaded files.
- **`subtitle_languages`** (**`list`**, optional): List of subtitle languages to download (default: `["az", "en", "fa", "tr"]`).
- **`max_resolution`** (**`int`**, optional): Maximum resolution for video downloads (default: `1080`).

#### `download_video`

Download a video or playlist from YouTube.

- **Parameters:**
  - **`video_url`** (**`str`** or **`dict`**): URL of the video or playlist to download, or a dictionary with URL and starting index. Example: `"https://www.youtube.com/watch?v=example"` or `{"https://www.youtube.com/playlist?list=PLzMcBGfZo4-lSq2IDrA6vpZEV92AmQfJK": 3}`.
  - **`playlist_start`** (**`int`**, optional): Starting index for the playlist download (default: `1`). This parameter is used only if `video_url` is a string.
  - **`skip_download`** (**`bool`**, optional): Flag to skip the download process (default: `False`).
  - **`force_download`** (**`bool`**, optional): Flag to force the download even if the URL has been saved before (default: `False`).
  - **`reverse_download`** (**`bool`**, optional): Flag to download the playlist in reverse order (default: `False`).

---

## 📂 Folder Structure

After downloading, the folder structure will look like this:

```
save_directory/
├── _urls.txt  # Contains all downloaded video URLs
│
├── Video_Title_Uploader/  # Folder for a single video
│   ├── _url.txt  # Contains the URL of this specific video
│   ├── 01_Video_Title.description  # Video description file
│   ├── 01_Video_Title.mp4
│   ├── 01_Video_Title.az.srt
│   ├── 01_Video_Title.en.srt
│   ├── 01_Video_Title.fa.srt
│   ├── 01_Video_Title.tr.srt
│   ├── 01_Video_Title.az.txt  # Converted subtitle text (Azerbaijani)
│   ├── 01_Video_Title.en.txt  # Converted subtitle text (English)
│   ├── 01_Video_Title.fa.txt  # Converted subtitle text (Farsi)
│   └── 01_Video_Title.tr.txt  # Converted subtitle text (Turkish)
│
└── Playlist_Title_Uploader/  # Folder for a playlist
    ├── _url.txt  # Contains the URL of the playlist
    │
    ├── 01_First_Video_Title.description  # Video description file
    ├── 01_First_Video_Title.mp4
    ├── 01_First_Video_Title.az.srt
    ├── 01_First_Video_Title.en.srt
    ├── 01_First_Video_Title.fa.srt
    ├── 01_First_Video_Title.tr.srt
    ├── 01_First_Video_Title.az.txt  # Converted subtitle text (Azerbaijani)
    ├── 01_First_Video_Title.en.txt  # Converted subtitle text (English)
    ├── 01_First_Video_Title.fa.txt  # Converted subtitle text (Farsi)
    ├── 01_First_Video_Title.tr.txt  # Converted subtitle text (Turkish)
    │
    ├── 02_Second_Video_Title.description  # Video description file
    ├── 02_Second_Video_Title.mp4
    ├── 02_Second_Video_Title.az.srt
    ├── 02_Second_Video_Title.en.srt
    ├── 02_Second_Video_Title.fa.srt
    ├── 02_Second_Video_Title.tr.srt
    ├── 02_Second_Video_Title.az.txt  # Converted subtitle text (Azerbaijani)
    ├── 02_Second_Video_Title.en.txt  # Converted subtitle text (English)
    ├── 02_Second_Video_Title.fa.txt  # Converted subtitle text (Farsi)
    └── 02_Second_Video_Title.tr.txt  # Converted subtitle text (Turkish)
```

---

## 📖 Further Reading

- [yt-dlp Documentation](https://github.com/yt-dlp/yt-dlp)
- [youtube-transcript-api Documentation](https://github.com/jdepoix/youtube-transcript-api)
- [pysrt Documentation](https://github.com/byroot/pysrt)

---

## 📌 Note

This project is under active development. Please report any issues or suggest improvements by opening an issue on GitHub.
