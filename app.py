from flask import Flask, request, Response
from flask_cors import CORS   
from konlpy.tag import Komoran
import json, re

app = Flask(__name__)
CORS(app)
app.config['JSON_AS_ASCII'] = False
komoran = Komoran()

@app.route('/')
def home():
    return "Сервер для анализа грамматик работает!"

# 1) Загрузка данных
with open('patterns.json', encoding='utf-8') as f:
    patterns = json.load(f)
with open('colors.json', encoding='utf-8') as f:
    colors_data = json.load(f)
combined_colors = colors_data.get('COMBINED', {})
word_colors = colors_data.get('WORDS', {})
pos_colors = colors_data.get('POS', {})
with open('komoran_corrections.json', encoding='utf-8') as f:
    komoran_fixes = json.load(f)
with open('komoran_split_rules.json', encoding='utf-8') as f:
    komoran_split_rules = json.load(f)

# 2) Функция фикса ошибок Komoran

def fix_komoran(tokens):
    fixed, i = [], 0
    while i < len(tokens):
        replaced = False
        word, pos = tokens[i]
        # split rules
        for rule in komoran_split_rules:
            if re.match(rule['regex'], f"{word}/{pos}"):
                parts = word.split()
                if len(parts) != 2:
                    break
                left, right = parts
                if left.endswith('은'):
                    stem, modifier = left[:-1], '은'
                elif left.endswith('ㄴ'):
                    stem, modifier = left[:-1], 'ㄴ'
                else:
                    break
                for w, p in rule['split']:
                    if w == "{adj_stem}": w = stem
                    elif w == "{modifier}": w = modifier
                    elif w == "{noun}": w = right
                    fixed.append([w, p])
                i += 1
                replaced = True
                break
        # n-граммы
        if not replaced:
            for n in [4, 3, 2, 1]:
                if i + n <= len(tokens):
                    key = ' '.join(f"{w}/{p}" for w, p in tokens[i:i+n])
                    if key in komoran_fixes:
                        fixed.extend(komoran_fixes[key])
                        i += n
                        replaced = True
                        break
        if not replaced:
            fixed.append(tokens[i])
            i += 1
    return fixed

# 3) Эндпоинт анализа
@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    text = data.get('text', '')

    # POS + исправления
    tokens_raw = komoran.pos(text)
    tokens_with_stems = fix_komoran(tokens_raw)

    # Собираем строку route и карту позиций
    tokens_str = [f"{w}/{p}" for w, p in tokens_with_stems]
    route = ' '.join(tokens_str)

    token_starts = []
    pos_cursor = 0
    char_to_token = {}
    for idx, ts in enumerate(tokens_str):
        token_starts.append(pos_cursor)
        for j in range(pos_cursor, pos_cursor + len(ts)):
            char_to_token[j] = idx
        pos_cursor += len(ts) + 1

    # Цвета
    def get_combined_color(word, pos):
        key = f"{word}/{pos}"
        for pattern, color in combined_colors.items():
            if re.fullmatch(pattern, key):
                return color
        return word_colors.get(word, pos_colors.get(pos, "#000000"))

    colored_tokens = [
        {"word": w, "pos": p, "color": get_combined_color(w, p)}
        for w, p in tokens_with_stems
    ]

    # Поиск и упорядочивание грамматик по токенам
    matches = []
    for pat in patterns:
        if pat.get('regex_text'):
            for m in re.finditer(pat['regex_text'], route):
                if any(match['id'] == pat['id'] for match in matches):
                    continue
                start = m.start()
                token_index = char_to_token.get(start)
                if token_index is None:
                    j = start + 1
                    while j < len(route) and j not in char_to_token:
                        j += 1
                    token_index = char_to_token.get(j, 0)
                matches.append({
                    'id':           pat['id'],
                    'pattern':      pat['pattern'],
                    'meaning':      pat['meaning'],
                    'example':      pat['example'],
                    'token_index':  token_index
                })
    matches.sort(key=lambda x: x['token_index'])
    for m in matches:
        m.pop('token_index')

    payload = {'tokens': colored_tokens, 'grammar_matches': matches}
    js = json.dumps(payload, ensure_ascii=False)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
