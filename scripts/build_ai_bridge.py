"""
build_ai_bridge.py
==================
organic-patterns の out1（油膜・大理石）を自作 StreamDiffusion サーバー
（streamdiffusion-ws, ws://localhost:8765）へ base64 JPEG で送り、AI 変換結果を
Script TOP `ai_out` に受けて表示する差分ビルド。さらに**音響エネルギーで
StreamDiffusion の t_index を変調**する（音が大きいほど AI の再解釈が強まる）。
これが本作品の核（moat）＝「音が AI の生成する絵そのものを動かす」。

前提:
  build_organic_patterns / build_audio_reactive を実行済み（out1, aud_lag が在る）。
  GPU 側で streamdiffusion-ws が起動し、Mac 側で SSH トンネル(8765)が通っていること。
  サーバーは --t-index 22 32（2要素）で起動している前提（TINDEX は要素数一致が必須）。
  ★重要（2026-09-11 S5で判明）: サーバーは **--guidance-scale 5 --cfg-type full** で
  起動すること。既定の guidance_scale=1.2 だとプロンプトが拡散に効かず出力が茶色い無地に
  潰れる。CFGを上げて初めてプロンプトが絵を支配し、油膜が虹色オイルスリックに変換される。
  推奨起動:
    CUDA_VISIBLE_DEVICES=1 python -u sd_ws_server.py --size 512 --acceleration xformers \
      --t-index 22 32 --guidance-scale 5 --cfg-type full \
      --prompt "iridescent oil slick, psychedelic marbled rainbow, liquid metal swirls, ornate detailed, vibrant saturated"

構成（hand-trail-ai の TD 側 3 点セットを移植し、送信ソースを out1 に差し替え）:
  websocket1(WebSocket DAT, client) ── callbacks → websocket1_callbacks1(Text DAT)
  ai_out(Script TOP) ── callbacks → ai_out_callbacks(Text DAT)   受信 JPEG をデコード表示
  ai_driver(Execute DAT)  毎フレーム out1 を force cook + 送信ドライバ（音響→TINDEX 変調）

再実行安全: 追加ノードは同名を削除してから作り直す。active は 0 で作るので、
ビルド後に別フレームで websocket1.par.active=1 して接続する
（WebSocket DAT の active は「接続状態」でなく有効フラグ。同一スクリプト内トグルは無効）。
"""

import td

PARENT = '/project1'
WS_ADDR = 'localhost'
WS_PORT = 8765

