# -*- coding: utf-8 -*-
"""
Генератор поля `distractors` для static/data/grammar.json (задача #4).
К каждому примеру — 3 неправильные грамматические формы того же слова.

Стратегии:
  noun      — существительное + частица: другие частицы (с учётом 받침)
  bare      — однословная форма глагола/прил.: основа + другое окончание
  TAIL_SWAP — конструкция «голова + хвост»: голова as-is, хвост меняется
  OVERRIDES — особые случаи прописаны вручную
"""
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PATH = 'static/data/grammar.json'


# ────────── ХЭЛПЕРЫ ──────────
def jong(w):
    for ch in reversed(w):
        if '가' <= ch <= '힣':
            return (ord(ch) - 0xAC00) % 28
    return -1


def noun_forms(base):
    j = jong(base)
    bat = j not in (0, -1)
    rieul = j == 8
    return [
        base + ('이' if bat else '가'),
        base + ('을' if bat else '를'),
        base + ('은' if bat else '는'),
        base + '에', base + '도', base + '의', base + '한테',
        base + ('으로' if (bat and not rieul) else '로'),
    ]


def noun_distractors(base, applied):
    rest = applied[len(base):]
    sp = rest.find(' ')
    tail = rest[sp:] if sp >= 0 else ''
    out = []
    for f in noun_forms(base):
        c = f + tail
        if c != applied and c not in out:
            out.append(c)
        if len(out) == 3:
            break
    return out


VERB_ENDINGS = ['고', '지만', '거나', '게', '기']


def bare_distractors(base, applied, salt=0):
    stem = base[:-1]
    pool = [stem + e for e in VERB_ENDINGS] + [base]
    r = salt % len(pool)
    pool = pool[r:] + pool[:r]
    out = []
    for p in pool:
        if p != applied and p not in out:
            out.append(p)
        if len(out) == 3:
            break
    return out


def head_of(applied):
    """Голова конструкции = первый токен (плюс второй, если первый — 안/못)."""
    toks = applied.split(' ')
    if toks[0] in ('안', '못') and len(toks) > 1:
        return toks[0] + ' ' + toks[1]
    return toks[0]


def tail_swap(applied, tails):
    head = head_of(applied)
    out = []
    for t in tails:
        c = head + ' ' + t
        if c != applied and c not in out:
            out.append(c)
        if len(out) == 3:
            break
    return out


# ────────── КОНСТРУКЦИИ: id → список хвостов-замен ──────────
TAIL_SWAP = {
    # --- TOPIK1 ---
    'eul-geoyeyo': ['수 있어요', '때', '것 같아요'],
    'go-sipda': ['있어요', '나서', '말아요'],
    'ji-anta': ['못해요', '말아요', '마세요'],
    'ji-motada': ['않아요', '않았어요', '마세요'],
    'go-itda': ['싶어요', '나서', '말아요'],
    'a-eo-boda': ['주세요', '놓으세요', '드세요'],
    # --- TOPIK2 ---
    'eul-su-itda': ['거예요', '때', '뻔했어요'],
    'eun-jeok-itda': ['후에', '것 같아요', '데다가'],
    'myeon-joheossda': ['안 돼요', '어때요', '될 거예요'],
    'dongan': ['것 같아요', '대신에', '중이에요'],
    'gi-wihaeseo': ['전에', '때문에', '로 했어요'],
    'ateun-hu': ['적이 있어요', '것 같아요', '데다가'],
    'gijeon-e': ['위해서', '때문에', '로 했어요'],
    'l-ttae': ['거예요', '수 있어요', '것 같아요'],
    'a-eo-bojida': ['주세요', '놓았어요', '버렸어요'],
    'a-eo-gada': ['봤어요', '버렸어요', '놓았어요'],
    'ge-doeda': ['해요', '만들었어요', '하세요'],
    'l-geoya': ['수 있어요', '때', '것 같아요'],
    'maneun': ['거예요', '수 있어요', '때'],
    'l-tende': ['거예요', '수 있어요', '것 같아요'],
    # --- TOPIK3 ---
    'neun-barame': ['것 같아요', '데다가', '대신에'],
    'ttaemada': ['거예요', '수 있어요', '것 같아요'],
    'go-naseo': ['싶어요', '있어요', '말아요'],
    'a-eo-nota': ['봤어요', '주세요', '버렸어요'],
    'ge-hada': ['됐어요', '만들었어요', '돼요'],
    'neun-daesine': ['것 같아요', '데다가', '편이에요'],
    'pyeonida': ['것 같아요', '데다가', '척해요'],
    'ri-ga-eopda': ['수 없어요', '것 같아요', '뻔했어요'],
    'neun-semida': ['것 같아요', '데다가', '척해요'],
    'eulgyeom': ['때', '거예요', '것 같아요'],
    # --- TOPIK4 ---
    'banmyeone': ['것 같아요', '데다가', '척해요'],
    'dedaga': ['것 같아요', '반면에', '척해요'],
    'neun-gime': ['것 같아요', '대신에', '데다가'],
    'gi-maryeonida': ['전에', '위해서', '때문에'],
    'gi-sipsangida': ['전에', '위해서', '때문에'],
    'cheok-hada': ['것 같다', '편이다', '모양이다'],
    'eul-jeongdoro': ['때', '수 있게', '만큼'],
    'gi-nareumida': ['전에', '위해서', '때문에'],
    'eul-ppeonhada': ['거예요', '것 같았어요', '수 있었어요'],
    'eul-baeya': ['때', '거예요', '수 있어요'],
    'eul-jigyeongida': ['것 같아요', '뻔했어요', '때예요'],
    'gi-ilssuida': ['전에', '때문에', '위해서'],
    'a-eo-bwatja': ['봤어요', '놓았어요', '버렸어요'],
    'a-eo-daeda': ['봤어요', '놓았어요', '버렸어요'],
    'neun-tonge': ['것 같아요', '데다가', '바람에'],
    'neun-madange': ['것 같아요', '데다가', '대신에'],
    'gi-jjagi-eopda': ['때문에', '마련이다', '위해서'],
    'a-eo-majianhda': ['주세요', '봤어요', '버렸어요'],
    'eul-teogi-eopda': ['거예요', '것 같다', '뻔했다'],
}

