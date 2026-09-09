# FastAPI 路由注册顺序回归测试
#
# Starlette 按注册顺序做首个 path-regex 匹配，不做类型回退。
# 曾经的 bug：静态路由（如 DELETE /tags/unbind、GET /training-data-evals/templates）
# 注册在 /{uuid} 动态路由之后，静态路径被动态路由抢先匹配，"unbind"/"templates"
# 解析成 UUID 失败 → 恒 422，对应功能整体失效。
import pytest
from fastapi.routing import APIRoute

from app.api.v1 import api_router


def _method_paths(routes, method):
    """返回 (method, path) 列表，保持注册顺序"""
    out = []
    for r in routes:
        if isinstance(r, APIRoute) and method in r.methods:
            out.append(r.path)
    return out


@pytest.mark.parametrize("prefix,method,static,dynamic", [
    ("/tags", "DELETE", "/unbind", "/{tag_id}"),
    ("/training-data-evals", "GET", "/templates", "/{eval_id}"),
    ("/training-data-evals", "GET", "/quality-rules", "/{eval_id}"),
    ("/training-data-evals", "GET", "/metrics/available", "/{eval_id}"),
])
def test_static_route_before_dynamic(prefix, method, static, dynamic):
    routes = api_router.routes
    paths = []
    for r in routes:
        if isinstance(r, APIRoute) and r.path.startswith(prefix):
            if method in r.methods:
                paths.append(r.path[len(prefix):] or "/")
    assert static in paths, f"{method} {prefix}{static} 未注册"
    assert dynamic in paths, f"{method} {prefix}{dynamic} 未注册"
    assert paths.index(static) < paths.index(dynamic), \
        f"{static} 必须在 {dynamic} 之前注册，否则被 UUID 动态路由遮蔽恒 422"
