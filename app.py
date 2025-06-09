from flask import Flask, request, Response
from flask_cors import CORS   
from konlpy.tag import Komoran  # <--- ИЗМЕНЕНИЕ 1
import json, re

app = Flask(__name__)
CORS(app) 
app.config['JSON_AS_ASCII'] = False
komoran = Komoran()  # <--- ИЗМЕНЕНИЕ 2

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
    
    parsed_for_grammar = komoran.pos(text)
    route = ' '.join(f'{word}/{pos}' for word, pos in parsed_for_grammar)
    print("ROUTE:", route)
    tokens_with_stems = komoran.pos(text)

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
        'tokens': tokens_with_stems,
        'grammar_matches': matches
    }
    print("MATCHES:", matches)
    js = json.dumps(payload, ensure_ascii=False)
    print("RESPONSE:", js)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
