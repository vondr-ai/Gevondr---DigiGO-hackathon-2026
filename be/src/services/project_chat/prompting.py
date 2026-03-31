from __future__ import annotations

from pathlib import Path

from jinja2 import Environment
from jinja2 import FileSystemLoader
from jinja2 import StrictUndefined


PROMPTS_DIR = Path(__file__).with_name("prompts")


def render_project_chat_system_prompt(
    *,
    project_name: str,
    project_description: str | None,
    actor_type: str,
    resolved_role: str | None,
    selected_norms: list[str],
) -> str:
    environment = Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = environment.get_template("project_chat_system.jinja")
    return template.render(
        project_name=project_name,
        project_description=project_description,
        actor_type=actor_type,
        resolved_role=resolved_role,
        selected_norms=selected_norms,
    ).strip()
