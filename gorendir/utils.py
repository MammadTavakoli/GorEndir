import os
import re
import pysrt
from tqdm import tqdm
from pathlib import Path
from typing import List, Optional, Generator
import unicodedata
import hashlib

def generate_file_hash(file_path: str, algorithm: str = 'md5') -> str:
    """Generate hash for file."""
    hash_func = hashlib.new(algorithm)
    
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_func.update(chunk)
    
    return hash_func.hexdigest()

def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """
    Sanitize filename for safe filesystem usage.
    
    Args:
        filename: Original filename
        max_length: Maximum length of sanitized filename
        
    Returns:
        Safe filename string
    """
    if not filename:
        return 'untitled'
    
    # Normalize Unicode
    filename = unicodedata.normalize('NFKD', filename)
    
    # Replace problematic characters
    replacements = {
        '/': '⧸',
        '\\': '⧹',
        ':': 'ː',
        '*': '∗',
        '?': '？',
        '"': '＂',
        '<': '＜',
        '>': '＞',
        '|': '｜',
        '｜': '│',
        '：': 'ː'
    }
    
    for old, new in replacements.items():
        filename = filename.replace(old, new)
    
    # Remove remaining invalid characters (Windows + Unix)
    invalid_chars = r'[<>:"/\\|?*\x00-\x1F]'
    filename = re.sub(invalid_chars, '_', filename)
    
    # Remove leading/trailing dots and spaces (Windows restriction)
    filename = filename.strip('. ')
    
    # Replace multiple underscores with single
    filename = re.sub(r'_+', '_', filename)
    
    # Truncate if too long
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        if len(ext) > 20:  # Unusually long extension
            ext = ext[:20]
        # Keep extension, truncate name
        name = name[:max_length - len(ext) - 1]
        filename = name + ext
    
    # Ensure filename is not empty
    if not filename or filename == '.' or filename == '..':
        filename = f'file_{hashlib.md5(filename.encode()).hexdigest()[:8]}'
    
    return filename

def convert_srt_to_text(
    srt_file_path: Union[str, Path],
    append_text: str = '*******',
    output_file: Optional[str] = None,
    clean_text: bool = True
) -> Optional[str]:
    """
    Convert SRT file to plain text with enhanced features.
    
    Args:
        srt_file_path: Path to SRT file
        append_text: Text to append between subtitle lines
        output_file: Optional custom output file path
        clean_text: Whether to clean text (remove formatting)
        
    Returns:
        Path to created text file or None if failed
    """
    try:
        srt_path = Path(srt_file_path)
        
        if not srt_path.exists():
            print(f"❌ File not found: {srt_file_path}")
            return None
        
        # Load subtitles
        subs = pysrt.open(str(srt_path), encoding='utf-8')
        
        if not subs:
            print(f"⚠️ No subtitles found in: {srt_path.name}")
            return None
        
        # Process subtitles
        texts = []
        prev_text = ""
        
        for sub in subs:
            current_text = sub.text
            
            # Clean text if requested
            if clean_text:
                current_text = clean_subtitle_text(current_text)
            
            # Skip duplicates
            if current_text == prev_text:
                continue
            
            # Add to list
            texts.append(current_text)
            prev_text = current_text
        
        # Join with append_text
        full_text = append_text.join(texts)
        
        # Create output filename
        if not output_file:
            output_file = srt_path.with_suffix('.txt')
        else:
            output_file = Path(output_file)
        
        # Enhance formatting
        enhanced_text = enhance_text_formatting(full_text, append_text)
        
        # Write to file
        output_file.write_text(enhanced_text, encoding='utf-8')
        
        print(f"✅ Converted: {srt_path.name} -> {output_file.name}")
        return str(output_file)
        
    except pysrt.exceptions.PysrtError as e:
        print(f"❌ SRT parsing error in {os.path.basename(srt_file_path)}: {e}")
    except UnicodeDecodeError:
        print(f"❌ Encoding error in {os.path.basename(srt_file_path)}")
        # Try different encodings
        try:
            return convert_srt_to_text_with_encoding(srt_file_path, append_text, output_file)
        except:
            return None
    except Exception as e:
        print(f"❌ Failed to process {os.path.basename(srt_file_path)}: {e}")
    
    return None

