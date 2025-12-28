from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import requests
from difflib import SequenceMatcher

app = Flask(__name__)
CORS(app)
app.config['JSON_AS_ASCII'] = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# === ПАРОЛЬ АДМИНИСТРАТОРА ДЛЯ ОБНОВЛЕНИЯ КЭША ===
ADMIN_SECRET = "my_super_secret_password_123"

# === НАСТРОЙКА КЭША ===
CACHE_FILE = '/data/cache.json' if os.path.exists('/data') else 'cache.json'

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка чтения кэша: {e}")
            return {}
    return {}

def save_cache(new_data):
    try:
        current_cache = load_cache()
        current_cache.update(new_data)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_cache, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка записи кэша: {e}")

# Загрузка кэша в память при старте
analysis_cache = load_cache()

COLOR_MAP = {
    "noun": "#4A90E2",      
    "verb": "#D0021B",      
    "adj": "#F5A623",       
    "particle": "#9013FE",  
    "ending": "#50E3C2",    
    "adverb": "#B8E986",    
    "number": "#BD10E0",    
    "other": "#4A4A4A"      
}

# === БЛОК ОБРАБОТКИ КОРЕЙСКОГО ТЕКСТА ===

# Списки букв для разбора (Jamo)
CHOSUNG_LIST = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
JUNGSUNG_LIST = ['ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ', 'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ', 'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ']
JONGSUNG_LIST = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ', 'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']

