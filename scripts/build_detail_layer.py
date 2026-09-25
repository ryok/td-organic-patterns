"""
build_detail_layer.py
=====================
2層目のフィードバックで「細かい膜」を重ねる拡張。

ベースエンジンのループ（null1、640×360）は大理石の**大きな流れ**を作る。ここに
1280×720 のもう1本のループを足し、**細かい膜状のディテール**を作って表示側に
スクリーン合成する。

  null1 ─ det_up(1280×720へ拡大) ─────────────┐
                                                ├ det_comp(difference) ─ det_sharp ─ det_level ─ det_null ─┐
  det_fb(← det_null) ─ det_warp(細かいノイズでワープ)┘                                                  │
        ↑────────────────────────────────────────────────────────────────────────────────────────┘
  det_null ─ det_edge ─ det_view(濃さ=高域で揺れる)┐
  disp_comp ────────────────────────────────────── detail_mix(screen) ─ hsv1 ─ out1

設計のポイント
--------------
- **ベースのループには触らない**（README の規則）。1本目のループの出力 null1 を
  読むだけで、合成は表示側（disp_comp と hsv1 の間）で行う。
- 構成は1本目と同じ「差分合成 → ドメインワープ → シャープ → 減衰」。違いは
  ノイズの周期（2.4 → 0.45）と解像度（2倍）、減衰の速さ（残留 0.99 → 0.94）。
  細かい模様を短い尾で描き、大きな流れ（det_up）を差分の相手にすることで、
  細部が大きな流れの形に沿って出る。
- 細部の濃さ（det_view.opacity）は**高域の音**で揺れる（パラメータバス tag='detail'）。
  ハイハットやシンバルで細かい膜がきらめく。
- 詳細層を外したいときは build_organic_patterns.py から組み直す（hsv1 の入力が
  disp_comp に戻る）。

使い方
------
1. build_organic_patterns.py（音で揺らすなら build_audio_reactive.py も）を実行済みで
2. このスクリプトを実行
build_organic_patterns.py を再実行すると hsv1 の入力が元に戻るので、このスクリプトも再実行する。
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
HR = (1280, 720)

NODES = {
    # 大きな流れ（1本目のループの出力）を高解像度へ拡大して差分の相手にする
    'det_up': dict(type='resolutionTOP', x=0, y=600, res=HR, pars={}),
    # 細かい膜の元になるノイズ。周期を小さく、時間変化を速めに
    'det_noise': dict(type='noiseTOP', x=0, y=760, res=HR, pars={
        'type': 'simplex3d', 'period': 0.45, 'harmon': 3, 'amp': 0.5, 'mono': False,
        'tz': ('expr', 'absTime.seconds*0.11'),
    }),
    # 2本目のループ。fb1 と同じく入力にも det_null を繋ぐ（未接続だとエラー）
    'det_fb': dict(type='feedbackTOP', x=-200, y=680, pars={'top': 'det_null'}),
    'det_warp': dict(type='displaceTOP', x=160, y=760, res=HR, pars={
        'displaceweightx': 0.006, 'displaceweighty': 0.006,
        'uvweight': 0.5, 'extend': 'mirror',
    }),
    'det_comp': dict(type='compositeTOP', x=320, y=680, res=HR, pars={'operand': 'difference'}),
    'det_sharp': dict(type='convolveTOP', x=480, y=680, pars={
        'dat': 'sharpkernel', 'normalize': True,
    }),
    # 残留 0.94: 1本目(0.99)より速く消える＝尾が短く細かい
    'det_level': dict(type='levelTOP', x=640, y=680, res=HR, pars={
        'opacity': 0.94, 'blacklevel': 0.05, 'gamma1': 0.9,
    }),
    'det_null': dict(type='nullTOP', x=800, y=680, res=HR, pars={}),
    # 表示用: 細部の輪郭だけを取り出し、濃さを音で揺らす
    'det_edge': dict(type='edgeTOP', x=960, y=680, pars={'strength': 2.5}),
    'det_view': dict(type='levelTOP', x=1120, y=680, res=HR, pars={'opacity': 0.35}),
    'detail_mix': dict(type='compositeTOP', x=900, y=450, res=HR, pars={'operand': 'screen'}),
}

WIRES = {
    'det_up':     [(0, 'null1')],
    'det_fb':     [(0, 'det_null')],
    'det_warp':   [(0, 'det_fb'), (1, 'det_noise')],
    'det_comp':   [(0, 'det_warp'), (1, 'det_up')],
    'det_sharp':  [(0, 'det_comp')],
    'det_level':  [(0, 'det_sharp')],
    'det_null':   [(0, 'det_level')],
    'det_edge':   [(0, 'det_null')],
    'det_view':   [(0, 'det_edge')],
    'detail_mix': [(0, 'disp_comp'), (1, 'det_view')],
}

# 細部の濃さ = 0.35 + 高域*2.5（0〜1 にクランプ）。aud_out が無ければ高域項は 0。
DETAIL_TERM = f"{pbus.ch('aud_out', 'high')}*2.5"


def build_detail():
    p = tdb.get_parent(PARENT)
    tdb.require(p, 'null1', 'disp_comp', 'hsv1', 'sharpkernel', hint='build_organic_patterns.py')

    created = tdb.build_nodes(p, NODES, WIRES)

    # 表示チェーンに差し込む: disp_comp → detail_mix → hsv1
    p.op('hsv1').inputConnectors[0].connect(created['detail_mix'])

    pbus.add_term(p, 'det_view', 'opacity', 'detail', DETAIL_TERM, base='0.35', clamp=(0.0, 1.0))

    print('[detail_layer] build complete. A second 1280x720 feedback loop adds fine film '
          'detail, screen-composited between disp_comp and hsv1. Detail intensity follows '
          'the high band (aud_out).')
    return created


if __name__ == '__main__':
    build_detail()
