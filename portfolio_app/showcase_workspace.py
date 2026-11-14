"""Model descriptions and published aggregate historical results."""
from portfolio_app.project_dossier_view import render_project_dossiers


def render_showcase_workspace(root, *, language="zh", mode="local"):
    return render_project_dossiers(root, language=language, local_results=True)
