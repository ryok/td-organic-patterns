"""
build_accent.py
===============
ベースの油膜・大理石エンジンに「小節頭アクセント」を重ねる差分ビルドスクリプト。
拍頭より一段強い"パンチ"を各小節の 1 拍目（ダウンビート）に与え、Ableton の
アクセント音（メトロノームの高い方）に視覚的な山を合わせる。

■ 位置づけ（既存の拍脈動の"上"に載る強調）
  build_bpm_sync/audio_reactive は毎拍の連続脈動を作る。本スクリプトはそれと別に
  「小節頭だけ」急峻に持ち上げる項を後置加算する。つまり毎拍の呼吸に対して、
  小節の頭で一段大きく息を吸う演出。位相ロック(build_ableton_link)済みなら
  この山は DAW のダウンビートに正確に一致する。

■ アクセント包絡（小節頭で最大→急減衰）
  rampbar は小節頭で 0、小節末で 1 に向かうランプ。よって
      env = (1 - rampbar) ** POW
  は小節頭(rampbar=0)で 1、そこから減衰する。POW を上げるほど山が鋭くなり
  「拍の点」に近づく（POW=6 でおよそ 1 拍かけて減衰し、パンチとして読める）。
  各パラメータには env に gain を掛けた項を足す（gain=小節頭で足し込む最大量）。

■ base + gain の「後置加算」設計（既存式を壊さない）
  warp/hsv/opacity の各式は audio/bpm/onset/midi/位相ロックの項が既に乗っている。
  それらを消さないよう、式末尾に「+ env*gain」を追記する（重複追記はしない＝
  再実行安全）。谷では env≈0 なので、繋いでも元の絵の谷を壊さない fail-safe。

■ 位相ソースはビルド時に選ぶ（毎フレーム分岐を撒かない）
  beatsync(位相ロック層)があればそれ、無ければ beat1 を rampbar 供給源とする。
  式内に op('beatsync') is not None の三項を撒くと、_apply_scene の多重所有問題と
  同種の脆さを招くため、ビルド時に供給源名を1つ確定して term を組む。

■ フィードバック opacity への配慮（発散注意＝小 gain）
  level1.opacity（フィードバック残留）へのアクセントは構造の"尾"を小節頭で伸ばす
  が、大きくすると 0/1 張り付き＝発散を招く（README「実装上の要点」）。よって
  ここだけ極小 gain に留める。

使い方:
  1. build_organic_patterns.py + build_bpm_sync.py を実行済みで
     （位相ロックまで欲しければ build_ableton_link.py も実行しておく）
  2. Textport にこのファイルを貼り付けて Enter
  3. 小節頭で構造がひと突きし、明度・彩度が一段上がる。位相ロック時は DAW の
     ダウンビートに一致する

再実行も安全: 各項は同一文字列なら二重加算しない（冪等）。
"""

import td

PARENT = '/project1'

# アクセントの鋭さ（大きいほど小節頭に集中した鋭い山）。
ACCENT_SHARP = 6

# アクセントを足す対象: (ノード, パラメータ, gain=小節頭で足し込む最大量)。
# gain の単位は各パラメータに準拠。opacity だけは発散回避のため極小に留める。
ACCENT_GAINS = [
    ('warp_disp', 'displaceweightx', 0.30),   # 構造のひと突き（ドメインワープ変位）
    ('warp_disp', 'displaceweighty', 0.30),
    ('hsv1',      'valuemult',       0.70),   # 明度パンチ
    ('hsv1',      'saturationmult',  1.80),   # 色の濃さを一段
    ('level1',    'opacity',         0.003),  # 尾を微かに伸ばす（★小 gain 厳守）
]


def _append_term(par, term):
    """既存式(or 現在値)にアクセント項を後置加算。重複追記はしない(再実行安全)。"""
    cur = par.expr or ''
    if term in cur:
        return                      # 既に追記済み（再ビルド）→ 二重加算を防ぐ
    if cur.strip() == '':
        cur = repr(par.eval())      # 式が無ければ現在値をベース定数として採用
    par.expr = f"({cur}) + {term}"


def build_accent():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。')
    if p.op('hsv1') is None or p.op('warp_disp') is None:
        raise RuntimeError(
            'ベースネットワークが未構築です。先に build_organic_patterns.py を実行してください。'
        )

    # 位相供給源をビルド時に確定（位相ロック層があれば beatsync、無ければ beat1）
    if p.op('beatsync') is not None:
        src = 'beatsync'
    elif p.op('beat1') is not None:
        src = 'beat1'
    else:
        raise RuntimeError(
            '拍位相の供給源がありません。先に build_bpm_sync.py を実行してください。'
        )

    env = f"(1-op('{src}')['rampbar'])**{ACCENT_SHARP}"

    for node_name, par_name, gain in ACCENT_GAINS:
        target = p.op(node_name)
        if target is None or not hasattr(target.par, par_name):
            print(f'[warn] {node_name}.{par_name} が見つからずスキップ')
            continue
        _append_term(getattr(target.par, par_name), f"{env}*{gain}")

    print(f'[accent] build complete. Downbeat accent added via {src} rampbar '
          f'(sharp={ACCENT_SHARP}). Structure punches and brightness/saturation lift '
          'on each bar head; phase-locked to the DAW downbeat when beatsync is present.')
    return src


if __name__ == '__main__':
    build_accent()
