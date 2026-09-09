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

## 拡張: 音楽反応（Audio Reactive）

ベースの油膜・大理石エンジンを音で駆動する派生。低域でドメインワープが波打ち、
中域でうねりの元エネルギーが増え、高域で金属エッジと彩度がきらめく。

1. まず [scripts/build_organic_patterns.py](scripts/build_organic_patterns.py) を実行
2. 続けて [scripts/build_audio_reactive.py](scripts/build_audio_reactive.py) を実行
3. `aud_in`（Audio Device In）のデバイスをマイク/ライン入力に設定
4. `/project1/out1` を表示して音を鳴らす

| 音の帯域 | 駆動するパラメータ | 見た目の変化 |
|---|---|---|
| 低域（キック/ベース） | `warp_disp` の変位量 | 大理石がビートで波打つ |
| 中域（コード/ボーカル） | `seed_noise` の amp | うねりの元エネルギーが増える |
| 高域（ハイハット/シンバル） | `edge1` strength ／ `hsv1` 彩度 | 金属リムと色がきらめく |
| 全体音量（RMS） | `level1` opacity | 大音量ほど構造が長く残る |

### 設計のポイント（base + gain）

各パラメータは `base + op('aud_lag')['band']*gain` の式で駆動する。無音時は解析値が
0 に収束して base 値そのまま＝元の静的パッチと同じ絵になる。マイク未接続でも壊れず、
鳴らすと動く。オーディオを「置換」でなく「加算」にすることでライブでの堅牢性を確保。

左が無音時（ベースと同一）、右がビート入力時（変位・彩度・エッジが増幅）:

| 無音（base値のみ） | ビート入力時（base + band*gain） |
|---|---|
| ![idle](reference/audioreactive_idle_preview.png) | ![beat](reference/audioreactive_beat_preview.png) |

- **FFT のジッタは Lag CHOP で平滑化**（attack=0.02 / release=0.15）。生の Audio
  Spectrum はフレーム毎に激しく揺れるため、そのまま繋ぐとパラメータが痙攣する。
- **帯域分割は Trim CHOP のサンプル範囲で**。Audio Spectrum の 22050 サンプルを
  低/中/高にインデックスで割る（厳密な Hz 変換より体感優先）。

## 拡張: BPM同期（Beat Sync）

音楽反応が「鳴っている音のエネルギーに連続追従」なのに対し、BPM同期は先に定義した
**拍グリッドにスナップ**する。大理石が拍頭で脈動し、小節ごとに色相がスイープする。
両者は加算合成で併存でき、BPM同期だけでもフルスタックでも動く。

1. [scripts/build_organic_patterns.py](scripts/build_organic_patterns.py)（必要なら
   [scripts/build_audio_reactive.py](scripts/build_audio_reactive.py) も）を実行済みで
2. 続けて [scripts/build_bpm_sync.py](scripts/build_bpm_sync.py) を実行
3. `/local/time` の tempo（既定 120BPM）を曲に合わせる。ライブでは Tap Tempo /
   Ableton Link で上書き
4. `/project1/out1` を表示。120BPM なら 0.5 秒ごとに脈動する

| 拍要素 | 駆動するパラメータ | 見た目の変化 |
|---|---|---|
| 拍頭パルス（rampbeat） | `warp_disp` の変位量 | 拍でワープがスナップ |
| 拍頭パルス（rampbeat） | `hsv1` valuemult | 拍で明度がポップ |
| 小節ランプ（rampbar） | `hsv1` hueoffset | 小節ごとに色相スイープ |

### 設計のポイント（状態を持たない拍エンベロープ）

拍の減衰パルスは `(1 - op('beat1')['rampbeat'])**2` で式生成する。拍頭=1 →
拍末=0、二乗でアタックを鋭くする。1フレームの pulse スパイクを Lag で平滑化する
方式も試したが、スパイクは捉えづらく状態依存で不安定だった。**rampbeat 由来の
閉じた式はテンポから確定的に決まり、どのフレームでも値が一意=再現・検証が容易**。

- **Beat CHOP の bpm/pulse/rampbeat/rampbar は出力チャンネルの ON/OFF トグル**で
  あってテンポ設定ではない。実テンポはローカル Time COMP (`/local/time`) の tempo。
- **無音でも動く**（Beat CHOP は内部クロック駆動）。音量追従と違い、音がなくても
  拍は刻まれる。

![bpm sync](reference/bpmsync_preview.png)

## 拡張: オンセット検出でシーン切替（Onset Scenes）

連続追従（音量）・拍グリッド（BPM）に続く**イベント駆動**の第3軸。低域キックの
オンセット（立ち上がり）を検出するたびにシーンが進み、表示側ブレンドモードと色相
基準がジャンプする。曲の展開に合わせて絵の質感が切り替わる。

1. [scripts/build_organic_patterns.py](scripts/build_organic_patterns.py)（+
   [scripts/build_audio_reactive.py](scripts/build_audio_reactive.py) 推奨）を実行済みで
2. 続けて [scripts/build_onset_scenes.py](scripts/build_onset_scenes.py) を実行
3. `/project1/out1` を表示し、キック（低域）を入れる。テストは `__onsettest`
   Constant CHOP に `low=0.5` を注入すると1フレームでシーンが進む

| scene | 表示ブレンド | hue基準 | 質感 |
|---|---|---|---|
| 0 | add | 0° | 元（金属リムを加算） |
| 1 | screen | 90° | 発光的に持ち上げ |
| 2 | overlay | 180° | コントラスト強調・色相反対 |
| 3 | lightercolor | 270° | 明色優先で硬質に |

| scene 0 (add) | scene 1 (screen) | scene 2 (overlay) | scene 3 (lightercolor) |
|---|---|---|---|
| ![s0](reference/onset_scene0_add.png) | ![s1](reference/onset_scene1_screen.png) | ![s2](reference/onset_scene2_overlay.png) | ![s3](reference/onset_scene3_lightercolor.png) |

### 設計のポイント（ヒステリシス状態機械 + ループを触らない）

- **オンセット検出はシュミットトリガ**。単純な `level > threshold` は1キックで
  閾値付近を何度も横切り多重発火する。上下2閾値（HI=0.18 発火 / LO=0.08 再武装）で
  「一度発火したら LO まで戻るまで再発火しない」＝1キック1回だけ前進を保証する。
- **状態は Execute DAT の `onFrameStart` で保持**。シーンindexは Constant CHOP、
  再武装フラグ `armed` は DAT storage（`store/fetch`）に置く。CHOP に置くとクック
  順序で競合しうるが、Python 側の永続変数なら決定的に読み書きできる。
- **シーン切替は表示側 `disp_comp` を変え、ループ内 `comp1` は触らない**。
  vividlight 等の非線形ブレンドをフィードバックループに置くと出力が 0/1 に
  張り付き崩壊する（Emboss がループを凍らせるのと同じアトラクタ問題）。ループ内は
  difference 固定、質感の切替は out 手前の表示側合成で行う。

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
