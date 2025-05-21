from setuptools import setup, find_packages

setup(
    name="GorEndir",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "yt-dlp",
        "yt-dlp[browser-cookies]",
        "youtube-transcript-api",
        "colorama",       
        "pysrt",
        "copy",
        "tqdm",
        "pytube3"
    ],
    description="A Python package to download YouTube videos and subtitles.",
    author="mohammad tavakoli heshejin",
    author_email="m.tavakoli.h@gmail.com",
    url="https://github.com/MammadTavakoli/GorEndir",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
