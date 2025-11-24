from flask import Flask, request, Response, jsonify
from flask_cors import CORS   
from konlpy.tag import Komoran  # <--- ИЗМЕНЕНИЕ 1
import json, re
import os 
import librosa
import numpy as np
import requests
import psutil
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean

app = Flask(__name__)
CORS(app) 
app.config['JSON_AS_ASCII'] = False
komoran = Komoran()  # <--- ИЗМЕНЕНИЕ 2

def log_memory_usage(stage=""):
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / (1024 * 1024) # в мегабайтах
    print(f"--- MEMORY USAGE [{stage}]: {memory_mb:.2f} MB")

def compare_pronunciation(original_file_path, user_file_path):
    try:
        # --- ОПТИМИЗАЦИИ ---
        TARGET_SR = 16000  # Снижаем частоту дискретизации. 16кГц достаточно для речи.
        MAX_DURATION = 10  # Обрабатываем не более 10 секунд аудио.

        # Загружаем аудио, сразу применяя оптимизации
        original_audio, sr1 = librosa.load(
            original_file_path, 
            sr=TARGET_SR,         # 1. Принудительно ставим низкую частоту
            mono=True,            # 2. Преобразуем в моно (в 2 раза меньше данных)
            duration=MAX_DURATION # 3. Обрезаем длинные файлы
        )
        user_audio, sr2 = librosa.load(
            user_file_path, 
            sr=TARGET_SR, 
            mono=True, 
            duration=MAX_DURATION
        )

        # --- Остальной код остается прежним ---
        original_mfcc = librosa.feature.mfcc(y=original_audio, sr=TARGET_SR, n_mfcc=13)
        user_mfcc = librosa.feature.mfcc(y=user_audio, sr=TARGET_SR, n_mfcc=13)
        
        distance, path = fastdtw(original_mfcc.T, user_mfcc.T, dist=euclidean)

        normalized_distance = distance / (len(original_mfcc[0]) + len(user_mfcc[0]))
        
        similarity = max(0, 100 - (normalized_distance * 10)) 

        return {
            "similarity": round(similarity),
            "status": "success"
        }
        
    except Exception as e:
        # Добавляем traceback для лучшей отладки в будущем
        import traceback
        print(traceback.format_exc())
        return {
            "status": "error",
            "message": str(e)
        }

