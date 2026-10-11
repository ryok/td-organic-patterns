"""
td_rank_norm.py
===============
音の帯域の大きさを「生の値」ではなく「直近 N 秒の中での順位」に直す正規化。
build_rank_norm.py が Script CHOP の callbacks DAT にこのファイルの本文を埋め込んで
使う。TouchDesigner に依存しないので test_td_rank_norm.py で単体検証できる。

なぜ順位か
----------
固定ゲインは「どの曲で較正したか」に縛られる（2026-09-27 に1曲40秒で較正）。
音圧の小さい曲では絵がほとんど動かず、大きい曲では張り付いて白く飛ぶ。順位なら
その曲・その区間の中で相対的にどれだけ大きいかだけを見るので、曲ごとの音量差も
曲の中の静かな区間と大きな区間の差も吸収される。

  rank  = 直近の履歴のうち現在値より小さいものの割合（同値は半分として数える）
  out01 = clamp((rank - P_LO) / (P_HI - P_LO), 0, 1)   # p10→0、p90→1
  out   = out01 * ref                                   # 較正済みの大きさに戻す

ref を掛けて返すのは、映像側の各ゲイン（build_audio_reactive の MAPPINGS など）が
生の値の大きさ（較正曲の p95）に合わせてあるため。0〜1 のまま渡すと high×29 の
edge 強度が 30 を超え、opacity は上限に張り付く。ref 倍で返せば「どの曲も較正曲と
同じ揺れ幅で動く」ようになり、ゲインは一切変えずに済む。

設計上の判断
------------
- 窓は時間（WINDOW_SEC 秒）で切る。参考にした作品の「直近64打」は打音（イベント）
  単位の話で、毎フレームの連続値に 64 サンプルを当てると 60fps で約1秒になり、
  ほぼ雑音を正規化してしまう。同じ作品で連続量（ローパスの開き）に使っている
  「直近30秒」に合わせた。サンプリングは SAMPLE_HZ に間引き、fps に依存させない。
- 無音（floor 未満）は 0 を返し、履歴にも入れない。入れると無音の区間で履歴が
  ほぼ同じ小さい値で埋まり、ノイズの揺れが 0〜ref の全幅に引き伸ばされる。
- 履歴が MIN_SAMPLES に満たない立ち上がりは生の値をそのまま返す（従来と同じ絵）。
"""

from bisect import bisect_left, bisect_right, insort
from collections import deque

WINDOW_SEC = 30.0       # 順位を取る履歴の長さ（秒）
SAMPLE_HZ = 20.0        # 履歴に積む頻度（=最大 600 サンプル）
MIN_SAMPLES = 40        # これ未満の間は生の値を返す（約2秒）
P_LO, P_HI = 0.10, 0.90  # この順位を 0 / 1 に写す
FLOOR_RATIO = 0.01      # ref のこの割合未満は無音とみなす（0.05 だと -12dB の曲で中央値が
                        # 足切りされ、p50 が 2.1 倍ずれた。2026-10-11 実測）


class RankNorm:
    """1チャンネル分の順位正規化。t（秒）は単調増加する時刻。"""

    def __init__(self, ref, window_sec=WINDOW_SEC, sample_hz=SAMPLE_HZ,
                 min_samples=MIN_SAMPLES, p_lo=P_LO, p_hi=P_HI,
                 floor_ratio=FLOOR_RATIO):
        self.ref = float(ref)
        self.floor = self.ref * floor_ratio
        self.period = 1.0 / sample_hz
        self.min_samples = min_samples
        self.p_lo, self.p_hi = p_lo, p_hi
        maxlen = max(1, int(round(window_sec * sample_hz)))
        self._order = deque(maxlen=maxlen)   # 入った順（古いものを捨てるため）
        self._sorted = []                    # 同じ値を昇順で（順位を二分探索で引く）
        self._next_t = None

    def __len__(self):
        return len(self._sorted)

    def _push(self, v):
        if len(self._order) == self._order.maxlen:
            old = self._order[0]
            del self._sorted[bisect_left(self._sorted, old)]
        self._order.append(v)
        insort(self._sorted, v)

    def rank(self, v):
        """履歴の中で v より小さいものの割合（同値は半分）。履歴が空なら 0。"""
        n = len(self._sorted)
        if n == 0:
            return 0.0
        lo = bisect_left(self._sorted, v)
        hi = bisect_right(self._sorted, v)
        return (lo + 0.5 * (hi - lo)) / n

    def update(self, v, t):
        """現在値 v（時刻 t 秒）を受け取り、正規化後の値を返す。"""
        v = float(v)
        # NaN/inf は 0 にして履歴にも入れない。NaN は大小比較がすべて偽なので、
        # 1つ入ると bisect が壊れ、以後ずっと順位 0.5（=ref/2）を返し続ける
        # （2026-10-11 実機で、上流の Lag が NaN を出したときに起きた）
        if v != v or v in (float('inf'), float('-inf')) or v < self.floor:
            return 0.0
        if self._next_t is None or t < self._next_t - 1.0:
            self._next_t = t          # 初回か、時計が戻った（巻き戻し等）ときは今から数え直す
        if t >= self._next_t:
            self._push(v)
            # t + period ではなく予定時刻に足す。fps が period を割り切らないとき
            # （30fps と 20Hz）に間隔が2フレームへ丸まり、実効頻度が落ちるのを防ぐ
            self._next_t += self.period
            if self._next_t < t:      # 長く止まっていた後は追いつこうとまとめて積まない
                self._next_t = t + self.period
        if len(self._sorted) < self.min_samples:
            return v
        r = (self.rank(v) - self.p_lo) / (self.p_hi - self.p_lo)
        return min(1.0, max(0.0, r)) * self.ref
