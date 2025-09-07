from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_loader = FileSystemLoader(str(Path(__file__).parent / "templates"))
env = Environment(loader=_loader, autoescape=select_autoescape(["html"]))
render = env.get_template  # render("confirm.html").render(ctx)
