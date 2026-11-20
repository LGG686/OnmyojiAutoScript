# This Python file uses the following encoding: utf-8
"""局域网访问口令校验（可选，默认关闭）。

OAS 自身没有鉴权：`--key` 只被解析、从未参与校验，所以 WebUI 一旦绑到 0.0.0.0，同网段的
任何人都能启停脚本、改写配置。App 侧「局域网控制」开关只决定监听地址，口令默认留空——空值
下本中间件直接放行，OASX 这类既没有口令输入位置、也不带自定义请求头的客户端才连得上。

需要口令时在部署设置页给 `Password` 填值，此后非回环来源必须带上同一个值：请求头
`X-OAS-Token`、查询参数 `token` 或 Cookie `token` 任一命中即可。浏览器用 `?token=` 打开
一次后会被种下同名 Cookie，页面里的后续请求才带得上。回环来源始终放行——Android App 就
运行在被控设备上。

LAN access guard for OAS (opt-in, off by default). OAS has no authentication of its own
(`--key` is parsed and never checked), so a WebUI bound to 0.0.0.0 lets anyone on the subnet
start/stop the script and rewrite configs. The app's LAN switch only picks the listen address;
the password stays empty by default, and this middleware then passes every client through —
which is what LAN clients such as OASX need, since they neither ask for a token nor send
custom headers. Filling `Password` in the deploy settings page turns it on: non-loopback
callers must present the same value via the `X-OAS-Token` header, the `token` query parameter
or a `token` cookie. Opening the page once with `?token=` sets that cookie so the page's own
requests carry it. Loopback callers are always allowed — the Android app runs on the device.
"""
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

LOOPBACK_HOSTS = frozenset({'127.0.0.1', '::1', '::ffff:127.0.0.1'})
TOKEN_HEADER = b'x-oas-token'
TOKEN_FIELD = 'token'


def _header_token(scope: dict) -> str:
    """请求头里的口令；没带则为空串。"""
    for name, value in scope.get('headers') or []:
        if name.lower() == TOKEN_HEADER:
            return value.decode('latin-1')
    return ''


def _query_token(scope: dict) -> str:
    """查询串里的口令；SSE 与 WebSocket 也走同一条路径。"""
    query = parse_qs((scope.get('query_string') or b'').decode('latin-1'))
    values = query.get(TOKEN_FIELD)
    return values[0] if values else ''


def _cookie_token(scope: dict) -> str:
    """Cookie 里的口令；浏览器带 `?token=` 打开过一次后靠它维持会话。"""
    for name, value in scope.get('headers') or []:
        if name.lower() != b'cookie':
            continue
        jar = SimpleCookie()
        try:
            jar.load(value.decode('latin-1'))
        except Exception:
            continue
        morsel = jar.get(TOKEN_FIELD)
        if morsel is not None:
            return morsel.value
    return ''


def _set_cookie(password: str) -> bytes:
    jar = SimpleCookie()
    jar[TOKEN_FIELD] = password
    jar[TOKEN_FIELD]['path'] = '/'
    jar[TOKEN_FIELD]['httponly'] = True
    jar[TOKEN_FIELD]['samesite'] = 'Lax'
    return jar[TOKEN_FIELD].OutputString().encode('latin-1')


def _cookie_sender(send, password: str):
    """包一层 send，在响应头里补 Set-Cookie；不改动 body 与流式语义。"""
    header = _set_cookie(password)

    async def wrapped(message):
        if message['type'] == 'http.response.start':
            message = {**message, 'headers': list(message.get('headers') or []) + [(b'set-cookie', header)]}
        await send(message)

    return wrapped


class LanAuthMiddleware:
    """纯 ASGI 中间件：不包裹响应，SSE 与 WebSocket 的流式语义保持不变。"""

    def __init__(self, app, password: str | None = None):
        self.app = app
        self.password = (password or '').strip() or None

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket') or self.password is None:
            return await self.app(scope, receive, send)
        client = scope.get('client') or ('', 0)
        if client[0] in LOOPBACK_HOSTS:
            return await self.app(scope, receive, send)
        if _header_token(scope) == self.password or _cookie_token(scope) == self.password:
            return await self.app(scope, receive, send)
        if scope['type'] == 'http' and _query_token(scope) == self.password:
            # 浏览器首次用 ?token= 进入：顺手种 Cookie，页面里的相对请求才带得上
            return await self.app(scope, receive, _cookie_sender(send, self.password))
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
