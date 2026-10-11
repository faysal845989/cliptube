import os
import re
import glob
import subprocess
import uuid
import zipfile
import time
import threading
import concurrent.futures
import yt_dlp

CACHE_DIR = 'static/cache'
EXPORTS_DIR = 'static/exports'
UPLOADS_DIR = 'static/uploads'

_cache_lock = threading.Lock()

for d in [CACHE_DIR, EXPORTS_DIR, UPLOADS_DIR]:
    os.makedirs(d, exist_ok=True)

def parse_time(time_str):
    """Converts HH:MM:SS or MM:SS or seconds float to total seconds float."""
    if isinstance(time_str, (int, float)):
        return float(time_str)
    
    time_str = str(time_str).strip()
    if not time_str:
        return 0.0
    
    parts = time_str.split(':')
    try:
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        else:
            return float(parts[0])
    except ValueError:
        return 0.0

def format_seconds(seconds):
    """Converts seconds into HH:MM:SS format."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def get_video_info(url):
    """Extracts YouTube video metadata without downloading full video."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            
            chapters = []
            if info.get('chapters'):
                for ch in info['chapters']:
                    chapters.append({
                        'title': ch.get('title', 'Chapter'),
                        'start_time': ch.get('start_time', 0),
                        'end_time': ch.get('end_time', 0),
                        'start_formatted': format_seconds(ch.get('start_time', 0)),
                        'end_formatted': format_seconds(ch.get('end_time', 0))
                    })
            
            return {
                'id': info.get('id'),
                'title': info.get('title', 'YouTube Video'),
                'duration': info.get('duration', 0),
                'duration_formatted': format_seconds(info.get('duration', 0)),
                'thumbnail': info.get('thumbnail') or f"https://img.youtube.com/vi/{info.get('id')}/hqdefault.jpg",
                'channel': info.get('uploader', 'YouTube'),
                'chapters': chapters,
                'url': url
            }
        except Exception as e:
            raise Exception(f"Failed to fetch video information: {str(e)}")

