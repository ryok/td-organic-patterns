"""
test_td_param_bus.py
====================
td_param_bus のコンポーズ契約を TouchDesigner 無しで検証する。
TD の Par / パラメータコレクション / storage / op() を最小スタブで再現し、
順序非依存・冪等・旧「全置換で他項が消える」バグの解消・多所有者共存・clamp・
remove を確認する。

実行:
    python3 scripts/test_td_param_bus.py    # 標準出力に各ケースの結果
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import td_param_bus as pbus
importlib.reload(pbus)


class Par:
    def __init__(self, expr=None, val=0.0):
        self._expr, self._val = expr, val

    @property
    def expr(self):
        return self._expr

    @expr.setter
    def expr(self, v):
        self._expr = v

    def eval(self):
        return self._val


class ParColl:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Node:
    def __init__(self, **pars):
        self.par = ParColl(**pars)


class Parent:
    """storage + op() のスタブ。"""
    def __init__(self):
        self._store, self._ops = {}, {}

    def op(self, name):
        return self._ops.get(name)

    def store(self, k, v):
        self._store[k] = v

    def fetch(self, k, default=None):
        return self._store.get(k, default)


def _engine():
    p = Parent()
    p._ops['warp_disp'] = Node(displaceweightx=Par(val=0.09))
    p._ops['hsv1'] = Node(saturationmult=Par(val=2.2),
                          valuemult=Par(val=1.25),
                          hueoffset=Par(expr='absTime.seconds*6'))
    p._ops['level1'] = Node(opacity=Par(val=0.99))
    return p


def test_order_independence():
    a = _engine()
    pbus.add_term(a, 'hsv1', 'saturationmult', 'audio', "op('aud_lag')['high']*1.5", base='2.2')
    pbus.add_term(a, 'hsv1', 'saturationmult', 'accent', "env*1.8")
    b = _engine()
    pbus.add_term(b, 'hsv1', 'saturationmult', 'accent', "env*1.8", base='2.2')
    pbus.add_term(b, 'hsv1', 'saturationmult', 'audio', "op('aud_lag')['high']*1.5", base='2.2')
    for e in (a.op('hsv1').par.saturationmult.expr, b.op('hsv1').par.saturationmult.expr):
        assert '2.2' in e and "op('aud_lag')['high']*1.5" in e and 'env*1.8' in e, e
    print('OK order-independence')


def test_idempotent():
    p = _engine()
    pbus.add_term(p, 'hsv1', 'saturationmult', 'audio', "op('aud_lag')['high']*1.5", base='2.2')
    e1 = p.op('hsv1').par.saturationmult.expr
    pbus.add_term(p, 'hsv1', 'saturationmult', 'audio', "op('aud_lag')['high']*1.5", base='2.2')
    e2 = p.op('hsv1').par.saturationmult.expr
    assert e1 == e2 and e2.count("op('aud_lag')['high']*1.5") == 1, e2
    print('OK idempotent')


def test_whole_replace_no_longer_wipes():
    """旧バグ: audio→accent の後に audio 再実行で accent 項が消えていた。"""
    p = _engine()
    pbus.add_term(p, 'hsv1', 'saturationmult', 'audio', "op('aud_lag')['high']*1.5", base='2.2')
    pbus.add_term(p, 'hsv1', 'saturationmult', 'accent', "env*1.8")
    pbus.add_term(p, 'hsv1', 'saturationmult', 'audio', "op('aud_lag')['high']*1.5", base='2.2')
    assert 'env*1.8' in p.op('hsv1').par.saturationmult.expr
    print('OK accent survives audio re-run')


def test_hueoffset_multiowner():
    p = _engine()
    pbus.add_term(p, 'hsv1', 'hueoffset', 'bpm_hue', pbus.PHASE_SRC + "['rampbar']*40", base='absTime.seconds*6')
    pbus.add_term(p, 'hsv1', 'hueoffset', 'scene_hue', "float(op('scene_table')[1,'hue_base'])", base='absTime.seconds*6')
    pbus.add_term(p, 'hsv1', 'hueoffset', 'midi', "op('ctrl')['k3']*180", base='absTime.seconds*6')
    e = p.op('hsv1').par.hueoffset.expr
    for frag in ('absTime.seconds*6', "['rampbar']*40",
                 "float(op('scene_table')[1,'hue_base'])", "op('ctrl')['k3']*180"):
        assert frag in e, (frag, e)
    print('OK hueoffset 3 owners coexist')


def test_clamp():
    p = _engine()
    pbus.add_term(p, 'level1', 'opacity', 'audio', "op('aud_lag')['rms']*0.012", base='0.985', clamp=(0.0, 0.999))
    pbus.add_term(p, 'level1', 'opacity', 'accent', "env*0.003")
    e = p.op('level1').par.opacity.expr
    assert e.startswith('tdu.clamp(') and e.endswith(', 0.0, 0.999)'), e
    assert '0.985' in e and 'env*0.003' in e, e
    print('OK clamp')


def test_wrap():
    """色相は % 360 で折り返す（TD の [-360,360] クランプ張り付き防止）。"""
    p = _engine()
    pbus.add_term(p, 'hsv1', 'hueoffset', 'scene_hue', "90", base='absTime.seconds*6', wrap=360)
    pbus.add_term(p, 'hsv1', 'hueoffset', 'midi', "k3*180")
    e = p.op('hsv1').par.hueoffset.expr
    assert e.endswith(') % 360'), e
    # 実数で評価して折り返しを確認（absTime.seconds=317.65 → 1905.9+90=1995.9 → 195.9）
    val = eval(e, {'absTime': type('T', (), {'seconds': 317.65}), 'k3': 0})
    assert 0 <= val < 360 and abs(val - 195.9) < 1e-6, val
    print('OK wrap')


class _Chop:
    """チャンネル名→値。存在しないチャンネルは TD と同様 None を返す。"""
    def __init__(self, **chans):
        self._c = chans

    def __getitem__(self, k):
        return self._c.get(k)


def _ev(expr, ops):
    """ops に無い名前は None を返す op() で式を評価する（TD の欠損 op を再現）。"""
    tdu = type('tdu', (), {'clamp': staticmethod(lambda v, lo, hi: max(lo, min(hi, v)))})
    return eval(expr, {'op': lambda n: ops.get(n), 'tdu': tdu})


def test_ch_null_safe():
    e = pbus.ch('aud_lag', 'low') + '*0.35'
    assert abs(_ev(e, {'aud_lag': _Chop(low=0.5)}) - 0.175) < 1e-9     # 通常
    assert _ev(e, {}) == 0                                               # op 欠損 → 0
    assert _ev(e, {'aud_lag': _Chop(mid=0.5)}) == 0                      # ch 欠損 → 0
    print('OK ch null-safe')


def test_phase_zero_is_not_missing():
    """拍頭(rampbeat=0)を『欠損』と取り違えない（`or` 形式だと既定1に化けて包絡が消える）。"""
    env = '(1-' + pbus.phase('rampbeat') + ')**2'
    assert _ev(env, {'beat1': _Chop(rampbeat=0.0)}) == 1                 # 拍頭 → 包絡最大
    assert _ev(env, {}) == 0                                             # 位相源なし → 包絡0
    assert _ev(env, {'beatsync': _Chop(rampbeat=0.5), 'beat1': _Chop(rampbeat=0.9)}) == 0.25  # beatsync 優先
    print('OK phase: zero is not missing / fallback')


def test_missing_op_does_not_kill_other_terms():
    """aud_lag 欠損でも同じ式の bpm/midi 項は生きている（2026-09-25 実機で全滅した症状の回帰）。"""
    p = _engine()
    pbus.add_term(p, 'warp_disp', 'displaceweightx', 'audio', pbus.ch('aud_lag', 'low') + '*0.35', base='0.09')
    pbus.add_term(p, 'warp_disp', 'displaceweightx', 'bpm', '(1-' + pbus.phase('rampbeat') + ')**2*0.18')
    pbus.add_term(p, 'warp_disp', 'displaceweightx', 'midi', pbus.ch('ctrl', 'k1') + '*0.4')
    e = p.op('warp_disp').par.displaceweightx.expr
    v = _ev(e, {'beat1': _Chop(rampbeat=0.0), 'ctrl': _Chop(k1=0.5)})   # aud_lag だけ欠損
    assert abs(v - (0.09 + 0.18 + 0.2)) < 1e-9, v
    print('OK missing aud_lag keeps bpm/midi terms alive')


def test_remove():
    p = _engine()
    pbus.add_term(p, 'hsv1', 'saturationmult', 'audio', "A", base='2.2')
    pbus.add_term(p, 'hsv1', 'saturationmult', 'accent', "B")
    pbus.remove_term(p, 'hsv1', 'saturationmult', 'accent')
    e = p.op('hsv1').par.saturationmult.expr
    assert 'B' not in e and 'A' in e, e
    print('OK remove')


def test_reset():
    p = _engine()
    pbus.add_term(p, 'hsv1', 'saturationmult', 'audio', "A", base='2.2')
    pbus.reset(p)
    assert pbus.dump(p) == {}
    print('OK reset')


if __name__ == '__main__':
    test_order_independence()
    test_idempotent()
    test_whole_replace_no_longer_wipes()
    test_hueoffset_multiowner()
    test_clamp()
    test_wrap()
    test_ch_null_safe()
    test_phase_zero_is_not_missing()
    test_missing_op_does_not_kill_other_terms()
    test_remove()
    test_reset()
    print('\nALL PASS')
