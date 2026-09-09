"""
build_onset_scenes.py
=====================
ベースの油膜・大理石エンジンに「オンセット検出によるシーン切替」を重ねる
差分ビルドスクリプト。

3つの時間軸の第3。
  - build_audio_reactive.py = 音量エネルギーへの連続追従（滑らかなうねり）
  - build_bpm_sync.py       = 拍グリッドへのクオンタイズ（リズミカルな脈動）
  - build_onset_scenes.py   = イベント駆動（キックのたびに質感がジャンプ）

前提:
  build_organic_patterns.py 実行済み（comp1, disp_comp, hsv1 が存在）。
  低域ソースとして build_audio_reactive.py の aud_lag['low'] を監視する。
  未適用でも動く（監視値 0 = シーンは進まない）。テスト時は __onsettest で注入可。

■ オンセット検出の状態機械（ヒステリシス / シュミットトリガ）
  連続値マッピングと違い「閾値を超えた"瞬間"だけ発火」する必要がある。単純な
  `level > threshold` だと1つのキックで閾値付近を何度も横切り多重発火する。
  そこで上下2閾値を使う:
    - armed 状態で level > HI → 発火（シーン+1）、armed=0 に落とす
    - armed=0 で level < LO   → 再武装（armed=1）
  これで「1キック=1回だけシーン前進」を保証する。状態は Execute DAT の
  onFrameStart で前フレームと比較し、armed フラグは DAT storage に持つ
  （CHOP に置くとクック順序で競合しうるため、Python 側の永続変数が確実）。

■ 重要: シーン切替は「表示側 disp_comp」を変える（ループ内 comp1 は触らない）
  当初 comp1（フィードバックループ内の合成）のブレンドを切り替えたが、
  vividlight 等の非線形ブレンドはループに置くと出力が 0/1 に張り付き
  フィードバックが崩壊する（Emboss TOP がループを凍らせるのと同じアトラクタ
  問題。README「実装上の要点」参照）。ループ内は difference 固定にし、質感の
  切替は out 手前の表示側合成 disp_comp で行う。ここは非線形ブレンドでも安全。

使い方:
  1. build_organic_patterns.py（+ build_audio_reactive.py 推奨）を実行済みで
  2. Textport にこのファイルを貼り付けて Enter
  3. /project1/out1 を表示。キック（低域）が入るたびシーンが進み質感が変わる
  4. テスト: op('/project1').create(constantCHOP,'__onsettest') に name0='low',
     value0=0.5 を入れると 1 フレームでシーンが 1 つ進む（撤去で live に戻る）

再実行も安全: 追加ノードは同名を削除してから作り直す。
"""

import td

PARENT = '/project1'
ONSET_HI = 0.18   # 発火閾値（上）
ONSET_LO = 0.08   # 再武装閾値（下）

# シーン定義: (表示側ブレンド, hue 基準オフセット[度])。
# すべて disp_comp（表示側）に適用されるブレンド=ループ非依存で安全なもの。
SCENES = [
    ('add',          0),    # scene 0: 元（金属リムを加算）
    ('screen',       90),   # scene 1: 発光的に持ち上げ
    ('overlay',      180),  # scene 2: コントラスト強調・色相反対
    ('lightercolor', 270),  # scene 3: 明色優先で硬質に
]

