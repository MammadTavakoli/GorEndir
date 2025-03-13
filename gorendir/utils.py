import os
import re
import pysrt
from tqdm import tqdm  # For progress bars

import re


def sanitize_filename_2(filename: str) -> str:
    """
    Sanitizes filenames to include Unicode letters, numbers, and spaces.
    - Replaces all invalid characters (including '/') with underscores.
    - Collapses underscores, trims edges, and handles empty results.
    """
    sanitized = re.sub(r'[^\w\s]', '_', filename, flags=re.UNICODE)
    sanitized = re.sub(r'_+', '_', sanitized).strip(' _')
    return sanitized or 'untitled'

def sanitize_filename(filename):
    """
    Sanitizes a filename by replacing invalid characters with underscores.
    Replaces '/' with '⧸' before handling other invalid characters.
    """
    # Replace '/' with '⧸'
    filename = filename.replace('/', '⧸')
    
    # Replace other invalid characters with underscores
    invalid_chars_pattern = r'[<>:"/\\|｜?*：]'
    return re.sub(invalid_chars_pattern, '_', filename)

def convert_srt_to_text(srt_file_path, append_text='*******'):
    """
    Converts an .srt subtitle file to a plain text file.

    :param srt_file_path: Path to the .srt file.
    :param append_text: Text to append between subtitle lines (default: '*******').
    """
    try:
        subs = pysrt.open(srt_file_path)
        texts = ''
        for sub in subs:
            texts += sub.text.replace('\n', ' ') + append_text

        # Construct the text file path
        basename_without_ext = os.path.splitext(os.path.basename(srt_file_path))[0]
        dirname = os.path.dirname(srt_file_path)
        text_file_path = os.path.join(dirname, basename_without_ext + '.txt')

        # Write to the text file and clean up the text
        with open(text_file_path, 'w', encoding='utf-8') as text_file:
            texts = texts.replace('.' + append_text, '.\n\n')
            texts = texts.replace('?' + append_text, '?\n\n')
            texts = texts.replace(append_text, ' ')
            text_file.write(texts)
            
    except Exception as e:
        print(f"❌ Failed to process file: {os.path.basename(srt_file_path)}")
        print(f"   Error: {e}")

def convert_all_srt_to_text(folder_path, append_text='*******'):
    """
    Converts all .srt files in a folder (and subfolders) to plain text.

    :param folder_path: Path to the folder containing .srt files.
    :param append_text: Text to append between subtitle lines (default: '*******').
    """
    # Get all .srt files in the folder and subfolders
    srt_files = []
    for dirpath, _, filenames in os.walk(folder_path):
        for filename in filenames:
            if filename.lower().endswith(".srt"):
                srt_files.append(os.path.join(dirpath, filename))

    # Process files with a progress bar
    if srt_files:
        print(f"📂 Found {len(srt_files)} .srt files in '{folder_path}'", "\n")
        for srt_file in tqdm(srt_files, desc="Converting files", unit="file"):          
            convert_srt_to_text(srt_file, append_text)    
        print("\n", "------", '\n')
    else:
        print(f"❌ No .srt files found in '{folder_path}'")

def rename_files_in_folder(folder_path):
    """
    Renames all files in the specified folder and its subfolders by sanitizing filenames.

    Args:
        folder_path: Path to the folder containing files to rename.
    """
    # Collect total number of files for tqdm progress bar
    total_files = sum(len(filenames) for _, _, filenames in os.walk(folder_path))

    # Initialize tqdm progress bar
    with tqdm(total=total_files, desc="Renaming files") as pbar:
        # Walk through all files and subfolders
        for folder_name, _, filenames in os.walk(folder_path):
            for filename in filenames:
                # Sanitize the filename
                new_filename = sanitize_filename_2(filename)

                # Create full file paths
                old_file_path = os.path.join(folder_name, filename)
                new_file_path = os.path.join(folder_name, new_filename)

                # Rename the file if the name has changed
                if old_file_path != new_file_path:
                    try:
                        os.rename(old_file_path, new_file_path)
                    except Exception as e:
                        print(f"Error renaming {old_file_path}: {e}")

                # Update the progress bar
                pbar.update(1)
    print("\n", "🎉 All files processed!")
