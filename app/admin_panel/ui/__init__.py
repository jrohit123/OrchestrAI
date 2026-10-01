"""The admin panel's front end, kept as Python strings so it ships with the code (the repo's
ignore files exclude loose .html files) and is served by pages.py."""

import hashlib

from app.admin_panel.ui import (
    css,
    js_core,
    js_overview_cases,
    js_people,
    js_rest,
    js_routing,
    js_studio,
    js_studio_form,
)

APP_CSS = css.CSS

# one closure, so every part can use the helpers defined in js_core
APP_JS = (
    "(() => {\n'use strict';\n"
    + "\n".join(
        part.JS
        for part in (
            js_core,
            js_overview_cases,
            js_people,
            js_routing,
            js_studio_form,
            js_studio,
            js_rest,
        )
    )
    + "\n})();\n"
)

# changes whenever the code changes, so browsers fetch the new files after a deploy
VERSION = hashlib.sha1((APP_CSS + APP_JS).encode("utf-8")).hexdigest()[:10]
