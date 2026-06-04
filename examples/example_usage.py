"""
GorEndir - Example Usage Script
================================
نحوه استفاده از دانلودر گورندیر

نصب:
    pip install -r requirements.txt
    # یا
    pip install .
"""

from gorendir import YouTubeDownloader

save_path = "/path/to/downloads"


def download_videos(video_urls, save_path, reverse_download=False, skip_download=False, playlist_end=0):
    """دانلود ویدیو یا زیرنویس از یوتوب"""
    downloader = YouTubeDownloader(
        save_directory=save_path,
        max_resolution=1080,
        subtitle_languages=["en", "fa"]
    )

    result = downloader.download_video(
        video_urls=video_urls,
        reverse_download=reverse_download,
        skip_download=skip_download,
        playlist_start=1,          # پیش‌فرض (وقتی URL دیکشنری باشد، از مقدار دیکشنری استفاده می‌شود)
        force_download=True,
        yt_dlp_write_subs=True,
        download_subtitles=True,
        playlist_end=playlist_end  # 0 = بدون محدودیت
    )
    
    return result


# ──────────────────────────────────────────────────
#  کانفیگ‌ها
# ──────────────────────────────────────────────────

sbtitle_reverse_urls = {
    'name': 'sbtitle_reverse_urls',
    'reverse_download': True,
    'skip_download': True,        # فقط زیرنویس
    'playlist_end': 0,            # 0 = همه ویدیوها
    'urls': [
        # {"https://youtube.com/playlist?list=XXX": 5},   # از ویدیوی ۵ام از آخر شروع کن
    ]
}

video_reverse_urls = {
    'name': 'video_reverse_urls',
    'reverse_download': True,
    'skip_download': False,       # ویدیو + زیرنویس
    'playlist_end': 0,
    'urls': [
        # "https://www.youtube.com/playlist?list=XXX",
        # {"https://www.youtube.com/playlist?list=XXX": 3},  # از ویدیوی ۳ام از آخر
    ]
}

sbtitle_urls = {
    'name': 'sbtitle_urls',
    'reverse_download': False,
    'skip_download': True,        # فقط زیرنویس
    'playlist_end': 0,
    'urls': [
        # "https://youtube.com/playlist?list=XXX",
    ]
}

video_urls = {
    'name': 'video_urls',
    'reverse_download': False,
    'skip_download': False,       # ویدیو + زیرنویس
    'playlist_end': 0,
    'urls': [
        # ─── مثال‌های مختلف ───

        # ۱) دانلود کل پلی‌لیست از اول تا آخر
        "https://youtube.com/playlist?list=PLF1O-3n-kbQ7z9VwO7Yp_iHKyMIdUQzBE",

        # ۲) شروع از ویدیوی ۸ام (۷ تای اول رد می‌شوند)
        # {"https://youtube.com/playlist?list=PLF1O-3n-kbQ7z9VwO7Yp_iHKyMIdUQzBE": 8},

        # ۳) شروع از ویدیوی ۳ام + فقط ۵ ویدیو دانلود کن
        #    (با playlist_end=5 در کانفیگ بالا)
        # {"https://youtube.com/playlist?list=PLF1O-3n-kbQ7z9VwO7Yp_iHKyMIdUQzBE": 3},
    ]
}


# ──────────────────────────────────────────────────
#  اجرا
# ──────────────────────────────────────────────────

video_list = [sbtitle_reverse_urls, video_reverse_urls, sbtitle_urls, video_urls]

for video in video_list:
    print('*' * 20, video['name'], '*' * 20)
    urls = video['urls']
    if len(urls) > 0:
        download_videos(
            video_urls=urls,
            save_path=save_path,
            reverse_download=video['reverse_download'],
            skip_download=video['skip_download'],
            playlist_end=video.get('playlist_end', 0),
        )
