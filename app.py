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

def normalize_text(text):
    return "".join(char for char in text if char.isalnum()).lower()

def similar(a, b):
    clean_a = normalize_text(a)
    clean_b = normalize_text(b)
    if not clean_a and not clean_b: return 100
    if not clean_a or not clean_b: return 0
    return SequenceMatcher(None, clean_a, clean_b).ratio() * 100

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
    Ты профессиональный преподаватель корейского языка. Сделай разбор предложения для JSON API.
    Входящее предложение: "{text}"

    Инструкции:
    1. Переведи на русский.
    2. Разбей на токены. "pos_type" выбери строго из: ["noun", "verb", "adj", "particle", "ending", "adverb", "number", "other"].
    3. Найди грамматику.

    ОТВЕТЬ ТОЛЬКО ВАЛИДНЫМ JSON:
    {{
      "translation": "перевод предложения",
      "tokens": [
        {{ "token": "фрагмент", "pos_type": "тип", "meaning": "значение слова" }}
      ],
      "grammar": [
        {{ "pattern": "формула", "explanation": "объяснение", "example": "пример" }}
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

# === НАСТРОЙКИ TELEGRAM ===
TG_BOT_TOKEN = "7828959849:AAEWW1imJPB_7GaB2S8P62060JP5DcVqtC0"  # Вставь сюда токен
TG_ADMIN_ID = "910912532"             # Вставь сюда цифры ID

@app.route('/report', methods=['POST'])
def report_error():
    data = request.get_json()
    text = data.get('text', 'Нет текста')
    comment = data.get('comment', 'Без комментария')

    # Формируем сообщение для тебя
    message = (
        f"🚨 <b>Репорт об ошибке!</b>\n\n"
        f"🇰🇷 <b>Предложение:</b>\n{text}\n\n"
        f"💬 <b>Комментарий:</b>\n{comment}"
    )

    # Отправляем в Телеграм
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TG_ADMIN_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload)
        return jsonify({"status": "sent"})
    except Exception as e:
        print(f"TG Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)