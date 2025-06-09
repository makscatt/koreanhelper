from flask import Flask, request, Response
from konlpy.tag import Okt  # <--- ИЗМЕНЕНИЕ 1
import json, re

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
okt = Okt()  # <--- ИЗМЕНЕНИЕ 2

@app.route('/')
def home():
    return "Сервер для анализа грамматик работает!"
# 1) Загрузка базы грамматик
with open('patterns.json', encoding='utf-8') as f:
    patterns = json.load(f)

# 2) Эндпоинт анализа
@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    print("RAW DATA:", data)
    text = data.get('text', '')
    print("TEXT:", text.encode('utf-8'))
    
    # 1. Анализ для поиска грамматик (с окончаниями)
    parsed_for_grammar = okt.pos(text, stem=False) 
    route = ' '.join(f'{word}/{pos}' for word, pos in parsed_for_grammar)
    # 2. Анализ для поля "tokens" (с основами)
    tokens_with_stems = okt.pos(text, stem=True)

    
    print("ROUTE:", route)
    
    
    matches = []
    for pat in patterns:
        if pat.get('regex_text'):
            found = re.findall(pat['regex_text'], route)
            if found and not any(match['id'] == pat['id'] for match in matches):
                matches.append({
                    'id': pat['id'],
                    'pattern': pat['pattern'],
                    'meaning': pat['meaning'],
                    'example': pat['example']
                })

    payload = {
        'tokens': tokens_with_stems, # Используем токены с основами
        'grammar_matches': matches
    }
    print("MATCHES:", matches)
    # сериализуем в чистый UTF-8 JSON
    js = json.dumps(payload, ensure_ascii=False)
    # возвращаем руками
    print("RESPONSE:", js)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