# Хвосты для отдельных примеров (когда внутри правила примеры разнотипны).
TAIL_SWAP_EX = {
    'topik3/mankeum/1': ['후에', '것 같아요', '데다가'],
    'topik4/ppunman-anira/0': ['때', '것 같아요', '수 있어요'],
    'topik4/ppunman-anira/1': ['때', '것 같아요', '수 있어요'],
}


# ────────── РУЧНЫЕ ИСКЛЮЧЕНИЯ ──────────
OVERRIDES = {
    # --- TOPIK1: частицы / союзы ---
    'topik1/eun-neun/1': ['저를', '저도', '저에게'],
    'topik1/eun-neun/2': ['커피가 / 주스가', '커피를 / 주스를', '커피도 / 주스도'],
    'topik1/eseo/1': ['학교가', '학교를', '학교까지'],
    'topik1/do/0': ['저는', '저를', '저에게'],
    'topik1/ui/1': ['저', '절', '제가'],
    'topik1/ui/2': ['나', '날', '내가'],
    'topik1/geurigo/0': ['그래서', '하지만', '그런데'],
    'topik1/geurigo/1': ['그래서', '하지만', '그런데'],
    'topik1/geurigo/2': ['그래서', '하지만', '그런데'],
    'topik1/geuraeseo/0': ['그리고', '하지만', '그런데'],
    'topik1/geuraeseo/1': ['그리고', '하지만', '그런데'],
    'topik1/geuraeseo/2': ['그리고', '하지만', '그런데'],
    'topik1/hajiman/0': ['그리고', '그래서', '그런데'],
    'topik1/hajiman/1': ['그리고', '그래서', '그런데'],
    'topik1/hajiman/2': ['그리고', '그래서', '그런데'],
    'topik1/go/0': ['만나거나, 먹었어요', '만나서, 먹었어요', '만나지만, 먹었어요'],
    'topik1/go/1': ['크거나, 넓어요', '커서, 넓어요', '크지만, 넓어요'],
    'topik1/go/2': ['씻거나, 잤어요', '씻어서, 잤어요', '씻지만, 잤어요'],
    'topik1/geona/0': ['보고, 들어요', '보지만, 들어요', '봐서, 들어요'],
    'topik1/geona/1': ['읽고, 자요', '읽지만, 자요', '읽어서, 자요'],
    'topik1/geona/2': ['마시고, 먹어요', '마시지만, 먹어요', '마셔서, 먹어요'],
    'topik1/buteo-kkaji/0': ['9시에서 6시까지', '9시부터 6시에', '9시까지 6시부터'],
    'topik1/buteo-kkaji/1': ['1월에서 3월까지', '1월부터 3월에', '1월까지 3월부터'],
    'topik1/buteo-kkaji/2': ['서울부터 부산에', '서울까지 부산부터', '서울에 부산까지'],
    'topik1/eureo-gada/0': ['먹고 가다', '먹어서 가다', '먹으려고 가다'],
    'topik1/eureo-gada/1': ['사고 가다', '사서 가다', '사려고 가다'],
    'topik1/eureo-gada/2': ['운동하고 가다', '운동해서 가다', '운동하려고 가다'],
    'topik1/a-eo-boda/2': ['간 적이 있어요', '가고 싶어요', '갈 거예요'],
    # --- TOPIK1: однословные определения отсутствуют; bare ---
    # --- TOPIK2: причастия (голую форму меняем на другие причастия) ---
    'topik2/verb-past-participle/0': ['먹는', '먹을', '먹던'],
    'topik2/verb-past-participle/1': ['가는', '갈', '가던'],
    'topik2/verb-past-participle/2': ['만드는', '만들', '만들던'],
    'topik2/verb-present-participle/0': ['먹은', '먹을', '먹던'],
    'topik2/verb-present-participle/1': ['다닌', '다닐', '다니던'],
    'topik2/verb-present-participle/2': ['산', '살', '살던'],
    'topik2/verb-future-participle/0': ['먹은', '먹는', '먹던'],
    'topik2/verb-future-participle/1': ['간', '가는', '가던'],
    'topik2/verb-future-participle/2': ['-는 것 같다 / -는 수 있다', '-ㄴ 것 같다 / -ㄴ 수 있다', '-던 것 같다 / -던 수 있다'],
    'topik2/adj-present-participle/0': ['작는', '작을', '작던'],
    'topik2/adj-present-participle/1': ['크는', '클', '크던'],
    'topik2/adj-present-participle/2': ['기는', '길', '길던'],
    'topik2/neun-deut-hada/0': ['비가 온 것 같아요', '비가 올 것 같아요', '비가 오던 것 같아요'],
    'topik2/neun-deut-hada/1': ['맛있은 것 같아요', '맛있을 것 같아요', '맛있던 것 같아요'],
    'topik2/neun-deut-hada/2': ['가는 것 같아요', '갈 것 같아요', '가던 것 같아요'],
    'topik2/giro-hada/0': ['가기로 했어요', '가게 됐어요', '갈까 해요'],
    'topik2/giro-hada/1': ['먹기로 했어요', '먹게 됐어요', '먹을까 해요'],
    'topik2/giro-hada/2': ['가지 않기로 했어요', '가지 않게 됐어요', '가지 않을까 해요'],
    'topik2/a-eo-ya-hada/0': ['가도 돼요', '가면 돼요', '가게 됐어요'],
    'topik2/a-eo-ya-hada/1': ['먹어도 돼요', '먹으면 돼요', '먹게 됐어요'],
    'topik2/a-eo-ya-hada/2': ['해도 돼요?', '하면 돼요?', '하게 됐어요?'],
    'topik2/a-eo-do-doeda/0': ['앉아야 해요', '앉으면 돼요', '앉고 있어요'],
    'topik2/a-eo-do-doeda/1': ['써야 해요?', '쓰면 돼요?', '쓰고 있어요?'],
    'topik2/a-eo-do-doeda/2': ['안 와야 해요', '안 오면 돼요', '안 오고 있어요'],
    'topik2/a-eo-seo-an-doeda/0': ['해도 돼요', '해야 해요', '하고 싶어요'],
    'topik2/a-eo-seo-an-doeda/1': ['포기해도 돼요', '포기해야 해요', '포기하고 싶어요'],
    'topik2/a-eo-seo-an-doeda/2': ['마셔도 돼요', '마셔야 해요', '마시고 싶어요'],
    'topik2/giro/0': ['공부하려고 했어요', '공부하게 됐어요', '공부할까 했어요'],
    'topik2/giro/1': ['만나려고 했어요', '만나게 됐어요', '만날까 했어요'],
    'topik2/giro/2': ['가지 않으려고 했어요', '가지 않게 됐어요', '가지 않을까 했어요'],
    'topik2/ateun-hu/1': ['수업 전에', '수업 동안', '수업 중에'],
    'topik2/ateun-hu/2': ['3일 전에', '3일 동안', '3일 만에'],
    'topik2/gijeon-e/1': ['시험 후에', '시험 동안', '시험 중에'],
    'topik2/dongan/2': ['3년 전에', '3년 후에', '3년 만에'],
    'topik2/eul-su-rok/1': ['빠를 때', '빠른 만큼', '빠르기 때문에'],
    # --- TOPIK3 ---
    'topik3/dago-hada/0': ['가냐고 해요', '가라고 해요', '가자고 해요'],
    'topik3/dago-hada/1': ['춥냐고 해요', '춥겠다고 해요', '추웠다고 해요'],
    'topik3/dago-hada/2': ['학생이냐고 해요', '학생이었다고 해요', '학생이래요'],
    'topik3/nyago-hada/0': ['먹는다고 했어요', '먹으라고 했어요', '먹자고 했어요'],
    'topik3/nyago-hada/1': ['춥다고 했어요', '춥겠다고 했어요', '추웠다고 했어요'],
    'topik3/nyago-hada/2': ['학생이라고 했어요', '학생이었다고 했어요', '학생이래요'],
    'topik3/rago-hada/0': ['간다고 했어요', '가냐고 했어요', '가자고 했어요'],
    'topik3/rago-hada/1': ['가지 않는다고 했어요', '가지 말자고 했어요', '가냐고 했어요'],
    'topik3/rago-hada/2': ['드신다고 했어요', '드시냐고 했어요', '드시자고 했어요'],
    'topik3/jago-hada/0': ['만난다고 했어요', '만나냐고 했어요', '만나라고 했어요'],
    'topik3/jago-hada/1': ['먹지 말라고 했어요', '먹지 않는다고 했어요', '먹냐고 했어요'],
    'topik3/jago-hada/2': ['시작한다고 했어요', '시작하냐고 했어요', '시작하라고 했어요'],
    'topik3/deokbune/0': ['친구 때문에', '친구 덕에', '친구 탓에'],
    'topik3/deokbune/1': ['도와준 탓에', '도와주는 덕분에', '도와줄 덕분에'],
    'topik3/deokbune/2': ['부모님 때문에', '부모님 덕에', '부모님 탓에'],
    'topik3/tase/0': ['날씨 때문에', '날씨 덕분에', '날씨 덕에'],
    'topik3/tase/1': ['늦게 일어나는 탓에', '늦게 일어날 탓에', '늦게 일어나던 탓에'],
    'topik3/tase/2': ['나 탓이에요', '날 탓해요', '나는 탓이에요'],
    'topik3/gillae/2': ['뭐 하니까', '뭐 하는데', '뭐 해서'],
    'topik3/go-haeseo/0': ['피곤해서', '피곤하니까', '피곤한데'],
    'topik3/go-haeseo/1': ['먹어서', '먹으니까', '먹는데'],
    'topik3/go-haeseo/2': ['멀어서', '머니까', '먼데'],
    'topik3/neun-daesine/2': ['밥처럼', '밥하고', '밥보다'],
    'topik3/ina-bakke/0': ['시간으로 / 시간에서', '시간까지 / 시간부터', '시간에 / 시간도'],
    'topik3/na-boda/0': ['오는 것 같아요', '올 것 같아요', '오는 모양이에요'],
    'topik3/na-boda/1': ['맛있는 것 같아요', '맛있을 것 같아요', '맛있는 모양이에요'],
    'topik3/na-boda/2': ['외국인인 것 같아요', '외국인일 것 같아요', '외국인인 모양이에요'],
    'topik3/eulkka-bwa/0': ['늦을 것 같아서', '늦지 않게', '늦으면 어쩌지'],
    'topik3/eulkka-bwa/1': ['잊을 것 같아서', '잊지 않게', '잊으면 어쩌지'],
    'topik3/eulkka-bwa/2': ['걱정할 것 같아서', '걱정하지 않게', '걱정하면 어쩌지'],
    'topik3/janhayo/2': ['학생이거든요', '학생이네요', '학생이군요'],
    'topik3/neun-semida/2': ['포기한 것 같아요', '포기한 데다가', '포기한 척해요'],
    'topik3/passive-verbs/0': ['봐요', '보고 있어요', '볼 거예요'],
    'topik3/passive-verbs/1': ['잡아요', '잡고 있어요', '잡을 거예요'],
    'topik3/passive-verbs/2': ['열어요, 끊어요', '열고 있어요, 끊고 있어요', '열 거예요, 끊을 거예요'],
    'topik3/causative-verbs/0': ['먹어요', '먹고 있어요', '먹을 거예요'],
    'topik3/causative-verbs/1': ['읽어요, 알아요', '읽고 있어요, 알고 있어요', '읽을 거예요, 알 거예요'],
    'topik3/causative-verbs/2': ['자요, 낮아요', '자고 있어요, 낮고 있어요', '잘 거예요, 낮을 거예요'],
    'topik3/ryeodeon-chamida/0': ['전화하려고 했어요', '전화할 뻔했어요', '전화하던 중이었어요'],
    'topik3/ryeodeon-chamida/1': ['가려고 했어요', '갈 뻔했어요', '가던 중이었어요'],
    'topik3/ryeodeon-chamida/2': ['출발하려고 했어요', '출발할 뻔했어요', '출발하던 중이었어요'],
    'topik3/a-eoseo-geureonji/0': ['피곤한 탓인지', '피곤하기 때문인지', '피곤한지'],
    'topik3/a-eoseo-geureonji/1': ['잔 탓인지', '자기 때문인지', '잤는지'],
    'topik3/a-eoseo-geureonji/2': ['주말인 탓인지', '주말이기 때문인지', '주말인지'],
    'topik3/neunji-alda/0': ['있는 것 같아요', '있다고 해요', '있을 거예요'],
    'topik3/neunji-alda/1': ['비싼 것 같아요', '비싸다고 해요', '비쌀 거예요'],
    'topik3/neunji-alda/2': ['온 것 같아요', '왔다고 해요', '올 거예요'],
    'topik3/neutral-style/2': ['학생이야', '학생이에요', '학생입니다'],
    'topik3/a-eo-gajigo/0': ['비싸서', '비싸기 때문에', '비싼 탓에'],
    'topik3/a-eo-gajigo/1': ['사서', '사기 때문에', '산 탓에'],
    'topik3/a-eo-gajigo/2': ['몰라서', '모르기 때문에', '모르는 탓에'],
    'topik3/a-eo-beorida/2': ['끝내 봤어요', '끝내 놓았어요', '끝내 주세요'],
    # --- TOPIK4 ---
    'topik4/ppunman-anira/2': ['학생일 뿐만 아니라', '학생인 데다가', '학생 외에도'],
    'topik4/e-dallyeo-itda/1': ['하기 나름이다', '하기 마련이다', '하는 셈이다'],
    'topik4/neun-tonge/2': ['고장 난 통에', '고장 날 통에', '고장 나던 통에'],
    'topik4/euryeoni-hada/0': ['바쁜가 하고', '바쁘겠거니 하고', '바쁘다고 하고'],
    'topik4/euryeoni-hada/1': ['그런가 하다', '그렇겠거니 하다', '그렇다고 하다'],
    'topik4/euryeoni-hada/2': ['갔는가 하다', '갔겠거니 하다', '갔다고 하다'],
    'topik4/da-motae/0': ['참다가', '참으면서', '참는 대신'],
    'topik4/da-motae/1': ['기다리다가', '기다리면서', '기다리는 대신'],
    'topik4/da-motae/2': ['슬프다가', '슬프면서', '슬픈 대신'],
}


