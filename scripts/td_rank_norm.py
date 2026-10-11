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
- 履歴は件数ではなく時刻で古いものを捨てる（WINDOW_SEC より前のサンプルは無音中も
  消える）。件数だけで区切ると、無音を挟んで次の曲に移ったとき前の曲のサンプルが
  残り、小さい曲が大きい曲と比べられて最大30秒ほど反応しなくなる（PR #10 のレビュー）。
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
        self.window = float(window_sec)
        maxlen = max(1, int(round(window_sec * sample_hz)))
        self._order = deque(maxlen=maxlen)   # (時刻, 値) を入った順に（古いものを捨てるため）
        self._sorted = []                    # 同じ値を昇順で（順位を二分探索で引く）
        self._next_t = None
        self._last_t = None

    def __len__(self):
        return len(self._sorted)

    def _drop_oldest(self):
        _, old = self._order.popleft()
        del self._sorted[bisect_left(self._sorted, old)]

    def _push(self, v, t):
        if len(self._order) == self._order.maxlen:
            self._drop_oldest()
        self._order.append((t, v))
        insort(self._sorted, v)

    def _expire(self, t):
        """時刻 t から見て窓より古いサンプルを捨てる。時計が戻ったら履歴を空にする
        （残った時刻が未来になり、いつまでも捨てられなくなるため）。"""
        if self._last_t is not None and t < self._last_t - 1.0:
            self._order.clear()
            self._sorted = []
            self._next_t = None
        self._last_t = t
        while self._order and self._order[0][0] < t - self.window:
            self._drop_oldest()

    def rank(self, v):
        """履歴の中で v より小さいものの割合（同値は半分）。履歴が空なら 0。"""
        n = len(self._sorted)
        if n == 0:
            return 0.0
        lo = bisect_left(self._sorted, v)
        hi = bisect_right(self._sorted, v)
        return (lo + 0.5 * (hi - lo)) / n

    def observe(self, v, t):
        """現在値 v（時刻 t 秒）を履歴に積み、履歴の中での順位（0〜1）を返す。
        無音・NaN/inf は 0.0。履歴が min_samples に満たない立ち上がりは None
        （呼び出し側で生の値の判定に落とす）。オンセット検出はこれを直接使う。"""
        v = float(v)
        self._expire(t)               # 無音や NaN のフレームでも古いサンプルは捨てる
        # NaN/inf は 0 にして履歴にも入れない。NaN は大小比較がすべて偽なので、
        # 1つ入ると bisect が壊れ、以後ずっと順位 0.5（=ref/2）を返し続ける
        # （2026-10-11 実機で、上流の Lag が NaN を出したときに起きた）
        if v != v or v in (float('inf'), float('-inf')) or v < self.floor:
            return 0.0
        if self._next_t is None or t < self._next_t - 1.0:
            self._next_t = t          # 初回か、時計が戻った（巻き戻し等）ときは今から数え直す
        if t >= self._next_t:
            self._push(v, t)
            # t + period ではなく予定時刻に足す。fps が period を割り切らないとき
            # （30fps と 20Hz）に間隔が2フレームへ丸まり、実効頻度が落ちるのを防ぐ
            self._next_t += self.period
            if self._next_t < t:      # 長く止まっていた後は追いつこうとまとめて積まない
                self._next_t = t + self.period
        if len(self._sorted) < self.min_samples:
            return None
        return self.rank(v)

    def update(self, v, t):
        """現在値 v（時刻 t 秒）を受け取り、正規化後の値（0〜ref）を返す。
        立ち上がりは生の値をそのまま返す。"""
        r = self.observe(v, t)
        if r is None:
            return float(v)
        r = (r - self.p_lo) / (self.p_hi - self.p_lo)
        return min(1.0, max(0.0, r)) * self.ref


class OnsetDetector:
    """オンセット検出（低域キックでシーンを進める）の判定。TD 非依存。
    build_onset_scenes.py の onset_exec がこのファイルごと埋め込んで使い、
    test_td_rank_norm.py が記録なしで回数を検証する。

    判定はシュミットトリガ（上下2つのしきい値）: armed のとき hi を上抜けたら発火して
    armed=0、armed=0 のとき lo を下回ったら再武装。1キックで1回だけ発火する。
    値としきい値は次のどちらか:
      - 順位: 直近30秒の低域の中での順位と rank_hi/rank_lo（既定）
      - 生の値: 低域の値そのものと hi/lo。立ち上がり（履歴が約2秒たまるまで）・
        テスト注入・順位モードを切ったときに使う
    順位で発火するときは、生の値が min_level を超えている必要もある。順位は直近30秒の
    上位15%を必ずどこかで拾うので、キックの無い静かな区間の揺れで発火しないようにする。
    """

    def __init__(self, hi, lo, rank_hi, rank_lo, low_ref, min_level):
        self.hi, self.lo = hi, lo
        self.rank_hi, self.rank_lo = rank_hi, rank_lo
        self.min_level = min_level
        self.norm = RankNorm(low_ref)

    def thresholds(self, lvl, t, test=False, rank_on=True):
        """判定に使う (値, 発火しきい値, 再武装しきい値) を返す。"""
        if test or not rank_on:
            return lvl, self.hi, self.lo
        r = self.norm.observe(lvl, t)
        if r is None:                    # 立ち上がり: 履歴がたまるまで生の値で判定
            return lvl, self.hi, self.lo
        if lvl <= self.min_level:        # 静かな区間: 順位が高くても発火させない（再武装はさせる）
            r = min(r, self.rank_lo)
        return r, self.rank_hi, self.rank_lo

    @staticmethod
    def step(armed, x, hi, lo):
        """シュミットトリガの1ステップ。(発火したか, 次の armed) を返す。"""
        if armed and x > hi:
            return True, 0
        if (not armed) and x < lo:
            return False, 1
        return False, armed

    def feed(self, lvl, t, armed, test=False, rank_on=True):
        """1フレーム分。(発火したか, 次の armed) を返す。"""
        x, hi, lo = self.thresholds(lvl, t, test, rank_on)
        return self.step(armed, x, hi, lo)
