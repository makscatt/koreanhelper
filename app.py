from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import requests
from difflib import SequenceMatcher
import re

app = Flask(__name__)

# --- ИСПРАВЛЕНИЕ 1: Разрешаем доступ отовсюду (фикс CORS) ---
CORS(app, resources={r"/*": {"origins": "*"}})
app.config['JSON_AS_ASCII'] = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_SECRET = "my_super_secret_password_123"
CACHE_FILE = '/data/cache.json' if os.path.exists('/data') else 'cache.json'

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

CHOSUNG_LIST = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
JUNGSUNG_LIST = ['ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ', 'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ', 'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ']
JONGSUNG_LIST = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ', 'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Cache read error: {e}")
            return {}
    return {}

def save_cache(new_data):
    try:
        current_cache = load_cache()
        current_cache.update(new_data)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_cache, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Cache write error: {e}")

analysis_cache = load_cache()

def decompose_hangul(text):
    result = ""
    for char in text:
        code = ord(char)
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
    text = re.sub(r'[^\w\s]', '', text)
    return "".join(char for char in text if char.isalnum()).lower()

def similar(reference, user_input):
    clean_ref = normalize_text(reference)
    clean_usr = normalize_text(user_input)
    
    if not clean_usr: return 0
    if clean_ref == clean_usr: return 100
    
    decomp_ref = decompose_hangul(clean_ref)
    decomp_usr = decompose_hangul(clean_usr)
    
    return SequenceMatcher(None, decomp_ref, decomp_usr).ratio() * 100

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    text = data.get('text', '').strip()
    force_update = data.get('force', False)
    secret_key = data.get('secret', '')
    
    # 1. Получаем промпт (если его нет, будет пустая строка)
    custom_prompt = data.get('prompt', '').strip()

    if not text:
        return jsonify({"tokens": [], "grammar_matches": []})

    is_admin_request = force_update and (secret_key == ADMIN_SECRET)
    
    if text in analysis_cache and not is_admin_request:
        return jsonify(analysis_cache[text])

    # Базовая инструкция
    system_prompt = f"""
    Ты — лучший преподаватель корейского языка. Твоя задача — сделать разбор для JSON API.
    Входящее предложение: "{text}"

    ИНСТРУКЦИЯ ПО ГРАММАТИКЕ:
    1. В поле "pattern" НЕ пиши абстрактные формулы.
    2. ОБЯЗАТЕЛЬНО подставляй слово из предложения в начальной форме.
    3. Объясняй простым языком.

    ИНСТРУКЦИЯ ПО ЦВЕТАМ (TOKENS):
    pos_type: "noun", "verb", "adj", "adverb", "particle", "ending", "other".

    ОТВЕТЬ ТОЛЬКО ВАЛИДНЫМ JSON:
    {{
      "translation": "Естественный перевод на русский",
      "tokens": [
        {{ "token": "фрагмент", "pos_type": "verb", "meaning": "значение" }}
      ],
      "grammar": [
        {{ 
          "pattern": "Слово + Грамматика", 
          "explanation": "Объяснение", 
          "example": "Пример" 
        }}
      ]
    }}
    """

    # 2. Если есть дополнительный промпт от админа — добавляем его в конец
    if custom_prompt:
        system_prompt += f"\n\nВАЖНОЕ УТОЧНЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ:\n{custom_prompt}\nОбязательно учти этот контекст или исправление при анализе!"

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4o",
                "messages": [{"role": "system", "content": system_prompt}],
                "temperature": 0.2
            }
        )
        
        gpt_data = response.json()
        if 'error' in gpt_data:
            return jsonify({"tokens": [], "grammar_matches": [{"pattern": "Error", "meaning": "API Error", "example": ""}]})

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

        # Обновляем кэш новым результатом
        analysis_cache[text] = final_response
        save_cache({text: final_response})

        return jsonify(final_response)

    except Exception as e:
        return jsonify({"tokens": [], "grammar_matches": [{"pattern": "Error", "meaning": str(e), "example": ""}]}), 500

