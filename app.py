from flask import Flask, request, Response
from konlpy.tag import Komoran
import json, re


app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  
komoran = Komoran()

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
    parsed = komoran.pos(text)
    route = ' '.join(f"{w}/{p}" for w,p in parsed)
    print("ROUTE:", route)
    for pat in patterns:
        print("PATTERN:", pat["regex"])
        print("MATCH:", re.search(pat["regex"], route))
    matches = []
    for pat in patterns:
    # проверяем сначала по тегам
        if re.search(pat['regex'], route):
           matches.append({
            'id': pat['id'],
            'pattern': pat['pattern'],
            'meaning': pat['meaning'],
            'example': pat['example']
           })
    # затем – только если есть непустой regex_text
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
    print("MATCHES:", matches)
# сериализуем в чистый UTF-8 JSON
    js = json.dumps(payload, ensure_ascii=False)
# возвращаем руками
    print("RESPONSE:", js)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
