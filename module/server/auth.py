# This Python file uses the following encoding: utf-8
"""局域网访问口令校验。

OAS 自身没有任何鉴权：`--key` 只被解析、从未参与校验，所以一旦 WebUI 绑到 0.0.0.0，
同网段的任何人都能直接启停脚本、改写配置。App 侧「局域网控制」开关把监听地址钉在回环或
全网卡上，这一层负责把口令真正生效：非回环来源必须带上 `config/deploy.yaml` 里的
`Password`（请求头 `X-OAS-Token`、查询参数 `token` 或同名 Cookie 任一命中即可）。

回环来源直接放行——Android App 通过 127.0.0.1 控制运行时，它本身就运行在被控设备上。

LAN access guard for OAS. OAS itself has no authentication (`--key` is parsed and never
checked), so binding the WebUI to 0.0.0.0 would let anyone on the same subnet start/stop
the script and rewrite configs. The app's LAN switch decides whether the host binds to
loopback or all interfaces; this layer makes the password real: non-loopback clients must
present `Password` from `config/deploy.yaml` in the `X-OAS-Token` header, the `token` query
parameter, or a cookie of the same name. Loopback callers are always allowed — the Android
app controls the runtime over 127.0.0.1 from the device itself.
"""
from urllib.parse import parse_qs

LOOPBACK_HOSTS = frozenset({'127.0.0.1', '::1', '::ffff:127.0.0.1'})
TOKEN_HEADER = b'x-oas-token'
TOKEN_FIELD = 'token'


def _supplied_token(scope: dict) -> str:
    """从请求头或查询串取口令；SSE 与 WebSocket 也走同一条路径。"""
    for name, value in scope.get('headers') or []:
        if name.lower() == TOKEN_HEADER:
            return value.decode('latin-1')
    query = parse_qs((scope.get('query_string') or b'').decode('latin-1'))
    values = query.get(TOKEN_FIELD)
    return values[0] if values else ''


class LanAuthMiddleware:
    """纯 ASGI 中间件：不包裹响应，SSE 与 WebSocket 的流式语义保持不变。"""

    def __init__(self, app, password: str | None = None):
        self.app = app
        self.password = (password or '').strip() or None

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket') or self.password is None:
            return await self.app(scope, receive, send)
        client = scope.get('client') or ('', 0)
        if client[0] in LOOPBACK_HOSTS or _supplied_token(scope) == self.password:
            return await self.app(scope, receive, send)
        if scope['type'] == 'websocket':
            # 1008 = policy violation；不先 accept 就已经是拒绝
            await send({'type': 'websocket.close', 'code': 1008})
            return
        body = b'{"message":"unauthorized: OAS WebUI password required"}'
        await send({
            'type': 'http.response.start',
            'status': 401,
            'headers': [(b'content-type', b'application/json; charset=utf-8'),
                        (b'content-length', str(len(body)).encode())],
        })
        await send({'type': 'http.response.body', 'body': body})