# --- ИСПРАВЛЕНИЕ 2: Новая функция чата с поддержкой OPTIONS и логами ---
@app.route('/chat', methods=['POST', 'OPTIONS'])
def chat_endpoint():
    # Хак для браузера: если он спрашивает "можно?", говорим "можно"
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response, 200

    data = request.get_json()
    messages = data.get('messages', [])

    if not messages:
        return jsonify({"reply": "Ошибка: Нет сообщений"}), 400

    print(f"DEBUG CHAT: received {len(messages)} messages")

    try:
        # Проверяем ключ API
        if not OPENAI_API_KEY:
            print("ERROR: API Key is missing on Server!")
            return jsonify({"reply": "Ошибка сервера: Нет ключа API"}), 500

        # Запрос к OpenAI
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4o-mini", # Дешевая модель
                "messages": messages,
                "max_tokens": 200,
                "temperature": 0.7
            }
        )
        
        gpt_data = response.json()

        if 'error' in gpt_data:
            print("OpenAI Error:", gpt_data)
            return jsonify({"reply": f"Ошибка OpenAI: {gpt_data['error']['message']}"}), 500

        reply_text = gpt_data['choices'][0]['message']['content']
        
        # Явно добавляем заголовки CORS к ответу (для надежности)
        response = jsonify({"reply": reply_text})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

    except Exception as e:
        print(f"Server Exception: {e}")
        return jsonify({"reply": "Ошибка на сервере."}), 500
# --- КОНЕЦ ИСПРАВЛЕНИЙ ---

# --- НОВЫЙ ЭНДПОИНТ ДЛЯ ЧИСТОГО РАСПОЗНАВАНИЯ ГОЛОСА ---
@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    if 'user_audio' not in request.files:
        return jsonify({"error": "No file"}), 400
    
    user_file = request.files['user_audio']
    filename = "temp_chat_voice.webm"
    user_file.save(filename)

    try:
        # Используем requests, как и везде в твоем коде
        headers = { "Authorization": f"Bearer {OPENAI_API_KEY}" }
        
        data_payload = {
            "model": "whisper-1",
            "language": "ko" # Корейский язык
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
            print("Whisper Error:", data)
            return jsonify({"text": ""}), 500

        return jsonify({"text": data.get('text', '')})

    except Exception as e:
        print(f"Transcribe Error: {e}")
        return jsonify({"text": ""}), 500
    finally:
        if os.path.exists(filename):
            os.remove(filename)

@app.route('/compare-audio', methods=['POST'])
def compare_audio_files():
    if 'user_audio' not in request.files:
        return jsonify({"status": "error", "message": "No audio file"}), 400
    
    reference_text = request.form.get('reference_text', '').strip()
    user_file = request.files['user_audio']
    
    filename = "temp_whisper.webm"
    user_file.save(filename)

    try:
        headers = { "Authorization": f"Bearer {OPENAI_API_KEY}" }
        
        prompt_context = f"한국어 받아쓰기입니다. 정답을 한글로만 쓰세요. 단어: {reference_text}"

        data_payload = {
            "model": "whisper-1",
            "language": "ko",
            "prompt": prompt_context,
            "temperature": 0.0
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
            print("Whisper API Error:", data)
            return jsonify({"status": "error", "message": data['error']['message']}), 500

        user_text = data.get('text', '').strip()
        similarity = similar(reference_text, user_text)

        print(f"DEBUG: Ref='{reference_text}' | Heard='{user_text}' | Score={similarity}")

        return jsonify({
            "status": "success",
            "similarity": round(similarity),
            "user_text": user_text 
        })

    except Exception as e:
        print(f"Compare Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if os.path.exists(filename):
            os.remove(filename)

@app.route('/')
def home():
    return "Server Running"

@app.route('/translate_text', methods=['POST'])
def translate_text():
    data = request.get_json()
    text = data.get('text', '')
    
    if not text:
        return jsonify({"translation": ""})

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "Ты переводчик. Переведи этот корейский текст на русский язык максимально точно и естественно. Верни ТОЛЬКО перевод."},
                    {"role": "user", "content": text}
                ],
                "max_tokens": 200
            }
        )
        gpt_data = response.json()
        translation = gpt_data['choices'][0]['message']['content'].strip()
        
        return jsonify({"translation": translation})

    except Exception as e:
        print(f"Translate error: {e}")
        return jsonify({"translation": "Ошибка перевода"}), 500

@app.route('/tts', methods=['POST'])
def text_to_speech():
    data = request.get_json()
    text = data.get('text', '')
    voice_type = data.get('voice', 'echo') 

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "tts-1-hd",   # Включаем HD качество (живее звучание)
            "input": text,
            "voice": voice_type,
            "speed": 1.0           # Скорость: 1.0 = норма, 0.9 = чуть медленнее
        }

        response = requests.post("https://api.openai.com/v1/audio/speech", json=payload, headers=headers)
        
        if response.status_code != 200:
            return jsonify({"error": "OpenAI Error"}), 500

        return response.content, 200, {'Content-Type': 'audio/mpeg'}

    except Exception as e:
        print(f"TTS Error: {e}")
        return jsonify({"error": str(e)}), 500        

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)