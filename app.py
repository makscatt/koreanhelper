from flask import Flask, request, Response, jsonify
from flask_cors import CORS   
from konlpy.tag import Komoran
import json, re
import os 
import numpy as np
import requests
import psutil
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
from pydub import AudioSegment
from python_speech_features import mfcc

import static_ffmpeg
static_ffmpeg.add_paths()

app = Flask(__name__)
CORS(app) 
app.config['JSON_AS_ASCII'] = False
komoran = Komoran()

def log_memory_usage(stage=""):
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / (1024 * 1024)
    print(f"--- MEMORY USAGE [{stage}]: {memory_mb:.2f} MB")

def load_audio_lightweight(file_path, target_sr=16000, max_duration=10):
    audio = AudioSegment.from_file(file_path)
    
    if len(audio) > max_duration * 1000:
        audio = audio[:max_duration * 1000]
        
    audio = audio.set_channels(1).set_frame_rate(target_sr)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
    
    return samples, target_sr

def compare_pronunciation(original_file_path, user_file_path):
    try:
        TARGET_SR = 16000
        
        original_audio, _ = load_audio_lightweight(original_file_path, target_sr=TARGET_SR)
        user_audio, _ = load_audio_lightweight(user_file_path, target_sr=TARGET_SR)
        
        original_mfcc = mfcc(original_audio, TARGET_SR, winlen=0.025, winstep=0.01, numcep=13, nfilt=26)
        user_mfcc = mfcc(user_audio, TARGET_SR, winlen=0.025, winstep=0.01, numcep=13, nfilt=26)
        
        distance, path = fastdtw(original_mfcc, user_mfcc, dist=euclidean)
        
        normalized_distance = distance / (len(original_mfcc) + len(user_mfcc))
        print(f"=== DEBUG: DISTANCE = {normalized_distance} ===") 
        similarity = max(0, 100 - (normalized_distance * 2)) 

        return {
            "similarity": round(similarity),
            "status": "success"
        }
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {
            "status": "error",
            "message": str(e)
        }

