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
# 1.1) Загрузка маппинга POS→цветов
with open('colors.json', encoding='utf-8') as f:
    colors_data = json.load(f)

combined_colors = colors_data.get('COMBINED', {})
word_colors = colors_data.get('WORDS', {})
pos_colors = colors_data.get('POS', {})
# 1.2) Загрузка исправлений для Komoran
with open('komoran_corrections.json', encoding='utf-8') as f:
    komoran_fixes = json.load(f)
# 1.3) Загрузка правил разбиения слитых токенов
with open('komoran_split_rules.json', encoding='utf-8') as f:
    komoran_split_rules = json.load(f)

# 1.4) Функция фикса ошибок Komoran

def fix_komoran(tokens):
    fixed = []
    i = 0
    while i < len(tokens):
        replaced = False
        word, pos = tokens[i]
        # 0) Проверка по split-правилам
        for rule in komoran_split_rules:
            if re.match(rule['regex'], f"{word}/{pos}"):
                parts = word.split()
                if len(parts) != 2:
                    break
                left, right = parts[0], parts[1]
                if left.endswith('은'):
                    stem, modifier = left[:-1], '은'
                elif left.endswith('ㄴ'):
                    stem, modifier = left[:-1], 'ㄴ'
                else:
                    break
                fixed_entry = []
                for w, p in rule['split']:
                    if w == "{adj_stem}": w = stem
                    elif w == "{modifier}": w = modifier
                    elif w == "{noun}": w = right
                    fixed_entry.append([w, p])
                fixed.extend(fixed_entry)
                i += 1
                replaced = True
                break
        # 1) Комбинации из 4,3,2,1 n-грамм
        if not replaced:
            for n in [4, 3, 2, 1]:
                if i + n <= len(tokens):
                    key = ' '.join(f"{w}/{p}" for w, p in tokens[i:i + n])
                    if key in komoran_fixes:
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
    text = data.get('text', '')
    
    # POS-токены и корректировка
    tokens_raw = komoran.pos(text)
    tokens_with_stems = fix_komoran(tokens_raw)

    # === ИЗМЕНЕНИЕ: вычисление позиционной карты токенов ===
    tokens_str = [f"{w}/{p}" for w, p in tokens_with_stems]
    route = ' '.join(tokens_str)

    token_starts = []
    pos_cursor = 0
    for ts in tokens_str:
        token_starts.append(pos_cursor)
        pos_cursor += len(ts) + 1  # +1 за пробел

    # Цвета для токенов
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

    # Поиск грамматик с сортировкой по индексу токена
    matches = []
    for pat in patterns:
        if pat.get('regex_text'):
            for m in re.finditer(pat['regex_text'], route):
                if not any(match['id'] == pat['id'] for match in matches):
                    token_index = max(i for i, st in enumerate(token_starts) if st <= m.start())
                    matches.append({
                        'id': pat['id'],
                        'pattern': pat['pattern'],
                        'meaning': pat['meaning'],
                        'example': pat['example'],
                        'token_index': token_index
                    })
    matches.sort(key=lambda x: x['token_index'])
    for m in matches:
        m.pop('token_index')
    # === /ИЗМЕНЕНИЕ ===

    payload = {
        'tokens':           colored_tokens,
        'grammar_matches':  matches
    }

    js = json.dumps(payload, ensure_ascii=False)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
