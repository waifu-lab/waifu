class Feature:
    """IncomingRequest.features 的已知旗標"""

    LIVE2D = "live2d"  # 前端可呈現情緒 / 播放音訊
    LIPSYNC = "lipsync"  # 前端需要後端計算 viseme（模型無原生 lipsync）


class SessionMeta:
    """Session.metadata 的已知 key"""

    LIVE2D_EXPRESSIONS = "live2d_expressions"  # 前端 live2dsync 回報的可用表情列表


class RequestMeta:
    """IncomingRequest.metadata 的已知 key"""

    SKIP_AUTO_TITLE = "skip_auto_title"  # True 時不自動產生對話標題
