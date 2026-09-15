import sys, os
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for p in (os.path.join(_root, 'src'), _root):
    sys.path.insert(0, p)
from types import SimpleNamespace as S
from worker import is_hallucination

segs = [
    (S(text=' Субтитры делал DimaTorzok', no_speech_prob=0.9, avg_logprob=-0.2), True),
    (S(text=' Обсудим бюджет проекта', no_speech_prob=0.1, avg_logprob=-0.3), False),
    (S(text='   ', no_speech_prob=0.9, avg_logprob=-0.5), True),
    (S(text=' Да, я согласен с планом', no_speech_prob=0.6, avg_logprob=-0.9), True),
    (S(text=' Нормальная речь', no_speech_prob=0.6, avg_logprob=-0.5), False),
    (S(text=' Продолжение следует...', no_speech_prob=0.4, avg_logprob=-0.1), True),
]
for seg, expected in segs:
    got = is_hallucination(seg)
    assert got == expected, f"FAIL: {seg.text!r} -> {got}, expected {expected}"
print("HALLUCINATION_FILTER_OK")
