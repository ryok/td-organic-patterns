"""
td_param_bus.py
===============
TouchDesigner のパラメータ式を「ベース + 名前付き加算項」で決定的に合成する
共有バス。各拡張(build_*.py)は自分のタグの項を add_term() で登録するだけで、
`.expr` を奪い合わない。合成は base + Σterms を毎回ゼロから組み直すため、
**拡張の実行順序に依存せず、再実行しても冪等**（同タグは上書き）になる。

なぜ必要か
----------
従来は2つの非互換な流儀が混在していた:
  1. 全置換型 (audio_reactive / bpm_sync): `par.expr = "2.2 + ..."` で丸ごと上書き。
     先行項を手で再埋め込みする必要があり、`hsv1.hueoffset` のように複数拡張が
     触るパラメータは「最後の書き手が勝ち、他を黙って捨てる」事故が起きた。
  2. 読み取り加算型 (accent / midi_osc): `par.expr = f"({cur}) + {term}"`。
     全置換型を後から流すと、追記した項ごと消える。
このバスは全書き手を「タグ付き加算項の登録」に一本化してこの競合を構造的に消す。

TD ランタイム上の注意
--------------------
- sys.path 経由で import したモジュールのグローバルには TD の `op`/`me` が
  注入されない。よって全関数は `parent`(= /project1 の COMP)を引数で受け取り、
  `parent.op(...)` / `parent.store()` / `parent.fetch()` だけを使う。
- 登録簿は `parent` の storage に置く(`param_bus` キー)。ノードは名前で参照する
  ため、ベースエンジンを作り直して同名ノードが再生成されても壊れない。
- `tdu.clamp(...)` は式文字列として埋め込むだけ。評価は TD 側の式コンテキストで
  行われる(このモジュールは tdu を import しない)。

使い方(各 build_*.py 側)
-----------------------
    import importlib, os, sys
    try:
        _SD = os.path.dirname(os.path.abspath(__file__))
    except NameError:                               # Textport へのペースト時
        _SD = os.environ.get('TD_ORGANIC_SCRIPTS',
                             '/Users/ryookada/work/td-organic-patterns/scripts')
    if _SD not in sys.path:
        sys.path.insert(0, _SD)
    import td_param_bus as pbus
    importlib.reload(pbus)                          # 編集を確実に反映

    p = op('/project1')
    pbus.add_term(p, 'hsv1', 'saturationmult', tag='audio',
                  term="op('aud_lag')['high']*1.5", base='2.2')
"""

STORE_KEY = 'param_bus'

# 位相ソース式: 位相ロック層(beatsync, build_ableton_link 由来)があればそれ、
# 無ければ beat1(build_bpm_sync 由来)。beat 項を書く拡張(bpm_sync/accent)はこれを
# 使えば、ableton_link を後から入れても式を張り替えずに自動で beatsync へ切替わる。
# （op(...) は不在時 None を返し、None は falsy なので or で beat1 に落ちる。）
PHASE_SRC = "(op('beatsync') or op('beat1'))"


def _registry(parent):
    """storage から登録簿を取り出す(無ければ空 dict)。"""
    return parent.fetch(STORE_KEY, {})


def _save(parent, reg):
    parent.store(STORE_KEY, reg)


def reset(parent):
    """フルリビルド時に呼ぶ。全登録項を破棄する。
    ベース値は次回 add_term() 時にライブのパラメータから再捕捉されるため、
    ベースエンジンを作り直した直後に呼べば「素の base」から再合成できる。"""
    _save(parent, {})


def add_term(parent, node, par, tag, term, base=None, clamp=None, wrap=None):
    """(node, par) に tag 付きの加算項 term を登録し、式を再合成する。

    base:  明示すると登録簿のベースを更新(最後の明示が勝つ)。None のときは
           初回登録に限りライブのパラメータ式/値から捕捉する。
    clamp: (lo, hi) を渡すと合成後の式全体を tdu.clamp(..., lo, hi) で締める
           (opacity のようにフィードバック発散を防ぎたい残留率パラメータ用)。
    wrap:  周期 w を渡すと合成後の式全体を (...) % w で折り返す(色相のような
           周期パラメータ用)。hsv1.hueoffset は TD 側で [-360,360] にクランプされる
           ため、absTime ベースの単調増加をそのまま渡すと1分で 360 に張り付く。
    同じ tag を再登録すると項は上書きされる(＝冪等・再実行安全)。
    """
    reg = _registry(parent)
    key = node + '.' + par
    entry = reg.get(key) or {'base': None, 'terms': {}, 'clamp': None, 'wrap': None}

    if base is not None:
        entry['base'] = base if isinstance(base, str) else repr(base)
    elif entry['base'] is None:
        cur = getattr(parent.op(node).par, par)
        entry['base'] = cur.expr or repr(cur.eval())

    if clamp is not None:
        entry['clamp'] = [clamp[0], clamp[1]]
    if wrap is not None:
        entry['wrap'] = wrap

    entry['terms'][tag] = term          # 同 tag は上書き＝冪等
    reg[key] = entry
    _save(parent, reg)
    _compose(parent, node, par, entry)
    return entry


def remove_term(parent, node, par, tag):
    """登録済みの項を1つ外して再合成する(ライブでレイヤを消したいとき用)。"""
    reg = _registry(parent)
    key = node + '.' + par
    entry = reg.get(key)
    if not entry or tag not in entry['terms']:
        return
    del entry['terms'][tag]
    reg[key] = entry
    _save(parent, reg)
    _compose(parent, node, par, entry)


def _compose(parent, node, par, entry):
    """base + Σterms を組み立て、必要なら wrap → clamp の順に巻いて .expr へ1回だけ書く。"""
    expr = entry.get('base') or '0'
    for term in entry['terms'].values():
        expr = '(' + expr + ') + (' + term + ')'
    w = entry.get('wrap')
    if w:
        expr = '(' + expr + ') % ' + repr(w)
    c = entry.get('clamp')
    if c:
        expr = 'tdu.clamp(' + expr + ', ' + repr(c[0]) + ', ' + repr(c[1]) + ')'
    getattr(parent.op(node).par, par).expr = expr


def dump(parent):
    """登録簿を返す(デバッグ用)。textport で pbus.dump(op('/project1')) と打つ。"""
    return _registry(parent)