# --- НОВЫЙ ЭНДПОИНТ ДЛЯ ПРИЕМА АУДИО ---
@app.route('/compare-audio', methods=['POST'])
def compare_audio_files():
    log_memory_usage("Request Start")
    # 1. Проверяем, что получили файл от пользователя и URL
    if 'user_audio' not in request.files:
        return jsonify({"status": "error", "message": "Файл 'user_audio' не найден"}), 400
    if 'original_video_url' not in request.form:
        return jsonify({"status": "error", "message": "Параметр 'original_video_url' не найден"}), 400

    user_file = request.files['user_audio']
    original_video_url = request.form['original_video_url']

    upload_folder = 'temp_uploads'
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
        
    # Пути для временных файлов
    user_path = os.path.join(upload_folder, "user_temp.webm")
    original_path = os.path.join(upload_folder, "original_temp_video") # Имя не важно, librosa определит формат

    try:
        # 2. Сохраняем файл пользователя
        user_file.save(user_path)
        log_memory_usage("User file saved") 

        # 3. Скачиваем эталонное видео по URL
        response = requests.get(original_video_url, stream=True)
        response.raise_for_status() # Проверка на ошибки типа 404 Not Found
        with open(original_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        log_memory_usage("Original video downloaded")

        # 4. Сравниваем (librosa сам извлечет аудио из видео)
        result = compare_pronunciation(original_path, user_path)
        log_memory_usage("Comparison finished")

    except requests.exceptions.RequestException as e:
        # Ошибка, если не удалось скачать видео
        return jsonify({"status": "error", "message": f"Не удалось скачать эталонное видео: {e}"}), 500
    except Exception as e:
        # Другие возможные ошибки
        return jsonify({"status": "error", "message": f"Внутренняя ошибка сервера: {e}"}), 500
    finally:
        # 5. Гарантированно удаляем временные файлы
        if os.path.exists(user_path):
            os.remove(user_path)
        if os.path.exists(original_path):
            os.remove(original_path)
            
    return jsonify(result)

@app.route('/')
def home():
    return "Сервер для анализа грамматик работает!"
# 1) Загрузка базы грамматик
with open('patterns.json', encoding='utf-8') as f:
    patterns = json.load(f)
# 1.1) Загрузка маппинга POS→цветов
with open('colors.json', encoding='utf-8') as f:
    colors_data = json.load(f)

combined_colors = colors_data.get('COMBINED', {})
multi_token_colors = colors_data.get('MULTI', {})
word_colors = colors_data.get('WORDS', {})
pos_colors = colors_data.get('POS', {})
    # 1.2) Загрузка исправлений для Komoran
with open('komoran_corrections.json', encoding='utf-8') as f:
    komoran_fixes = json.load(f)
    # 1.3) Загрузка правил разбиения слитых токенов
with open('komoran_split_rules.json', encoding='utf-8') as f:
    komoran_split_rules = json.load(f)
# 1.5) Поверхностные оверрайды разборов (ДО komoran.pos)
with open('komoran_surface_overrides.json', encoding='utf-8') as f:
    surface_overrides = {k: [tuple(x) for x in v] for k, v in json.load(f).items()}

# ---- Функции фиксов ----
def pos_or_override(txt: str):
    key = txt.strip()
    if key in surface_overrides:
        return surface_overrides[key]  # уже список (word,pos)
    return komoran.pos(txt)

def fix_komoran(tokens):
    fixed = []
    i = 0
    while i < len(tokens):
        replaced = False
        # 0) Проверка по split-правилам
        word, pos = tokens[i]
        for rule in komoran_split_rules:
            if re.match(rule['regex'], f"{word}/{pos}"):
                print("SPLIT MATCH:", word, pos)

                # Разбиваем по пробелу
                parts = word.split()
                if len(parts) != 2:
                    break  # Защита от некорректных случаев

                left, right = parts[0], parts[1]

                # Выделение основы и окончания из левой части (형용사 + ETM)
                if left.endswith('은'):
                    stem = left[:-1]
                    modifier = '은'
                elif left.endswith('ㄴ'):
                    stem = left[:-1]
                    modifier = 'ㄴ'
                else:
                    break  # Неизвестное окончание

                # Подстановка в шаблон split
                fixed_entry = []
                for w, p in rule['split']:
                    if w == "{adj_stem}":
                        w = stem
                    elif w == "{modifier}":
                        w = modifier
                    elif w == "{noun}":
                        w = right
                    fixed_entry.append([w, p])

                print("SPLIT FIX:", f"{word}/{pos}", "→", fixed_entry)
                fixed.extend(fixed_entry)
                i += 1
                replaced = True
                break
        # Пробуем 3-грамму, 2-грамму, 1-грамму — в этом порядке
        for n in [4, 3, 2, 1]:
            if i + n <= len(tokens):
                key = ' '.join(f"{w}/{p}" for w, p in tokens[i:i + n])
                print("CHECKING:", key)  # Добавь это
                if key in komoran_fixes:
                    print("FIXING:", key, "→", komoran_fixes[key])  # И это
                    fixed.extend(komoran_fixes[key])
                    i += n
                    replaced = True
                    break
        if not replaced:
            fixed.append(tokens[i])
            i += 1
    return fixed
# 2) Эндпоинт анализа
@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    print("RAW DATA:", data)
    text = data.get('text', '')
    print("TEXT:", text.encode('utf-8'))
    
    parsed_for_grammar = pos_or_override(text)
    route = ' '.join(f'{word}/{pos}' for word, pos in parsed_for_grammar)
    print("ROUTE:", route)
    tokens_raw = parsed_for_grammar
    tokens_with_stems = fix_komoran(tokens_raw)
    print("\nDEBUG: Порядок токенов после fix_komoran():")
    for idx, (w, p) in enumerate(tokens_with_stems):
        print(f"{idx}: {w}/{p}")
    print()

    # путь через fix_komoran:
    route = ' '.join(f'{word}/{pos}' for word, pos in tokens_with_stems)

    def get_combined_color(word, pos):
        key = f"{word}/{pos}"
        for pattern, color in combined_colors.items():
            if re.fullmatch(pattern, key):
                return color
        return word_colors.get(word, pos_colors.get(pos, "#000000"))

    def get_multitoken_colors(route, tokens):
        match_spans = []  # Список: [(start_index, end_index, color)]

        for pattern, color in multi_token_colors.items():
            if ' ' in pattern:  # ← т.е. цепочка токенов
                for m in re.finditer(pattern, route):
                    char_start = m.start()
                    char_end = m.end()

                # Считаем, какой это токен по счёту
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
                        cursor += 1  # за пробел
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


    # --- НАЧАЛО ИЗМЕНЕНИЙ ---
    final_matches = []
    occupied_spans = [] # Список для хранения "занятых" участков текста: [(start, end)]

    for pat in patterns:
        if pat.get('regex_text'):
            for m in re.finditer(pat['regex_text'], route):
                new_start, new_end = m.start(), m.end()
                
                # --- ЭТО НОВАЯ ЛОГИКА ---
                # Проверяем, не является ли новый матч ПОДМНОЖЕСТВОМ уже найденного
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
    # --- КОНЕЦ ИЗМЕНЕНИЙ ---

    # Сортируем и убираем временный ключ 'start'
    final_matches.sort(key=lambda x: x['start'])
    for m in final_matches:
        m.pop('start')                

    payload = {
        'tokens':           colored_tokens,
        'grammar_matches':  final_matches
    }
    print("MATCHES:", final_matches)
    js = json.dumps(payload, ensure_ascii=False)
    print("RESPONSE:", js)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
