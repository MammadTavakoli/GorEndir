import os
import re
import pysrt
from pathlib import Path
from typing import List, Dict, Optional, Union
import hashlib

def sanitize_filename(filename: str) -> str:
    """Safe filename generator."""
    # حذف کاراکترهای غیرمجاز سیستم عامل
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # جایگزینی فاصله‌های متعدد
    filename = re.sub(r'\s+', ' ', filename).strip()
    # محدودیت طول فایل
    if len(filename) > 200:
        filename = filename[:200]
    return filename or "untitled"

def convert_srt_to_text(srt_file_path: Union[str, Path], append_text: str = '*******', output_file=None, clean_text=True) -> Optional[str]:
    """Convert SRT to readable text file."""
    try:
        srt_path = Path(srt_file_path)
        if not srt_path.exists(): return None
        
        subs = pysrt.open(str(srt_path), encoding='utf-8')
        texts = []
        seen = set()
        
        for sub in subs:
            txt = sub.text.replace('\n', ' ').strip()
            # حذف تگ‌های HTML اگر clean_text فعال است
            if clean_text:
                txt = re.sub(r'<[^>]+>', '', txt)
            
            if txt and txt not in seen:
                texts.append(txt)
                seen.add(txt)
        
        full_text = f"\n{append_text}\n".join(texts)
        
        out_path = output_file if output_file else srt_path.with_suffix('.txt')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(full_text)
            
        return str(out_path)
    except Exception as e:
        print(f"Error converting {srt_file_path}: {e}")
        return None

def convert_all_srt_to_text(folder_path: Union[str, Path], append_text: str = '*******'):
    folder = Path(folder_path)
    for srt_file in folder.rglob('*.srt'):
        convert_srt_to_text(srt_file, append_text)

def rename_files_in_folder(folder_path, recursive=True):
    # پیاده‌سازی ساده‌شده برای جلوگیری از پیچیدگی
    pass
