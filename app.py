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

# --- ИЗМЕНЕНИЕ 1: Добавляем ключ и константы для Groq ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # Остается для TTS
GROQ_API_KEY = os.getenv("GROQ_API_KEY")     # Новый ключ для чата и Whisper

# --- ДОБАВЛЕНО: Константы для удобства ---
GROQ_API_URL_CHAT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_URL_TRANSCRIPTIONS = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_CHAT_MODEL_POWERFUL = "llama-3.1-70b-versatile" # НОВОЕ НАЗВАНИЕ
GROQ_CHAT_MODEL_FAST = "llama-3.1-8b-instant"     # НОВОЕ НАЗВАНИЕ
GROQ_WHISPER_MODEL = "whisper-large-v3"            # Whisper не изменился

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
    custom_prompt = data.get('prompt', '').strip()

    if not text:
        return jsonify({"tokens": [], "grammar_matches": []})

    is_admin_request = force_update and (secret_key == ADMIN_SECRET)
    
    if text in analysis_cache and not is_admin_request:
        return jsonify(analysis_cache[text])

    # --- ИЗМЕНЕНИЕ 2: Проверяем ключ Groq ---
    if not GROQ_API_KEY:
        return jsonify({"error": "Groq API key is not configured on the server."}), 500

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
    if custom_prompt:
        system_prompt += f"\n\nВАЖНОЕ УТОЧНЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ:\n{custom_prompt}\nОбязательно учти этот контекст или исправление при анализе!"

    try:
        # --- ИЗМЕНЕНИЕ 3: Используем API и модель Groq ---
        response = requests.post(
            GROQ_API_URL_CHAT,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_CHAT_MODEL_POWERFUL, # Llama 3 70b для качественного анализа
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

        analysis_cache[text] = final_response
        save_cache({text: final_response})

        return jsonify(final_response)

    except Exception as e:
        return jsonify({"tokens": [], "grammar_matches": [{"pattern": "Error", "meaning": str(e), "example": ""}]}), 500

@app.route('/report-issue', methods=['POST'])
def report_issue():
    # Эта функция не использует AI, поэтому изменений нет
    data = request.get_json()
    user_info = data.get('user_info', 'Неизвестный')
    block_key = data.get('block', 'Не определен')
    word_kr = data.get('korean', '?')
    video_id = data.get('video_id', '?')
    ai_context = data.get('ai_context', 'Нет данных анализа')
    message = (
        f"🚨 <b>СООБЩЕНИЕ ОБ ОШИБКЕ</b>\n\n"
        f"👤 <b>Пользователь:</b> {user_info}\n"
        f"📂 <b>Раздел:</b> {block_key}\n"
        f"🇰🇷 <b>Слово (база):</b> {word_kr}\n"
        f"📹 <b>Видео:</b> {video_id}\n\n"
        f"🤖 <b>Что выдал ИИ (экран):</b>\n"
        f"<pre>{ai_context}</pre>"
    )
    ERROR_BOT_TOKEN = os.getenv("ERROR_BOT_TOKEN")
    ADMIN_CHAT_ID = "910912532" 
    if not ERROR_BOT_TOKEN:
        return jsonify({"status": "error", "message": "No token"}), 500
    url = f"https://api.telegram.org/bot{ERROR_BOT_TOKEN}/sendMessage"
    payload = { 'chat_id': ADMIN_CHAT_ID, 'text': message, 'parse_mode': 'HTML' }
    try:
        requests.post(url, json=payload)
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"Report error: {e}")
        return jsonify({"status": "error"}), 500   

@app.route('/chat', methods=['POST', 'OPTIONS'])
def chat_endpoint():
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
        # --- ИЗМЕНЕНИЕ 4: Проверяем ключ Groq ---
        if not GROQ_API_KEY:
            print("ERROR: Groq API Key is missing on Server!")
            return jsonify({"reply": "Ошибка сервера: Нет ключа API"}), 500

        # --- ИЗМЕНЕНИЕ 5: Используем API и модель Groq для чата ---
        response = requests.post(
            GROQ_API_URL_CHAT,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_CHAT_MODEL_FAST, # Llama 3 8b для быстрого ответа
                "messages": messages,
                "max_tokens": 200,
                "temperature": 0.7
            }
        )
        
        gpt_data = response.json()

        if 'error' in gpt_data:
            print("Groq API Error:", gpt_data)
            return jsonify({"reply": f"Ошибка Groq: {gpt_data['error']['message']}"}), 500

        reply_text = gpt_data['choices'][0]['message']['content']
        
        response = jsonify({"reply": reply_text})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

    except Exception as e:
        print(f"Server Exception: {e}")
        return jsonify({"reply": "Ошибка на сервере."}), 500

