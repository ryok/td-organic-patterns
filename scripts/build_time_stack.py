"""
build_time_stack.py
===================
表示の最終段（hsv1）の直近 N フレームを**奥行き方向に積み上げ**、時間を立体として
見せる拡張。油膜・大理石の模様が、時間の地層のように奥へ連なって見える。

  hsv1 ─ ts_res(640×360) ─ ts_cache(Cache TOP・N枚)
                               ├ ts_sel0 (index 0  = 最新)
                               ├ ts_sel1 (index -1 = 1フレーム前)
                               ├ …
                               └ ts_sel47(index -47)
                                   │ インスタンステクスチャ（TOP のリスト）
  ts_table(i, tz, c) ─ ts_inst ─ ts_geo(板×N、i 番目の TOP を貼る) ─ ts_render ─ ts_comp ─ ts_out
                                   ts_cam(ゆっくり周回)             ts_bg(黒) ┘

設計のポイント
--------------
- **out1 は変えない**。out1 は ai_bridge（StreamDiffusion への送信）の送信元なので、
  時間の積層は別出力 ts_out として足す。ベースのループにも触らない（表示側の hsv1 を読むだけ）。
- **GLSL を使わない**。Cache TOP に N 枚溜め、Cache Select TOP を N 個作って k フレーム前を
  それぞれ取り出す。その TOP のリストを Geometry COMP のインスタンステクスチャ（instancetexs）
  に番号順で渡し、各板に貼る TOP を instancetexindex（= 表の列 i）で選ぶ。
  ※ instancetexindex は「リストの何番目の TOP か」を選ぶもので、2D テクスチャ配列の何枚目かは
    選ばない（最初は Texture 3D TOP 1個を渡して全板が同じフレームになっていた。PR #7 の
    CodeRabbit レビューで指摘され、左右2枚を同じフレームで描画する実験で確認）。
- **板の位置は固定、間隔は COMP の Z スケールで伸縮**。表の tz は 0,-1,-2…の整数で、
  ts_geo.sz（Z スケール）が板の間隔になる。板は XY 平面にあるので Z に伸ばしても歪まない。
  音で動かすのは sz の1パラメータだけ（パラメータバス tag='timestack'、低域で伸びる）。
- **自動露出**: 音楽反応で hsv1 が明るくなると加算で白く飛ぶので、積む元の平均輝度を
  測って（ts_lum → ts_lum_c → ts_lum_f で0.4秒平滑化）全層の明るさを下げる。
- **古い層ほど暗く**（表の c = 明るさ、インスタンスカラーで乗算）。加算合成なので
  奥行きの並べ替えが要らず、重なった所が明るくなる。1枚あたり LAYER_GAIN に落とし、
  最新の1枚だけ NEWEST_GAIN で明るく残す。
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
N = 48                      # 積む枚数（= Cache TOP の cachesize = Cache Select TOP の数）
STACK_RES = (640, 360)      # 積む1枚の解像度
OUT_RES = (1280, 720)       # 書き出し解像度（hsv1 と同じ）
FADE_MIN = 0.12             # 一番古い層の相対的な明るさ（新しい層が 1.0）
LAYER_GAIN = 0.09           # 1枚あたりの明るさ（加算合成。重なった所ほど明るくなる）
NEWEST_GAIN = 0.85          # 一番手前（最新フレーム）だけ明るく残し、今の模様を見分けやすくする
CAM_DIST = 3.3              # カメラから積層までの距離（板が画面の大半を占める程度）
# 自動露出: 全層の明るさ = EXPO_TARGET / (積む元の平均輝度(0.4秒で平滑化) + 0.02)。
# 音楽反応で hsv1 が明るくなると、固定のゲインでは48枚の加算で白く飛ぶ（実曲で確認）。
# 0.3 は無音・実曲の両方で白飛びせず、層が見分けられた値（実機で目視確認）。
EXPO_TARGET = 0.3
EXPO_RANGE = (0.25, 1.6)


def _sel(k):
    return f'ts_sel{k}'


NODES = {
    # 表示の最終段を縮小して溜める
    'ts_res': dict(type='resolutionTOP', x=1250, y=-150, res=STACK_RES, pars={}),
    'ts_cache': dict(type='cacheTOP', x=1410, y=-150, pars={'cachesize': N, 'step': 1}),
    # インスタンス表: i=貼る TOP の番号(=何フレーム前か), tz=奥行き(整数), c=明るさ
    'ts_table': dict(type='tableDAT', x=1250, y=-320, pars={}),
    'ts_inst': dict(type='dattoCHOP', x=1410, y=-320, pars={
        # 既定の chanperrow だと「1行=1チャンネル」になる。列 i/tz/c を各チャンネルにする
        'dat': 'ts_table', 'output': 'chanpercol', 'firstrow': 'names', 'firstcolumn': 'values',
    }),
    # 板を N 枚並べる Geometry COMP（中身の SOP は build 内で作る）
    'ts_geo': dict(type='geometryCOMP', x=1730, y=-230, pars={
        'instancing': True, 'instanceop': 'ts_inst',
        'instancetz': 'tz',
        # 番号順の明示リスト（'ts_sel*' だと ts_sel10 が ts_sel2 より先に並ぶ文字列順になる）
        'instancetexs': ' '.join(_sel(k) for k in range(N)), 'instancetexmode': 'replace',
        'instancetexindexop': 'ts_inst', 'instancetexindex': 'i',
        'instancecolorop': 'ts_inst', 'instancecolormode': 'multiply',
        'instancer': 'c', 'instanceg': 'c', 'instanceb': 'c',
        'material': 'ts_mat',
        'sz': 0.05,
    }),
    # 自動露出用: 積む元の平均輝度（1画素に平均 → r0,g0,b0 の3チャンネル）
    'ts_lum': dict(type='analyzeTOP', x=1410, y=-470, pars={'op': 'average', 'scope': 'image'}),
    'ts_lum_c': dict(type='toptoCHOP', x=1570, y=-470, pars={'top': 'ts_lum', 'crop': 'full'}),
    # 音楽反応で明るさが1フレームごとに大きく跳ねる（0.9→0.08 を実測）。そのまま露出に使うと
    # 積層全体が明滅するので、0.4 秒で追従させて曲の大きな起伏だけに反応させる。
    'ts_lum_f': dict(type='lagCHOP', x=1730, y=-470, pars={'lag1': 0.4, 'lag2': 0.4}),
    # 加算合成・深度を書かない（奥から手前へ光が重なる）。色＝全層に掛かる明るさ（自動露出）
    'ts_mat': dict(type='constantMAT', x=1730, y=-380, pars={
        'colormap': _sel(0),
        'blending': True, 'srcblend': 'one', 'destblend': 'one',
        'depthtest': False, 'depthwriting': False,
    }),
    # 斜め上から見下ろし、左右に ±40° ゆっくり周回する（真正面だと手前の板しか見えない）
    'ts_cam': dict(type='cameraCOMP', x=1890, y=-380, pars={
        'tx': ('expr', f"{CAM_DIST}*math.sin(math.radians(40*math.sin(absTime.seconds*0.12)))"),
        'ty': 1.6,   # 上から見下ろして、層の上面が見えるようにする
        'tz': ('expr', f"0.6 + {CAM_DIST}*math.cos(math.radians(40*math.sin(absTime.seconds*0.12)))"),
        'lookat': 'ts_geo',
        'fov': 45,
    }),
    # Render TOP に背景色のパラメータは無く、背景は透明（アルファ0）。そのまま出すと
    # 画面の大半が透明になり、PNG では白く見える（実機で確認）。黒の上に重ねて不透明にする。
    'ts_render': dict(type='renderTOP', x=1890, y=-230, res=OUT_RES, pars={
        'camera': 'ts_cam', 'geometry': 'ts_geo', 'lights': '',
    }),
    'ts_bg': dict(type='constantTOP', x=1890, y=-80, res=OUT_RES, pars={
        'colorr': 0, 'colorg': 0, 'colorb': 0, 'alpha': 1,
    }),
    'ts_comp': dict(type='compositeTOP', x=2050, y=-230, res=OUT_RES, pars={'operand': 'over'}),
    'ts_out': dict(type='nullTOP', x=2210, y=-230, res=OUT_RES, pars={}),
}

# k フレーム前を取り出す Cache Select TOP（index 0=最新、-k=k フレーム前）
for _k in range(N):
    NODES[_sel(_k)] = dict(type='cacheselectTOP', x=1570, y=-150 - 40 * _k, pars={
        'cachetop': 'ts_cache', 'index': -_k,
    })

# 自動露出の式。ts_lum_f が無ければ平均輝度 0.16 とみなす。
# TOP to CHOP を crop='full' にするとチャンネル名は r0/g0/b0（画素番号付き）になる。'r' と書くと
# チャンネルが見つからず既定値 0.16 に落ち、倍率が常に 1.0 になる（実機で確認）。
_LUM = ("((" + pbus.ch('ts_lum_f', 'r0', 0.16) + ")+(" + pbus.ch('ts_lum_f', 'g0', 0.16) + ")+("
        + pbus.ch('ts_lum_f', 'b0', 0.16) + "))/3")
EXPO_EXPR = f"tdu.clamp({EXPO_TARGET}/({_LUM}+0.02), {EXPO_RANGE[0]}, {EXPO_RANGE[1]})"
for _pn in ('colorr', 'colorg', 'colorb'):
    NODES['ts_mat']['pars'][_pn] = ('expr', EXPO_EXPR)

WIRES = {
    'ts_res':    [(0, 'hsv1')],
    'ts_cache':  [(0, 'ts_res')],
    'ts_lum':    [(0, 'ts_res')],
    'ts_lum_f':  [(0, 'ts_lum_c')],
    'ts_comp':   [(0, 'ts_render'), (1, 'ts_bg')],
    'ts_out':    [(0, 'ts_comp')],
}

# --- Execute DAT ts_driver: 毎フレーム ts_cache を force cook ---
# TD は「参照されているノードしか計算しない」。ts_out を誰も表示していないと ts_cache も
# 止まり、フレームが溜まらない（実機で確認: hsv1 は毎フレーム計算されるのに、キャッシュは
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

# 以前の版（Texture 3D TOP 方式）の名残で、今の定義表に無いノード。再ビルド時に消す。
STALE = ()


def _table_rows():
    """インスタンス表: 行ごとに1枚の板。k=0 が手前（最新 = ts_sel0）、k=N-1 が奥（最古）。"""
    rows = [['i', 'tz', 'c']]
    for k in range(N):
        fade = 1.0 - (1.0 - FADE_MIN) * (k / (N - 1))
        c = NEWEST_GAIN if k == 0 else LAYER_GAIN * fade
        rows.append([k, -k, round(c, 4)])
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

    created = tdb.build_nodes(p, NODES, WIRES, extra_destroy=STALE)

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