# --- WebSocket 送受信コールバック（in-flight ガード + 音響 TINDEX 送信） ---------
CALLBACKS_SRC = r'''
# WebSocket DAT (/project1/websocket1) コールバック
#   - out1 を base64 JPEG にして送信 (send_frame)
#   - in-flight ガード: 返信待ち中は送らない（サーバーを溢れさせない）
#   - send_tindex: 音響駆動の t_index をライブ送信（同じガード下）
#   - 受信 base64 JPEG を保持し Script TOP(ai_out) を再クック
#   - エンコードは cv2（TD の PIL は無関係 venv を掴んで dlopen 失敗するため）
import base64

SRC_TOP = '/project1/out1'
DST_TOP = '/project1/ai_out'
SIZE = 512

_latest_jpg_b64 = None
_inflight = False
_sent_at = 0.0
TIMEOUT = 3.0
_last_tindex = (22, 32)


def _encode(top, size=SIZE):
    import cv2
    import numpy as np
    a = top.numpyArray(delayed=False)                 # float32 RGBA 0..1, 左下原点
    rgb = (np.flipud(a)[:, :, :3] * 255).clip(0, 255).astype('uint8')
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    s = min(h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    bgr = bgr[y0:y0 + s, x0:x0 + s]
    if s != size:
        bgr = cv2.resize(bgr, (size, size))
    ok, enc = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(enc.tobytes()).decode('ascii')


def _guard_open():
    global _inflight
    now = absTime.seconds
    if _inflight:
        if now - _sent_at < TIMEOUT:
            return False
        debug('[ws] response timeout, releasing inflight')
        _inflight = False
    return True


def send_frame(dat):
    global _inflight, _sent_at
    if not _guard_open():
        return
    try:
        dat.sendText(_encode(op(SRC_TOP)))
        _inflight = True
        _sent_at = absTime.seconds
    except Exception as e:
        debug('send_frame err:', e)


def send_tindex(dat, a, b):
    global _inflight, _sent_at, _last_tindex
    if not _guard_open():
        return
    try:
        dat.sendText('TINDEX:%d,%d' % (a, b))
        _inflight = True
        _sent_at = absTime.seconds
        _last_tindex = (a, b)
    except Exception as e:
        debug('send_tindex err:', e)


def last_ta():
    return _last_tindex[0]


def onConnect(dat):
    global _inflight
    _inflight = False
    debug('[ws] connected', dat.par.netaddress.eval(), dat.par.port.eval())


def onDisconnect(dat):
    global _inflight
    _inflight = False
    debug('[ws] disconnected')


def onReceiveText(dat, rowIndex, message, *args):
    global _latest_jpg_b64, _inflight
    _inflight = False
    if message.startswith('OK:') or message.startswith('ERR:'):
        debug('[ws] server:', message)
        return
    _latest_jpg_b64 = message
    d = op(DST_TOP)
    if d is not None:
        d.cook(force=True)


def onReceiveBinary(dat, contents):
    return


def onReceivePing(dat, contents):
    dat.sendPong(contents)


def onReceivePong(dat, contents):
    return


def onMonitorMessage(dat, message):
    return
'''

# --- Script TOP ai_out: 受信 base64 JPEG を cv2 でデコードして出力 --------------
AI_OUT_SRC = r'''
import base64

CB_PATH = '/project1/websocket1_callbacks1'


def onCook(scriptOp):
    cb = op(CB_PATH)
    b64 = getattr(cb.module, '_latest_jpg_b64', None) if cb else None
    if not b64:
        import numpy as np
        scriptOp.copyNumpyArray(np.zeros((512, 512, 4), np.float32))
        return
    try:
        import cv2
        import numpy as np
        raw = base64.b64decode(b64)
        bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype('float32') / 255.0
        rgb = np.flipud(rgb)
        rgba = np.dstack([rgb, np.ones(rgb.shape[:2], 'float32')])
        scriptOp.copyNumpyArray(rgba)
    except Exception as e:
        debug('ai_out onCook err:', e)
'''

# --- Execute DAT ai_driver: 毎フレーム out1 を force cook + 送信（音響→TINDEX） --
DRIVER_SRC = r'''
# 1) 毎フレーム out1 を force cook（フィードバックループ=油膜の育ちを送信可否と独立に進める）
# 2) websocket1 が Active なら EVERY フレーム毎に 1 送信スロット。
#    音響エネルギー→t_index を算出し、有意変化かつ制御スロットなら TINDEX を、
#    それ以外は画像フレームを送る（1スロット1送信＝in-flightガードと衝突しない）。
WS = '/project1/websocket1'
CB = '/project1/websocket1_callbacks1'
SRC = '/project1/out1'
AUD = '/project1/aud_lag'
EVERY = 3          # 送信を試みる間隔（フレーム）。ガードがあるので小さくてよい
E_FULL = 0.03      # このエネルギーで最強変調（要チューニング。実測 aud_lag は 0.001〜0.02 帯）
# t_index レンジ（2026-09-11 S5で調整）: 無音=忠実寄り(20,30) → 大音量=強め(12,22)。
# guidance-scale 5 前提。10 以下まで下げると過剰変換になりやすいので 12 で止める。
TA_BASE, TA_MIN = 20, 12   # t_index[0]: 無音=20(忠実寄り) → 大音量=12(AI再解釈が強い)
TB_BASE, TB_MIN = 30, 22   # t_index[1]


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def onFrameStart(frame):
    src = op(SRC)
    if src is not None:
        src.cook(force=True)
    ws = op(WS)
    if ws is None or not ws.par.active.eval():
        return
    if frame % EVERY != 0:
        return
    cb = op(CB).module
    # 音響エネルギー（低0.5+中0.3+高0.6の加重）→ 0..1 正規化
    e = 0.0
    al = op(AUD)
    if al is not None:
        try:
            e = al['low'].eval() * 0.5 + al['mid'].eval() * 0.3 + al['high'].eval() * 0.6
        except Exception:
            e = 0.0
    n = _clamp(e / E_FULL, 0.0, 1.0)
    ta = int(round(TA_BASE - (TA_BASE - TA_MIN) * n))
    tb = int(round(TB_BASE - (TB_BASE - TB_MIN) * n))
    slot = frame // EVERY
    changed = abs(ta - cb.last_ta()) >= 2
    if changed and slot % 4 == 0:
        cb.send_tindex(ws, ta, tb)
    else:
        cb.send_frame(ws)


def onFrameEnd(frame):
    return


def onStart():
    return


def onCreate():
    return


def onExit():
    return
'''


