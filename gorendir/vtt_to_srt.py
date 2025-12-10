import re
import os
from pathlib import Path
from youtube_transcript_api.formatters import SRTFormatter
import logging
from typing import List, Optional
import chardet

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
        if '.' in time_str:
            hms, ms = time_str.split('.')
            ms = ms[:3]  # Keep only milliseconds
        else:
            hms, ms = time_str, '000'
        
        h, m, s = hms.split(':')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
    except Exception as e:
        logger.error(f"Error converting time '{time_str}': {e}")
        return 0.0

def detect_encoding(file_path: Path) -> str:
    """Detect file encoding."""
    try:
        with open(file_path, 'rb') as f:
            raw_data = f.read(10000)  # Read first 10KB for detection
            result = chardet.detect(raw_data)
            encoding = result.get('encoding', 'utf-8')
            # Fallback to common encodings if confidence is low
            if result.get('confidence', 0) < 0.7:
                try:
                    raw_data.decode('utf-8')
                    return 'utf-8'
                except:
                    return 'windows-1256'  # Common for Persian/Arabic
            return encoding
    except Exception as e:
        logger.warning(f"Could not detect encoding for {file_path}: {e}")
        return 'utf-8'

def clean_inline_tags(text: str) -> str:
    """Clean VTT inline tags and formatting."""
    if not text:
        return ""
    
    # Remove timestamp tags
    text = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', text)
    
    # Remove styling tags
    text = re.sub(r'</?[cvbisu]>', '', text, flags=re.IGNORECASE)
    
    # Remove WebVTT comment blocks
    text = re.sub(r'NOTE\s+.*?\n', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    # Fix common issues
    text = re.sub(r'\s*,\s*', ', ', text)  # Fix comma spacing
    text = re.sub(r'\s*\.\s*', '. ', text)  # Fix period spacing
    
    return text

def parse_vtt_blocks(vtt_path: Path) -> List[TranscriptLine]:
    """
    Parse VTT file into TranscriptLine objects with improved error handling.
    """
    transcripts = []
    last_text = ""
    
    try:
        encoding = detect_encoding(vtt_path)
        content = vtt_path.read_text(encoding=encoding)
        
        # Split into blocks (separated by blank lines)
        blocks = re.split(r'\n\s*\n', content.strip())
        
        for block in blocks:
            # Skip header blocks
            if block.startswith('WEBVTT') or block.startswith('NOTE') or '-->' not in block:
                continue
            
            lines = block.strip().split('\n')
            if len(lines) < 2:
                continue
            
            # Parse timestamp line
            time_match = re.match(r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})', lines[0])
            if not time_match:
                continue
            
            try:
                start = convert_to_seconds(time_match.group(1))
                end = convert_to_seconds(time_match.group(2))
                duration = end - start
                
                # Skip invalid durations
                if duration <= 0 or duration > 3600:  # Max 1 hour per subtitle
                    logger.warning(f"Invalid duration {duration}s in {vtt_path.name}")
                    continue
                
                # Combine text lines
                raw_text = ' '.join(lines[1:])
                clean_text = clean_inline_tags(raw_text)
                
                # Skip empty or duplicate text
                if not clean_text or clean_text == last_text:
                    continue
                
                # Validate text length (YouTube limit is about 42 chars per line)
                if len(clean_text) > 200:
                    logger.warning(f"Long subtitle text ({len(clean_text)} chars) in {vtt_path.name}")
                    # Split long text (basic splitting)
                    if len(clean_text) > 500:
                        clean_text = clean_text[:497] + "..."
                
                transcripts.append(TranscriptLine(start, duration, clean_text))
                last_text = clean_text
                
            except Exception as e:
                logger.warning(f"Error parsing block in {vtt_path.name}: {e}")
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
        logger.error(f"VTT file not found: {vtt_path}")
        return None
    
    # Create SRT filename (replace .vtt with .srt)
    srt_path = vtt_path.with_suffix('.srt')
    
    # Skip if SRT already exists and is newer
    if srt_path.exists() and srt_path.stat().st_mtime > vtt_path.stat().st_mtime:
        logger.info(f"SRT already exists and is newer: {srt_path}")
        return srt_path
    
    try:
        logger.info(f"Processing VTT file: {vtt_path.name}")
        
        transcripts = parse_vtt_blocks(vtt_path)
        
        if not transcripts:
            logger.warning(f"No valid transcripts found in {vtt_path.name}")
            return None
        
        # Format as SRT
        formatter = SRTFormatter()
        srt_content = formatter.format_transcript(transcripts)
        
        # Write SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        
        logger.info(f"✅ Converted to SRT: {srt_path.name} ({len(transcripts)} lines)")
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
        logger.error(f"Directory not found: {source_directory}")
        return
    
    if not source_path.is_dir():
        logger.error(f"Path is not a directory: {source_directory}")
        return
    
    logger.info(f"Processing VTT files in: {source_directory}")
    
    # Find VTT files
    if recursive:
        vtt_files = list(source_path.rglob('*.vtt'))
    else:
        vtt_files = list(source_path.glob('*.vtt'))
    
    if not vtt_files:
        logger.info("No VTT files found.")
        return
    
    logger.info(f"Found {len(vtt_files)} VTT file(s)")
    
    successful = 0
    failed = 0
    
    for vtt_file in vtt_files:
        try:
            result = vtt_to_srt_clean(vtt_file)
            if result:
                successful += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Error processing {vtt_file}: {e}")
            failed += 1
    
    logger.info(f"Conversion complete: {successful} successful, {failed} failed")
    
    # Clean up original VTT files if conversion was successful
    if successful > 0 and failed == 0:
        logger.info("Cleaning up original VTT files...")
        for vtt_file in vtt_files:
            try:
                srt_file = vtt_file.with_suffix('.srt')
                if srt_file.exists():
                    vtt_file.unlink()
                    logger.debug(f"Removed: {vtt_file.name}")
            except Exception as e:
                logger.warning(f"Could not remove {vtt_file}: {e}")

def batch_convert(vtt_files: List[Union[str, Path]], output_dir: Optional[Path] = None):
    """
    Batch convert multiple VTT files.
    """
    results = {'success': [], 'failed': []}
    
    for vtt_file in vtt_files:
        try:
            result = vtt_to_srt_clean(vtt_file)
            if result:
                results['success'].append(str(result))
            else:
                results['failed'].append(str(vtt_file))
        except Exception as e:
            results['failed'].append(f"{vtt_file}: {e}")
    
    return results