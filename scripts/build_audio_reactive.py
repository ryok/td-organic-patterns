"""
build_audio_reactive.py
=======================
build_organic_patterns.py の油膜・大理石エンジンを「音楽反応（Audio Reactive）」
に拡張する差分ビルドスクリプト。

前提:
  先に build_organic_patterns.py を実行して /project1 直下にベースネットワーク
  （seed_noise, warp_noise, warp_disp, comp1, level1, edge1, hsv1, out1 など）
  が構築済みであること。本スクリプトは「オーディオ解析チェーン」を追加し、
  ベースエンジンの主要パラメータを解析値で駆動する式を焼き込む。

設計方針（base + gain パターン）:
  各パラメータは `base + op('aud_out')['band']*gain` の形で式化する（aud_out は
  aud_lag を通すだけの出口。慣性の拡張 build_liquid_audio.py がここに差し込む）。
  - 無音時: 解析値が 0 → base 値そのまま（= 元の静的パッチと同じ絵）
  - 音が鳴ると: band 値が加算され、うねり/彩度/エッジ/発散ゲインが増幅
  こうすると「マイクを繋がなくても壊れない」かつ「鳴らすと動く」を両立できる。

オーディオ解析チェーン:
  aud_in(Audio Device In)
    → aud_spec(Audio Spectrum: FFT, 1ch×22050 sample)
      → band_low/mid/high(Trim: サンプル範囲で低中高に3分割)
        → aud_analyze_*(Analyze: average でスカラー化) / band_rms(rmspower)
          → ren_*(Rename: low/mid/high/rms に改名)
            → aud_merge(4ch に統合)
              → aud_lag(Lag: attack/release で FFT のジッタを平滑化)

使い方:
  1. build_organic_patterns.py を実行済みの状態で
  2. Textport にこのファイルを貼り付けて Enter
  3. Audio Device In のデバイスをマイク/ライン入力に設定
  4. /project1/out1 を表示して音を鳴らす

再実行も安全: 追加ノードは同名を削除してから作り直す。
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
LR = (640, 360)

# --- オーディオ解析チェーンのノード定義 ------------------------------------
# Audio Spectrum は 22050 サンプルの片側スペクトル。frequencylog=0（線形）にすると
# サンプル番号 ≒ Hz になる（実測: 400Hz→393番、2kHz→1997番）。その番号の範囲で
# 低/中/高に割る（厳密な Hz 変換ではなく体感優先）。
#
# 🚨 既定の frequencylog=1（対数目盛り）だと 60Hz が 5260番に出て番号≠Hz になる。
#    Trim も既定の relative='rel'（相対）だと start/end が入力の先頭/末尾からのずれに
#    なり、各帯域がスペクトル末尾まで丸ごと含んでしまう。どちらも初回コミットから
#    効いておらず、low/mid/high がほぼ同じ値になっていた（2026-09-25 実機で確認）。
AUDIO_NODES = {
    'aud_in': dict(type='audiodeviceinCHOP', x=-600, y=-400, pars={}),
    'aud_spec': dict(type='audiospectrumCHOP', x=-420, y=-400, pars={'frequencylog': 0}),
    # Trim CHOP: 絶対位置(relative='abs')のサンプル範囲で帯域を切り出す
    # （単位は startunit/endunit の既定 'samples'）
    'band_low':  dict(type='trimCHOP', x=-260, y=-320, pars={
        'relative': 'abs', 'start': 2, 'end': 120,
    }),
    'band_mid':  dict(type='trimCHOP', x=-260, y=-400, pars={
        'relative': 'abs', 'start': 120, 'end': 900,
    }),
    'band_high': dict(type='trimCHOP', x=-260, y=-480, pars={
        'relative': 'abs', 'start': 900, 'end': 4000,
    }),
    # Analyze CHOP: 帯域内の平均でスカラー化（=その帯のエネルギー）
    'aud_analyze_low':  dict(type='analyzeCHOP', x=-100, y=-320, pars={'function': 'average'}),
    'aud_analyze_mid':  dict(type='analyzeCHOP', x=-100, y=-400, pars={'function': 'average'}),
    'aud_analyze_high': dict(type='analyzeCHOP', x=-100, y=-480, pars={'function': 'average'}),
    # band_rms: 全帯の RMS パワー（=全体の音量感、opacity 微調整に使う）
    'band_rms': dict(type='analyzeCHOP', x=-100, y=-240, pars={'function': 'rmspower'}),
    # Rename: 後段 Merge でチャンネル名が衝突しないよう固有名に
    'ren_low':  dict(type='renameCHOP', x=60, y=-320, pars={'renamefrom': '*', 'renameto': 'low'}),
    'ren_mid':  dict(type='renameCHOP', x=60, y=-400, pars={'renamefrom': '*', 'renameto': 'mid'}),
    'ren_high': dict(type='renameCHOP', x=60, y=-480, pars={'renamefrom': '*', 'renameto': 'high'}),
    'ren_rms':  dict(type='renameCHOP', x=60, y=-240, pars={'renamefrom': '*', 'renameto': 'rms'}),
    # Merge: low/mid/high/rms を 4ch にまとめる
    'aud_merge': dict(type='mergeCHOP', x=240, y=-380, pars={}),
    # Lag: FFT はフレーム毎に激しく揺れるので attack/release で平滑化。
    # lag1(attack)=0.02 は立ち上がりを速く、lag2(release)=0.15 は余韻を残す。
    'aud_lag': dict(type='lagCHOP', x=420, y=-380, pars={'lag1': 0.02, 'lag2': 0.15}),
    # aud_out: 映像側の項が読む単一の出口（beatsync / ctrl と同じ思想）。ここでは
    # aud_lag をそのまま通すだけ。build_liquid_audio.py が手前にばね（慣性）の経路を
    # 差し込むときの差し替え口になる。オンセット検出は速い aud_lag を直接読む。
    'aud_out': dict(type='nullCHOP', x=900, y=-380, pars={}),
}

AUDIO_WIRES = {
    'aud_spec':          [(0, 'aud_in')],
    'band_low':          [(0, 'aud_spec')],
    'band_mid':          [(0, 'aud_spec')],
    'band_high':         [(0, 'aud_spec')],
    'aud_analyze_low':   [(0, 'band_low')],
    'aud_analyze_mid':   [(0, 'band_mid')],
    'aud_analyze_high':  [(0, 'band_high')],
    'band_rms':          [(0, 'aud_spec')],
    'ren_low':           [(0, 'aud_analyze_low')],
    'ren_mid':           [(0, 'aud_analyze_mid')],
    'ren_high':          [(0, 'aud_analyze_high')],
    'ren_rms':           [(0, 'band_rms')],
    'aud_merge':         [(0, 'ren_low'), (1, 'ren_mid'), (2, 'ren_high'), (3, 'ren_rms')],
    'aud_lag':           [(0, 'aud_merge')],
    'aud_out':           [(0, 'aud_lag')],
}

# --- ベースエンジンへ焼き込む項（tag='audio' でパラメータバスに加算登録） ------
# (対象ノード, パラメータ, 加算項, base, clamp) の形。式は SRC（aud_out）を読む。
# base はそのパラメータの無音時の静止値。バスが base+term を合成するので、
# bpm/accent/midi の項と同じパラメータでも奪い合わずに共存する。
# 参照は pbus.ch() で包む（SRC が欠けても 0 に落ち、同じ式の他タグ項を巻き込んで
# 止めない）。
#
# ゲインの較正（2026-09-27、実曲 40 秒を Ableton → BlackHole で入力して計測）:
# 帯域分割の修正（frequencylog=0 / Trim relative=abs）で各帯域と rms の値の大きさが
# 変わったため、修正前の設定を再現した解析と同じ曲で並べて計り、「p95 での揺れ幅が
# 修正前と同じ」になるよう換算した: 新ゲイン = 旧ゲイン × (修正前 p95 / 修正後 p95)。
#   low  p95 0.268（修正前 0.101）→ ×0.375   mid  0.069（0.097）→ ×1.42
#   high p95 0.018（修正前 0.088）→ ×4.82    rms  0.041（0.245）→ ×6.0
SRC = 'aud_out'
MAPPINGS = [
    # 低域(キック/ベース) → ドメインワープの変位量。ビートで大理石が波打つ。
    ('warp_disp', 'displaceweightx', f"{pbus.ch(SRC, 'low')}*0.13", '0.09', None),
    ('warp_disp', 'displaceweighty', f"{pbus.ch(SRC, 'low')}*0.13", '0.09', None),
    # 中域(コード/ボーカル) → シードノイズ振幅。うねりの元エネルギーを注入。
    ('seed_noise', 'amp', f"{pbus.ch(SRC, 'mid')}*0.85", '0.16', None),
    # 高域(ハイハット/シンバル) → エッジ強度と彩度。金属リムがきらめく。
    ('edge1', 'strength', f"{pbus.ch(SRC, 'high')}*29", '3.0', None),
    ('hsv1', 'saturationmult', f"{pbus.ch(SRC, 'high')}*7.2", '2.2', None),
    # 全体音量 → フィードバックゲイン。大音量ほど構造が長く残る（発散寸前まで）。
    # base=0.985 は無音時の安定値。p95 で +0.0029、実測最大でも +0.0034（0.988）。
    # clamp で 0.999 上限=残留率が1を超えて発散するのを防ぐ（accent/midi の opacity 項が
    # 同時に乗っても安全）。
    ('level1', 'opacity', f"{pbus.ch(SRC, 'rms')}*0.072", '0.985', (0.0, 0.999)),
]


def build_audio():
    p = tdb.get_parent(PARENT)
    tdb.require(p, 'seed_noise', hint='build_organic_patterns.py')

    # オーディオ解析ノードの生成 + パラメータ + 配線（同名は消してから作る）
    created = tdb.build_nodes(p, AUDIO_NODES, AUDIO_WIRES)

    # ベースエンジンへ項を登録（パラメータバスが base+term を合成）
    for node_name, par_name, term, base, clamp in MAPPINGS:
        target = p.op(node_name)
        if target is None or not hasattr(target.par, par_name):
            print(f'[warn] {node_name}.{par_name} が見つからずスキップ')
            continue
        pbus.add_term(p, node_name, par_name, tag='audio',
                      term=term, base=base, clamp=clamp)

    print('[audio_reactive] build complete. '
          'Set aud_in device to your mic/line, view /project1/out1, and play sound.')
    return created


if __name__ == '__main__':
    build_audio()
