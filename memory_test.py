# memory_test.py
import time
from memory_profiler import profile
# ИЗМЕНЕНИЕ: импортируем Okt вместо Komoran
from konlpy.tag import Okt

@profile
def load_okt():
    print("Начинаю загрузку Okt...")
    # ИЗМЕНЕНИЕ: создаем экземпляр Okt
    okt = Okt()
    print("Okt успешно загружен.")
    print("Теперь модель в памяти. Нажмите Ctrl+C для выхода через 10 секунд.")
    time.sleep(10)
    print("Тест завершен.")

if __name__ == '__main__':
    load_okt()