@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    if 'user_audio' not in request.files:
        return jsonify({"error": "No file"}), 400
    
    user_file = request.files['user_audio']
    filename = "temp_chat_voice.webm"
    user_file.save(filename)

    try:
        # --- ИЗМЕНЕНИЕ 6: Используем ключ Groq для Whisper ---
        headers = { "Authorization": f"Bearer {GROQ_API_KEY}" }
        
        # --- ИЗМЕНЕНИЕ 7: Используем модель Whisper v3 от Groq ---
        data_payload = {
            "model": GROQ_WHISPER_MODEL,
            "language": "ko"
        }
        
        files_payload = {
            "file": (filename, open(filename, "rb"), "audio/webm")
        }

        # --- ИЗМЕНЕНИЕ 8: Используем URL Groq для распознавания ---
        response = requests.post(
            GROQ_API_URL_TRANSCRIPTIONS, 
            headers=headers, 
            files=files_payload, 
            data=data_payload
        )
        
        data = response.json()

        if 'error' in data:
            print("Groq Whisper Error:", data)
            return jsonify({"text": ""}), 500

        return jsonify({"text": data.get('text', '')})

    except Exception as e:
        print(f"Transcribe Error: {e}")
        return jsonify({"text": ""}), 500
    finally:
        if os.path.exists(filename):
            os.remove(filename)

def clean_whisper_hallucinations(text, target_word):
    instruction_garbage = ["정답은", "정답", "단어", "라고", "합니다", "쓰세요", "한글로만", "문제", "답"]
    grammar_garbage = ["입니다", "이에요", "예요", "하고", "했다"]
    clean_text = text
    for phrase in instruction_garbage:
        clean_text = clean_text.replace(phrase, "")
    for phrase in grammar_garbage:
        if phrase not in target_word:
            clean_text = clean_text.replace(phrase, "")
    clean_text = clean_text.strip(".! ")
    clean_text_norm = normalize_text(clean_text)
    target_clean = normalize_text(target_word)
    if target_clean != "" and target_clean in clean_text_norm:
        return target_word
    return clean_text
    
@app.route('/compare-audio', methods=['POST'])
def compare_audio_files():
    if 'user_audio' not in request.files:
        return jsonify({"status": "error", "message": "No audio file"}), 400
    
    reference_text = request.form.get('reference_text', '').strip()
    user_file = request.files['user_audio']
    filename = "temp_whisper.webm"
    user_file.save(filename)

    try:
        # --- ИЗМЕНЕНИЕ 9: Аналогично, меняем всё на Groq ---
        headers = { "Authorization": f"Bearer {GROQ_API_KEY}" }
        prompt_context = f"유저가 다음 단어를 발음합니다: {reference_text}. 다른 말은 하지 말고 들린 대로만 적으세요."
        data_payload = {
            "model": GROQ_WHISPER_MODEL,
            "language": "ko",
            "prompt": prompt_context,
            "temperature": 0.0
        }
        files_payload = {
            "file": (filename, open(filename, "rb"), "audio/webm")
        }
        response = requests.post(
            GROQ_API_URL_TRANSCRIPTIONS, 
            headers=headers, 
            files=files_payload, 
            data=data_payload
        )
        data = response.json()

        if 'error' in data:
            print("Groq Whisper API Error:", data)
            return jsonify({"status": "error", "message": data['error']['message']}), 500

        raw_user_text = data.get('text', '').strip()
        processed_user_text = clean_whisper_hallucinations(raw_user_text, reference_text)
        similarity = similar(reference_text, processed_user_text)

        print(f"DEBUG: Ref='{reference_text}' | Raw='{raw_user_text}' | Clean='{processed_user_text}' | Score={similarity}")

        return jsonify({
            "status": "success",
            "similarity": round(similarity),
            "user_text": raw_user_text
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
        # --- ИЗМЕНЕНИЕ 10: Перевод тоже через Groq ---
        response = requests.post(
            GROQ_API_URL_CHAT,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_CHAT_MODEL_FAST,
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
    # --- БЕЗ ИЗМЕНЕНИЙ: Эта функция продолжает использовать OpenAI ---
    data = request.get_json()
    text = data.get('text', '').strip()
    voice_type = data.get('voice', 'nova') 

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice_type,
            "speed": 1.0
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