def decompose_hangul(text):
    result = ""
    for char in text:
        code = ord(char)
        # Проверка: это корейский слог? (диапазон Unicode AC00-D7A3)
        if 0xAC00 <= code <= 0xD7A3:
            code -= 0xAC00
            jong = code % 28
            jung = (code // 28) % 21
            cho = (code // 28) // 21
            
            result += CHOSUNG_LIST[cho] + JUNGSUNG_LIST[jung]
            if jong > 0:
                result += JONGSUNG_LIST[jong]
        else:
            result += char
    return result

def normalize_text(text):
    # Убираем все кроме букв и цифр, переводим в нижний регистр
    return "".join(char for char in text if char.isalnum()).lower()

def similar(reference, user_input):
    # 1. Сначала пробуем прямое сравнение
    clean_ref = normalize_text(reference)
    clean_usr = normalize_text(user_input)
    
    if not clean_ref and not clean_usr: return 100
    if not clean_ref or not clean_usr: return 0
    
    # 2. Если прямое сравнение дает низкий результат, разбираем на буквы (Jamo)
    # Это спасает "밥" vs "바" (66% match) или "감사" vs "암사" (75% match)
    decomp_ref = decompose_hangul(clean_ref)
    decomp_usr = decompose_hangul(clean_usr)
    
    return SequenceMatcher(None, decomp_ref, decomp_usr).ratio() * 100

# === ЭНДПОИНТ АНАЛИЗА ТЕКСТА (GPT) ===
@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    text = data.get('text', '').strip()
    
    force_update = data.get('force', False)
    secret_key = data.get('secret', '')

    if not text:
        return jsonify({"tokens": [], "grammar_matches": []})

    is_admin_request = force_update and (secret_key == ADMIN_SECRET)
    
    # Если есть в кэше и не просят обновить принудительно - отдаем из кэша
    if text in analysis_cache and not is_admin_request:
        print(f"Cache HIT: {text}")
        return jsonify(analysis_cache[text])

    if is_admin_request:
        print(f"Force Update Requested for: {text}")
    else:
        print(f"Cache MISS: Requesting GPT for {text}")

    system_prompt = f"""
    Ты — лучший преподаватель корейского языка. Твоя задача — сделать разбор для JSON API.
    Входящее предложение: "{text}"

    ИНСТРУКЦИЯ ПО ГРАММАТИКЕ (САМОЕ ВАЖНОЕ):
    1. В поле "pattern" НЕ пиши абстрактные формулы (типа "N + V").
    2. ОБЯЗАТЕЛЬНО подставляй слово из предложения в начальной форме (инфинитиве).
       - ПЛОХО: "V + (으)세요" или "Наречие + V"
       - ХОРОШО: "오다 + (으)세요" (где 오다 - это слово из '오세요')
       - ХОРОШО: "왜 (Наречие)"
    3. Объясняй простым понятным языком, чтобы даже дурак понял о чем ты. При этом не повторяй в объяснении мысль, которая и так очевидна в термине. Используй теги <b>жирный</b> и <br>.
    

    ИНСТРУКЦИЯ ПО ЦВЕТАМ (TOKENS):
    Для каждого слова выбери "pos_type" СТРОГО из списка (чтобы работала подсветка):
    - "noun" (существительные, местоимения)
    - "verb" (глаголы действия и состояния/прилагательные)
    - "adj" (если это чистое прилагательное перед сущ.)
    - "adverb" (наречия: почему, быстро, очень)
    - "particle" (частицы: ыль/рыль, нын/ын)
    - "ending" (окончания глаголов)
    - "other" (междометия и прочее)

    ОТВЕТЬ ТОЛЬКО ВАЛИДНЫМ JSON:
    {{
      "translation": "Естественный перевод на русский",
      "tokens": [
        {{ "token": "фрагмент слова", "pos_type": "verb", "meaning": "значение" }}
      ],
      "grammar": [
        {{ 
          "pattern": "Слово(Инфинитив) + Грамматика", 
          "explanation": "Максимально короткое и понятное даже идиотам объяснение, как это работает здесь.", 
          "example": "3 коротких примера с переводом. Каждый пример на отдельной строчке." 
        }}
      ]
    }}
    """

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-5-chat-latest",
                "messages": [{"role": "system", "content": system_prompt}],
                "temperature": 0.2
            }
        )
        
        gpt_data = response.json()
        
        if 'error' in gpt_data:
            print("OpenAI Error:", gpt_data['error'])
            return jsonify({"tokens": [], "grammar_matches": [{"pattern": "Ошибка", "meaning": "API Error", "example": ""}]})

        content_str = gpt_data['choices'][0]['message']['content']
        
        if content_str.startswith("```"):
            content_str = content_str.strip("`").replace("json", "").strip()
            
        result_json = json.loads(content_str)

        client_tokens = []
        for t in result_json.get("tokens", []):
            color = COLOR_MAP.get(t.get("pos_type"), "#000000")
            client_tokens.append({
                "word": t["token"],
                "pos": t["meaning"], 
                "color": color
            })

        client_grammar = []
        
        translation = result_json.get("translation", "")
        if translation:
            client_grammar.append({
                "pattern": "ПЕРЕВОД",
                "meaning": translation,
                "example": ""
            })

        for g in result_json.get("grammar", []):
            client_grammar.append({
                "pattern": g["pattern"],
                "meaning": g["explanation"],
                "example": g["example"]
            })

        final_response = {
            "tokens": client_tokens,
            "grammar_matches": client_grammar
        }

        # Сохраняем в память и файл
        analysis_cache[text] = final_response
        save_cache({text: final_response})

        return jsonify(final_response)

    except Exception as e:
        print(f"Server Error: {e}")
        return jsonify({"tokens": [], "grammar_matches": [{"pattern": "Ошибка", "meaning": str(e), "example": ""}]}), 500

# === ЭНДПОИНТ АНАЛИЗА АУДИО (WHISPER) ===
@app.route('/compare-audio', methods=['POST'])
def compare_audio_files():
    if 'user_audio' not in request.files:
        return jsonify({"status": "error", "message": "No audio file"}), 400
    
    reference_text = request.form.get('reference_text', '').strip()
    user_file = request.files['user_audio']
    
    filename = "temp_whisper.webm"
    user_file.save(filename)

    try:
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        
        data_payload = {
            "model": "whisper-1",
            "language": "ko",
            "prompt": reference_text 
        }
        
        files_payload = {
            "file": (filename, open(filename, "rb"), "audio/webm")
        }

        response = requests.post(
            "https://api.openai.com/v1/audio/transcriptions", 
            headers=headers, 
            files=files_payload, 
            data=data_payload
        )
        
        data = response.json()

        if 'error' in data:
            return jsonify({"status": "error", "message": data['error']['message']}), 500

        user_text = data.get('text', '').strip()
        similarity = similar(reference_text, user_text)

        return jsonify({
            "status": "success",
            "similarity": round(similarity),
            "user_text": user_text 
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if os.path.exists(filename):
            os.remove(filename)

@app.route('/')
def home():
    return "Server Running (Analize + Audio)"



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)