# Execute DAT に載せる状態機械コード
ONSET_CODE = r'''# onset_exec: 低域キックのオンセットでシーンを進める状態機械
# ヒステリシス(シュミットトリガ): HI を上抜けした瞬間だけ発火し、
# 一度 LO まで戻るまで再発火しない=1キック1回だけシーンが進む。
#
# 重要: シーン切替は「表示側 disp_comp」のブレンドを変える。ループ内 comp1 は
# difference 固定。vividlight 等の非線形ブレンドをループに置くとフィードバックが
# 0/1 に張り付き崩壊するため（Emboss がループを凍らせるのと同じアトラクタ問題）。

ONSET_SOURCE = "aud_lag"
HI = {HI}
LO = {LO}

def _kick_level():
    p = op('/project1')
    t = p.op('__onsettest')          # テスト用オーバーライドがあれば優先
    if t is not None:
        return float(t['low'])
    a = p.op(ONSET_SOURCE)
    if a is None:
        return 0.0
    return float(a['low'])

def _apply_scene(idx):
    p = op('/project1')
    st = p.op('scene_table')
    n = st.numRows - 1               # ヘッダ除く
    row = (idx % n) + 1
    blend = st[row, 'blend'].val
    hue_base = float(st[row, 'hue_base'].val)
    p.op('disp_comp').par.operand = blend    # 表示側を切替（ループは触らない）
    hsv = p.op('hsv1')
    base_expr = f"{hue_base} + absTime.seconds*6"
    if p.op('beat1') is not None:            # BPM同期があれば小節スイープを維持
        base_expr += " + op('beat1')['rampbar']*40"
    if p.op('ctrl') is not None:             # MIDI/OSC の手動色相(k3)も維持
        base_expr += " + op('ctrl')['k3']*180"
    hsv.par.hueoffset.expr = base_expr

def onFrameStart(frame):
    p = op('/project1')
    ss = p.op('scene_state')
    lvl = _kick_level()
    armed = ss.fetch('armed', 1)
    if armed and lvl > HI:
        idx = int(ss['scene']) + 1
        ss.par.value0 = idx
        _apply_scene(idx)
        ss.store('armed', 0)
    elif (not armed) and lvl < LO:
        ss.store('armed', 1)         # LO まで戻ったら再武装
    return
'''


def build_onset():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。')
    if p.op('disp_comp') is None or p.op('hsv1') is None:
        raise RuntimeError(
            'ベースネットワークが未構築です。先に build_organic_patterns.py を実行してください。'
        )

    # --- scene_state: シーンindexを保持する Constant CHOP（1ch） ---
    ex = p.op('scene_state')
    if ex:
        ex.destroy()
    ss = p.create(td.constantCHOP, 'scene_state')
    ss.nodeX, ss.nodeY = -600, -680
    ss.par.name0 = 'scene'
    ss.par.value0 = 0
    for i in range(1, 8):            # 既定の余分な ch を消して 1ch に
        nm = getattr(ss.par, f'name{i}', None)
        if nm is not None:
            nm.val = ''
    ss.store('armed', 1)

    # --- scene_table: シーン定義（表示側ブレンド + hue 基準） ---
    ex = p.op('scene_table')
    if ex:
        ex.destroy()
    st = p.create(td.tableDAT, 'scene_table')
    st.nodeX, st.nodeY = -430, -680
    st.clear()
    st.appendRow(['blend', 'hue_base'])
    for blend, hue in SCENES:
        st.appendRow([blend, str(hue)])

    # --- onset_exec: オンセット検出の状態機械（Execute DAT） ---
    ex = p.op('onset_exec')
    if ex:
        ex.destroy()
    ed = p.create(td.executeDAT, 'onset_exec')
    ed.nodeX, ed.nodeY = -260, -680
    ed.par.active = True
    ed.par.framestart = True         # onFrameStart を毎フレーム呼ぶ
    ed.text = ONSET_CODE.replace('{HI}', repr(ONSET_HI)).replace('{LO}', repr(ONSET_LO))

    # 初期状態: scene 0（add / hue 0）
    p.op('disp_comp').par.operand = SCENES[0][0]
    he = f"{SCENES[0][1]} + absTime.seconds*6"
    if p.op('beat1') is not None:
        he += " + op('beat1')['rampbar']*40"
    p.op('hsv1').par.hueoffset.expr = he

    print('[onset_scenes] build complete. Kicks in the low band advance the scene '
          '(display-side disp_comp blend + hue). Inject __onsettest low=0.5 to test.')
    return ed


if __name__ == '__main__':
    build_onset()
