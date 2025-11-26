# 1. FFMPEG FIRST
import static_ffmpeg
static_ffmpeg.add_paths()

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

app = Flask(__name__)
CORS(app) 
app.config['JSON_AS_ASCII'] = False
komoran = Komoran()

def log_memory_usage(stage=""):
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / (1024 * 1024)
    print(f"--- MEMORY USAGE [{stage}]: {memory_mb:.2f} MB", flush=True)

# 1. Функция обрезки тишины (Оставляем, она работает хорошо)
def trim_silence(audio_samples, threshold=0.02):
    magnitude = np.abs(audio_samples)
    if np.max(magnitude) < threshold:
        return audio_samples 
        
    start_idx = 0
    for i, sample in enumerate(magnitude):
        if sample > threshold:
            start_idx = i
            break
            
    end_idx = len(audio_samples)
    for i in range(len(magnitude) - 1, 0, -1):
        if magnitude[i] > threshold:
            end_idx = i + 1
            break
            
    return audio_samples[start_idx:end_idx]

# 2. Загрузка аудио (Простая версия + обрезка тишины)
def load_and_prep_audio(file_path, target_sr=16000):
    audio = AudioSegment.from_file(file_path)
    audio = audio.set_channels(1).set_frame_rate(target_sr)
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
    
    # Нормализация громкости
    if np.max(np.abs(samples)) > 0:
        samples = samples / np.max(np.abs(samples))
    
    # Режем тишину
    samples = trim_silence(samples, threshold=0.03)
    
    return samples, target_sr

def compare_pronunciation(original_file_path, user_file_path):
    try:
        log_memory_usage("Start")
        TARGET_SR = 16000
        
        orig_samples, _ = load_and_prep_audio(original_file_path, TARGET_SR)
        user_samples, _ = load_and_prep_audio(user_file_path, TARGET_SR)
        
        # --- ПРОВЕРКА ДЛИТЕЛЬНОСТИ ---
        orig_dur = len(orig_samples) / TARGET_SR
        user_dur = len(user_samples) / TARGET_SR
        print(f"=== DURATIONS: Orig={orig_dur:.2f}s, User={user_dur:.2f}s ===", flush=True)
        
        # Если длительность отличается более чем в 1.5 раза -> штраф
        duration_penalty = 1.0
        if orig_dur > 0 and user_dur > 0:
            ratio = max(orig_dur, user_dur) / min(orig_dur, user_dur)
            if ratio > 1.5:
                # Штрафуем: чем больше разница, тем меньше коэффициент (0.8, 0.7...)
                duration_penalty = 1.0 / (ratio * 0.8) 
                print(f"=== Duration Penalty applied: {duration_penalty:.2f} ===", flush=True)

        if user_dur < 0.1:
             return {"similarity": 0, "status": "success", "message": "Too short"}

        # --- ИЗВЛЕЧЕНИЕ MFCC ---
        # Используем простые настройки
        orig_mfcc = mfcc(orig_samples, TARGET_SR, winlen=0.025, winstep=0.01, numcep=13, nfilt=26)
        user_mfcc = mfcc(user_samples, TARGET_SR, winlen=0.025, winstep=0.01, numcep=13, nfilt=26)
        
        # --- НОРМАЛИЗАЦИЯ (Cepstral Mean Subtraction) ---
        # Критически важно для сравнения разных микрофонов!
        orig_mfcc -= (np.mean(orig_mfcc, axis=0) + 1e-8)
        user_mfcc -= (np.mean(user_mfcc, axis=0) + 1e-8)
        
        # --- DTW ---
        distance, path = fastdtw(orig_mfcc, user_mfcc, dist=euclidean)
        
        # Нормализуем дистанцию
        path_len = len(path) if len(path) > 0 else 1
        normalized_distance = distance / path_len
        
        print(f"=== RAW DISTANCE = {normalized_distance:.4f} ===", flush=True)

        # --- РАСЧЕТ ОЦЕНКИ ---
        # Калибровка под CMS и FastDTW:
        # Дистанция ~15-20 -> Отлично (90-100%)
        # Дистанция ~30 -> Хорошо (70%)
        # Дистанция ~40-50 -> Так себе (40-50%)
        # Дистанция >60 -> Плохо
        
        # Линейная формула с порогом
        base_score = max(0, 100 - (normalized_distance - 15) * 2.5)
        
        # Ограничиваем сверху 100
        if base_score > 100: base_score = 100
            
        # Применяем штраф за длительность
        final_score = base_score * duration_penalty
        
        print(f"=== SCORE: Base={base_score:.2f} * Penalty={duration_penalty:.2f} = {final_score:.2f} ===", flush=True)

        return {
            "similarity": round(final_score),
            "status": "success"
        }
        
    except Exception as e:
        import traceback
        print(traceback.format_exc(), flush=True)
        return {"status": "error", "message": str(e)}

@app.route('/compare-audio', methods=['POST'])
def compare_audio_files():
    if 'user_audio' not in request.files:
        return jsonify({"status": "error", "message": "No file"}), 400
    if 'original_video_url' not in request.form:
        return jsonify({"status": "error", "message": "No URL"}), 400

    user_file = request.files['user_audio']
    original_video_url = request.form['original_video_url']

    upload_folder = 'temp_uploads'
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        
    user_path = os.path.join(upload_folder, "user_temp.webm")
    original_path = os.path.join(upload_folder, "original_temp_video")

    try:
        user_file.save(user_path)
        r = requests.get(original_video_url, stream=True)
        r.raise_for_status()
        with open(original_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        
        result = compare_pronunciation(original_path, user_path)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if os.path.exists(user_path): os.remove(user_path)
        if os.path.exists(original_path): os.remove(original_path)
            
    return jsonify(result)

@app.route('/')
def home():
    return "Server OK"

# ... (ОСТАЛЬНОЙ КОД БЕЗ ИЗМЕНЕНИЙ ВНИЗУ: patterns, analyze...) ...
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