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
multi_token_colors = colors_data.get('MULTI', {})
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
        # 0) Проверка по split-правилам
        word, pos = tokens[i]
        for rule in komoran_split_rules:
            if re.match(rule['regex'], f"{word}/{pos}"):
                print("SPLIT MATCH:", word, pos)

                # Разбиваем по пробелу
                parts = word.split()
                if len(parts) != 2:
                    break  # Защита от некорректных случаев

                left, right = parts[0], parts[1]

                # Выделение основы и окончания из левой части (형용사 + ETM)
                if left.endswith('은'):
                    stem = left[:-1]
                    modifier = '은'
                elif left.endswith('ㄴ'):
                    stem = left[:-1]
                    modifier = 'ㄴ'
                else:
                    break  # Неизвестное окончание

                # Подстановка в шаблон split
                fixed_entry = []
                for w, p in rule['split']:
                    if w == "{adj_stem}":
                        w = stem
                    elif w == "{modifier}":
                        w = modifier
                    elif w == "{noun}":
                        w = right
                    fixed_entry.append([w, p])

                print("SPLIT FIX:", f"{word}/{pos}", "→", fixed_entry)
                fixed.extend(fixed_entry)
                i += 1
                replaced = True
                break
        # Пробуем 3-грамму, 2-грамму, 1-грамму — в этом порядке
        for n in [4, 3, 2, 1]:
            if i + n <= len(tokens):
                key = ' '.join(f"{w}/{p}" for w, p in tokens[i:i + n])
                print("CHECKING:", key)  # Добавь это
                if key in komoran_fixes:
                    print("FIXING:", key, "→", komoran_fixes[key])  # И это
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
    print("RAW DATA:", data)
    text = data.get('text', '')
    print("TEXT:", text.encode('utf-8'))
    
    parsed_for_grammar = komoran.pos(text)
    route = ' '.join(f'{word}/{pos}' for word, pos in parsed_for_grammar)
    print("ROUTE:", route)
    tokens_raw = komoran.pos(text)
    tokens_with_stems = fix_komoran(tokens_raw)
    print("\nDEBUG: Порядок токенов после fix_komoran():")
    for idx, (w, p) in enumerate(tokens_with_stems):
        print(f"{idx}: {w}/{p}")
    print()

    # путь через fix_komoran:
    route = ' '.join(f'{word}/{pos}' for word, pos in tokens_with_stems)

    def get_combined_color(word, pos):
        key = f"{word}/{pos}"
        for pattern, color in combined_colors.items():
            if re.fullmatch(pattern, key):
                return color
        return word_colors.get(word, pos_colors.get(pos, "#000000"))

    def get_multitoken_colors(route, tokens):
        match_spans = []  # Список: [(start_index, end_index, color)]

        for pattern, color in multi_token_colors.items():
            if ' ' in pattern:  # ← т.е. цепочка токенов
                for m in re.finditer(pattern, route):
                    char_start = m.start()
                    char_end = m.end()

                # Считаем, какой это токен по счёту
                    token_positions = []
                    cursor = 0
                    for i, tok in enumerate(tokens):
                        token_str = f"{tok[0]}/{tok[1]}"
                        if cursor == char_start:
                            start_idx = i
                        cursor += len(token_str)
                        if cursor >= char_end:
                            end_idx = i
                            break
                        cursor += 1  # за пробел
                    match_spans.append((start_idx, end_idx, color))
        return match_spans

    colored_tokens = []
    multi_color_ranges = get_multitoken_colors(route, tokens_with_stems)

    for i, (w, p) in enumerate(tokens_with_stems):
        color = get_combined_color(w, p)
        for start, end, group_color in multi_color_ranges:
            if start <= i <= end:
                color = group_color
                break
        colored_tokens.append({
            "word": w,
            "pos": p,
            "color": color
        })


    matches = []
    for pat in patterns:
        if pat.get('regex_text'):
            for m in re.finditer(pat['regex_text'], route):
                if not any(match['id'] == pat['id'] for match in matches):
                    matches.append({
                        'id': pat['id'],
                        'pattern': pat['pattern'],
                        'meaning': pat['meaning'],
                        'example': pat['example'],
                        'start': m.start()  # ← сохраняем индекс начала
                    })
    matches.sort(key=lambda x: x['start'])
    for m in matches:
        m.pop('start')                

    payload = {
        'tokens':           colored_tokens,
        'grammar_matches':  matches
    }
    print("MATCHES:", matches)
    js = json.dumps(payload, ensure_ascii=False)
    print("RESPONSE:", js)
    return Response(js, mimetype='application/json; charset=utf-8')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
