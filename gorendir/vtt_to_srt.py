import re
from pathlib import Path
from youtube_transcript_api.formatters import SRTFormatter
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TranscriptLine:
    def __init__(self, start, duration, text):
        self.start = start
        self.duration = duration
        self.text = text

def convert_to_seconds(time_str):
    h, m, s = time_str.split(":")
    s, ms = s.split(".")
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

def clean_inline_tags(text):
    text = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', text)
    text = re.sub(r'</?c>', '', text)
    return text.strip()

def parse_vtt_blocks(vtt_path):
    """
    خواندن فایل vtt و تقسیم به بلوک‌هایی که هر بلوک مجموعه خطوط پشت سر هم بدون خط خالی است
    حذف بلوک‌هایی که حتی یک خطشان شامل <c> است.
    بازگرداندن لیستی از خطوط تمیز (TranscriptLine)
    """
    with open(vtt_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # حذف هدرهای اولیه (WEBVTT و ...)
    content_lines = []
    header_done = False
    for line in lines:
        if header_done:
            content_lines.append(line.rstrip('\n'))
        else:
            if line.strip() == '':
                header_done = True

    # گروه‌بندی خطوط به بلوک‌های پاراگرافی (جداشده با خط خالی)
    blocks = []
    current_block = []
    for line in content_lines:
        if line.strip() == '':
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(line)
    if current_block:
        blocks.append(current_block)

    # حذف بلوک‌هایی که حداقل یک خطشان شامل <c> است
    filtered_blocks = []
    for block in blocks:
        if any('<c>' in l for l in block):
            # رد کردن کل بلوک
            continue
        filtered_blocks.append(block)

    # حالا هر بلوک را به SubtitleLines تبدیل می‌کنیم
    transcript = []
    last_text = ""

    for block in filtered_blocks:
        if len(block) < 2:
            continue
        # خط اول باید timestamp باشد
        time_match = re.match(r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})', block[0])
        if not time_match:
            continue

        start = convert_to_seconds(time_match.group(1))
        end = convert_to_seconds(time_match.group(2))
        duration = end - start

        raw_text = " ".join(block[1:])
        clean_text = clean_inline_tags(raw_text)

        # حذف خطوط تکراری یا خالی
        if clean_text == last_text or not clean_text.strip():
            continue

        transcript.append(TranscriptLine(start, duration, clean_text))
        last_text = clean_text

    return transcript

def vtt_to_srt_clean(vtt_path):
    vtt_path = Path(vtt_path)
    srt_path = vtt_path.with_suffix("._.srt")

    logger.info(f"Parsing and cleaning VTT file: {vtt_path}")
    transcript = parse_vtt_blocks(vtt_path)

    formatter = SRTFormatter()
    srt_content = formatter.format_transcript(transcript)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    logger.info(f"✅ Cleaned SRT saved to: {srt_path}")

def process_directory(source_directory):
    """
    Finds all .vtt files in a directory and its subdirectories and converts them to SRT.
    """
    source_path = Path(source_directory)
    if not source_path.is_dir():
        logger.error(f"Path '{source_directory}' is not a valid directory.")
        return

    logger.info(f"Starting recursive processing of VTT files in directory: {source_directory}")
    
    found_files = 0
    processed_files = 0

    # rglob searches recursively in the source directory and all its subdirectories.
    for vtt_file in source_path.rglob('*.vtt'):
        found_files += 1
        logger.info(f"Found VTT file: {vtt_file}")
        try:
            vtt_to_srt_clean(vtt_file)
            processed_files += 1
        except Exception as e:
            logger.error(f"Error processing file '{vtt_file}': {e}")

# # ---------- نقطه ورودی برنامه ----------
# if __name__ == "__main__":
#     # از کاربر بخواهید مسیر پوشه مبدا را وارد کند
#     # یا می‌توانید یک مسیر پیش‌فرض را اینجا تنظیم کنید.
#     # source_folder = input("لطفاً مسیر پوشه مبدا را وارد کنید (مثال: C:\\Users\\YourUser\\Videos): ")
    
#     # مثال: استفاده از پوشه جاری به عنوان پوشه مبدا
#     source_folder = os.getcwd() 
#     # اگر می‌خواهید یک مسیر خاص را تست کنید، خط بالا را کامنت کرده و خط زیر را فعال کنید:
#     # source_folder = r'C:\Users\YourUser\Videos\MyTranscripts' 

#     if source_folder:
#         process_directory(source_folder)
#     else:
#         logger.warning("مسیر پوشه مبدا وارد نشد. برنامه متوقف شد.")

