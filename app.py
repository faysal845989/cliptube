import os
import uuid
import subprocess
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from clipper import get_video_info, create_clip, create_batch_clips, format_seconds

app = Flask(__name__)
EXPORTS_DIR = os.path.join(app.root_path, 'static', 'exports')
UPLOADS_DIR = os.path.join(app.root_path, 'static', 'uploads')
CACHE_DIR = os.path.join(app.root_path, 'static', 'cache')

for d in [EXPORTS_DIR, UPLOADS_DIR, CACHE_DIR]:
    os.makedirs(d, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'mkv', 'mov', 'avi', 'webm', 'mp3', 'm4a'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def video_info():
    data = request.get_json()
    if not data or not data.get('url'):
        return jsonify({'error': 'YouTube URL is required.'}), 400
    
    url = data['url'].strip()
    try:
        info = get_video_info(url)
        return jsonify({'success': True, 'data': info})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded.'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected.'}), 400
    
    if file and allowed_file(file.filename):
        s_filename = secure_filename(file.filename)
        unique_prefix = uuid.uuid4().hex[:8]
        saved_filename = f"upload_{unique_prefix}_{s_filename}"
        filepath = os.path.join(UPLOADS_DIR, saved_filename)
        file.save(filepath)
        
        # Probe video duration using ffprobe
        ffprobe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', filepath]
        probe_res = subprocess.run(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        duration = float(probe_res.stdout.strip() or 0)
        
        return jsonify({
            'success': True,
            'data': {
                'title': s_filename,
                'filepath': filepath,
                'filename': saved_filename,
                'duration': duration,
                'duration_formatted': format_seconds(duration),
                'channel': 'Local File Upload',
                'url': f"/static/uploads/{saved_filename}"
            }
        })
    
    return jsonify({'error': 'Invalid file format. Please upload MP4, MKV, MOV, AVI, or WEBM.'}), 400

@app.route('/api/clip', methods=['POST'])
def clip_video():
    data = request.get_json() or {}
    url = data.get('url', '').strip() if data.get('url') else None
    input_filepath = data.get('filepath', '').strip() if data.get('filepath') else None
    
    if not url and not input_filepath:
        return jsonify({'error': 'YouTube URL or uploaded file path is required.'}), 400
    
    start_time = data.get('start_time', 0)
    end_time = data.get('end_time', 10)
    export_format = data.get('format', 'mp4')
    aspect_ratio = data.get('aspect_ratio', 'original')
    
    try:
        result = create_clip(
            url=url,
            input_filepath=input_filepath,
            start_time=start_time,
            end_time=end_time,
            export_format=export_format,
            aspect_ratio=aspect_ratio,
            output_dir=EXPORTS_DIR
        )
        return jsonify({'success': True, 'clip': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/batch-clip', methods=['POST'])
def batch_clip_video():
    data = request.get_json() or {}
    url = data.get('url', '').strip() if data.get('url') else None
    input_filepath = data.get('filepath', '').strip() if data.get('filepath') else None
    
    if not url and not input_filepath:
        return jsonify({'error': 'YouTube URL or uploaded file path is required.'}), 400
        
    interval_seconds = data.get('interval_seconds', 60)
    export_format = data.get('format', 'mp4')
    aspect_ratio = data.get('aspect_ratio', 'original')
    
    try:
        result = create_batch_clips(
            url=url,
            input_filepath=input_filepath,
            interval_seconds=interval_seconds,
            export_format=export_format,
            aspect_ratio=aspect_ratio,
            output_dir=EXPORTS_DIR
        )
        return jsonify({'success': True, 'batch': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<filename>')
def download_clip(filename):
    response = send_from_directory(EXPORTS_DIR, filename, as_attachment=True)
    # If auto-delete requested via query param
    if request.args.get('autodelete') == 'true':
        def delayed_delete():
            import time
            time.sleep(10)
            file_path = os.path.join(EXPORTS_DIR, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
        import threading
        threading.Thread(target=delayed_delete, daemon=True).start()
    return response

def cleanup_old_files(max_age_minutes=30):
    """Automatically removes clips, cache, and uploads older than max_age_minutes."""
    import time
    now = time.time()
    for directory in [EXPORTS_DIR, CACHE_DIR, UPLOADS_DIR]:
        if os.path.exists(directory):
            for f in os.listdir(directory):
                fp = os.path.join(directory, f)
                if os.path.isfile(fp):
                    try:
                        if (now - os.path.getmtime(fp)) > (max_age_minutes * 60):
                            os.remove(fp)
                    except Exception:
                        pass

@app.route('/api/storage-info', methods=['GET'])
def get_storage_info():
    total_size = 0
    file_count = 0
    for directory in [EXPORTS_DIR, CACHE_DIR, UPLOADS_DIR]:
        if os.path.exists(directory):
            for f in os.listdir(directory):
                fp = os.path.join(directory, f)
                if os.path.isfile(fp):
                    file_count += 1
                    total_size += os.path.getsize(fp)
    size_mb = round(total_size / (1024 * 1024), 2)
    return jsonify({'file_count': file_count, 'size_mb': size_mb})

@app.route('/api/clips/clear-all', methods=['POST'])
def clear_all_storage():
    """Deletes all generated clips, caches, and uploaded temporary files immediately."""
    deleted_count = 0
    freed_bytes = 0
    for directory in [EXPORTS_DIR, CACHE_DIR, UPLOADS_DIR]:
        if os.path.exists(directory):
            for f in os.listdir(directory):
                fp = os.path.join(directory, f)
                if os.path.isfile(fp):
                    try:
                        freed_bytes += os.path.getsize(fp)
                        os.remove(fp)
                        deleted_count += 1
                    except Exception:
                        pass
    freed_mb = round(freed_bytes / (1024 * 1024), 2)
    return jsonify({'success': True, 'deleted': deleted_count, 'freed_mb': freed_mb})

@app.route('/api/clips', methods=['GET'])
def list_clips():
    cleanup_old_files(max_age_minutes=30)
    clips = []
    if os.path.exists(EXPORTS_DIR):
        for f in os.listdir(EXPORTS_DIR):
            if (f.startswith('clip_') or f.startswith('batch_')) and (f.endswith('.mp4') or f.endswith('.mp3') or f.endswith('.gif') or f.endswith('.zip')):
                file_path = os.path.join(EXPORTS_DIR, f)
                try:
                    size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
                    mtime = os.path.getmtime(file_path)
                    clips.append({
                        'filename': f,
                        'size_mb': size_mb,
                        'mtime': mtime,
                        'download_url': f'/api/download/{f}',
                        'preview_url': f'/static/exports/{f}'
                    })
                except Exception:
                    pass
    clips.sort(key=lambda x: x['mtime'], reverse=True)
    return jsonify({'success': True, 'clips': clips})

@app.route('/api/clips/<filename>', methods=['DELETE'])
def delete_clip(filename):
    file_path = os.path.join(EXPORTS_DIR, filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            return jsonify({'success': True, 'message': 'Clip deleted.'})
        except Exception as e:
            return jsonify({'error': f'Could not delete file: {str(e)}'}), 400
    return jsonify({'error': 'File not found.'}), 404

if __name__ == '__main__':
    print("Starting YouTube & Local Video Clipper App on http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

