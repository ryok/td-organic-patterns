"""
build_midi_osc.py
=================
ベースの油膜・大理石エンジンに「MIDI/OSC 入力によるライブ演奏」を重ねる
差分ビルドスクリプト。フィジカルコントローラ(MIDIノブ)やスマホの TouchOSC で
パラメータを手で動かし、演者が介入できるようにする。

■ 位置づけ（4つの駆動源の中での役割）
  - build_audio_reactive.py = 鳴っている音のエネルギーへ自動追従
  - build_bpm_sync.py       = 拍グリッドへクオンタイズ（自動）
  - build_onset_scenes.py   = キックのオンセットでシーンジャンプ（自動）
  - build_midi_osc.py       = 人間が手で介入（半自動＝演奏）
  設計上これらは「加算合成」で共存する。オーディオで勝手に反応させつつ、
  盛り上がりでノブを回して displace を突き上げる、といった演奏ができる。

■ base + gain の「加算重畳」設計（既存式を壊さない）
  他スクリプトは各パラメータの式を丸ごと上書きするが、本スクリプトは
  「今ある式に MIDI/OSC 項を後置追記」する。こうすると audio/bpm の項が
  乗っていても消さずに済み、実行順に依存しない。
      新式 = (現在の式 or 現在値) + op('ctrl')['kN']*gain
  無入力時 ctrl の各 k は 0 なので、繋がなくても元の絵を壊さない（fail-safe）。

■ ctrl ノードの合流設計（ハードが無くても壊れない）
  expression が参照するのは常に単一の Null CHOP `op('ctrl')`。その手前で
  3ソースを Math CHOP(Combine=Add) で同名チャンネル加算する:
    - midi_map (MIDI In Map): ノブを k1..kN に手動割当。CC は既に 0..1 正規化
    - osc_in   (OSC In):      TouchOSC 等のフェーダ。アドレス /k1 → チャンネル k1
    - ctrl_manual (Constant):  k1..k6=0。★役割2つ★
        (1) k1..k6 を必ず存在させ「チャンネル無し」エラーを防ぐ(ハード未接続時)
        (2) ハード無しのテスト注入点（value0=k1 … を手で書けば演奏を模擬できる）

■ 要ライブ検証（TD 未接続でオフライン作成したため未確認の箇所）
  - MIDI In Map CHOP の出力チャンネル名: 実機でノブを回し Mapper で "k1".."k6"
    に割り当てる前提。名称が異なれば ctrl_manual の名前と合わせること。
  - Math CHOP の Combine パラメータ名（chopop/'add'）: バージョン差の可能性。
  - OSC In CHOP のポート/チャンネル命名: TouchOSC 側レイアウトに合わせる。
  これらは constant の k1..k6 が 0 で常在するため、未割当でも絵は壊れない。

使い方:
  1. build_organic_patterns.py（+ audio/bpm/onset は任意）を実行済みで
  2. Textport にこのファイルを貼り付けて Enter
  3. MIDI: midi_map をダブルクリック→ Device Mapper でノブを k1..k6 に割当
     OSC: TouchOSC を osc_in のポート(既定9000)に向け、フェーダ名を k1..k6 に
  4. ハード無しテスト: op('/project1/ctrl_manual').par.value0 = 0.5 等で k1 を動かす
     （value0=k1, value1=k2, … value5=k6）。0 に戻せば効果も消える

再実行も安全: 追加ノードは同名を削除してから作り直し、式の項は重複追記しない。
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
OSC_PORT = 9000        # TouchOSC 既定。ファイアウォール/同一LAN に注意
CTRL_CHANS = ['k1', 'k2', 'k3', 'k4', 'k5', 'k6']

# 手動ノブ → エンジンパラメータの割当（後置加算する項）。
# (対象ノード, パラメータ名, 'op(ctrl)参照式の右辺'）。
# gain は「ノブ全開(=1.0)で足し込む最大量」。単位は各パラメータに準拠。
# (対象ノード, パラメータ, 加算項, base, clamp)。tag='midi' でバスに登録する。
# base=None は「そのパラメータに既にベースがあれば継承、無ければライブ値を捕捉」。
# hueoffset だけは組み込みの時間スイープ base を明示して他タグと揃える。
MIDI_MAPPINGS = [
    # k1: 大理石の流れ(ドメインワープ変位)を手で突き上げる
    ('warp_disp', 'displaceweightx', "op('ctrl')['k1']*0.4", None, None),
    ('warp_disp', 'displaceweighty', "op('ctrl')['k1']*0.4", None, None),
    # k2: 彩度をライブで持ち上げる（虹色イリデッセンスの強調）
    ('hsv1', 'saturationmult', "op('ctrl')['k2']*3.0", None, None),
    # k3: 色相を手で回す（度）。自動の時間スイープに人手のオフセットを重ねる
    ('hsv1', 'hueoffset', "op('ctrl')['k3']*180", 'absTime.seconds*6', None),
    # k4: フィードバック残留(opacity)。clamp で 0.999 上限=発散防止（小gainでも保険）
    ('level1', 'opacity', "op('ctrl')['k4']*0.008", None, (0.0, 0.999)),
    # k5: シードノイズ振幅（うねりの元エネルギーを注入）
    ('seed_noise', 'amp', "op('ctrl')['k5']*0.5", None, None),
    # k6 はノート/ボタン用途（下の scene 前進に使う）。連続項には割り当てない
]

# MIDI ノート(ボタン=k6) でシーンを1つ進める状態機械（onset と同じヒステリシス）。
# scene_table / scene_state（build_onset_scenes.py 由来）がある時だけ有効化。
MIDI_SCENE_CODE = r'''# midi_scene_exec: k6(ノート/ボタン)の立ち上がりでシーンを1つ進める。
# ヒステリシス: k6>HI で発火し armed を落とす。k6<LO まで戻ると再武装。
# onset_exec と同じ scene_state/scene_table を共有するため、手動でも自動でも
# 同じシーンindexが進む（演者が任意のタイミングで質感を切り替えられる）。

HI = 0.5
LO = 0.2

def _btn():
    c = me.parent().op('ctrl')       # 絶対パスにせずDATが置かれたCOMPを基点にする
    if c is None:
        return 0.0
    try:
        return float(c['k6'])
    except Exception:
        return 0.0

def _apply_scene(idx):
    p = me.parent()                  # 相対参照: tox をどこに置いても壊れない
    st = p.op('scene_table')
    if st is None:
        return
    n = st.numRows - 1
    row = (idx % n) + 1
    p.op('disp_comp').par.operand = st[row, 'blend'].val   # 表示側ブレンドだけ切替
    # 色相はパラメータバスの 'scene_hue' 項(build_onset_scenes 由来)が scene_state
    # 経由で自動追従する。ここで hsv1.hueoffset を書き換えないので、bpm の小節スイープや
    # 手動色相(k3)を踏み潰さない。onset と midi の両状態機械が同じ index を進めるだけ。

def onFrameStart(frame):
    p = me.parent()                  # 相対参照: 入れ子/別配置でも scene_state を辿れる
    ss = p.op('scene_state')
    if ss is None:
        return
    lvl = _btn()
    armed = ss.fetch('midi_armed', 1)
    if armed and lvl > HI:
        idx = int(ss['scene']) + 1
        ss.par.value0 = idx
        _apply_scene(idx)
        ss.store('midi_armed', 0)
    elif (not armed) and lvl < LO:
        ss.store('midi_armed', 1)
    return
'''


def build_midi_osc():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。')
    if p.op('warp_disp') is None or p.op('hsv1') is None:
        raise RuntimeError(
            'ベースネットワークが未構築です。先に build_organic_patterns.py を実行してください。'
        )

    # --- ctrl_manual: k1..k6=0 の常在チャンネル（未接続時の保険＋テスト注入） ---
    ex = p.op('ctrl_manual')
    if ex:
        ex.destroy()
    cm = p.create(td.constantCHOP, 'ctrl_manual')
    cm.nodeX, cm.nodeY = -600, -840
    for i, ch in enumerate(CTRL_CHANS):
        getattr(cm.par, f'name{i}').val = ch
        getattr(cm.par, f'value{i}').val = 0.0
    for i in range(len(CTRL_CHANS), 8):     # 余分な既定 ch を消す
        nm = getattr(cm.par, f'name{i}', None)
        if nm is not None:
            nm.val = ''

    # --- midi_map: MIDI In Map CHOP。実機で Mapper に k1..k6 を割り当てる ---
    #   要ライブ検証: 出力ch名は Mapper 設定依存。Map CHOP の CC は既に 0..1。
    ex = p.op('midi_map')
    if ex:
        ex.destroy()
    mm = p.create(td.midiinmapCHOP, 'midi_map')
    mm.nodeX, mm.nodeY = -420, -840

    # --- osc_in: OSC In CHOP。TouchOSC 等のフェーダを受ける（ポート既定9000） ---
    #   要ライブ検証: ポート/チャンネル命名は送信側レイアウト依存。
    ex = p.op('osc_in')
    if ex:
        ex.destroy()
    oi = p.create(td.oscinCHOP, 'osc_in')
    oi.nodeX, oi.nodeY = -420, -760
    if hasattr(oi.par, 'port'):
        oi.par.port = OSC_PORT

    # --- ctrl_mix: 3ソースを同名チャンネルで加算（Math CHOP Combine=Add） ---
    #   要ライブ検証: Combine パラメータ名。TD では chopop(='add') が一般的。
    ex = p.op('ctrl_mix')
    if ex:
        ex.destroy()
    mix = p.create(td.mathCHOP, 'ctrl_mix')
    mix.nodeX, mix.nodeY = -240, -800
    for pn in ('chopop', 'chanop', 'combinechops'):   # バージョン差を吸収
        if hasattr(mix.par, pn):
            try:
                getattr(mix.par, pn).val = 'add'
            except Exception:
                pass
            break
    mix.inputConnectors[0].connect(mm)
    mix.inputConnectors[1].connect(oi)
    mix.inputConnectors[2].connect(cm)

    # --- ctrl: expression が参照する安定した単一 Null ---
    ex = p.op('ctrl')
    if ex:
        ex.destroy()
    ctrl = p.create(td.nullCHOP, 'ctrl')
    ctrl.nodeX, ctrl.nodeY = -80, -800
    ctrl.inputConnectors[0].connect(mix)

    # --- エンジン各パラメータに MIDI/OSC 項を登録（tag='midi'。audio/bpm 項と共存） ---
    for node_name, par_name, term, base, clamp in MIDI_MAPPINGS:
        target = p.op(node_name)
        if target is None or not hasattr(target.par, par_name):
            print(f'[warn] {node_name}.{par_name} が見つからずスキップ')
            continue
        # 色相は周期パラメータなので合成後に % 360（[-360,360] クランプ張り付き防止）
        wrap = 360 if (node_name, par_name) == ('hsv1', 'hueoffset') else None
        pbus.add_term(p, node_name, par_name, tag='midi',
                      term=term, base=base, clamp=clamp, wrap=wrap)

    # --- k6(ボタン) → シーン前進（onset のテーブルがある時だけ） ---
    ex = p.op('midi_scene_exec')
    if ex:
        ex.destroy()
    if p.op('scene_table') is not None and p.op('scene_state') is not None:
        ed = p.create(td.executeDAT, 'midi_scene_exec')
        ed.nodeX, ed.nodeY = -80, -680
        ed.par.active = True
        ed.par.framestart = True
        ed.text = MIDI_SCENE_CODE
        p.op('scene_state').store('midi_armed', 1)
        scene_note = ("k6(ボタン)でシーン前進も有効。")
    else:
        scene_note = ("scene_table 未検出のため k6→シーン前進はスキップ"
                      "（build_onset_scenes.py 実行後に再ビルドで有効化）。")

    print('[midi_osc] build complete. '
          f'Map knobs to k1..k6 (MIDI In Map) or send OSC /k1../k6 to port {OSC_PORT}. '
          + scene_note +
          " Test without hardware: op('/project1/ctrl_manual').par.value0 = 0.5")
    return ctrl


if __name__ == '__main__':
    build_midi_osc()
