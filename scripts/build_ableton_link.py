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

■ 位相ロック（真の Link の価値／要 DAW 検証・本 v1 では未実装）
  テンポ同期は「速さ」を合わせるが、DAW のダウンビートとの「位相」までは
  合わない（beat1 は TD のタイムライン 0 起点で走るため）。厳密に拍頭を DAW に
  合わせるには、beat1 の代わりに ablink の位相ロック済みランプ
  op('ablink')['rampbeat'] / ['rampbar'] を直接読む必要がある。ただし:
    - build_bpm_sync の BEAT_ENV と hueoffset の小節スイープ、さらに
      onset/midi の _apply_scene が参照する beat1 をすべて ablink に差し替える
      多点改修になり、多重所有の衝突（_apply_scene が式を再構築する問題）を
      再び招く。
    - 実 DAW ピアが無いと位相ロックの正しさを検証できない。
  以上より、位相ロックは実 DAW を繋いだ状態で検証してから入れる次層とする。

使い方:
  1. build_organic_patterns.py + build_bpm_sync.py を実行済みで
  2. Textport にこのファイルを貼り付けて Enter
  3. DAW(Ableton Live 等)で Link を ON にし、TD と同一 LAN に置く
  4. ablink['numpeers'] が 1 以上・['linked']=1 になれば接続成功。DAW の
     テンポを変えると /local/time.tempo が追従し、大理石の脈動が速さを変える
  5. DAW が無くてもエンジンは 120BPM で動く（fail-safe）

再実行も安全: ablink は同名を削除してから作り直す。
"""

import td

PARENT = '/project1'

# Link 由来テンポで /local/time を駆動する fail-safe 式。
# ピア不在/異常(=tempo<=1)のときは 120 に落として時計停止を防ぐ。
TEMPO_EXPR = ("op('ablink')['tempo'] if "
              "(op('ablink') is not None and op('ablink')['tempo'] > 1) else 120.0")

# 生やす出力チャンネル（これらは ON/OFF トグル。テンポ設定ではない）。
# tempo=共有テンポ, rampbeat/rampbar=位相ロック済みランプ(将来の位相ロック用),
# beat/bar=拍/小節カウンタ。
LINK_OUTPUT_TOGGLES = ('tempo', 'rampbeat', 'rampbar', 'beat', 'bar')


def build_ableton_link():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。')
    if p.op('beat1') is None:
        raise RuntimeError(
            'BPM 同期スタックが未構築です。先に build_bpm_sync.py を実行してください。'
        )

    # --- Ableton Link CHOP（再ビルド対応） ---
    ex = p.op('ablink')
    if ex:
        ex.destroy()
    al = p.create(td.abletonlinkCHOP, 'ablink')
    al.nodeX, al.nodeY = -600, -960

    # Link を有効化（active=ノード稼働 / enable=Link 参加）
    for pn in ('active', 'enable'):
        if hasattr(al.par, pn):
            getattr(al.par, pn).val = True
    # 必要な出力チャンネルを生やす（トグル）
    for tog in LINK_OUTPUT_TOGGLES:
        if hasattr(al.par, tog):
            getattr(al.par, tog).val = True
    al.cook(force=True)

    # --- テンポの供給源を Link に差し替え（/local/time を1点駆動） ---
    tc = op('/local/time')
    if tc is None or not hasattr(tc.par, 'tempo'):
        raise RuntimeError('/local/time の tempo が見つかりません。')
    tc.par.tempo.expr = TEMPO_EXPR

    print('[ableton_link] build complete. '
          'Enable Link in your DAW (same LAN). '
          "ablink['numpeers']>=1 & ['linked']=1 means connected; "
          'the DAW tempo now drives /local/time.tempo (fail-safe 120 when no peer). '
          'Phase-lock (rampbeat/rampbar direct) is a documented next layer '
          'requiring a live DAW to verify.')
    return al


if __name__ == '__main__':
    build_ableton_link()
