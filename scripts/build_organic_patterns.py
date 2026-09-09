"""
build_organic_patterns.py
==========================
TouchDesigner の Textport（Python コンソール）にペーストして実行すると、
Reddit r/TouchDesigner の "organic patterns" 投稿
(https://www.reddit.com/r/TouchDesigner/comments/1w3danp/organic_patterns/)
の質感を再現する生成ネットワークを /project1 直下に構築する。

作者 photoevaporation 本人のコメントによる技法:
  "feedback loops and blend mode operations ... Emboss, Edge, Sharpen
   effects inside a loop, while I shaped the aesthetic through lots of
   blend mode operations."

このスクリプトは上記を TouchDesigner 標準ノードで再構築したもの。
TD 標準 Emboss TOP はフィードバック段に置くと出力の +0.5 DC オフセットで
系が灰色に固まるため、ループ内のエッジ強調は Convolve(シャープ化カーネル)、
Emboss/Edge は表示側に配置している。大理石状の「流れ」は Transform の回転では
同心リングになるため、Displace TOP によるドメインワープで生成する。

使い方:
  1. TouchDesigner を起動（空プロジェクトでよい）
  2. Textport を開く（Alt+T / メニュー Dialogs > Textport and DATs）
  3. このファイルの中身を貼り付けて Enter
  4. /project1/out1 をビューアで表示。数十フレーム回すとパターンが育つ

再ビルド（作り直し）も安全: 既存の同名ノードは削除してから作る。
"""

import td

PARENT = '/project1'
LR = (640, 360)      # フィードバックループ解像度（低め=構造が大きく大理石化しやすい）
HR = (1280, 720)     # 表示解像度

# --- 構築するノード定義（吸い出した実パラメータ） --------------------------
# expr は式（時間駆動アニメーション）、val は静的値
NODES = {
    # mono=False が必須: Noise は既定でモノクロ(RGB同値)出力になり、
    # Difference 合成しても3チャンネルが同一のまま=グレースケールになる。
    # False にして RGB を分離することで油膜の虹色イリデッセンスが生まれる。
    'seed_noise': dict(type='noiseTOP', x=-600, y=200, res=LR, pars={
        'type': 'simplex3d', 'period': 2.4, 'harmon': 2, 'amp': 0.16,
        'mono': False,
        'tz': ('expr', 'absTime.seconds*0.05'),
    }),
    'warp_noise': dict(type='noiseTOP', x=-260, y=-150, res=LR, pars={
        'type': 'simplex3d', 'period': 3.5, 'harmon': 2, 'amp': 0.5,
        'mono': False,
        'tz': ('expr', 'absTime.seconds*0.03'),
    }),
    'warp_disp': dict(type='displaceTOP', x=-120, y=0, res=LR, pars={
        'displaceweightx': 0.09, 'displaceweighty': 0.09,
        'uvweight': 0.5, 'extend': 'mirror',
    }),
    'comp1': dict(type='compositeTOP', x=-400, y=100, res=LR, pars={
        'operand': 'difference',
    }),
    'convo_sharp1': dict(type='convolveTOP', x=200, y=100, pars={
        'dat': '/project1/sharpkernel', 'normalize': True,
    }),
    'level1': dict(type='levelTOP', x=600, y=100, res=LR, pars={
        'opacity': 0.99, 'blacklevel': 0.09, 'gamma1': 0.75,
    }),
    'null1': dict(type='nullTOP', x=800, y=100, res=LR, pars={}),
    'fb1': dict(type='feedbackTOP', x=-600, y=0, pars={'top': '/project1/null1'}),
    # --- 表示ブランチ ---
    'disp_level': dict(type='levelTOP', x=600, y=350, res=HR, pars={
        'brightness1': 1.15, 'blacklevel': 0.28, 'gamma1': 1.9,
        'inputfiltertype': 'nearest',
    }),
    'edge1': dict(type='edgeTOP', x=0, y=100, pars={'strength': 3.0}),
    'disp_comp': dict(type='compositeTOP', x=800, y=300, res=HR, pars={
        'operand': 'add',
    }),
    'hsv1': dict(type='hsvadjustTOP', x=1000, y=100, pars={
        'saturationmult': 2.2, 'valuemult': 1.25,
        'hueoffset': ('expr', 'absTime.seconds*6'),
    }),
    'out1': dict(type='outTOP', x=1200, y=100, res=HR, pars={}),
}

# 配線: node -> [(入力インデックス, 上流ノード名), ...]
# fb1 は par.top でループを閉じるが、Feedback TOP は入力コネクタが未接続だと
# "Not enough sources specified" エラーになるため null1 を入力にも配線する。
WIRES = {
    'fb1':          [(0, 'null1')],
    'comp1':        [(0, 'fb1'), (1, 'seed_noise')],
    'warp_disp':    [(0, 'comp1'), (1, 'warp_noise')],
    'convo_sharp1': [(0, 'warp_disp')],
    'level1':       [(0, 'convo_sharp1')],
    'null1':        [(0, 'level1')],
    'disp_level':   [(0, 'null1')],
    'edge1':        [(0, 'null1')],
    'disp_comp':    [(0, 'disp_level'), (1, 'edge1')],
    'hsv1':         [(0, 'disp_comp')],
    'out1':         [(0, 'hsv1')],
}

# シャープ化カーネル（中心を強め周囲を引く=高周波強調）
SHARP_KERNEL = [
    ['0',    '-0.4', '0'],
    ['-0.4', '2.6',  '-0.4'],
    ['0',    '-0.4', '0'],
]


def build():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。TDプロジェクトを確認してください。')

    # 既存の同名ノードを掃除（再ビルド対応）
    for name in list(NODES.keys()) + ['sharpkernel']:
        ex = p.op(name)
        if ex:
            ex.destroy()

    # カーネル用 Table DAT
    kd = p.create(td.tableDAT, 'sharpkernel')
    kd.nodeX, kd.nodeY = 200, 250
    kd.clear()
    for row in SHARP_KERNEL:
        kd.appendRow(row)

    # ノード生成 + パラメータ
    created = {}
    for name, spec in NODES.items():
        n = p.create(getattr(td, spec['type']), name)
        n.nodeX, n.nodeY = spec['x'], spec['y']
        res = spec.get('res')
        if res and hasattr(n.par, 'outputresolution'):
            n.par.outputresolution = 'custom'
            n.par.resolutionw = res[0]
            n.par.resolutionh = res[1]
        for pn, pv in spec['pars'].items():
            if not hasattr(n.par, pn):
                continue
            par = getattr(n.par, pn)
            if isinstance(pv, tuple) and pv[0] == 'expr':
                par.expr = pv[1]
            else:
                par.val = pv
        created[name] = n

    # 配線
    for name, links in WIRES.items():
        n = created[name]
        for idx, up in links:
            n.inputConnectors[idx].connect(created[up])

    # フィードバックのターゲット（ループを閉じる）
    created['fb1'].par.top = created['null1'].name

    print('[organic_patterns] build complete. View /project1/out1 and let it run.')
    return created


if __name__ == '__main__':
    build()
