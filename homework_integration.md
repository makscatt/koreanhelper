# Инструкция: добавление маркера «Домашка» в тренажёр

## Как это работает в целом

1. Учитель нажимает 📝 в тренажёре → в БД (`TrainerItemProgress`) пишется запись `status='homework'`
2. Дашборд автоматически подтягивает все такие записи и показывает карточки ДЗ
3. Клик по карточке на дашборде → переход в тренажёр с якорем `#item_id` → тренажёр открывает нужный элемент

---

## Шаг 1 — Определить `item_id`

`item_id` — уникальный строковый идентификатор элемента внутри тренажёра.

| Тренажёр    | item_id                          |
|-------------|----------------------------------|
| sentences   | `grammar_id` (например `i-ga`)   |
| texts       | `slug` (slugify от заголовка)    |
| новый       | любой уникальный id из JSON      |

Правило: `item_id` должен быть стабильным — одинаковым при каждой загрузке страницы.

---

## Шаг 2 — Добавить кнопку в HTML

Найти место рядом с элементом (карточка, строка, шапка) и добавить кнопку:

```html
<button class="hw-btn" onclick="toggleHomework('ITEM_ID')" title="Домашка">📝</button>
```

Стили кнопки (добавить в `<style>` тренажёра):

```css
.hw-btn {
  width: 32px; height: 32px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-surface);
  cursor: pointer;
  font-size: 16px;
  opacity: 0.4;
  transition: all 0.15s;
}
.hw-btn.active {
  opacity: 1;
  border-color: var(--primary);
  background: var(--primary-container);
}
```

---

## Шаг 3 — Добавить JS-логику

### 3.1 Хранилище статусов (в начале JS-блока)

```js
let hwChecks = {}; // { item_id: 'homework' }
```

### 3.2 Загрузка статусов при старте (добавить в loadChecks или loadData)

```js
async function loadHwChecks() {
  const res = await fetch('/api/items/get', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ student_id: STUDENT_ID, trainer: 'ИМЯ_ТРЕНАЖЁРА' })
  });
  const data = await res.json();
  if (data.ok) {
    for (const [key, val] of Object.entries(data.items)) {
      if (val === 'homework') hwChecks[key] = 'homework';
    }
  }
}
```

### 3.3 Тогл домашки

```js
async function toggleHomework(itemId) {
  const current = hwChecks[itemId] || '';
  const next = current === 'homework' ? '' : 'homework';

  await fetch('/api/items/set', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      student_id: STUDENT_ID,
      trainer: 'ИМЯ_ТРЕНАЖЁРА',
      item_id: itemId,
      status: next
    })
  });

  if (next) hwChecks[itemId] = next;
  else delete hwChecks[itemId];

  updateHwButton(itemId);
}
```

### 3.4 Визуальное обновление кнопки

```js
function updateHwButton(itemId) {
  const btn = document.querySelector(`.hw-btn[data-id="${itemId}"]`);
  if (btn) btn.classList.toggle('active', hwChecks[itemId] === 'homework');
}
```

> Кнопке в HTML нужно добавить `data-id`:
> ```html
> <button class="hw-btn" data-id="ITEM_ID" onclick="toggleHomework('ITEM_ID')">📝</button>
> ```

### 3.5 Подсветка при рендере элементов

При отрисовке каждого элемента добавлять класс если есть домашка:

```js
const isHw = hwChecks[itemId] === 'homework';
card.classList.toggle('hw-active', isHw);
// и на кнопку:
btn.classList.toggle('active', isHw);
```

---

## Шаг 4 — Обработка якоря при открытии

В конце init-цепочки (после загрузки данных) добавить:

```js
.then(() => {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash) {
    // sentences-style: выбрать тему
    setTopic(hash);

    // texts-style: открыть модалку
    const idx = allData.findIndex(item => item.id === hash);
    if (idx !== -1) openModal(idx);

    // универсально: скроллить к элементу с data-id
    const el = document.querySelector(`[data-id="${hash}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
});
```

Выбрать нужный вариант в зависимости от структуры тренажёра.

---

## Шаг 5 — Добавить иконку в словарь дашборда

В `dashboard.html` найти `trainer_meta` и добавить строку:

```jinja
'ИМЯ_ТРЕНАЖЁРА': {'icon': '🎯', 'name': 'Название'},
```

Если не добавить — тренажёр всё равно появится на дашборде с иконкой 📌 и техническим именем.

---

## Чеклист

- [ ] Определил `item_id`
- [ ] Добавил кнопку 📝 в HTML с `data-id`
- [ ] Добавил стили кнопки
- [ ] Добавил `hwChecks` и `loadHwChecks()`
- [ ] Добавил `toggleHomework()` и `updateHwButton()`
- [ ] Подсвечиваю элементы при рендере
- [ ] Добавил обработку `location.hash` в init
- [ ] Добавил тренажёр в `trainer_meta` в `dashboard.html`