@app.route('/compare-audio', methods=['POST'])
def compare_audio_files():
    log_memory_usage("Request Start")
    if 'user_audio' not in request.files:
        return jsonify({"status": "error", "message": "Файл 'user_audio' не найден"}), 400
    if 'original_video_url' not in request.form:
        return jsonify({"status": "error", "message": "Параметр 'original_video_url' не найден"}), 400

    user_file = request.files['user_audio']
    original_video_url = request.form['original_video_url']

    upload_folder = 'temp_uploads'
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        
    user_path = os.path.join(upload_folder, "user_temp.webm")
    original_path = os.path.join(upload_folder, "original_temp_video")

    try:
        user_file.save(user_path)
        log_memory_usage("User file saved") 

        response = requests.get(original_video_url, stream=True)
        response.raise_for_status()
        with open(original_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        log_memory_usage("Original video downloaded")

        result = compare_pronunciation(original_path, user_path)
        log_memory_usage("Comparison finished")

    except requests.exceptions.RequestException as e:
        return jsonify({"status": "error", "message": f"Не удалось скачать эталонное видео: {e}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"Внутренняя ошибка сервера: {e}"}), 500
    finally:
        if os.path.exists(user_path):
            os.remove(user_path)
        if os.path.exists(original_path):
            os.remove(original_path)
            
    return jsonify(result)

@app.route('/')
def home():
    return "Сервер работает!"

with open('patterns.json', encoding='utf-8') as f:
    patterns = json.load(f)

with open('colors.json', encoding='utf-8') as f:
    colors_data = json.load(f)

combined_colors = colors_data.get('COMBINED', {})
multi_token_colors = colors_data.get('MULTI', {})
word_colors = colors_data.get('WORDS', {})
pos_colors = colors_data.get('POS', {})

with open('komoran_corrections.json', encoding='utf-8') as f:
    komoran_fixes = json.load(f)

with open('komoran_split_rules.json', encoding='utf-8') as f:
    komoran_split_rules = json.load(f)

with open('komoran_surface_overrides.json', encoding='utf-8') as f:
    surface_overrides = {k: [tuple(x) for x in v] for k, v in json.load(f).items()}

def pos_or_override(txt: str):
    key = txt.strip()
    if key in surface_overrides:
        return surface_overrides[key]
    return komoran.pos(txt)

def fix_komoran(tokens):
    fixed = []
    i = 0
    while i < len(tokens):
        replaced = False
        word, pos = tokens[i]
        for rule in komoran_split_rules:
            if re.match(rule['regex'], f"{word}/{pos}"):
                parts = word.split()
                if len(parts) != 2:
                    break 

                left, right = parts[0], parts[1]

                if left.endswith('은'):
                    stem = left[:-1]
                    modifier = '은'
                elif left.endswith('ㄴ'):
                    stem = left[:-1]
                    modifier = 'ㄴ'
                else:
                    break

                fixed_entry = []
                for w, p in rule['split']:
                    if w == "{adj_stem}":
                        w = stem
                    elif w == "{modifier}":
                        w = modifier
                    elif w == "{noun}":
                        w = right
                    fixed_entry.append([w, p])

                fixed.extend(fixed_entry)
                i += 1
                replaced = True
                break
        for n in [4, 3, 2, 1]:
            if i + n <= len(tokens):
                key = ' '.join(f"{w}/{p}" for w, p in tokens[i:i + n])
                if key in komoran_fixes:
                    fixed.extend(komoran_fixes[key])
                    i += n
                    replaced = True
                    break
        if not replaced:
            fixed.append(tokens[i])
            i += 1
    return fixed

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    text = data.get('text', '')
    
    parsed_for_grammar = pos_or_override(text)
    route = ' '.join(f'{word}/{pos}' for word, pos in parsed_for_grammar)
    tokens_raw = parsed_for_grammar
    tokens_with_stems = fix_komoran(tokens_raw)

    route = ' '.join(f'{word}/{pos}' for word, pos in tokens_with_stems)

    def get_combined_color(word, pos):
        key = f"{word}/{pos}"
        for pattern, color in combined_colors.items():
            if re.fullmatch(pattern, key):
                return color
        return word_colors.get(word, pos_colors.get(pos, "#000000"))

    def get_multitoken_colors(route, tokens):
        match_spans = [] 

        for pattern, color in multi_token_colors.items():
            if ' ' in pattern:
                for m in re.finditer(pattern, route):
                    char_start = m.start()
                    char_end = m.end()

                    token_positions = []
                    cursor = 0
                    for i, tok in enumerate(tokens):
                        token_str = f"{tok[0]}/{tok[1]}"
                        if cursor == char_start:
                            start_idx = i
                        cursor += len(token_str)
                        if cursor >= char_end:
                            end_idx = i
                            break
                        cursor += 1
                    match_spans.append((start_idx, end_idx, color))
        return match_spans

    colored_tokens = []
    multi_color_ranges = get_multitoken_colors(route, tokens_with_stems)

    for i, (w, p) in enumerate(tokens_with_stems):
        color = get_combined_color(w, p)
        for start, end, group_color in multi_color_ranges:
            if start <= i <= end:
                color = group_color
                break
        colored_tokens.append({
            "word": w,
            "pos": p,
            "color": color
        })

    final_matches = []
    occupied_spans = []

    for pat in patterns:
        if pat.get('regex_text'):
            for m in re.finditer(pat['regex_text'], route):
                new_start, new_end = m.start(), m.end()
                
                is_subpattern = False
                for start, end in occupied_spans:
                    if new_start >= start and new_end <= end:
                        is_subpattern = True
                        break
                
                if not is_subpattern:
                    final_matches.append({
                        'id': pat['id'],
                        'pattern': pat['pattern'],
                        'meaning': pat['meaning'],
                        'example': pat['example'],
                        'start': new_start
                    })
                    occupied_spans.append((new_start, new_end))

    final_matches.sort(key=lambda x: x['start'])
    for m in final_matches:
        m.pop('start')                

    payload = {
        'tokens':           colored_tokens,
        'grammar_matches':  final_matches
    }
    js = json.dumps(payload, ensure_ascii=False)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)