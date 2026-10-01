"""Legacy-compatible chat API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/chat/send": ("POST", service.chat),
        "/chat/new_session": ("GET", service.new_session),
        "/chat/sessions": ("GET", service.get_sessions),
        "/chat/get_session": ("GET", service.get_session),
        "/chat/stop": ("POST", service.stop_session),
        "/chat/delete_session": ("GET", service.delete_webchat_session),
        "/chat/batch_delete_sessions": ("POST", service.batch_delete_sessions),
        "/chat/update_session_display_name": (
            "POST",
            service.update_session_display_name,
        ),
        "/chat/message/edit": ("POST", service.update_message),
        "/chat/message/regenerate": ("POST", service.regenerate_message),
        "/chat/thread/create": ("POST", service.create_thread),
        "/chat/thread/get": ("GET", service.get_thread),
        "/chat/thread/send": ("POST", service.send_thread_message),
        "/chat/thread/delete": ("POST", service.delete_thread),
        "/chat/get_file": ("GET", service.get_file),
        "/chat/get_attachment": ("GET", service.get_attachment),
        "/chat/post_file": ("POST", service.post_file),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
