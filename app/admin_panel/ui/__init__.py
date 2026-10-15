"""The admin panel's front end, kept as Python strings so it ships with the code (the repo's
ignore files exclude loose .html files) and is served by pages.py."""

import hashlib

from app.admin_panel.ui import (
    css,
    js_assistant,
    js_auth,
    js_boot,
    js_canvas,
    js_canvas_panels,
    js_core,
    js_flows,
    js_home,
    js_icons,
    js_menu,
    js_overview_cases,
    js_people,
    js_people_import,
    js_reminders,
    js_rest,
    js_roles,
    js_routing,
    js_settings,
    js_stepwin,
    js_studio,
    js_studio_form,
    js_super,
    js_usecases,
    js_whatsapp,
    js_whatsapp_builder,
    js_whatsapp_templates,
)

APP_CSS = css.CSS

# one closure, so every part can use the helpers defined in js_core
APP_JS = (
    "(() => {\n'use strict';\n"
    + "\n".join(
        part.JS
        for part in (
            js_core,
            js_icons,
            js_menu,
            js_overview_cases,
            js_people,
            js_people_import,
            js_roles,
            js_routing,
            js_reminders,
            js_usecases,
            js_studio_form,
            js_studio,
            js_canvas,
            js_canvas_panels,
            js_stepwin,
            js_flows,
            js_home,
            js_rest,
            js_settings,
            js_whatsapp_builder,
            js_whatsapp,
            js_whatsapp_templates,
            js_assistant,
            js_auth,
            js_super,
            js_boot,
        )
    )
    + "\n})();\n"
)

# changes whenever the code changes, so browsers fetch the new files after a deploy
VERSION = hashlib.sha1((APP_CSS + APP_JS).encode("utf-8")).hexdigest()[:10]
