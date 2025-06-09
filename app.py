from flask import Flask, request, Response
from konlpy.tag import Okt  # <--- ИЗМЕНЕНИЕ 1
import json, re

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
okt = Okt()  # <--- ИЗМЕНЕНИЕ 2

# Добавляем главную страницу
@app.route('/')
def home():
    return "Сервер для анализа грамматик на Okt работает!"

# 1) Загрузка базы грамматик
with open('patterns.json', encoding='utf-8') as f:
    patterns = json.load(f)

# 2) Эндпоинт анализа
@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    text = data.get('text', '')
    
    # ИСПОЛЬЗУЕМ okt ВМЕСТО komoran
    parsed = okt.pos(text)  # <--- ИЗМЕНЕНИЕ 3
    
    route = ' '.join(f"{w}/{p}" for w, p in parsed)
    
    matches = []
    for pat in patterns:
        if re.search(pat['regex'], route):
            matches.append({
                'id': pat['id'],
                'pattern': pat['pattern'],
                'meaning': pat['meaning'],
                'example': pat['example']
            })
        elif pat.get('regex_text') and re.search(pat['regex_text'], text):
            matches.append({
                'id': pat['id'],
                'pattern': pat['pattern'],
                'meaning': pat['meaning'],
                'example': pat['example']
            })

    payload = {
        'tokens': parsed,
        'grammar_matches': matches
    }
    
    js = json.dumps(payload, ensure_ascii=False)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)