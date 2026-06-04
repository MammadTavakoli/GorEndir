import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional, Union
import hashlib

logger = logging.getLogger("gorendir")

# ──────────────────────────────────────────────────────────────
# Shared filename sanitizer (single source of truth)
# ──────────────────────────────────────────────────────────────
def sanitize_filename(filename: str) -> str:
    """
    Safe filename generator — single source of truth for the whole project.
    
    - Removes OS-invalid characters: <>:"/\\|?*
    - Normalizes whitespace (collapse multiple spaces to one)
    - Preserves spaces (readability over legacy underscore replacement)
    - Truncates to 200 characters
    - Falls back to 'untitled' if result is empty
    """
    if not isinstance(filename, str):
        filename = str(filename)
    
    # Remove invalid characters for all major OSes
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Normalize whitespace
    filename = re.sub(r'\s+', ' ', filename).strip()
    # Truncate to avoid OS path limits (255 chars for most filesystems)
    if len(filename) > 200:
        filename = filename[:200].strip()
    return filename or "untitled"


def file_hash(filepath: Union[str, Path], algorithm: str = 'md5', chunk_size: int = 8192) -> Optional[str]:
    """Calculate hash of a file for deduplication or verification."""
    try:
        h = hashlib.new(algorithm)
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.warning(f"Failed to hash {filepath}: {e}")
        return None


def convert_srt_to_text(
    srt_file_path: Union[str, Path],
    append_text: str = '*******',
    output_file: Optional[Union[str, Path]] = None,
    clean_text: bool = True,
    remove_duplicates: bool = True
) -> Optional[str]:
    """
    Convert SRT subtitle file to readable text file.
    
    Args:
        srt_file_path: Path to the SRT file
        append_text: Separator text between subtitle entries
        output_file: Custom output path (defaults to same name with .txt extension)
        clean_text: If True, remove HTML tags from text
        remove_duplicates: If True, remove duplicate text lines
    
    Returns:
        Path to the output text file, or None on failure
    """
    try:
        import pysrt
        
        srt_path = Path(srt_file_path)
        if not srt_path.exists():
            logger.warning(f"SRT file not found: {srt_file_path}")
            return None
        
        subs = pysrt.open(str(srt_path), encoding='utf-8')
        texts = []
        seen = set()
        
        for sub in subs:
            txt = sub.text.replace('\n', ' ').strip()
            
            # Remove HTML tags if clean_text is enabled
            if clean_text:
                txt = re.sub(r'<[^>]+>', '', txt)
                txt = txt.strip()
            
            # Skip empty lines
            if not txt:
                continue
            
            # Skip duplicates if enabled
            if remove_duplicates and txt in seen:
                continue
            
            texts.append(txt)
            if remove_duplicates:
                seen.add(txt)
        
        full_text = f"\n{append_text}\n".join(texts)
        
        out_path = Path(output_file) if output_file else srt_path.with_suffix('.txt')
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(full_text)
            
        logger.info(f"Converted SRT -> TXT: {out_path.name} ({len(texts)} lines)")
        return str(out_path)
        
    except ImportError:
        logger.error("pysrt is not installed. Run: pip install pysrt")
        return None
    except Exception as e:
        logger.error(f"Error converting {srt_file_path}: {e}")
        return None


def convert_all_srt_to_text(
    folder_path: Union[str, Path],
    append_text: str = '*******',
    clean_text: bool = True,
    remove_duplicates: bool = True
) -> Dict[str, int]:
    """
    Convert all SRT files in a directory to text files.
    
    Args:
        folder_path: Directory to search for SRT files
        append_text: Separator text between subtitle entries
        clean_text: If True, remove HTML tags
        remove_duplicates: If True, remove duplicate lines
    
    Returns:
        Dict with 'converted' and 'failed' counts
    """
    folder = Path(folder_path)
    stats = {'converted': 0, 'failed': 0, 'skipped': 0}
    
    if not folder.is_dir():
        logger.error(f"Path is not a directory: {folder_path}")
        return stats
    
    for srt_file in folder.rglob('*.srt'):
        # Skip files that are already converted (same name with .txt exists)
        txt_file = srt_file.with_suffix('.txt')
        if txt_file.exists() and txt_file.stat().st_size > 10:
            stats['skipped'] += 1
            continue
            
        result = convert_srt_to_text(srt_file, append_text, clean_text=clean_text, remove_duplicates=remove_duplicates)
        if result:
            stats['converted'] += 1
        else:
            stats['failed'] += 1
    
    logger.info(f"SRT->TXT conversion complete: {stats['converted']} converted, {stats['skipped']} skipped, {stats['failed']} failed")
    return stats


def rename_files_in_folder(
    folder_path: Union[str, Path],
    pattern: Optional[str] = None,
    recursive: bool = True
) -> int:
    """
    Rename files in a folder based on a pattern.
    
    Args:
        folder_path: Directory containing files to rename
        pattern: Regex pattern for matching (not yet implemented)
        recursive: If True, rename files in subdirectories too
    
    Returns:
        Number of files renamed
    """
    # Placeholder for future implementation
    logger.info(f"rename_files_in_folder called for {folder_path} (not yet implemented)")
    return 0
