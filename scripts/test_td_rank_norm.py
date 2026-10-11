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
from collections import deque

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


def case_expire_after_silence():
    """大きい曲 → 無音40秒 → 小さい曲。無音の間に前の曲の履歴が時刻で消え、
    小さい曲は立ち上がり後すぐに自分の中の順位で反応する（PR #10 のレビュー指摘）。"""
    norm = rn.RankNorm(REF)
    loud = [0.03 + 0.0002 * (i % 50) for i in range(int(FPS * 40))]     # 0.03〜0.0398
    t, _ = feed(norm, loud)
    t, _ = feed(norm, [0.0] * int(FPS * 40), t0=t)                       # 無音（floor 未満）
    after_silence = len(norm)
    quiet = [0.004 + 0.0002 * (i % 50) for i in range(int(FPS * 5))]    # 0.004〜0.0138
    t, _ = feed(norm, quiet, t0=t)
    top = norm.update(0.0138, t)
    assert after_silence == 0, after_silence
    assert abs(top - REF) < 1e-12, top
    # 比較: 件数だけで区切る旧実装相当（窓を無限に長くする）だと前の曲が残り、反応しない
    old = rn.RankNorm(REF, window_sec=1e9)
    old._order = deque(maxlen=int(rn.WINDOW_SEC * rn.SAMPLE_HZ))
    t2, _ = feed(old, loud)
    t2, _ = feed(old, [0.0] * int(FPS * 40), t0=t2)
    t2, _ = feed(old, quiet, t0=t2)
    stale = old.update(0.0138, t2)
    assert stale < REF * 0.1, stale          # 前の曲600件の中では下位に沈む
    return (f'無音40秒後の履歴 {after_silence}件 → 小さい曲の5秒後に最大音={top:.4f}(=ref)'
            f'（件数だけで区切ると {stale:.4f}）')


def case_clock_reset():
    """時計が1秒以上戻ったら履歴を空にする（未来の時刻が残って捨てられなくなるのを防ぐ）。"""
    norm = rn.RankNorm(REF)
    t, _ = feed(norm, [0.01] * int(FPS * 10), t0=100.0)
    before = len(norm)
    norm.observe(0.01, 0.0)
    assert before > 0 and len(norm) <= 1, (before, len(norm))
    return f'時刻 110→0 で履歴 {before}件 → {len(norm)}件'


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


# --- オンセット検出（OnsetDetector）。しきい値は build_onset_scenes.py の値をそのまま使う ---
import math
import types
sys.modules.setdefault('td', types.ModuleType('td'))   # build_*.py の import td を通すだけ
import build_onset_scenes as bo


def make_detector():
    return rn.OnsetDetector(bo.ONSET_HI, bo.ONSET_LO, bo.ONSET_RANK_HI, bo.ONSET_RANK_LO,
                            bo.LOW_REF, round(bo.LOW_REF * bo.ONSET_MIN_RATIO, 4))


def kicks(peak, sec=30.0, every=0.5, seed=0):
    """every 秒ごとのキック（指数減衰）＋小さな揺れ。低域の値を 60fps で返す。"""
    random.seed(seed)
    out = []
    for i in range(int(FPS * sec)):
        t = i / FPS
        ph = t % every
        out.append(peak * (math.exp(-ph / 0.08) + 0.05 * random.random()))
    return out


def count_fires(det, vals, test=False, rank_on=True):
    armed, n = 1, 0
    for i, v in enumerate(vals):
        fire, armed = det.feed(v, i / FPS, armed, test=test, rank_on=rank_on)
        n += fire
    return n


def case_onset_one_fire_per_kick():
    """キック60回（30秒）で、順位でも生の値でも発火はちょうど60回（多重発火しない）。"""
    vals = kicks(0.3)
    a = count_fires(make_detector(), vals)
    b = count_fires(make_detector(), vals, rank_on=False)
    assert a == 60 and b == 60, (a, b)
    return f'キック60回 → 順位 {a}回 / 生の値 {b}回'


def case_onset_quiet_song():
    """音量1/4の曲: 生の値のしきい値では0回、順位なら立ち上がり以降のキックをすべて拾う。"""
    vals = kicks(0.3 * 0.25)
    raw = count_fires(make_detector(), vals, rank_on=False)
    rank = count_fires(make_detector(), vals)
    warm = int(rn.MIN_SAMPLES / rn.SAMPLE_HZ / 0.5)          # 立ち上がり約2秒ぶんのキック
    assert raw == 0, raw
    assert 60 - warm - 1 <= rank <= 60, rank
    return f'音量1/4 → 生の値 {raw}回 / 順位 {rank}回（立ち上がりの約{warm}回は生の値の判定）'


def case_onset_no_kick_section():
    """キックの無い静かな揺れ（最大0.05、keys のステム相当）は、最低ラインで発火しない。
    最低ラインを外すと順位だけで発火してしまうことも確かめる。"""
    random.seed(3)
    vals, x = [], 0.02
    for _ in range(int(FPS * 60)):
        x = min(0.05, max(0.005, x + random.uniform(-0.004, 0.004)))
        vals.append(x)
    gated = count_fires(make_detector(), vals)
    det = make_detector()
    det.min_level = 0.0
    ungated = count_fires(det, vals)
    assert gated == 0, gated
    assert ungated > 0, ungated
    return f'キック無し60秒 → 最低ラインあり {gated}回 / なし {ungated}回'


def case_onset_test_injection():
    """テスト注入（__onsettest）は履歴が空でも生の値で即発火する。"""
    det = make_detector()
    fire, armed = det.feed(0.5, 0.0, 1, test=True)
    assert fire and armed == 0, (fire, armed)
    return 'low=0.5 の注入で1フレーム目に発火'


def case_onset_nan_rearms():
    """上流が NaN を出しても、順位の経路では0扱いで再武装できる（生の値の経路は止まる）。"""
    det = make_detector()
    count_fires(det, kicks(0.3, sec=5))                       # 履歴を作る
    _, armed = det.feed(0.5, 5.0, 1)                          # 発火して armed=0
    _, armed = det.feed(float('nan'), 5.1, armed)
    raw_armed = rn.OnsetDetector.step(0, float('nan'), bo.ONSET_HI, bo.ONSET_LO)[1]
    assert armed == 1, armed
    assert raw_armed == 0, raw_armed
    return f'NaN で 順位の経路は再武装（armed={armed}）/ 生の値の経路は止まったまま（armed={raw_armed}）'


if __name__ == '__main__':
    cases = [case_scale_invariant, case_percentile_mapping, case_silence_floor,
             case_warmup_passthrough, case_window_cap_and_adapt, case_nan_ignored,
             case_observe_rank, case_expire_after_silence, case_clock_reset,
             case_fps_independent, case_onset_one_fire_per_kick, case_onset_quiet_song,
             case_onset_no_kick_section, case_onset_test_injection, case_onset_nan_rearms]
    for c in cases:
        print(f'[ok] {c.__name__}: {c()}')
    print(f'all {len(cases)} cases passed')
