"""
build_liquid_audio.py
=====================
音への反応に「慣性」をつける拡張。build_audio_reactive.py の平滑化（1段の Lag）の
あとに、帯域ごとに定数の違う**ばね（Spring CHOP）**を通してから映像側に渡す。

  aud_lag ─┬─ liq_sel_low  → liq_spring_low  ─┐
           ├─ liq_sel_mid  → liq_spring_mid  ─┤
           ├─ liq_sel_high → liq_spring_high ─┼─ liq_merge ─┐
           └─ liq_sel_rms（ばねに通さない）─────┘            ├─ liq_switch ─ aud_out → 映像側の項
           └──────────────────────────────────────────────┘ (0=そのまま / 1=慣性あり)

なぜばねか
----------
Lag は1次の遅れ（指数的に近づくだけ）なので、音が止まると絵もすっと止まる。ばねは
質量・ばね・減衰を持つ2次の連続時間系 m·x'' + c·x' + k·x = k·u で、入力を追いかけ
ながら少し行き過ぎて戻る。これで「重いものがゆっくり揺れ、余韻が残る」動きになる。
帯域ごとに固有振動数を変え、低域は重くゆっくり、高域は軽く速く動かす。

  固有振動数 ω = sqrt(k/m)、減衰比 ζ = c / (2·sqrt(k·m))
  ζ < 1 で行き過ぎ（オーバーシュート）あり。ζ≈0.55〜0.7 で1回だけ軽く揺れ戻る。

rms（全体の音量）はばねに通さない: rms は level1.opacity（フィードバックの残留率）を
動かしている。ばねの行き過ぎで残留率が跳ねるとループが暴走しかねないため、そのまま通す。

オンセット検出（build_onset_scenes.py）は速い aud_lag を直接読むので影響を受けない
（ばねで鈍らせるとキックの立ち上がりを取り逃す）。

使い方
------
1. build_organic_patterns.py → build_audio_reactive.py を実行済みで
2. このスクリプトを実行
3. 比較: op('/project1/liq_switch').par.index = 0（慣性なし）/ 1（慣性あり）

build_audio_reactive.py を再実行すると aud_out が作り直され、ばねの経路が外れる。
その場合はこのスクリプトも再実行する。
"""

import td

# --- 共有モジュール読込（td_param_bus=式の合成 / td_build=ノード構築） ---
import importlib, os, sys
try:
    _SD = os.path.dirname(os.path.abspath(__file__))
except NameError:                                   # Textport へのペースト時
    _SD = os.environ.get('TD_ORGANIC_SCRIPTS',
                         '/Users/ryookada/work/td-organic-patterns/scripts')
if _SD not in sys.path:
    sys.path.insert(0, _SD)
import td_param_bus as pbus, td_build as tdb
importlib.reload(pbus); importlib.reload(tdb)

PARENT = '/project1'

# 帯域ごとのばね定数（質量 m=1）: (k, c)
#   low : k=40  → ω≈6.3rad/s(約1.0Hz),  ζ≈0.55  重くゆっくり、軽く揺れ戻る
#   mid : k=150 → ω≈12.2rad/s(約1.9Hz), ζ≈0.60
#   high: k=900 → ω≈30rad/s(約4.8Hz),   ζ≈0.70  軽く速い、ほぼ揺れ戻らない
SPRINGS = {
    'low':  (40.0, 7.0),
    'mid':  (150.0, 14.7),
    'high': (900.0, 42.0),
}
MASS = 1.0
LIQUID_ON = 1          # liq_switch の初期 index（1=慣性あり）

X0, Y0 = 560, -700     # ノード配置の基準


def build_liquid():
    p = tdb.get_parent(PARENT)
    tdb.require(p, 'aud_lag', 'aud_out', hint='build_audio_reactive.py')

    names = ['liq_switch', 'liq_merge', 'liq_sel_rms']
    for b in SPRINGS:
        names += [f'liq_sel_{b}', f'liq_spring_{b}']
    tdb.destroy(p, *names)

    springs = []
    for i, (band, (k, c)) in enumerate(SPRINGS.items()):
        sel = tdb.ensure(p, f'liq_sel_{band}', 'selectCHOP', X0, Y0 - i * 80,
                         pars={'chop': 'aud_lag', 'channames': band})
        springs.append(tdb.ensure(p, f'liq_spring_{band}', 'springCHOP', X0 + 160, Y0 - i * 80,
                                  inputs=[sel],
                                  pars={'method': 'disp', 'springk': k, 'mass': MASS,
                                        'dampingk': c}))
    rms = tdb.ensure(p, 'liq_sel_rms', 'selectCHOP', X0 + 160, Y0 - len(SPRINGS) * 80,
                     pars={'chop': 'aud_lag', 'channames': 'rms'})
    merge = tdb.ensure(p, 'liq_merge', 'mergeCHOP', X0 + 320, Y0 - 120, inputs=springs + [rms])
    sw = tdb.ensure(p, 'liq_switch', 'switchCHOP', X0 + 480, Y0 - 60,
                    inputs=['aud_lag', merge], pars={'index': LIQUID_ON})

    # 映像側の出口 aud_out の入力を差し替える（aud_lag 直結 → liq_switch 経由）
    p.op('aud_out').inputConnectors[0].connect(sw)

    print('[liquid_audio] build complete. aud_out now reads liq_switch '
          f"(index={LIQUID_ON}: 1=spring inertia, 0=raw aud_lag). "
          "Compare with op('/project1/liq_switch').par.index = 0 / 1.")
    return sw


if __name__ == '__main__':
    build_liquid()
