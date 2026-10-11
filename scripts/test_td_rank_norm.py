"""
test_td_rank_norm.py
====================
td_rank_norm の順位正規化を TouchDesigner 無しで検証する。

実行:
    python3 scripts/test_td_rank_norm.py    # 標準出力に各ケースの結果
"""
import importlib
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import td_rank_norm as rn
importlib.reload(rn)

FPS = 60.0
REF = 0.018            # high の較正値（p95）


def feed(norm, values, t0=0.0):
    """values を 60fps で流し、(最後の時刻, 出力列) を返す。"""
    out = []
    t = t0
    for v in values:
        out.append(norm.update(v, t))
        t += 1.0 / FPS
    return t, out


def case_scale_invariant():
    """音量だけ違う同じ曲 → 正規化後は同じ値になる（曲ごとの音量差が消える）。"""
    random.seed(1)
    song = [0.01 + random.random() * 0.03 for _ in range(int(FPS * 40))]
    a, b = rn.RankNorm(REF), rn.RankNorm(REF)
    _, oa = feed(a, song)
    _, ob = feed(b, [v * 0.25 for v in song])      # 1/4 の音量
    tail = slice(-int(FPS * 5), None)
    diff = max(abs(x - y) for x, y in zip(oa[tail], ob[tail]))
    assert diff < 1e-12, diff
    raw_ratio = max(song[tail]) / max(v * 0.25 for v in song[tail])
    return f'1/4音量でも同じ出力（最大差 {diff:.1e}、生の値は {raw_ratio:.0f}倍違う）'


def case_percentile_mapping():
    """p10 以下→0、p90 以上→ref、中央値→ref/2 前後。"""
    norm = rn.RankNorm(REF)
    vals = [0.002 + 0.0001 * (i % 200) for i in range(int(FPS * 40))]   # 0.002〜0.0219 の一様
    t, _ = feed(norm, vals)
    lo = norm.update(0.0025, t)
    hi = norm.update(0.0215, t)
    mid = norm.update(0.012, t)
    assert lo == 0.0, lo
    assert abs(hi - REF) < 1e-12, hi
    assert abs(mid - REF / 2) < REF * 0.05, mid
    return f'p10以下={lo}, p90以上={hi:.4f}(=ref), 中央={mid:.4f}(≈ref/2)'


def case_silence_floor():
    """無音（ref の1%未満）は 0 を返し、履歴にも入らない。"""
    norm = rn.RankNorm(REF)
    _, out = feed(norm, [REF * 0.005] * int(FPS * 10))
    assert all(o == 0.0 for o in out)
    assert len(norm) == 0, len(norm)
    return f'10秒の無音で出力0・履歴{len(norm)}件'


def case_warmup_passthrough():
    """履歴が MIN_SAMPLES 未満の立ち上がりは生の値をそのまま返す。"""
    norm = rn.RankNorm(REF)
    v = 0.013
    first = norm.update(v, 0.0)
    assert first == v, first
    return f'立ち上がりは生の値 {first} を返す'


def case_window_cap_and_adapt():
    """履歴は WINDOW_SEC×SAMPLE_HZ で頭打ち。大きい区間の後、静かな区間に慣れる。"""
    norm = rn.RankNorm(REF)
    t, _ = feed(norm, [0.03] * int(FPS * 40))                 # 大きい区間 40秒
    cap = int(rn.WINDOW_SEC * rn.SAMPLE_HZ)
    assert len(norm) == cap, (len(norm), cap)
    quiet = [0.004 + 0.002 * ((i // 7) % 5) for i in range(int(FPS * 40))]   # 0.004〜0.012
    just_after = norm.update(0.012, t)
    t, _ = feed(norm, quiet, t0=t)
    adapted = norm.update(0.012, t)
    assert just_after == 0.0, just_after
    assert abs(adapted - REF) < 1e-12, adapted
    return (f'履歴上限 {len(norm)}件。静かな区間の最大音は、直後={just_after}'
            f' → 40秒後={adapted:.4f}(=ref)')


def case_nan_ignored():
    """上流が NaN/inf を出しても 0 を返し、履歴を壊さない（壊れると以後 ref/2 に張り付く）。"""
    norm = rn.RankNorm(REF)
    vals = [0.002 + 0.0001 * (i % 200) for i in range(int(FPS * 20))]
    t, _ = feed(norm, vals)
    n = len(norm)
    bad = [norm.update(x, t + i) for i, x in enumerate((float('nan'), float('inf'), float('-inf')))]
    assert bad == [0.0, 0.0, 0.0], bad
    assert len(norm) == n, (len(norm), n)
    hi = norm.update(0.0215, t + 5)
    assert abs(hi - REF) < 1e-12, hi
    return f'NaN/inf→{bad}、履歴{n}件のまま、その後も p90以上=ref'


def case_observe_rank():
    """observe は立ち上がり中 None、その後は生の順位（0〜1、p10/p90 の写しなし）。
    オンセット検出が順位そのものでしきい値判定するために使う。"""
    norm = rn.RankNorm(REF)
    assert norm.observe(0.01, 0.0) is None
    vals = [0.002 + 0.0001 * (i % 200) for i in range(int(FPS * 20))]
    t, _ = feed(norm, vals)
    top = norm.observe(0.0219, t)
    mid = norm.observe(0.012, t)
    silent = norm.observe(REF * 0.005, t)
    assert top > 0.97, top
    assert abs(mid - 0.5) < 0.05, mid
    assert silent == 0.0, silent
    return f'立ち上がり None → 最大付近 {top:.3f} / 中央 {mid:.3f} / 無音 {silent}'


def case_fps_independent():
    """30fps と 120fps で流しても履歴の件数は同じ（時間で間引く）。"""
    counts = []
    for fps in (30.0, 120.0):
        norm = rn.RankNorm(REF)
        t = 0.0
        for _ in range(int(fps * 10)):
            norm.update(0.01, t)
            t += 1.0 / fps
        counts.append(len(norm))
    assert abs(counts[0] - counts[1]) <= 1, counts
    return f'10秒で 30fps={counts[0]}件 / 120fps={counts[1]}件'


if __name__ == '__main__':
    cases = [case_scale_invariant, case_percentile_mapping, case_silence_floor,
             case_warmup_passthrough, case_window_cap_and_adapt, case_nan_ignored,
             case_observe_rank, case_fps_independent]
    for c in cases:
        print(f'[ok] {c.__name__}: {c()}')
    print(f'all {len(cases)} cases passed')
