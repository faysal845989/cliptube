import os
import re
import sys
import time
import json
import logging
import requests

# Fix Windows console UTF-8 encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Load .env file manually if exists
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    print("TELEGRAM_BOT_TOKEN is missing in .env file!")
    sys.exit(1)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

from clipper import get_video_info, create_clip, create_batch_clips, EXPORTS_DIR

user_states = {}

def extract_youtube_url(text):
    if not text:
        return None
    url_pattern = r'(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/(?:watch\?v=|embed/|v/|shorts/)?[\w-]+[^\s]*)'
    match = re.search(url_pattern, text)
    return match.group(0) if match else None

def parse_duration_to_seconds(text):
    """
    Parses user input into total seconds.
    Examples:
    '30s' -> 30, '1m' or '1' -> 60, '2' or '2m' -> 120, '1.5' -> 90, '3m' -> 180
    """
    text = text.strip().lower()
    try:
        if text.endswith('m') or text.endswith('min') or text.endswith('mins'):
            clean = text.replace('mins', '').replace('min', '').replace('m', '').strip()
            return int(float(clean) * 60)
        elif text.endswith('s') or text.endswith('sec') or text.endswith('secs'):
            clean = text.replace('secs', '').replace('sec', '').replace('s', '').strip()
            return int(float(clean))
        else:
            val = float(text)
            if val <= 15: # User entered 1, 2, 3, 5, 1.5 -> treat as minutes
                return int(val * 60)
            return int(val) # User entered 30, 45, 90 -> treat as seconds
    except Exception:
        return 60 # Default fallback

def send_message(chat_id, text, reply_markup=None, parse_mode='Markdown'):
    data = {'chat_id': chat_id, 'text': text}
    if parse_mode:
        data['parse_mode'] = parse_mode
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    try:
        r = requests.post(f"{API_URL}/sendMessage", data=data, timeout=15)
        return r.json()
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return None

def send_photo(chat_id, photo_url, caption="", reply_markup=None, parse_mode='Markdown'):
    data = {'chat_id': chat_id, 'photo': photo_url, 'caption': caption}
    if parse_mode:
        data['parse_mode'] = parse_mode
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    try:
        r = requests.post(f"{API_URL}/sendPhoto", data=data, timeout=15)
        return r.json()
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        return send_message(chat_id, caption, reply_markup=reply_markup, parse_mode=parse_mode)

def send_file(chat_id, file_path, file_type='video', caption="", parse_mode='Markdown'):
    endpoint = "sendVideo" if file_type == 'video' else ("sendAudio" if file_type == 'audio' else "sendDocument")
    key = "video" if file_type == 'video' else ("audio" if file_type == 'audio' else "document")
    
    data = {'chat_id': chat_id, 'caption': caption}
    if parse_mode:
        data['parse_mode'] = parse_mode
        
    try:
        with open(file_path, 'rb') as f:
            files = {key: f}
            r = requests.post(f"{API_URL}/{endpoint}", data=data, files=files, timeout=600)
            return r.json()
    except Exception as e:
        logger.error(f"Error sending file {file_path}: {e}")
        return None

def answer_callback_query(callback_query_id, text=""):
    try:
        requests.post(f"{API_URL}/answerCallbackQuery", data={'callback_query_id': callback_query_id, 'text': text}, timeout=10)
    except Exception:
        pass

def delete_message(chat_id, message_id):
    try:
        requests.post(f"{API_URL}/deleteMessage", data={'chat_id': chat_id, 'message_id': message_id}, timeout=10)
    except Exception:
        pass

def edit_message_text(chat_id, message_id, text, parse_mode='Markdown', reply_markup=None):
    try:
        data = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
        if parse_mode:
            data['parse_mode'] = parse_mode
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        requests.post(f"{API_URL}/editMessageText", data=data, timeout=15)
    except Exception:
        pass

