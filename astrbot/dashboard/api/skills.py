"""Legacy-compatible skills API routing."""


def register_legacy_routes(app, service):
    routes = {
        "/skills": ("GET", service.get_skills),
        "/skills/upload": ("POST", service.upload_skill),
        "/skills/batch-upload": ("POST", service.batch_upload_skills),
        "/skills/download": ("GET", service.download_skill),
        "/skills/files": ("GET", service.list_skill_files),
        "/skills/file": [
            ("GET", service.get_skill_file),
            ("POST", service.update_skill_file),
        ],
        "/skills/update": ("POST", service.update_skill),
        "/skills/delete": ("POST", service.delete_skill),
        "/skills/neo/candidates": ("GET", service.get_neo_candidates),
        "/skills/neo/releases": ("GET", service.get_neo_releases),
        "/skills/neo/payload": ("GET", service.get_neo_payload),
        "/skills/neo/evaluate": ("POST", service.evaluate_neo_candidate),
        "/skills/neo/promote": ("POST", service.promote_neo_candidate),
        "/skills/neo/rollback": ("POST", service.rollback_neo_release),
        "/skills/neo/sync": ("POST", service.sync_neo_release),
        "/skills/neo/delete-candidate": ("POST", service.delete_neo_candidate),
        "/skills/neo/delete-release": ("POST", service.delete_neo_release),
    }

    for path, definition in routes.items() if isinstance(routes, dict) else routes:
        definitions = definition if isinstance(definition, list) else [definition]
        for method, handler in definitions:
            app.add_url_rule("/api" + path, view_func=handler, methods=[method])
