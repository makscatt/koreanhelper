from konlpy.tag import Komoran
komoran = Komoran()
text = "가야 해요"
result = komoran.pos(text)
print(result)