def main():
    data = json.load(open(PATH, encoding='utf-8'))
    problems = []
    counter = 0
    filled = 0
    for level, items in data.items():
        for item in items:
            iid = item.get('id')
            for ei, ex in enumerate(item.get('examples', [])):
                key = "%s/%s/%d" % (level, iid, ei)
                base = ex.get('base', '') or ''
                applied = ex.get('applied', '') or ''
                d = None
                if key in OVERRIDES:
                    d = OVERRIDES[key]
                elif key in TAIL_SWAP_EX:
                    d = tail_swap(applied, TAIL_SWAP_EX[key])
                elif iid in TAIL_SWAP and ' ' in applied:
                    d = tail_swap(applied, TAIL_SWAP[iid])
                elif (base.endswith('다') and ' ' not in base
                      and ' ' not in applied and base != '-'):
                    d = bare_distractors(base, applied, counter)
                elif (base and base not in ('-', '저', '나')
                      and applied.startswith(base)
                      and not applied[len(base):].startswith(' ')
                      and not any(c in base for c in ' ,/→')):
                    d = noun_distractors(base, applied)
                counter += 1
                if (not d or len(d) != 3 or len(set(d)) != 3
                        or applied in d or any(not x for x in d)):
                    problems.append((key, base, applied, str(d)))
                    continue
                ex['distractors'] = list(d)
                filled += 1

    if problems:
        print('ПРОБЛЕМЫ (%d):' % len(problems))
        for p in problems:
            print('  ', p)
        print('NOT WRITTEN.')
        return
    with open(PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('OK: distractors filled for %d examples.' % filled)


if __name__ == '__main__':
    main()
