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
  各パラメータは `base + op('aud_lag')['band']*gain` の形で式化する。
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

# --- パラメータバス読込（詳細は td_param_bus.py） ---
import importlib, os, sys
try:
    _SD = os.path.dirname(os.path.abspath(__file__))
except NameError:                                   # Textport へのペースト時
    _SD = os.environ.get('TD_ORGANIC_SCRIPTS',
                         '/Users/ryookada/work/td-organic-patterns/scripts')
if _SD not in sys.path:
    sys.path.insert(0, _SD)
import td_param_bus as pbus
importlib.reload(pbus)

PARENT = '/project1'
LR = (640, 360)

# --- オーディオ解析チェーンのノード定義 ------------------------------------
# Audio Spectrum は 22050 サンプルの片側スペクトル。人間の可聴域の主要帯を
# サンプルインデックス範囲で低/中/高に割る（厳密な Hz 変換ではなく体感優先）。
AUDIO_NODES = {
    'aud_in': dict(type='audiodeviceinCHOP', x=-600, y=-400, pars={}),
    'aud_spec': dict(type='audiospectrumCHOP', x=-420, y=-400, pars={}),
    # Trim CHOP: サンプル範囲で帯域を切り出す（start/end はサンプル番号）
    'band_low':  dict(type='trimCHOP', x=-260, y=-320, pars={
        'units': 'samples', 'start': 2, 'end': 120,
    }),
    'band_mid':  dict(type='trimCHOP', x=-260, y=-400, pars={
        'units': 'samples', 'start': 120, 'end': 900,
    }),
    'band_high': dict(type='trimCHOP', x=-260, y=-480, pars={
        'units': 'samples', 'start': 900, 'end': 4000,
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
}

# --- ベースエンジンへ焼き込む項（tag='audio' でパラメータバスに加算登録） ------
# (対象ノード, パラメータ, 加算項, base, clamp) の形。式は絶対 op() 参照で
# aud_lag を読む。base はそのパラメータの無音時の静止値。バスが base+term を
# 合成するので、bpm/accent/midi の項と同じパラメータでも奪い合わずに共存する。
# aud_lag 参照は pbus.ch() で包む（aud_lag が欠けても 0 に落ち、同じ式の他タグ項を
# 巻き込んで止めない）。
MAPPINGS = [
    # 低域(キック/ベース) → ドメインワープの変位量。ビートで大理石が波打つ。
    ('warp_disp', 'displaceweightx', f"{pbus.ch('aud_lag', 'low')}*0.35", '0.09', None),
    ('warp_disp', 'displaceweighty', f"{pbus.ch('aud_lag', 'low')}*0.35", '0.09', None),
    # 中域(コード/ボーカル) → シードノイズ振幅。うねりの元エネルギーを注入。
    ('seed_noise', 'amp', f"{pbus.ch('aud_lag', 'mid')}*0.6", '0.16', None),
    # 高域(ハイハット/シンバル) → エッジ強度と彩度。金属リムがきらめく。
    ('edge1', 'strength', f"{pbus.ch('aud_lag', 'high')}*6.0", '3.0', None),
    ('hsv1', 'saturationmult', f"{pbus.ch('aud_lag', 'high')}*1.5", '2.2', None),
    # 全体音量 → フィードバックゲイン。大音量ほど構造が長く残る（発散寸前まで）。
    # base=0.985 は無音時の安定値。clamp で 0.999 上限=残留率が1を超えて発散するのを
    # 防ぐ（accent/midi の opacity 項が同時に乗っても安全）。
    ('level1', 'opacity', f"{pbus.ch('aud_lag', 'rms')}*0.012", '0.985', (0.0, 0.999)),
]


def build_audio():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。')
    if p.op('seed_noise') is None:
        raise RuntimeError(
            'ベースネットワークが未構築です。先に build_organic_patterns.py を実行してください。'
        )

    # 既存のオーディオノードを掃除（再ビルド対応）
    for name in AUDIO_NODES:
        ex = p.op(name)
        if ex:
            ex.destroy()

    # ノード生成 + パラメータ
    created = {}
    for name, spec in AUDIO_NODES.items():
        n = p.create(getattr(td, spec['type']), name)
        n.nodeX, n.nodeY = spec['x'], spec['y']
        for pn, pv in spec['pars'].items():
            if not hasattr(n.par, pn):
                continue
            getattr(n.par, pn).val = pv
        created[name] = n

    # 配線
    for name, links in AUDIO_WIRES.items():
        n = created[name]
        for idx, up in links:
            n.inputConnectors[idx].connect(created[up])

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
