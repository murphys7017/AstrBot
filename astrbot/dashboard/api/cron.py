"""Legacy-compatible cron API routing."""


def register_legacy_routes(app, service):
    routes = [
        ("/cron/jobs", ("GET", service.list_jobs)),
        ("/cron/jobs", ("POST", service.create_job)),
        ("/cron/jobs/<job_id>", ("PATCH", service.update_job)),
        ("/cron/jobs/<job_id>", ("DELETE", service.delete_job)),
        ("/cron/jobs/<job_id>/run", ("POST", service.run_job_now)),
    ]

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
