"""
build_ableton_link.py
=====================
ベースの油膜・大理石エンジン（の BPM 同期スタック）を「Ableton Link で実 DAW の
テンポに同期」させる差分ビルドスクリプト。Ableton Live などと同一 LAN 上で Link を
有効にすると、TD 全体のテンポがセッションの共有テンポに追従する。

■ 位置づけ（テンポの所在を DAW に移す）
  build_bpm_sync.py は Beat CHOP(beat1) を /local/time の tempo で駆動していた
  （ライブでは Tap Tempo 等で手打ち）。本スクリプトはその tempo の供給源を
  Ableton Link CHOP の出力に差し替える。つまり:
      Ableton Link CHOP(ablink) の出力 tempo → /local/time.tempo → beat1 → 全下流
  こうすると audio/bpm/onset/MIDI の既存式を一切書き換えずに、エンジン全体が
  DAW のテンポへ追従する（beat1 を読む式はそのままで良い）。

■ なぜ「/local/time を1点駆動」なのか（ゼロ書き換え設計）
  beat1 の rampbeat/rampbar はグローバル時間(/local/time)から確定的に決まる。
  その tempo だけを Link 由来にすれば、beat1・BPM 脈動・オンセット・MIDI の
  すべてが自動追従する。個々の式に op('ablink') を撒かないことで、多重所有
  （同一パラメータに複数系統が寄与する）による衝突を避ける。

■ fail-safe（DAW が居なくても壊れない）
  Ableton Link CHOP はピア 0 でも自前クロックで tempo=120 を出力する（実測）。
  よって /local/time.tempo をそのまま引いても 0 に落ちて時計が止まる事故はない。
  それでも保険として「tempo>1 のときだけ追従、さもなくば 120」の三項式にする。

■ tempo パラメータは「出力トグル」（Beat CHOP と同じ罠）
  ablink の tempo/rampbeat/rampbar/beat/bar パラメータは出力チャンネルの ON/OFF
  トグルであってテンポ設定ではない。実テンポは出力チャンネル 'tempo' に出る。
  本スクリプトはこれらのトグルを ON にして必要な出力チャンネルを生やす。

■ 位相ロック（拍頭まで DAW に合わせる／本スクリプトで実装）
  テンポ同期は「速さ」を合わせるが、DAW のダウンビートとの「位相」までは
  合わない（beat1 は TD のタイムライン 0 起点で走るため）。厳密に拍頭を DAW に
  合わせるには、beat1 の代わりに ablink の位相ロック済みランプ
  op('ablink')['rampbeat'] / ['rampbar'] を読む必要がある。

  ■ 多重所有を避ける設計＝単一 Null `beatsync` に集約（ctrl と同じ思想）
    各式に「ablink があれば ablink、無ければ beat1」の三項を撒くと、hueoffset の
    ように複数系統(base/bpm/onset/midi)が寄与するパラメータで衝突を再燃させる
    （_apply_scene が式を丸ごと再構築して他系統の項を踏み潰す多重所有バグ）。
    そこで位相ソースの選択は CHOP 網に一元化する:
        beatsync_free (Select from beat1  : rampbeat/rampbar)
        beatsync_link (Select from ablink : rampbeat/rampbar 位相ロック済み)
        beatsync_sw   (Switch: ablink があれば link、無ければ free)
        beatsync      (Null : 式が参照する安定した単一点)
    式側の張り替えは不要: bpm_sync / accent の拍項はパラメータバスの
    pbus.phase()（"(op('beatsync') or op('beat1'))" を null 安全に包んだもの）で
    位相を読むので、この beatsync Null ができた瞬間に自動で切替わる。
    フォールバック（DAW/ablink 不在 → beat1）は Switch の index 式に集約。

  ■ fail-safe: ablink 不在なら Switch が beat1 側を選ぶので、位相ロック層を載せて
    も DAW が居なければ従来通り beat1 のタイムライン位相で回る（絵は壊れない）。
    ablink はピア0でも自前クロックで位相を出すため、DAW 未接続でも beatsync は
    有効なランプを供給する（DAW が来た瞬間にその位相へロックする）。

  ■ onset/midi の _apply_scene との整合（要同時改修）
    hueoffset の小節スイープは build_onset_scenes.py / build_midi_osc.py の
    _apply_scene でも再構築される。そちらも beat1→beatsync 優先に更新済み。
    beatsync があれば beatsync、無ければ beat1、という優先順位で全書き手が揃う。

使い方:
  1. build_organic_patterns.py + build_bpm_sync.py を実行済みで
  2. Textport にこのファイルを貼り付けて Enter
  3. DAW(Ableton Live 等)で Link を ON にし、TD と同一 LAN に置く
  4. ablink['numpeers'] が 1 以上・['linked']=1 になれば接続成功。DAW の
     テンポを変えると /local/time.tempo が追従し、拍頭も DAW のダウンビートに
     位相ロックする（大理石の脈動ピークがキックに揃う）
  5. DAW が無くてもエンジンは 120BPM・beat1 位相で動く（fail-safe）

再実行も安全: ablink / beatsync* は同名を削除してから作り直し、式の張り替えは
op('beat1')→op('beatsync') の置換なので二重適用しても冪等。
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

# Link 由来テンポで /local/time を駆動する fail-safe 式。
# ピア不在/異常(=tempo<=1)のときは 120 に落として時計停止を防ぐ。
#
# ★フルパス必須★: この式が走るのは /local/time であって /project1 ではない。
# パラメータ式内の op('name') は「そのパラメータを持つ op の親」を基点に相対解決
# されるため、/local/time から相対名 'ablink' を引くと /local 配下を探して None に
# なる（→常に else の 120 に落ちる）。ablink は /project1 配下なので、供給源と
# 消費点がネットワークをまたぐこの1点だけはフルパスで参照する。
#   罠の顕在化: 両者 120 のときは「ablink=None→else=120」と「実 tempo=120」が
#   偶然一致して正常に見える。DAW テンポを 120 以外にした瞬間に追従しないと露見。
TEMPO_EXPR = ("op('/project1/ablink')['tempo'] if "
              "(op('/project1/ablink') is not None and op('/project1/ablink')['tempo'] > 1) "
              "else 120.0")

# 生やす出力チャンネル（これらは ON/OFF トグル。テンポ設定ではない）。
# tempo=共有テンポ, rampbeat/rampbar=位相ロック済みランプ(位相ロックで使用),
# beat/bar=拍/小節カウンタ。
LINK_OUTPUT_TOGGLES = ('tempo', 'rampbeat', 'rampbar', 'beat', 'bar')

# 位相ロックで使う位相ランプのチャンネル（beat1 / ablink 双方に同名で存在）。
PHASE_CHANS = 'rampbeat rampbar'

# ablink があれば link(1)、無ければ free(0=beat1) を選ぶ Switch の index 式。
# フォールバックはここ1点に集約する（各パラメータ式には撒かない）。
BEATSYNC_INDEX_EXPR = "1 if op('ablink') is not None else 0"

# 注: 以前はここで各パラメータ式の op('beat1') を op('beatsync') へ文字列置換して
# いたが、パラメータバス導入後は bpm_sync / accent の拍項が PHASE_SRC
# ("(op('beatsync') or op('beat1'))") を使うため、beatsync ができた瞬間に自動で
# そちらへ切替わる。バスを経由しないライブ式の直接書き換えはバスの再合成と競合する
# ため撤去した（位相ロックは beatsync Null を作るだけでよい）。


def build_ableton_link():
    p = tdb.get_parent(PARENT)
    tdb.require(p, 'beat1', hint='build_bpm_sync.py')

    # --- Ableton Link CHOP ---
    # active=ノード稼働 / enable=Link 参加、続けて必要な出力チャンネルのトグルを ON
    al = tdb.ensure(p, 'ablink', 'abletonlinkCHOP', -600, -960,
                    pars=dict.fromkeys(('active', 'enable', *LINK_OUTPUT_TOGGLES), True),
                    cook=True)

    # --- テンポの供給源を Link に差し替え（/local/time を1点駆動） ---
    tc = op('/local/time')
    if tc is None or not hasattr(tc.par, 'tempo'):
        raise RuntimeError('/local/time の tempo が見つかりません。')
    tc.par.tempo.expr = TEMPO_EXPR

    # --- 位相ロック: 位相ソースを単一 Null `beatsync` に集約 ---
    #   beatsync_free(beat1) と beatsync_link(ablink) を Switch で選び、Null で束ねる。
    #   4ノードは先にまとめて消す（片方だけ作り直された中間状態を挟まない）。
    tdb.destroy(p, 'beatsync', 'beatsync_sw', 'beatsync_free', 'beatsync_link')

    # beat1 側（フォールバック=DAW/ablink 不在時のタイムライン位相）
    free = tdb.ensure(p, 'beatsync_free', 'selectCHOP', -600, -1080,
                      pars={'chop': 'beat1', 'channames': PHASE_CHANS})
    # ablink 側（Link ネットワークに位相ロック済みのランプ）
    link = tdb.ensure(p, 'beatsync_link', 'selectCHOP', -600, -1160,
                      pars={'chop': 'ablink', 'channames': PHASE_CHANS})
    # Switch: 入力0=free(beat1)、入力1=link(ablink)。ablink があれば index=1
    sw = tdb.ensure(p, 'beatsync_sw', 'switchCHOP', -420, -1120,
                    inputs=[free, link], pars={'index': ('expr', BEATSYNC_INDEX_EXPR)})
    # Null: 式が参照する安定した単一点
    tdb.ensure(p, 'beatsync', 'nullCHOP', -240, -1120, inputs=[sw], cook=True)

    # 下流の位相参照は張り替え不要（pbus.phase() が beatsync を自動優先する）。
    # この beatsync Null ができた時点で bpm/accent の拍項が自動で切替わる。

    print('[ableton_link] build complete. '
          'Enable Link in your DAW (same LAN). '
          "ablink['numpeers']>=1 & ['linked']=1 means connected; "
          'the DAW tempo now drives /local/time.tempo (fail-safe 120 when no peer). '
          "Phase-lock ON: rampbeat/rampbar are read via op('beatsync') "
          '(ablink phase-locked when present, beat1 otherwise). '
          'No expression rebinding needed — the parameter bus terms auto-switch '
          'to beatsync as soon as this Null exists.')
    return al


if __name__ == '__main__':
    build_ableton_link()
