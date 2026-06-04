import re
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Use project logger
logger = logging.getLogger("gorendir")


class TranscriptLine:
    """Represents a single subtitle line with timing information."""
    
    def __init__(self, start: float, duration: float, text: str):
        self.start = start
        self.duration = duration
        self.text = text
    
    def __repr__(self):
        return f"TranscriptLine(start={self.start:.3f}, duration={self.duration:.3f}, text={self.text[:50]!r})"


def convert_to_seconds(time_str: str) -> float:
    """
    Convert VTT timestamp (HH:MM:SS.mmm) to seconds.
    
    Handles both full format (00:01:23.456) and short format (01:23.456).
    """
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        raise ValueError(f"Invalid time format: {time_str}")
    
    s, ms = s.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def clean_inline_tags(text: str) -> str:
    """Remove VTT inline tags like <c>, <00:00:00.000>, etc."""
    text = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', text)
    text = re.sub(r'</?c>', '', text)
    # Also clean common VTT formatting tags
    text = re.sub(r'</?b>', '', text)
    text = re.sub(r'</?i>', '', text)
    text = re.sub(r'</?u>', '', text)
    text = re.sub(r'<[^>]+>', '', text)  # Catch-all for any remaining tags
    return text.strip()


def parse_vtt_blocks(vtt_path: Path) -> List[TranscriptLine]:
    """
    Parse a VTT file into clean TranscriptLine objects.
    
    - Removes header sections
    - Filters out blocks with karaoke-style <c> tags
    - Deduplicates consecutive identical text
    - Cleans inline tags
    """
    encodings = ['utf-8', 'utf-8-sig', 'latin-1']
    lines = None
    
    for enc in encodings:
        try:
            with open(vtt_path, 'r', encoding=enc) as f:
                lines = f.readlines()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    if lines is None:
        logger.error(f"Could not read VTT file with any encoding: {vtt_path}")
        return []

    # Remove header (everything before first blank line)
    content_lines = []
    header_done = False
    for line in lines:
        if header_done:
            content_lines.append(line.rstrip('\n'))
        else:
            if line.strip() == '':
                header_done = True

    # Group lines into blocks (separated by blank lines)
    blocks: List[List[str]] = []
    current_block: List[str] = []
    for line in content_lines:
        if line.strip() == '':
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(line)
    if current_block:
        blocks.append(current_block)

    # Filter out blocks containing karaoke-style <c> tags
    filtered_blocks = []
    for block in blocks:
        if any('<c>' in line for line in block):
            continue
        filtered_blocks.append(block)

    # Parse each block into TranscriptLine
    transcript: List[TranscriptLine] = []
    last_text = ""
    
    # Flexible timestamp pattern (handles both HH:MM:SS.mmm and MM:SS.mmm)
    timestamp_pattern = re.compile(
        r'(\d{1,2}:?\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{1,2}:?\d{2}:\d{2}\.\d{3})'
    )

    for block in filtered_blocks:
        if len(block) < 2:
            continue
        
        # First line should be a timestamp
        time_match = timestamp_pattern.match(block[0])
        if not time_match:
            continue

        try:
            start = convert_to_seconds(time_match.group(1))
            end = convert_to_seconds(time_match.group(2))
            duration = end - start
        except (ValueError, IndexError) as e:
            logger.debug(f"Skipping block with invalid timestamp: {block[0]} ({e})")
            continue

        raw_text = " ".join(block[1:])
        clean_text = clean_inline_tags(raw_text)

        # Skip duplicates or empty lines
        if clean_text == last_text or not clean_text.strip():
            continue

        transcript.append(TranscriptLine(start, duration, clean_text))
        last_text = clean_text

    return transcript


def vtt_to_srt_clean(vtt_path: Path, output_suffix: str = ".clean.srt") -> Optional[Path]:
    """
    Convert a VTT file to a clean SRT file.
    
    Args:
        vtt_path: Path to the source VTT file
        output_suffix: Suffix for the output SRT file (default: .clean.srt)
    
    Returns:
        Path to the created SRT file, or None on failure
    """
    vtt_path = Path(vtt_path)
    
    # Create output path with clean suffix instead of weird "._.srt"
    srt_path = vtt_path.with_suffix(output_suffix)

    logger.info(f"Parsing and cleaning VTT file: {vtt_path.name}")
    transcript = parse_vtt_blocks(vtt_path)

    if not transcript:
        logger.warning(f"No transcript data extracted from {vtt_path.name}")
        return None

    # Format as SRT
    srt_lines = []
    for idx, line in enumerate(transcript, 1):
        start_h = int(line.start // 3600)
        start_m = int((line.start % 3600) // 60)
        start_s = int(line.start % 60)
        start_ms = int((line.start % 1) * 1000)
        
        end_time = line.start + line.duration
        end_h = int(end_time // 3600)
        end_m = int((end_time % 3600) // 60)
        end_s = int(end_time % 60)
        end_ms = int((end_time % 1) * 1000)
        
        srt_lines.append(f"{idx}")
        srt_lines.append(
            f"{start_h:02d}:{start_m:02d}:{start_s:02d},{start_ms:03d} --> "
            f"{end_h:02d}:{end_m:02d}:{end_s:02d},{end_ms:03d}"
        )
        srt_lines.append(line.text)
        srt_lines.append("")  # Blank line between entries

    srt_content = "\n".join(srt_lines)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    logger.info(f"✅ Cleaned SRT saved to: {srt_path.name} ({len(transcript)} lines)")
    return srt_path


def process_directory(source_directory) -> Dict[str, int]:
    """
    Find all .vtt files in a directory and convert them to clean SRT.
    
    Args:
        source_directory: Path to search for VTT files
    
    Returns:
        Dict with 'processed', 'failed', 'skipped' counts
    """
    source_path = Path(source_directory)
    stats = {'processed': 0, 'failed': 0, 'skipped': 0}
    
    if not source_path.is_dir():
        logger.error(f"Path '{source_directory}' is not a valid directory.")
        return stats

    logger.info(f"Starting VTT->SRT processing in: {source_directory}")
    
    vtt_files = list(source_path.rglob('*.vtt'))
    logger.info(f"Found {len(vtt_files)} VTT file(s)")

    for vtt_file in vtt_files:
        # Check if already converted
        clean_srt = vtt_file.with_suffix(".clean.srt")
        if clean_srt.exists() and clean_srt.stat().st_size > 10:
            logger.debug(f"Already converted: {vtt_file.name}")
            stats['skipped'] += 1
            continue
            
        try:
            result = vtt_to_srt_clean(vtt_file)
            if result:
                stats['processed'] += 1
            else:
                stats['failed'] += 1
        except Exception as e:
            logger.error(f"Error processing '{vtt_file.name}': {e}")
            stats['failed'] += 1

    logger.info(
        f"VTT->SRT complete: {stats['processed']} processed, "
        f"{stats['skipped']} skipped, {stats['failed']} failed"
    )
    return stats
