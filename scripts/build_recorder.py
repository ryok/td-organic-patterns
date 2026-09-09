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

PARENT = '/project1'
REC_RES = (480, 270)   # GIF/軽量動画向けの縮小解像度
REC_FPS = 24
REC_CODEC = 'mpeg4'    # macOS 互換。NVIDIA機なら 'h264nvgpu' が軽い
REC_FILE = '/Users/ryookada/work/td-organic-patterns/reference/demo_loop.mp4'


def build_recorder():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。')
    if p.op('hsv1') is None:
        raise RuntimeError(
            'ベースネットワークが未構築です。先に build_organic_patterns.py を実行してください。'
        )

    # 縮小段（再ビルド対応）
    ex = p.op('rec_res')
    if ex:
        ex.destroy()
    rr = p.create(td.resolutionTOP, 'rec_res')
    rr.nodeX, rr.nodeY = 1250, 250
    rr.par.outputresolution = 'custom'
    rr.par.resolutionw = REC_RES[0]
    rr.par.resolutionh = REC_RES[1]
    rr.inputConnectors[0].connect(p.op('hsv1'))

    # Movie File Out
    ex = p.op('rec_out')
    if ex:
        ex.destroy()
    m = p.create(td.moviefileoutTOP, 'rec_out')
    m.nodeX, m.nodeY = 1400, 100
    m.par.type = 'movie'
    m.par.videocodec = REC_CODEC
    if hasattr(m.par, 'fps'):
        m.par.fps = REC_FPS
    m.par.file = REC_FILE
    m.inputConnectors[0].connect(rr)

    print(f'[recorder] build complete. codec={REC_CODEC}, res={REC_RES}, '
          f'file={REC_FILE}\n'
          "  Record with: op('/project1/rec_out').par.record = True  (…wait…)  = False")
    return m


if __name__ == '__main__':
    build_recorder()