def build_ai_bridge():
    p = op(PARENT)
    if p is None:
        raise RuntimeError(f'{PARENT} が見つかりません。')
    if p.op('out1') is None:
        raise RuntimeError('out1 が未構築です。先に build_organic_patterns.py を実行してください。')

    # 冪等: 既存を掃除
    for name in ('ai_driver', 'websocket1', 'websocket1_callbacks1', 'ai_out', 'ai_out_callbacks'):
        ex = p.op(name)
        if ex:
            ex.destroy()

    # コールバック Text DAT
    cb = p.create(td.textDAT, 'websocket1_callbacks1')
    cb.nodeX, cb.nodeY = -600, 200
    cb.text = CALLBACKS_SRC

    # WebSocket DAT（client）— active=0 で作成（後で別フレームに 1 して接続）
    ws = p.create(td.websocketDAT, 'websocket1')
    ws.nodeX, ws.nodeY = -420, 200
    for pn, pv in (('netaddress', WS_ADDR), ('port', WS_PORT), ('active', False)):
        if hasattr(ws.par, pn):
            getattr(ws.par, pn).val = pv
    # callbacks は OP 参照パラメータ。相対パス './...' は解決されず None になるため
    # 絶対パスで設定する（2026-09-11 実機で確認）。
    if hasattr(ws.par, 'callbacks'):
        ws.par.callbacks.val = PARENT + '/websocket1_callbacks1'

    # ai_out（Script TOP）+ その callbacks DAT
    aoc = p.create(td.textDAT, 'ai_out_callbacks')
    aoc.nodeX, aoc.nodeY = -600, 60
    aoc.text = AI_OUT_SRC
    ao = p.create(td.scriptTOP, 'ai_out')
    ao.nodeX, ao.nodeY = -420, 60
    if hasattr(ao.par, 'callbacks'):
        ao.par.callbacks.val = PARENT + '/ai_out_callbacks'

    # ai_driver（Execute DAT）
    drv = p.create(td.executeDAT, 'ai_driver')
    drv.nodeX, drv.nodeY = -420, 340
    drv.text = DRIVER_SRC
    for pn in ('active', 'framestart'):
        if hasattr(drv.par, pn):
            getattr(drv.par, pn).val = True

    print('[ai_bridge] build complete. '
          'Ensure GPU server + SSH tunnel(8765) are up, then set '
          "op('/project1/websocket1').par.active = 1 (別フレームで) to connect. "
          'View /project1/ai_out.')
    return dict(ws=ws, cb=cb, ai_out=ao, driver=drv)


if __name__ == '__main__':
    build_ai_bridge()