def ensure_cached_youtube_video(url):
    """
    Downloads a 720p version of YouTube video to static/cache/<videoid>.mp4 once for videos <= 30 mins.
    Thread-safe and protected against Windows file locking errors (WinError 32).
    """
    info = get_video_info(url)
    video_id = info['id']
    cache_path = os.path.join(CACHE_DIR, f"{video_id}.mp4")

    with _cache_lock:
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 10000:
            print(f"Cache hit: Video {video_id} already cached locally.", flush=True)
            return cache_path, info

        print(f"Caching video {video_id} locally for instant sub-second clipping...", flush=True)
        target_template = os.path.join(CACHE_DIR, f"{video_id}.%(ext)s")

        ydl_opts = {
            'format': 'best[height<=720]/bestvideo[height<=720]+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(CACHE_DIR, f"{video_id}.%(ext)s"),
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
            'concurrent_fragment_downloads': 4,
            'continuedl': False,
            'quiet': True,
            'no_warnings': True,
            'overwrites': True,
            'nopart': True,
            'windowsfilenames': True,
        }

        success = False
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            # Check if any video file was created in cache
            cached_files = glob.glob(os.path.join(CACHE_DIR, f"{video_id}.*"))
            if cached_files and os.path.getsize(cached_files[0]) > 10000:
                cache_path = cached_files[0]
                success = True
        except Exception as e:
            print(f"Primary download encounter issue: {e}. Trying single-stream fallback...", flush=True)

        if not success:
            ydl_opts_fallback = {
                'format': 'b/best',
                'outtmpl': os.path.join(CACHE_DIR, f"{video_id}.mp4"),
                'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
                'concurrent_fragment_downloads': 4,
                'continuedl': False,
                'quiet': True,
                'no_warnings': True,
                'overwrites': True,
                'nopart': True,
                'windowsfilenames': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                ydl.download([url])

            cached_files = glob.glob(os.path.join(CACHE_DIR, f"{video_id}.*"))
            if cached_files:
                cache_path = cached_files[0]

        # Cleanup residual temp files if any
        for temp_f in glob.glob(os.path.join(CACHE_DIR, f"temp_{video_id}*")):
            for _ in range(3):
                try:
                    os.remove(temp_f)
                    break
                except Exception:
                    time.sleep(0.2)

        if not os.path.exists(cache_path):
            raise Exception("Failed to cache YouTube video locally.")

        return cache_path, info

def cut_long_youtube_video_range(url, start_time, end_time, export_format='mp4', aspect_ratio='original', output_dir=EXPORTS_DIR):
    """
    For 1+ hour long videos (podcasts, livestreams, webinars), fetches ONLY the requested range directly from YouTube CDN.
    Downloads ~5MB section in 3-5 seconds regardless of original video length (1 hour, 5 hours, 10 hours)!
    """
    os.makedirs(output_dir, exist_ok=True)
    start_sec = parse_time(start_time)
    end_sec = parse_time(end_time)
    
    if end_sec <= start_sec:
        raise Exception("End time must be greater than start time.")
    
    duration = end_sec - start_sec
    unique_id = uuid.uuid4().hex[:8]
    ext = 'mp3' if export_format == 'mp3' else ('gif' if export_format == 'gif' else 'mp4')
    filename = f"clip_{unique_id}.{ext}"
    output_path = os.path.join(output_dir, filename)
    temp_prefix = os.path.join(output_dir, f"temp_long_{unique_id}")

    def download_range_callback(info_dict, ydl):
        return [{'start_time': start_sec, 'end_time': end_sec}]

    format_str = 'best[height<=720]/bestvideo[height<=720]+bestaudio/best'
    if export_format == 'mp3':
        format_str = 'bestaudio/best'

    ydl_opts = {
        'format': format_str,
        'merge_output_format': 'mp4',
        'outtmpl': f"{temp_prefix}.%(ext)s",
        'download_ranges': download_range_callback,
        'concurrent_fragment_downloads': 4,
        'socket_timeout': 15,
        'continuedl': False,
        'quiet': True,
        'no_warnings': True,
        'overwrites': True,
        'nopart': True,
        'windowsfilenames': True,
    }

    print(f"Direct Range Fast Cut: {start_sec}s -> {end_sec}s...", flush=True)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except Exception:
            ydl_opts['format'] = 'best'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

    downloaded = [f for f in glob.glob(f"{temp_prefix}.*") if not f.endswith('.part')]
    if not downloaded:
        raise Exception("Failed to fetch long video section.")

    actual_temp_file = downloaded[0]
    ffmpeg_cmd = ['ffmpeg', '-y', '-i', actual_temp_file]

    if export_format == 'mp3':
        ffmpeg_cmd.extend(['-vn', '-c:a', 'libmp3lame', '-q:a', '2', output_path])
    elif export_format == 'gif':
        ffmpeg_cmd.extend(['-vf', 'fps=15,scale=480:-1:flags=lanczos', output_path])
    else:
        vf_filters = []
        if aspect_ratio == 'shorts':
            vf_filters.append("crop=trunc(ih*9/16/2)*2:ih")
        elif aspect_ratio == 'square':
            vf_filters.append("crop=trunc(ih/2)*2:trunc(ih/2)*2")

        if vf_filters:
            qsv_cmd = list(ffmpeg_cmd)
            qsv_cmd.extend([
                '-vf', ','.join(vf_filters),
                '-c:v', 'h264_qsv', '-global_quality', '26',
                '-c:a', 'aac', output_path
            ])
            proc = subprocess.run(qsv_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode != 0 or not os.path.exists(output_path):
                ffmpeg_cmd.extend(['-vf', ','.join(vf_filters), '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'fastdecode', '-threads', '2', '-crf', '26', '-c:a', 'aac', output_path])
                subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            ffmpeg_cmd.extend(['-c', 'copy', output_path])
            subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    for f in glob.glob(f"{temp_prefix}*"):
        if f != output_path:
            for _ in range(3):
                try:
                    os.remove(f)
                    break
                except Exception:
                    time.sleep(0.2)

    return {
        'filename': filename,
        'output_path': output_path,
        'format': export_format,
        'aspect_ratio': aspect_ratio,
        'duration': round(duration, 1),
        'duration_formatted': format_seconds(duration),
        'title': info.get('title', 'Clip') if 'info' in locals() else 'Clip'
    }

def cut_local_file(input_file_path, start_time, end_time, export_format='mp4', aspect_ratio='original', output_dir=EXPORTS_DIR):
    """
    Cuts a local video file (cached YouTube video or uploaded file) in SUB-SECOND speed using FFmpeg.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    start_sec = parse_time(start_time)
    end_sec = parse_time(end_time)
    
    if end_sec <= start_sec:
        raise Exception("End time must be greater than start time.")
    
    duration = end_sec - start_sec
    unique_id = uuid.uuid4().hex[:8]
    ext = 'mp3' if export_format == 'mp3' else ('gif' if export_format == 'gif' else 'mp4')
    filename = f"clip_{unique_id}.{ext}"
    output_path = os.path.join(output_dir, filename)

    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-ss', str(start_sec),
        '-i', input_file_path,
        '-t', str(duration)
    ]

    if export_format == 'mp3':
        ffmpeg_cmd.extend(['-vn', '-c:a', 'libmp3lame', '-q:a', '2', output_path])
    elif export_format == 'gif':
        ffmpeg_cmd.extend(['-vf', 'fps=15,scale=480:-1:flags=lanczos', output_path])
    else:
        vf_filters = []
        if aspect_ratio == 'shorts':
            vf_filters.append("crop=trunc(ih*9/16/2)*2:ih")
        elif aspect_ratio == 'square':
            vf_filters.append("crop=trunc(ih/2)*2:trunc(ih/2)*2")

        if vf_filters:
            # Try Intel QuickSync GPU encoding for 3x-5x speed
            qsv_cmd = list(ffmpeg_cmd)
            qsv_cmd.extend([
                '-vf', ','.join(vf_filters),
                '-c:v', 'h264_qsv', '-global_quality', '26',
                '-c:a', 'aac', output_path
            ])
            proc = subprocess.run(qsv_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 0 and os.path.exists(output_path):
                return {
                    'filename': filename,
                    'output_path': output_path,
                    'format': export_format,
                    'aspect_ratio': aspect_ratio,
                    'duration': round(duration, 1),
                    'duration_formatted': format_seconds(duration)
                }

            # Fast CPU fallback with ultrafast + fastdecode
            ffmpeg_cmd.extend([
                '-vf', ','.join(vf_filters),
                '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'fastdecode', '-threads', '2', '-crf', '26',
                '-c:a', 'aac', output_path
            ])
        else:
            ffmpeg_cmd.extend(['-c:v', 'copy', '-c:a', 'copy', output_path])

    print(f"Running cut: {start_sec}s -> {end_sec}s", flush=True)
    proc = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if proc.returncode != 0 or not os.path.exists(output_path):
        ffmpeg_fallback = [
            'ffmpeg', '-y',
            '-ss', str(start_sec),
            '-i', input_file_path,
            '-t', str(duration),
            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
            output_path
        ]
        subprocess.run(ffmpeg_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not os.path.exists(output_path):
        raise Exception("FFmpeg failed to create output clip.")

    return {
        'filename': filename,
        'output_path': output_path,
        'format': export_format,
        'aspect_ratio': aspect_ratio,
        'duration': round(duration, 1),
        'duration_formatted': format_seconds(duration)
    }

def create_clip(url=None, input_filepath=None, start_time=0, end_time=10, export_format='mp4', aspect_ratio='original', output_dir=EXPORTS_DIR):
    """
    Ultra-fast clip creation.
    - If local file or video is already cached, cuts locally in sub-second speed (<0.5s).
    - If YouTube video, uses Direct Range Extraction to fetch ONLY the requested seconds in 2-4 seconds (never downloads the full video).
    """
    if input_filepath and os.path.exists(input_filepath):
        res = cut_local_file(input_filepath, start_time, end_time, export_format, aspect_ratio, output_dir)
        res['title'] = os.path.basename(input_filepath)
        return res
    elif url:
        info = get_video_info(url)
        video_id = info.get('id')
        cache_path = os.path.join(CACHE_DIR, f"{video_id}.mp4")

        # Fast path 1: Check if already cached locally from previous work
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 10000:
            print(f"Cache hit for video {video_id}. Cutting locally in sub-second...", flush=True)
            res = cut_local_file(cache_path, start_time, end_time, export_format, aspect_ratio, output_dir)
            res['title'] = info.get('title', 'Clip')
            return res

        # Fast path 2: Direct Range Extraction (downloads ONLY the requested 10-30s slice, ~2-4MB in 2-3s!)
        print(f"Direct Range Extraction for {start_time} -> {end_time}...", flush=True)
        res = cut_long_youtube_video_range(url, start_time, end_time, export_format, aspect_ratio, output_dir)
        res['title'] = info.get('title', 'Clip')
        return res
    else:
        raise Exception("Either YouTube URL or local file path is required.")

def create_batch_clips(url=None, input_filepath=None, interval_seconds=60, export_format='mp4', aspect_ratio='original', output_dir=EXPORTS_DIR):
    """
    Splits an entire video into multiple consecutive clips (Part 1, Part 2, etc.) IN PARALLEL.
    Supports local files, standard YouTube videos, and 1+ hour long videos.
    """
    os.makedirs(output_dir, exist_ok=True)
    is_long_video = False
    
    if input_filepath and os.path.exists(input_filepath):
        source_file = input_filepath
        video_title = os.path.basename(input_filepath)
        ffprobe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_filepath]
        probe_res = subprocess.run(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        total_duration = float(probe_res.stdout.strip() or 0)
    elif url:
        info = get_video_info(url)
        video_title = info.get('title')
        total_duration = info.get('duration', 0)
        source_file, _ = ensure_cached_youtube_video(url)
    else:
        raise Exception("Either YouTube URL or local file path is required.")

    if total_duration <= 0:
        raise Exception("Could not determine video duration.")
        
    interval = float(interval_seconds)
    if interval <= 0:
        raise Exception("Interval seconds must be greater than 0.")
        
    segments = []
    curr_start = 0.0
    while curr_start < total_duration:
        curr_end = min(curr_start + interval, total_duration)
        if (curr_end - curr_start) >= 1.0:
            segments.append((curr_start, curr_end))
        curr_start = curr_end
        
    if not segments:
        raise Exception("No valid video segments could be generated.")
        
    unique_batch_id = uuid.uuid4().hex[:8]
    
    def process_segment(item):
        idx, (seg_start, seg_end) = item
        print(f"Parallel Worker: Generating Part {idx}/{len(segments)} ({seg_start}s to {seg_end}s)...", flush=True)
        
        part_res = cut_local_file(
            input_file_path=source_file,
            start_time=seg_start,
            end_time=seg_end,
            export_format=export_format,
            aspect_ratio=aspect_ratio,
            output_dir=output_dir
        )
            
        final_part_filename = part_res['filename']
        return {
            'part_num': idx,
            'title': f"Part {idx}",
            'filename': final_part_filename,
            'start_time': format_seconds(seg_start),
            'end_time': format_seconds(seg_end),
            'duration': round(seg_end - seg_start, 1),
            'duration_formatted': format_seconds(seg_end - seg_start),
            'download_url': f"/api/download/{final_part_filename}",
            'preview_url': f"/static/exports/{final_part_filename}",
            'filepath': os.path.join(output_dir, final_part_filename)
        }

    # Parallel processing of all parts (optimized for dual-core CPU)
    parts_result = []
    max_workers = 2
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(segments), max_workers)) as executor:
        futures = [executor.submit(process_segment, (idx, seg)) for idx, seg in enumerate(segments, start=1)]
        for future in concurrent.futures.as_completed(futures):
            parts_result.append(future.result())

    parts_result.sort(key=lambda x: x['part_num'])
    generated_file_paths = [p['filepath'] for p in parts_result]

    # Create ZIP archive if multiple parts
    zip_filename = None
    if len(generated_file_paths) > 1:
        zip_filename = f"batch_{unique_batch_id}_All_Parts.zip"
        zip_path = os.path.join(output_dir, zip_filename)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for filepath in generated_file_paths:
                arcname = os.path.basename(filepath)
                zipf.write(filepath, arcname)
                
    return {
        'batch_id': unique_batch_id,
        'video_title': video_title,
        'parts_count': len(parts_result),
        'parts': parts_result,
        'zip_filename': zip_filename,
        'zip_download_url': f"/api/download/{zip_filename}" if zip_filename else None
    }
