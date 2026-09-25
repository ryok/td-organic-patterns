"""
build_recorder.py
=================
作例クリップを書き出すための録画パイプラインをベースネットワークに追加する。

構成:
  hsv1(表示最終段) → rec_res(Resolution: 480x270 に縮小) → rec_out(Movie File Out)

■ macOS のコーデック事情（ハマりどころ）
  - h264nvgpu は NVIDIA NVENC 専用。Apple Silicon / Intel Mac では
    "Nvidia H.264 codec is not supported on this OS" で書き出しゼロになる。
  - macOS で TD 単体完結なら mpeg4（互換重視・そこそこ軽い）か prores（高品質・
    大容量）。本スクリプトは mpeg4 を既定にする。
  - GIF コーデックも選べるが、GIF はフレーム間圧縮が弱く容量が爆発する
    （実測: 480x270 の数十秒で 100MB 超）。GIF が要るなら ffmpeg で
    2パスパレット最適化する方が桁違いに軽い（後述）。

■ 録画の進め方（前回の time.sleep 教訓）
  Movie File Out は record ON の間、クックされたフレームを実時間で書き出す。
  Python 内で time.sleep するとメインスレッドが止まりクックも止まるため、
  「record ON → 別処理で壁時計時間を進める → record OFF」で撮る。
  TD アプリは MCP/外部呼び出しの合間も独立して動き続けるので、ON にして
  数秒待って OFF にすればその間のフレームが入る。

■ README 用メディアの作り方（TD 書き出し後に ffmpeg）
  1. TD で mpeg4 の作例を書き出す（この pipeline）
  2. 軽量 H.264（保存用・フルクオリティ）:
       ffmpeg -y -i demo_loop.mp4 -c:v libx264 -crf 26 -preset slow \
              -movflags +faststart -an demo_loop_h264.mp4
  3. README インライン用の最適化 GIF（2パスパレット）:
       ffmpeg -y -t 8 -i demo_loop.mp4 \
         -vf "fps=10,scale=320:-1:flags=lanczos,palettegen=stats_mode=diff" \
         -update 1 _palette.png
       ffmpeg -y -t 8 -i demo_loop.mp4 -i _palette.png -lavfi \
         "fps=10,scale=320:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" \
         demo_loop.gif
     （GitHub の markdown は mp4 をインライン再生しないため、動きを見せるループは
      GIF が確実。フルクオリティは H.264 mp4 で別途残す）

使い方:
  1. build_organic_patterns.py 実行済み（+ 各拡張は任意）で
  2. Textport にこのファイルを貼り付けて Enter
  3. 録画: op('/project1/rec_out').par.record = True  … 数秒 …  = False
  4. reference/demo_loop.mp4 が書き出される
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
REC_RES = (480, 270)   # GIF/軽量動画向けの縮小解像度
REC_FPS = 24
REC_CODEC = 'mpeg4'    # macOS 互換。NVIDIA機なら 'h264nvgpu' が軽い
REC_FILE = '/Users/ryookada/work/td-organic-patterns/reference/demo_loop.mp4'


def build_recorder():
    p = tdb.get_parent(PARENT)
    tdb.require(p, 'hsv1', hint='build_organic_patterns.py')

    # 縮小段
    rr = tdb.ensure(p, 'rec_res', 'resolutionTOP', 1250, 250, res=REC_RES, inputs=['hsv1'])

    # Movie File Out
    m = tdb.ensure(p, 'rec_out', 'moviefileoutTOP', 1400, 100, inputs=[rr],
                   pars={'type': 'movie', 'videocodec': REC_CODEC, 'fps': REC_FPS,
                         'file': REC_FILE})

    print(f'[recorder] build complete. codec={REC_CODEC}, res={REC_RES}, '
          f'file={REC_FILE}\n'
          "  Record with: op('/project1/rec_out').par.record = True  (…wait…)  = False")
    return m


if __name__ == '__main__':
    build_recorder()
