from setuptools import setup, find_packages

setup(
    name="GorEndir",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "yt-dlp>=2024.1.0",
        "youtube-transcript-api>=0.6.0",
        "pysrt>=1.1.0",
        "tqdm>=4.65.0",
        "pytube>=15.0.0",
        "requests>=2.31.0",
        "chardet>=5.0.0",
    ],
    python_requires=">=3.8",
    description="A Python package to download YouTube videos and subtitles with advanced features.",
    author="Mohammad Tavakoli Heshejin",
    author_email="m.tavakoli.h@gmail.com",
    url="https://github.com/MammadTavakoli/GorEndir",
    license="MIT",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Multimedia :: Video",
    ],
    keywords=["youtube", "downloader", "subtitle", "yt-dlp", "video"],
)