def convert_srt_to_text_with_encoding(
    srt_file_path: str,
    append_text: str,
    output_file: Optional[str]
) -> Optional[str]:
    """Try to convert SRT with different encodings."""
    encodings = ['utf-8-sig', 'latin-1', 'windows-1256', 'cp1252']
    
    for encoding in encodings:
        try:
            with open(srt_file_path, 'r', encoding=encoding) as f:
                content = f.read()
            
            # Write with UTF-8
            with open(srt_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Retry conversion
            return convert_srt_to_text(srt_file_path, append_text, output_file)
            
        except:
            continue
    
    return None

def clean_subtitle_text(text: str) -> str:
    """Clean subtitle text from formatting."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Remove speaker labels (e.g., "JOHN: Hello")
    text = re.sub(r'^[A-Z][A-Z\s]*:\s*', '', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove music symbols
    text = re.sub(r'♪[^♪]*♪', '', text)
    
    return text.strip()

def enhance_text_formatting(text: str, append_text: str) -> str:
    """Enhance text formatting for better readability."""
    # Replace append_text with appropriate punctuation
    text = text.replace('.' + append_text, '.\n\n')
    text = text.replace('?' + append_text, '?\n\n')
    text = text.replace('!' + append_text, '!\n\n')
    
    # Handle remaining append_text
    text = text.replace(append_text, '\n')
    
    # Fix multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Capitalize sentences
    sentences = re.split(r'([.!?]\s+)', text)
    enhanced = []
    
    for i in range(0, len(sentences), 2):
        if i < len(sentences):
            sentence = sentences[i]
            if i+1 < len(sentences):
                punctuation = sentences[i+1]
            else:
                punctuation = ''
            
            if sentence.strip():
                # Capitalize first letter
                sentence = sentence.strip()
                if sentence:
                    sentence = sentence[0].upper() + sentence[1:]
                enhanced.append(sentence + punctuation)
    
    return ''.join(enhanced)

def convert_all_srt_to_text(
    folder_path: Union[str, Path],
    append_text: str = '*******',
    recursive: bool = True,
    clean_text: bool = True
) -> Dict[str, List[str]]:
    """
    Convert all SRT files in folder to text.
    
    Returns:
        Dictionary with 'success' and 'failed' lists
    """
    folder = Path(folder_path)
    results = {'success': [], 'failed': []}
    
    if not folder.exists():
        print(f"❌ Folder not found: {folder_path}")
        return results
    
    # Find SRT files
    if recursive:
        srt_files = list(folder.rglob('*.srt'))
    else:
        srt_files = list(folder.glob('*.srt'))
    
    if not srt_files:
        print(f"📭 No SRT files found in '{folder_path}'")
        return results
    
    print(f"📂 Found {len(srt_files)} SRT file(s) in '{folder_path}'")
    
    # Process files
    for srt_file in tqdm(srt_files, desc="Converting SRT files", unit="file"):
        try:
            result = convert_srt_to_text(srt_file, append_text, clean_text=clean_text)
            if result:
                results['success'].append(str(srt_file))
            else:
                results['failed'].append(str(srt_file))
        except Exception as e:
            results['failed'].append(f"{srt_file}: {e}")
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Conversion Summary:")
    print(f"  ✅ Success: {len(results['success'])}")
    print(f"  ❌ Failed:  {len(results['failed'])}")
    
    if results['failed']:
        print(f"\nFailed files:")
        for failed in results['failed'][:10]:  # Show first 10 failures
            print(f"  - {failed}")
        if len(results['failed']) > 10:
            print(f"  ... and {len(results['failed']) - 10} more")
    
    print(f"{'='*50}")
    return results

def rename_files_in_folder(
    folder_path: Union[str, Path],
    recursive: bool = True,
    dry_run: bool = False,
    preserve_extensions: bool = True
) -> Dict[str, List[str]]:
    """
    Rename all files in folder with sanitized names.
    
    Args:
        folder_path: Root folder to process
        recursive: Process subfolders
        dry_run: Only show what would be renamed
        preserve_extensions: Keep original file extensions
        
    Returns:
        Dictionary with rename results
    """
    folder = Path(folder_path)
    results = {
        'renamed': [],
        'skipped': [],
        'errors': [],
        'total_processed': 0
    }
    
    if not folder.exists():
        print(f"❌ Folder not found: {folder_path}")
        return results
    
    # Collect files
    if recursive:
        all_files = list(folder.rglob('*'))
    else:
        all_files = list(folder.glob('*'))
    
    # Filter out directories
    files = [f for f in all_files if f.is_file()]
    
    if not files:
        print(f"📭 No files found in '{folder_path}'")
        return results
    
    print(f"📂 Found {len(files)} file(s) to process")
    
    if dry_run:
        print("🚧 DRY RUN - No files will be renamed")
    
    # Process files
    for file_path in tqdm(files, desc="Renaming files", unit="file"):
        results['total_processed'] += 1
        
        try:
            original_name = file_path.name
            original_stem = file_path.stem
            original_ext = file_path.suffix
            
            # Sanitize filename
            if preserve_extensions:
                sanitized_stem = sanitize_filename(original_stem)
                new_name = sanitized_stem + original_ext
            else:
                new_name = sanitize_filename(original_name)
            
            # Skip if no change
            if new_name == original_name:
                results['skipped'].append(str(file_path))
                continue
            
            new_path = file_path.parent / new_name
            
            # Check for naming conflicts
            if new_path.exists():
                # Add hash to avoid conflict
                file_hash = generate_file_hash(str(file_path))[:8]
                new_name = f"{sanitize_filename(original_stem)}_{file_hash}{original_ext}"
                new_path = file_path.parent / new_name
            
            if not dry_run:
                file_path.rename(new_path)
                results['renamed'].append(f"{original_name} -> {new_name}")
            else:
                results['renamed'].append(f"[DRY RUN] {original_name} -> {new_name}")
                
        except Exception as e:
            error_msg = f"{file_path.name}: {e}"
            results['errors'].append(error_msg)
            print(f"❌ Error: {error_msg}")
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Renaming Summary:")
    print(f"  📊 Total processed: {results['total_processed']}")
    print(f"  ✅ Renamed: {len(results['renamed'])}")
    print(f"  ⏭️  Skipped: {len(results['skipped'])}")
    print(f"  ❌ Errors: {len(results['errors'])}")
    
    if results['renamed'] and not dry_run:
        print(f"\nRenamed files (first 5):")
        for renamed in results['renamed'][:5]:
            print(f"  - {renamed}")
        if len(results['renamed']) > 5:
            print(f"  ... and {len(results['renamed']) - 5} more")
    
    if results['errors']:
        print(f"\nErrors (first 5):")
        for error in results['errors'][:5]:
            print(f"  - {error}")
        if len(results['errors']) > 5:
            print(f"  ... and {len(results['errors']) - 5} more")
    
    print(f"{'='*50}")
    
    return results

def find_duplicate_files(folder_path: Union[str, Path], recursive: bool = True) -> Dict[str, List[str]]:
    """
    Find duplicate files by content hash.
    """
    folder = Path(folder_path)
    duplicates = {}
    file_hashes = {}
    
    # Collect files
    if recursive:
        all_files = list(folder.rglob('*'))
    else:
        all_files = list(folder.glob('*'))
    
    files = [f for f in all_files if f.is_file()]
    
    print(f"🔍 Checking {len(files)} files for duplicates...")
    
    for file_path in tqdm(files, desc="Finding duplicates"):
        try:
            file_hash = generate_file_hash(str(file_path))
            
            if file_hash in file_hashes:
                duplicates.setdefault(file_hash, []).append(str(file_path))
            else:
                file_hashes[file_hash] = str(file_path)
        except Exception as e:
            print(f"⚠️ Could not hash {file_path}: {e}")
    
    # Only keep hashes with multiple files
    duplicates = {k: v for k, v in duplicates.items() if len(v) > 1}
    
    if duplicates:
        print(f"\nFound {len(duplicates)} duplicate file group(s)")
        for i, (hash_val, files) in enumerate(duplicates.items()[:5], 1):
            print(f"\nGroup {i} (hash: {hash_val[:8]}...):")
            for file in files:
                print(f"  - {file}")
    else:
        print("🎉 No duplicate files found")
    
    return duplicates