"""
build_bpm_sync.py
=================
ベースの油膜・大理石エンジンに「BPM同期（拍グリッドへのクオンタイズ）」を
重ねる差分ビルドスクリプト。

オーディオ反応（build_audio_reactive.py）との違い:
  - オーディオ反応 = 鳴っている音の「エネルギーに連続追従」（滑らかなうねり）
  - BPM同期      = 先に定義した「拍グリッドにスナップ」（リズミカルな脈動）
  両者は加算合成で併存できる。BPM同期だけでも、フルスタックでも動く。

前提:
  build_organic_patterns.py 実行済み（warp_disp, hsv1, seed_noise 等が存在）。
  build_audio_reactive.py は任意（あれば aud_lag['low'] を低域項として合成する）。

拍エンベロープの作り方（状態を持たない閉じた式）:
  Beat CHOP の rampbeat（拍ごと 0→1 の鋸波）から
      env = (1 - rampbeat)**2      # 拍頭=1 → 拍末=0 の減衰パルス、二乗でアタックを鋭く
  を式で直接生成する。Lag による pulse 平滑化も試したが、1フレームのスパイクは
  ポーリングで捉えづらく状態依存で不安定。rampbeat 由来のエンベロープはテンポから
  確定的に決まり、どのフレームでも値が一意=再現・検証が容易。

テンポの所在:
  Beat CHOP の bpm/pulse/rampbeat/rampbar パラメータは「出力チャンネルの ON/OFF
  トグル」であってテンポ設定ではない。実テンポはコンポーネントのローカル Time COMP
  (/local/time) の tempo が持つ。ライブでは Tap Tempo や Ableton Link で
  /local/time の tempo を曲に合わせる。

使い方:
  1. build_organic_patterns.py（必要なら build_audio_reactive.py も）を実行済みで
  2. Textport にこのファイルを貼り付けて Enter
  3. /project1/out1 を表示。120BPM 既定なら 0.5 秒ごとに大理石が脈動する
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
TEMPO_BPM = 120.0   # /local/time に書き込むテンポ（ライブでは Tap Tempo 等で上書き）

# 拍エンベロープ: 拍頭=1 → 拍末=0 の減衰パルス。
# 位相ソースは PHASE_SRC 経由（beatsync 導入後も式を張り替えず自動追従）。
BEAT_ENV = f"(1-{pbus.PHASE_SRC}['rampbeat'])**2"

# BPM同期でエンジンへ焼き込む式（gain 係数）
GAINS = {
    'warp_disp_pulse': 0.18,  # 変位のスナップ量
    'value_pop':       0.4,   # 拍頭の明度ポップ
    'hue_bar_sweep':   40.0,  # 小節あたりの色相スイープ（度）
}


def build_bpm():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。')
    if p.op('warp_disp') is None or p.op('hsv1') is None:
        raise RuntimeError(
            'ベースネットワークが未構築です。先に build_organic_patterns.py を実行してください。'
        )

    # Beat CHOP（再ビルド対応）
    ex = p.op('beat1')
    if ex:
        ex.destroy()
    b = p.create(td.beatCHOP, 'beat1')
    b.nodeX, b.nodeY = -600, -560
    # 出力チャンネルを有効化（これらは ON/OFF トグル。テンポ設定ではない）
    for tog in ('pulse', 'rampbeat', 'rampbar'):
        if hasattr(b.par, tog):
            getattr(b.par, tog).val = True

    # テンポはローカル Time COMP が持つ
    tcomp = op('/local/time')
    if tcomp is not None and hasattr(tcomp.par, 'tempo'):
        tcomp.par.tempo = TEMPO_BPM

    # エンジンへ拍項を登録（tag='bpm'）。audio の低域項(tag='audio')とは別タグなので
    # 同じ warp_disp でも奪い合わず共存する。以前の _audio_low_term() の手動合成は不要。
    G = GAINS
    beat_pulse = f"{BEAT_ENV}*{G['warp_disp_pulse']}"
    pbus.add_term(p, 'warp_disp', 'displaceweightx', 'bpm', beat_pulse, base='0.09')
    pbus.add_term(p, 'warp_disp', 'displaceweighty', 'bpm', beat_pulse, base='0.09')
    pbus.add_term(p, 'hsv1', 'valuemult', 'bpm', f"{BEAT_ENV}*{G['value_pop']}", base='1.25')
    # 色相の小節スイープは 'bpm_hue' タグ。PHASE_SRC で beatsync/beat1 を自動選択。
    pbus.add_term(p, 'hsv1', 'hueoffset', 'bpm_hue',
                  f"{pbus.PHASE_SRC}['rampbar']*{G['hue_bar_sweep']}",
                  base='absTime.seconds*6', wrap=360)

    print(f'[bpm_sync] build complete at {TEMPO_BPM} BPM. '
          'Set /local/time tempo (or Tap Tempo) to match your track.')
    return b


if __name__ == '__main__':
    build_bpm()
