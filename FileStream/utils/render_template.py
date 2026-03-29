import jinja2
import urllib.parse
from FileStream.config import Telegram, Server
from FileStream.utils.database import Database
from FileStream.utils.human_readable import humanbytes
db = Database(Telegram.DATABASE_URL, Telegram.SESSION_NAME)


def _render_template(template_name, **context):
    environment = jinja2.Environment(autoescape=True)
    with open(f"FileStream/template/{template_name}", encoding="utf-8") as file_handle:
        template = environment.from_string(file_handle.read())
    return template.render(**context)

async def render_page(db_id):
    file_data=await db.get_file(db_id)
    src = urllib.parse.urljoin(Server.URL, f'dl/{file_data["_id"]}')
    file_size = humanbytes(file_data['file_size'])
    file_name = file_data['file_name'].replace("_", " ")

    if str((file_data['mime_type']).split('/')[0].strip()) == 'video':
        template_file = "play.html"
    else:
        template_file = "dl.html"

    return _render_template(
        template_file,
        file_name=file_name,
        file_url=src,
        file_size=file_size
    )


def render_admin_login(error_message=None):
    return _render_template(
        "admin_login.html",
        error_message=error_message,
        site_url=Server.URL,
    )


def render_admin_dashboard(**context):
    return _render_template("admin_dashboard.html", **context)
