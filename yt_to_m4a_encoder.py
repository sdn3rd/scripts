import argparse
import subprocess
import os
from yt_dlp import YoutubeDL

def download_audio(url, temp_file_base):
    """Download audio from YouTube using yt-dlp without appending extra extensions."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_file_base + '.%(ext)s',  # Ensure no preset extension
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'postprocessor_args': [
            '-metadata', 'title=Downloaded with ytencode.py'
        ],
        'quiet': False,  # Set to True to reduce yt-dlp output
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    # After extraction, the file should be temp_file_base.mp3
    expected_file = temp_file_base + '.mp3'
    if os.path.exists(expected_file):
        return expected_file
    else:
        raise FileNotFoundError(f"Expected temp audio file '{expected_file}' not found after download.")

def convert_audio(input_file, output_file):
    """Convert the downloaded audio to AAC format using ffmpeg."""
    try:
        subprocess.run([
            'ffmpeg', '-y',  # Overwrite output file if it exists
            '-i', input_file,
            '-map', '0:a',
            '-c:a', 'aac',
            '-b:a', '98k',
            '-ar', '22050',
            output_file
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print(f"Error during conversion: {e.stderr.decode().strip()}")
        exit(1)

def main():
    parser = argparse.ArgumentParser(description="Download and convert YouTube audio to AAC format.")
    parser.add_argument('url', help="The YouTube URL to download.")
    parser.add_argument('output', help="The output filename (e.g., output.m4a).")
    args = parser.parse_args()

    temp_file_base = "temp_audio"

    try:
        print(f"Downloading audio from: {args.url}")
        actual_temp_file = download_audio(args.url, temp_file_base)

        print(f"Converting to AAC format: {args.output}")
        convert_audio(actual_temp_file, args.output)

        print(f"Conversion completed successfully! Output saved to: {args.output}")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Cleanup temporary files
        temp_files = [temp_file_base + ext for ext in ['.mp3']]
        for file in temp_files:
            if os.path.exists(file):
                os.remove(file)

if __name__ == "__main__":
        main()