def handle_update(update):
    if 'message' in update:
        msg = update['message']
        chat_id = msg['chat']['id']
        text = msg.get('text', '').strip()
        
        if not text:
            return

        # Handle Start command
        if text.startswith('/start') or text.startswith('/help'):
            welcome = (
                "🎬 **Welcome to auto cliper Bot!** (@autocliperfabot)\n\n"
                "Send me any YouTube video link to clip or split into Reels/Shorts automatically!\n\n"
                "📌 **Supported Aspect Ratios & Formats:**\n"
                "• 📱 **9:16 Vertical** (TikTok / Reels / Shorts)\n"
                "• 🔳 **1:1 Square** (Facebook Feed / Instagram Post)\n"
                "• 🔄 **Both (9:16 & 1:1)** (Generates Both Videos!)\n"
                "• 🎵 **Audio MP3**\n\n"
                "📌 **Batch Split:** Set custom minutes (e.g. 1m, 2m, 3m, 5m, 30s)!\n\n"
                "💡 *Usage:* Simply paste any YouTube link here!"
            )
            send_message(chat_id, welcome)
            return

        # Check if user is awaiting batch interval input
        if chat_id in user_states and user_states[chat_id].get('awaiting_batch_time'):
            st = user_states.pop(chat_id)
            url = st['url']
            
            interval_sec = parse_duration_to_seconds(text)
            interval_display = f"{interval_sec}s" if interval_sec < 60 else f"{round(interval_sec/60, 1)}m"

            status_res = send_message(chat_id, f"📦 Batch splitting video into {interval_display} clips... Please wait...")
            msg_id = status_res['result']['message_id'] if status_res and 'result' in status_res else None

            try:
                res = create_batch_clips(url=url, interval_seconds=interval_sec)
                if res.get('zip_filename'):
                    zip_path = os.path.join(EXPORTS_DIR, res['zip_filename'])
                    send_file(chat_id, zip_path, file_type='document', caption=f"📦 Batch Split Complete ({interval_display} per clip): {res['parts_count']} parts")
                else:
                    for part in res['parts']:
                        send_file(chat_id, part['filepath'], file_type='video', caption=f"🎬 {part['title']} ({part['start_time']} - {part['end_time']})")

                if msg_id:
                    delete_message(chat_id, msg_id)
            except Exception as e:
                logger.error(f"Error batch clipping: {e}", exc_info=True)
                if msg_id:
                    edit_message_text(chat_id, msg_id, f"❌ Error: {str(e)}")
            return

        # Check if user is in an active state waiting for start/end time input
        if chat_id in user_states and user_states[chat_id].get('awaiting_time'):
            st = user_states.pop(chat_id)
            url = st['url']
            opt = st.get('mode', 'clip')
            
            time_parts = text.split()
            if len(time_parts) < 2:
                send_message(chat_id, "⚠️ Please enter Start and End time separated by space (e.g. `0:10 0:40` or `10 40`).")
                return

            start_t, end_t = time_parts[0], time_parts[1]
            fmt = 'mp3' if opt == 'mp3' else 'mp4'

            status_res = send_message(chat_id, f"⚡ Creating clip ({start_t} to {end_t})... Please wait...")
            msg_id = status_res['result']['message_id'] if status_res and 'result' in status_res else None

            try:
                if opt == 'both':
                    # Create BOTH 9:16 Shorts and 1:1 Square
                    res_shorts = create_clip(url=url, start_time=start_t, end_time=end_t, export_format='mp4', aspect_ratio='shorts')
                    res_square = create_clip(url=url, start_time=start_t, end_time=end_t, export_format='mp4', aspect_ratio='square')

                    caption_shorts = f"📱 **9:16 Vertical Reel** ({start_t} - {end_t})\n🎬 {res_shorts.get('title', 'Clip')}"
                    send_file(chat_id, res_shorts['output_path'], file_type='video', caption=caption_shorts)

                    caption_square = f"🔳 **1:1 Square Feed Video** ({start_t} - {end_t})\n🎬 {res_square.get('title', 'Clip')}"
                    send_file(chat_id, res_square['output_path'], file_type='video', caption=caption_square)

                    try:
                        os.remove(res_shorts['output_path'])
                        os.remove(res_square['output_path'])
                    except Exception:
                        pass
                else:
                    aspect = 'shorts' if opt == 'shorts' else ('square' if opt == 'square' else 'original')
                    res = create_clip(url=url, start_time=start_t, end_time=end_t, export_format=fmt, aspect_ratio=aspect)
                    output_path = res['output_path']
                    
                    ratio_tag = "📱 9:16 Vertical" if aspect == 'shorts' else ("🔳 1:1 Square" if aspect == 'square' else "🎬 Original")
                    caption = f"{ratio_tag} **{res.get('title', 'Clip')}**\n⏱ Duration: {res['duration_formatted']} ({start_t} - {end_t})"

                    send_file(chat_id, output_path, file_type='audio' if fmt=='mp3' else 'video', caption=caption)
                    try:
                        os.remove(output_path)
                    except Exception:
                        pass

                if msg_id:
                    delete_message(chat_id, msg_id)

            except Exception as e:
                logger.error(f"Error creating clip: {e}", exc_info=True)
                if msg_id:
                    edit_message_text(chat_id, msg_id, f"❌ Error creating clip: {str(e)}")
                else:
                    send_message(chat_id, f"❌ Error creating clip: {str(e)}")
            return

        # Check if text contains a YouTube URL
        yt_url = extract_youtube_url(text)
        if yt_url:
            status_res = send_message(chat_id, "🔍 Fetching YouTube video details...")
            msg_id = status_res['result']['message_id'] if status_res and 'result' in status_res else None

            try:
                info = get_video_info(yt_url)
                if msg_id:
                    delete_message(chat_id, msg_id)

                user_states[chat_id] = {'url': yt_url, 'info': info}

                caption = (
                    f"🎥 **{info['title']}**\n"
                    f"👤 Channel: {info['channel']}\n"
                    f"⏱ Duration: {info['duration_formatted']}\n\n"
                    f"Select your format & ratio below 👇"
                )

                keyboard = {
                    'inline_keyboard': [
                        [
                            {'text': '📱 9:16 Shorts', 'callback_data': 'opt_shorts'},
                            {'text': '🔳 1:1 Square', 'callback_data': 'opt_square'}
                        ],
                        [
                            {'text': '🔄 Both (9:16 & 1:1)', 'callback_data': 'opt_both'},
                            {'text': '✂️ Custom 16:9 Clip', 'callback_data': 'opt_clip'}
                        ],
                        [
                            {'text': '📦 Batch Split (Custom Mins)', 'callback_data': 'opt_batch_custom'},
                            {'text': '🎵 Audio MP3', 'callback_data': 'opt_mp3'}
                        ]
                    ]
                }

                if info.get('thumbnail'):
                    send_photo(chat_id, info['thumbnail'], caption=caption, reply_markup=keyboard)
                else:
                    send_message(chat_id, caption, reply_markup=keyboard)

            except Exception as e:
                logger.error(f"Error fetching video info: {e}", exc_info=True)
                if msg_id:
                    edit_message_text(chat_id, msg_id, f"❌ Failed to fetch video info: {str(e)}")
                else:
                    send_message(chat_id, f"❌ Failed to fetch video info: {str(e)}")

    elif 'callback_query' in update:
        cb = update['callback_query']
        cb_id = cb['id']
        chat_id = cb['message']['chat']['id']
        data = cb['data']

        state = user_states.get(chat_id)
        if not state:
            answer_callback_query(cb_id, "Session expired. Send link again.")
            return

        url = state['url']

        # Handle Preset Batch Split duration buttons (e.g., preset_batch_60)
        if data.startswith('preset_batch_'):
            seconds = int(data.replace('preset_batch_', ''))
            answer_callback_query(cb_id, f"Splitting into {seconds}s clips...")
            
            interval_display = f"{seconds}s" if seconds < 60 else f"{int(seconds/60)}m"
            status_res = send_message(chat_id, f"📦 Batch splitting video into {interval_display} clips... Please wait...")
            msg_id = status_res['result']['message_id'] if status_res and 'result' in status_res else None

            try:
                res = create_batch_clips(url=url, interval_seconds=seconds)
                if res.get('zip_filename'):
                    zip_path = os.path.join(EXPORTS_DIR, res['zip_filename'])
                    send_file(chat_id, zip_path, file_type='document', caption=f"📦 Batch Split Complete ({interval_display} clips): {res['parts_count']} parts")
                else:
                    for part in res['parts']:
                        send_file(chat_id, part['filepath'], file_type='video', caption=f"🎬 {part['title']} ({part['start_time']} - {part['end_time']})")

                if msg_id:
                    delete_message(chat_id, msg_id)
            except Exception as e:
                logger.error(f"Error batch clipping: {e}", exc_info=True)
                if msg_id:
                    edit_message_text(chat_id, msg_id, f"❌ Error: {str(e)}")
            return

        opt = data.replace('opt_', '')

        if opt == 'batch_custom':
            answer_callback_query(cb_id)
            user_states[chat_id]['awaiting_batch_time'] = True
            
            prompt = (
                "📦 **Custom Batch Split Duration**\n\n"
                "Please select or type your desired clip length:\n"
                "• Type `1` or `1m` for 1 minute clips\n"
                "• Type `2` or `2m` for 2 minute clips\n"
                "• Type `3` or `3m` for 3 minute clips\n"
                "• Type `30s` for 30 second clips\n"
                "• Or type any number (e.g., `1.5` for 1.5 minutes)"
            )

            preset_keyboard = {
                'inline_keyboard': [
                    [
                        {'text': '⏱ 30 Secs', 'callback_data': 'preset_batch_30'},
                        {'text': '⏱ 1 Minute', 'callback_data': 'preset_batch_60'},
                    ],
                    [
                        {'text': '⏱ 2 Minutes', 'callback_data': 'preset_batch_120'},
                        {'text': '⏱ 3 Minutes', 'callback_data': 'preset_batch_180'},
                    ],
                    [
                        {'text': '⏱ 5 Minutes', 'callback_data': 'preset_batch_300'},
                    ]
                ]
            }
            send_message(chat_id, prompt, reply_markup=preset_keyboard)
            return

        answer_callback_query(cb_id)
        user_states[chat_id]['mode'] = opt
        user_states[chat_id]['awaiting_time'] = True

        mode_name = "Audio MP3" if opt == 'mp3' else ("9:16 Shorts" if opt == 'shorts' else ("1:1 Square Video" if opt == 'square' else ("Both 9:16 & 1:1 Videos" if opt == 'both' else "16:9 Video Clip")))
        prompt = (
            f"✂️ Selected Mode: **{mode_name}**\n\n"
            f"Please send the **Start and End time** for your clip.\n\n"
            f"Examples:\n"
            f"• `0:10 0:40` (10s to 40s)\n"
            f"• `1:30 3:00` (1m30s to 3m)\n"
            f"• `10 40` (10s to 40s)"
        )
        send_message(chat_id, prompt)

def main():
    print("Telegram Bot (@autocliperfabot) started successfully!")
    print("Listening for messages on Telegram...")
    offset = 0
    while True:
        try:
            r = requests.get(f"{API_URL}/getUpdates", params={'offset': offset, 'timeout': 20}, timeout=25)
            res = r.json()
            if res.get('ok'):
                for update in res.get('result', []):
                    offset = update['update_id'] + 1
                    try:
                        handle_update(update)
                    except Exception as err:
                        logger.error(f"Error handling update: {err}", exc_info=True)
        except Exception as e:
            logger.error(f"Network error in polling loop: {e}")
            time.sleep(3)

if __name__ == '__main__':
    main()
