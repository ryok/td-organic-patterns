"""
build_rank_norm.py
==================
音の帯域（low/mid/high）の大きさを「直近30秒の中での順位」に直してから映像側に
渡す拡張。固定ゲインのままでも、音圧の小さい曲で絵が止まらず、大きい曲で張り付か
ない。正規化の中身は td_rank_norm.py（TD 非依存・test_td_rank_norm.py で検証）。

  （aud_out の手前にあったもの: aud_lag か liq_switch）
      ├────────────────────────────┐
      └─ aud_rank（Script CHOP）────┴─ rank_switch ─ aud_out → 映像側の項
                                       (0=そのまま / 1=順位で正規化)

何が変わるか
------------
- 曲ごとの音量差: 較正した曲（2026-09-27）より音圧が低い曲でも、同じ揺れ幅で動く
- 曲の中の幅: 静かなイントロの打音にも反応し、ドロップでは p90 で頭打ちになる
  （p90 以上は全部 ref。生の値のように何倍にも跳ねて白く飛ばない）
- 出力は 0〜1 ではなく 0〜ref（較正曲の p95）。映像側のゲイン（MAPPINGS、
  build_detail_layer の ×12、build_time_stack の ×0.35）を変えずに済むようにするため

rms（全体の音量）は正規化しない
-------------------------------
rms は level1.opacity（フィードバックの残り具合）を動かす。順位にすると静かな区間でも
大きな区間と同じだけ尾が伸び、曲の「絶対的な大きさ」が絵から消える。参考にした作品も
打音の大きさは順位にしつつ、静けさ（hush）は別の項で持っている。ここでも rms は生の
値のまま通し、絶対量のチャンネルとして残す（含めたいなら REFS に 'rms': 0.041 を足す）。

オンセット検出（build_onset_scenes.py）は aud_lag を直接読むので影響を受けない。
HI/LO のしきい値は生の値のまま（曲依存が残る。直すなら別の拡張で）。

使い方
------
1. build_organic_patterns → build_audio_reactive（→ 任意で build_liquid_audio）を実行済みで
2. このスクリプトを実行する
3. 比較: op('/project1/rank_switch').par.index = 0（生の値）/ 1（順位で正規化）

🚨 実行順: build_liquid_audio.py は aud_out の入力を liq_switch に繋ぎ直すので、
後から流すとこの拡張が外れる。liquid を再実行したら、このスクリプトも再実行する。
build_audio_reactive.py を再実行した場合も aud_out が作り直されるので同様。

再実行も安全: rank_switch が既に入っていれば、その手前を元の上流とみなして作り直す。
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

# 順位(p10→0, p90→1)に掛け戻す大きさ = 2026-09-27 の較正曲での各帯域の p95
# （build_audio_reactive.py の MAPPINGS のコメントと同じ値）。ここに無いチャンネルは素通し。
REFS = {'low': 0.268, 'mid': 0.069, 'high': 0.018}
RANK_ON = 1            # rank_switch の初期 index（1=順位で正規化）

X0, Y0 = 560, -540     # ノード配置の基準（aud_out の左下）

# Script CHOP の callbacks。td_rank_norm.py の本文の後ろに付ける。
# 状態（帯域ごとの履歴）は DAT モジュールのグローバルに置く。storage に入れると
# toe 保存時に pickle され、DAT 内で定義したクラスは復元できない。
CALLBACKS_TAIL = r'''

# --- Script CHOP の callbacks（build_rank_norm.py が生成） --------------------
import td

REFS = {REFS}
_STATE = {{}}


def onSetupParameters(scriptOp):
    return


def onPulse(par):
    return


def onCook(scriptOp):
    scriptOp.clear()
    if not scriptOp.inputs:
        return
    src = scriptOp.inputs[0]
    # 上流は time slice（フレームごとに可変長）だが、ここでは各フレームの現在値1つだけを
    # 出す。time slice のままだと numSamples を変えられない（TD が警告を出す）
    scriptOp.isTimeSlice = False
    scriptOp.numSamples = 1
    t = td.absTime.seconds
    for c in src.chans():
        v = c.eval()
        ref = REFS.get(c.name)
        if ref is not None:
            n = _STATE.get(c.name)
            if n is None or n.ref != ref:
                n = _STATE[c.name] = RankNorm(ref)
            v = n.update(v, t)
        scriptOp.appendChan(c.name)[0] = v
    return
'''


def _callbacks_src():
    with open(os.path.join(_SD, 'td_rank_norm.py'), encoding='utf-8') as f:
        core = f.read()
    return core + CALLBACKS_TAIL.format(REFS=repr(REFS))


def build_rank_norm():
    p = tdb.get_parent(PARENT)
    tdb.require(p, 'aud_out', hint='build_audio_reactive.py')

    # 元の上流を決める。再実行時は rank_switch の手前（入力0）が元の上流
    out = p.op('aud_out')
    up = out.inputs[0] if out.inputs else None
    if up is not None and up.name == 'rank_switch':
        up = up.inputs[0] if up.inputs else None
    if up is None:
        raise RuntimeError('aud_out に入力がありません。build_audio_reactive.py を再実行してください。')

    tdb.destroy(p, 'rank_switch', 'aud_rank', 'aud_rank_callbacks')
    tdb.ensure(p, 'aud_rank_callbacks', 'textDAT', X0, Y0 - 100, text=_callbacks_src())
    # callbacks は兄弟名で指定（tox を別の場所に置いても解決される。'./' 付きは None になる）
    rank = tdb.ensure(p, 'aud_rank', 'scriptCHOP', X0 + 160, Y0 - 100, inputs=[up],
                      pars={'callbacks': 'aud_rank_callbacks'})
    sw = tdb.ensure(p, 'rank_switch', 'switchCHOP', X0 + 320, Y0,
                    inputs=[up, rank], pars={'index': RANK_ON})

    out.inputConnectors[0].connect(sw)

    print(f'[rank_norm] build complete. aud_out now reads rank_switch (upstream={up.name}, '
          f'index={RANK_ON}: 1=rank-normalized {sorted(REFS)}, 0=raw). '
          "Compare with op('/project1/rank_switch').par.index = 0 / 1.")
    return sw


if __name__ == '__main__':
    build_rank_norm()
