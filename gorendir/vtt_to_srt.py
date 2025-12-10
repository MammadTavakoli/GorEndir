import re
import logging
from pathlib import Path
# خط زیر بسیار مهم است و باعث رفع خطای شما می‌شود
from typing import List, Optional, Union 
from youtube_transcript_api.formatters import SRTFormatter

# سعی در ایمپورت chardet، اگر نبود utf-8 پیش‌فرض است
try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False

logger = logging.getLogger(__name__)

class TranscriptLine:
    """Represents a single subtitle line."""
    def __init__(self, start: float, duration: float, text: str):
        self.start = start
        self.duration = duration
        self.text = text
        
    def __repr__(self):
        return f"TranscriptLine(start={self.start}, duration={self.duration}, text='{self.text[:50]}...')"

def convert_to_seconds(time_str: str) -> float:
    """Convert VTT time format to seconds."""
    try:
        # مدیریت فرمت‌های مختلف زمان (با یا بدون میلی‌ثانیه)
        if '.' in time_str:
            main, ms = time_str.split('.')
            ms = int(ms[:3].ljust(3, '0'))
        elif ',' in time_str: # گاهی اوقات فرمت srt ممکن است قاطی شود
            main, ms = time_str.split(',')
            ms = int(ms[:3].ljust(3, '0'))
        else:
            main, ms = time_str, 0
            
        parts = main.split(':')
        if len(parts) == 3: # HH:MM:SS
            h, m, s = parts
        elif len(parts) == 2: # MM:SS
            h, m, s = 0, parts[0], parts[1]
        else:
            return 0.0
        
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
    except Exception as e:
        # logger.warning(f"Error converting time '{time_str}': {e}")
        return 0.0

def detect_encoding(file_path: Path) -> str:
    """Detect file encoding."""
    if not HAS_CHARDET:
        return 'utf-8'
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)
            result = chardet.detect(raw_data)
            if result.get('confidence', 0) > 0.7:
                return result.get('encoding', 'utf-8')
            return 'utf-8'
    except Exception:
        return 'utf-8'

def clean_inline_tags(text: str) -> str:
    """Clean VTT inline tags and formatting."""
    if not text:
        return ""
    
    # حذف تگ‌های زمان و استایل
    text = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', text)
    text = re.sub(r'</?[^>]+>', '', text)
    
    # حذف کامنت‌های WebVTT
    text = re.sub(r'NOTE\s+.*?\n', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # تمیزکاری فاصله‌ها
    text = text.replace('&nbsp;', ' ')
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def parse_vtt_blocks(vtt_path: Path) -> List[TranscriptLine]:
    """Parse VTT file into TranscriptLine objects."""
    transcripts = []
    
    try:
        encoding = detect_encoding(vtt_path)
        # استفاده از errors='replace' برای جلوگیری از کرش کردن در کاراکترهای عجیب
        content = vtt_path.read_text(encoding=encoding, errors='replace')
        
        # جدا کردن بلوک‌ها با خط خالی
        blocks = re.split(r'\n\s*\n', content.strip())
        
        for block in blocks:
            # نادیده گرفتن هدرها
            if block.startswith('WEBVTT') or block.startswith('NOTE') or '-->' not in block:
                continue
            
            lines = block.strip().split('\n')
            if len(lines) < 2:
                continue
            
            # پیدا کردن خط زمان
            time_line_idx = -1
            for i, line in enumerate(lines):
                if '-->' in line:
                    time_line_idx = i
                    break
            
            if time_line_idx == -1:
                continue
            
            # استخراج زمان
            time_match = re.search(r'(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})', lines[time_line_idx])
            
            if not time_match:
                continue
            
            try:
                start = convert_to_seconds(time_match.group(1))
                end = convert_to_seconds(time_match.group(2))
                duration = end - start
                
                # ترکیب خطوط متنی (خطوط بعد از زمان)
                raw_text = ' '.join(lines[time_line_idx+1:])
                clean_text = clean_inline_tags(raw_text)
                
                if clean_text:
                    transcripts.append(TranscriptLine(start, duration, clean_text))
                
            except Exception:
                continue
        
    except Exception as e:
        logger.error(f"Failed to parse VTT file {vtt_path}: {e}")
        return []
    
    return transcripts

def vtt_to_srt_clean(vtt_path: Union[str, Path]) -> Optional[Path]:
    """
    Convert VTT file to clean SRT format.
    Returns path to SRT file if successful.
    """
    vtt_path = Path(vtt_path)
    if not vtt_path.exists():
        return None
    
    srt_path = vtt_path.with_suffix('.srt')
    
    # اگر فایل srt وجود دارد و حجمش منطقی است، دوباره نساز
    if srt_path.exists() and srt_path.stat().st_size > 10:
        return srt_path
    
    try:
        transcripts = parse_vtt_blocks(vtt_path)
        
        if not transcripts:
            return None
        
        # فرمت دهی به SRT
        formatter = SRTFormatter()
        srt_content = formatter.format_transcript(transcripts)
        
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        
        return srt_path
        
    except Exception as e:
        logger.error(f"❌ Failed to convert {vtt_path.name}: {e}")
        return None

def process_directory(source_directory: Union[str, Path], recursive: bool = True):
    """
    Convert all VTT files in directory to SRT format.
    """
    source_path = Path(source_directory)
    
    if not source_path.exists():
        return
    
    if recursive:
        vtt_files = list(source_path.rglob('*.vtt'))
    else:
        vtt_files = list(source_path.glob('*.vtt'))
    
    for vtt_file in vtt_files:
        vtt_to_srt_clean(vtt_file)
