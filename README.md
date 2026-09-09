# TD Organic Patterns

TouchDesigner でフィードバックループ＋ドメインワープにより、油膜・大理石状の
有機的な虹色パターンを生成するネットワーク。

Reddit r/TouchDesigner の投稿
[organic patterns ⚗️](https://www.reddit.com/r/TouchDesigner/comments/1w3danp/organic_patterns/)
（作者: photoevaporation）の質感を、作者本人がコメントで明かした技法をもとに
TouchDesigner 標準ノードで再構築したもの。

元投稿の映像は [Reddit のオリジナル投稿](https://www.reddit.com/r/TouchDesigner/comments/1w3danp/organic_patterns/) を参照。
本リポジトリでの再現結果:

![reproduction](reference/reproduction_preview.png)

## 作者が明かした技法

> "It's mostly experimenting through **feedback loops** and **blend mode
> operations**. In this clip, for example, the patterns are created using
> **Emboss, Edge, and Sharpen effects inside a loop**, while I shaped the
> aesthetic through lots of blend mode operations."

## 使い方

### A. Python ビルドスクリプト（推奨・gitで差分が追える）

1. TouchDesigner を起動（空プロジェクトでよい）
2. Textport を開く（`Alt+T` / メニュー `Dialogs > Textport and DATs`）
3. [scripts/build_organic_patterns.py](scripts/build_organic_patterns.py) の中身を貼り付けて実行
4. `/project1/out1` をビューアで表示。数十フレーム回すとパターンが育つ

再実行すると既存の同名ノードを削除してから作り直すため、何度でも安全に再構築できる。

### B. .tox を読み込む

[tox/organic_patterns.tox](tox/organic_patterns.tox) を任意の COMP にドラッグ＆ドロップ。
（.tox はバイナリのため差分は追えない。パラメータ調整の履歴は A 側で管理する）

## ネットワーク構成

```
seed_noise ──┐(difference)                    warp_noise
             ↓                                    │
    ┌──→ comp1 ──→ warp_disp ←────────────────────┘(変位マップ)
    │              ↓
    │        convo_sharp1 ──→ level1(decay 0.99) ──→ null1 ──┐
    │                                                  │      │
    └────────────── fb1 (feedback) ←───────────────────┘      │
                                                              │
   表示: null1 ──→ disp_level(コントラスト/黒抜き) ──┐          │
         null1 ──→ edge1(金属リム) ────────────────→ disp_comp(add) ──→ hsv1(彩度/hue回転) ──→ out1
```

| 原作の要素 | 実現しているノード / 技法 |
|---|---|
| 有機的な自己組織化 | フィードバックループ（null1 → fb1 → comp1） |
| うねる大理石の流れ | ドメインワープ（warp_noise で駆動する Displace TOP） |
| 虹色イリデッセンス | comp1 の Difference 合成 ＋ HSV hue の時間回転 |
| 金属質のエッジ | Edge TOP を Add 合成 |
| 黒い抜け・深い色調 | disp_level の blacklevel / gamma で暗部クリップ |
| 発散防止 | level1 opacity=0.99（フィードバックゲイン < 1） |

## 実装上の要点（ハマりどころ）

- **Noise TOP は `mono=False` が必須**。既定のモノクロ出力だと RGB 全チャンネルが
  同値になり、Difference 合成してもグレースケールのままになる。False にして
  RGB を分離することで初めて虹色が生まれる。
- **TD 標準の Emboss TOP はフィードバックループに置けない**。出力に +0.5 の DC
  オフセットがあり、毎フレーム系を灰色 0.5 へ引き戻す“アトラクタ”になって系が
  凍る。ループ内のエッジ強調は Convolve(シャープ化カーネル) を使い、Emboss/Edge は
  表示側に置く。
- **大理石の「流れ」は Transform の回転では出ない**（同心リング状のアーティファクト
  になる）。非剛体のうねりは Displace TOP によるドメインワープでのみ得られる。
- **色は塗るのではなく発生させる**。Difference 合成で RGB チャンネルが位相ずれし、
  油膜の補色イリデッセンスが副産物として現れる。彩度・黒は表示側で後付け。

## 調整の勘所

- 発散したら: `level1` の opacity を下げる
- 構造が固まったら: `warp_noise` の period を下げる / `seed_noise` の amp を上げる
- パターンを大きく: ループ解像度 `LR` を下げる（既定 640×360）
- 色を濃く: `hsv1` の saturationmult を上げる / `comp1` を別のブレンドモードに

## 完全一致について

作者は Patreon でパッチ（.toe）を配布していると明言している。厳密な完全再現が必要な
場合はそちらが最短。本リポジトリは作者の手法を標準ノードで再構築した教材的実装。
