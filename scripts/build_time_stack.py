"""
build_time_stack.py
===================
表示の最終段（hsv1）の直近 N フレームを**奥行き方向に積み上げ**、時間を立体として
見せる拡張。油膜・大理石の模様が、時間の地層のように奥へ連なって見える。

  hsv1 ─ ts_res(640×360) ─ ts_cache(Texture 3D TOP / 2D配列・N枚)
                                   │ インスタンステクスチャ
  ts_table(i, tz, c) ─ ts_inst ─ ts_geo(板×N、i枚目を貼る) ─ ts_render ─ ts_out
                                   ts_cam(ゆっくり周回)

設計のポイント
--------------
- **out1 は変えない**。out1 は ai_bridge（StreamDiffusion への送信）の送信元なので、
  時間の積層は別出力 ts_out として足す。ベースのループにも触らない（表示側の hsv1 を読むだけ）。
- **GLSL を使わない**。Texture 3D TOP を 2D テクスチャ配列（texture2darray）にして、
  Geometry COMP のインスタンステクスチャ（instancetexs）に渡し、各板に貼る枚数を
  instancetexindex（= 表の列 i）で選ぶ。
- **板の位置は固定、間隔は COMP の Z スケールで伸縮**。表の tz は 0,1,2…の整数で、
  ts_geo.sz（Z スケール）が板の間隔になる。板は XY 平面にあるので Z に伸ばしても歪まない。
  音で動かすのは sz の1パラメータだけ（パラメータバス tag='timestack'、低域で伸びる）。
- **古い層ほど暗く**（表の c = 明るさ、インスタンスカラーで乗算）。加算合成なので
  奥行きの並べ替えが要らず、重なった所が明るくなる。ただし明るい模様を N 枚そのまま
  足すと全面が白く飽和する（実機で確認）。1枚あたり LAYER_GAIN に落とし、最新の1枚だけ
  NEWEST_GAIN で明るく残す。
- **解像度は落として積む**（640×360×N 枚）。N=48 で約 44MB。フル解像度にすると VRAM を食う。

使い方
------
1. build_organic_patterns.py（音で動かすなら build_audio_reactive.py も）を実行済みで
2. このスクリプトを実行し、/project1/ts_out を表示する
build_organic_patterns.py を再実行しても hsv1 の名前は変わらないので、再実行は不要。
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
N = 48                      # 積む枚数（= Texture 3D TOP の cachesize）
STACK_RES = (640, 360)      # 積む1枚の解像度
OUT_RES = (1280, 720)       # 書き出し解像度（hsv1 と同じ）
FADE_MIN = 0.12             # 一番古い層の相対的な明るさ（新しい層が 1.0）
LAYER_GAIN = 0.09           # 1枚あたりの明るさ（加算合成。重なった所ほど明るくなる。0.16 だと中央が白く飛んだ）
NEWEST_GAIN = 0.85          # 一番手前（最新フレーム）だけ明るく残し、今の模様を見分けやすくする
CAM_DIST = 3.3              # カメラから積層までの距離（板が画面の大半を占める程度）
NEWEST_LAST = True          # Texture 3D TOP の配列で最新フレームが末尾(N-1)に入るか

NODES = {
    # 表示の最終段を縮小して積む
    'ts_res': dict(type='resolutionTOP', x=1250, y=-150, res=STACK_RES, pars={}),
    'ts_cache': dict(type='texture3dTOP', x=1410, y=-150, res=STACK_RES, pars={
        'type': 'texture2darray', 'cachesize': N, 'step': 1,
    }),
    # インスタンス表: i=貼る配列の枚数, tz=奥行き(整数), c=明るさ
    'ts_table': dict(type='tableDAT', x=1250, y=-320, pars={}),
    'ts_inst': dict(type='dattoCHOP', x=1410, y=-320, pars={
        # 既定の chanperrow だと「1行=1チャンネル」になる。列 i/tz/c を各チャンネルにする
        'dat': 'ts_table', 'output': 'chanpercol', 'firstrow': 'names', 'firstcolumn': 'values',
    }),
    # 板を N 枚並べる Geometry COMP（中身の SOP は build 内で作る）
    'ts_geo': dict(type='geometryCOMP', x=1570, y=-230, pars={
        'instancing': True, 'instanceop': 'ts_inst',
        'instancetz': 'tz',
        'instancetexs': 'ts_cache', 'instancetexmode': 'replace',
        'instancetexindexop': 'ts_inst', 'instancetexindex': 'i',
        'instancecolorop': 'ts_inst', 'instancecolormode': 'multiply',
        'instancer': 'c', 'instanceg': 'c', 'instanceb': 'c',
        'material': 'ts_mat',
        'sz': 0.05,
    }),
    # 加算合成・深度を書かない（奥から手前へ光が重なる）
    'ts_mat': dict(type='constantMAT', x=1570, y=-380, pars={
        'colormap': 'ts_cache',
        'blending': True, 'srcblend': 'one', 'destblend': 'one',
        'depthtest': False, 'depthwriting': False,
    }),
    # 斜め上から見下ろし、左右にゆっくり周回する
    'ts_cam': dict(type='cameraCOMP', x=1730, y=-380, pars={
        'tx': ('expr', f"{CAM_DIST}*math.sin(math.radians(28*math.sin(absTime.seconds*0.12)))"),
        'ty': 0.9,
        'tz': ('expr', f"0.6 + {CAM_DIST}*math.cos(math.radians(28*math.sin(absTime.seconds*0.12)))"),
        'lookat': 'ts_geo',
        'fov': 45,
    }),
    # Render TOP に背景色のパラメータは無く、背景は透明（アルファ0）。そのまま出すと
    # 画面の大半が透明になり、PNG では白く見える（実機で確認）。黒の上に重ねて不透明にする。
    'ts_render': dict(type='renderTOP', x=1730, y=-230, res=OUT_RES, pars={
        'camera': 'ts_cam', 'geometry': 'ts_geo', 'lights': '',
    }),
    'ts_bg': dict(type='constantTOP', x=1730, y=-80, res=OUT_RES, pars={
        'colorr': 0, 'colorg': 0, 'colorb': 0, 'alpha': 1,
    }),
    'ts_comp': dict(type='compositeTOP', x=1890, y=-230, res=OUT_RES, pars={'operand': 'over'}),
    'ts_out': dict(type='nullTOP', x=2050, y=-230, res=OUT_RES, pars={}),
}

WIRES = {
    'ts_res':    [(0, 'hsv1')],
    'ts_cache':  [(0, 'ts_res')],
    'ts_comp':   [(0, 'ts_render'), (1, 'ts_bg')],
    'ts_out':    [(0, 'ts_comp')],
}

# --- Execute DAT ts_driver: 毎フレーム ts_cache を force cook ---
# TD は「参照されているノードしか計算しない」。ts_out を誰も表示していないと ts_cache も
# 止まり、フレームが積まれない（実機で確認: hsv1 は毎フレーム計算されるのに ts_cache は
# 保存・測定のたびに1回ずつしか計算されていなかった）。表示していない間も履歴を育てて
# おくため、キャッシュ（軽い）だけを毎フレーム回す。描画（ts_render）は表示時だけ計算される。
# パスは相対（Execute DAT の親基点で解決）。完全版 tox に /project1 の絶対参照を残さないため。
DRIVER_SRC = r'''
CACHE = 'ts_cache'


def onFrameStart(frame):
    c = op(CACHE)
    if c is not None:
        c.cook(force=True)
    return
'''

# 板の間隔 = 0.05 + 低域*0.35（0.03〜0.2 にクランプ）。低域（キック・ベース）で積層が伸びる。
# 低域は aud_out['low']。音が無ければ 0.05 のまま。
SPACING_TERM = f"{pbus.ch('aud_out', 'low')}*0.35"


def _table_rows():
    """インスタンス表: 行ごとに1枚の板。tz は手前(0)から奥へ。新しい層を手前に置く。"""
    rows = [['i', 'tz', 'c']]
    for k in range(N):
        # k=0 が手前（最新）、k=N-1 が奥（最古）
        idx = (N - 1 - k) if NEWEST_LAST else k
        fade = 1.0 - (1.0 - FADE_MIN) * (k / (N - 1))
        c = NEWEST_GAIN if k == 0 else LAYER_GAIN * fade
        rows.append([idx, -k, round(c, 4)])
    return rows


def _build_geo_contents(geo):
    """Geometry COMP の中身を 16:9 の板1枚にする（既定の torus 等は消す）。"""
    for c in list(geo.children):
        c.destroy()
    rect = geo.create(td.rectangleSOP, 'rect')
    for pn, pv in (('sizex', 1.6), ('sizey', 0.9)):
        if hasattr(rect.par, pn):
            getattr(rect.par, pn).val = pv
    rect.render = True
    rect.display = True
    return rect


def build_time_stack():
    p = tdb.get_parent(PARENT)
    tdb.require(p, 'hsv1', hint='build_organic_patterns.py')

    created = tdb.build_nodes(p, NODES, WIRES)

    t = created['ts_table']
    t.clear()
    for r in _table_rows():
        t.appendRow(r)

    _build_geo_contents(created['ts_geo'])

    # ts_driver（Execute DAT）: 本文を入れてから active/framestart を ON（ai_driver と同じ流儀）
    tdb.ensure(p, 'ts_driver', 'executeDAT', 1410, -40, text=DRIVER_SRC,
               pars={'active': True, 'framestart': True})

    # 板の間隔（Z スケール）を低域で伸ばす
    pbus.add_term(p, 'ts_geo', 'sz', 'timestack', SPACING_TERM, base='0.05', clamp=(0.03, 0.2))

    print(f'[time_stack] build complete. The last {N} frames of hsv1 are stacked in depth '
          f'and rendered to ts_out (out1 is unchanged). Layer spacing follows the low band.')
    return created


if __name__ == '__main__':
    build_time_stack()
