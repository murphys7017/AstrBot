"""Legacy-compatible static_file API routing."""


def register_legacy_routes(app, service):
    index_ = [
        "/",
        "/auth/login",
        "/auth/setup",
        "/config",
        "/logs",
        "/extension",
        "/dashboard/default",
        "/alkaid",
        "/alkaid/knowledge-base",
        "/alkaid/long-term-memory",
        "/alkaid/other",
        "/console",
        "/chat",
        "/settings",
        "/platforms",
        "/providers",
        "/about",
        "/extension-marketplace",
        "/conversation",
        "/tool-use",
    ]

    for i in index_:
        app.add_url_rule(i, view_func=service.index)

    @app.errorhandler(404)
    async def page_not_found(e) -> str:
        return "404 Not found。如果你初次使用打开面板发现 404, 请参考文档: https://docs.astrbot.app/faq.html。如果你正在测试回调地址可达性，显示这段文字说明测试成功了。"
