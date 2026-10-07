"""The emails of the dashboard sign-in: a code, an invitation, a note to the super admins.

Wording lives here and nowhere else. Every name that comes from outside is escaped before it goes
into the HTML part."""

from html import escape

from app.services.mailer import send_email

BRAND = "OrchestrAI"

_PURPOSE = {
    "signup": ("Your sign-up code", "You asked to sign up for the dashboard."),
    "reset": ("Your password reset code", "You asked to choose a new password."),
}


def _page(title: str, body_html: str) -> str:
    return (
        '<div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;color:#1a1a2e;">'
        f'<h2 style="margin:0 0 12px;">{escape(title)}</h2>{body_html}'
        '<hr style="margin:20px 0;border:none;border-top:1px solid #eee;">'
        f'<p style="color:#888;font-size:12px;">{escape(BRAND)}</p></div>'
    )


async def send_code(
    to_email: str, name: str, purpose: str, code: str, minutes: int
) -> bool:
    title, why = _PURPOSE[purpose]
    text = (
        f"Hi {name},\n\n{why}\n\nYour code is {code}\n\n"
        f"It works for {minutes} minutes and only once. If this was not you, ignore this "
        "email and do not share the code with anyone."
    )
    html = _page(
        title,
        f"<p>Hi {escape(name)},</p><p>{escape(why)}</p>"
        '<div style="font-size:34px;font-weight:bold;letter-spacing:10px;text-align:center;'
        'padding:14px;background:#f0f0ff;border-radius:8px;color:#4a00e0;margin:16px 0;">'
        f"{escape(code)}</div>"
        f"<p>It works for {minutes} minutes and only once. If this was not you, ignore "
        "this email and do not share the code with anyone.</p>",
    )
    return await send_email(to_email, name, f"{BRAND}: {title.lower()}", text, html)


async def send_invite(to_email: str, name: str, who: str, where: str, url: str) -> bool:
    text = (
        f"Hi {name},\n\n{who} has given you access to the {where} dashboard.\n\n"
        f"Open {url} and choose Sign up. Use this email address; we will send you a code "
        "and you choose your own password."
    )
    html = _page(
        f"You can now sign in to {where}",
        f"<p>Hi {escape(name)},</p><p>{escape(who)} has given you access to the "
        f"<b>{escape(where)}</b> dashboard.</p>"
        f'<p><a href="{escape(url, quote=True)}">Open the dashboard</a> and choose '
        "<b>Sign up</b>. Use this email address; we will send you a code and you choose "
        "your own password.</p>",
    )
    return await send_email(
        to_email, name, f"{BRAND}: you can sign in to {where}", text, html
    )


async def send_already_signed_up(to_email: str, name: str) -> bool:
    text = (
        f"Hi {name},\n\nSomeone, hopefully you, tried to sign up with this address, but you "
        "already have an account. Sign in with your password, or choose Forgot password if "
        "you do not remember it."
    )
    html = _page(
        "You already have an account",
        f"<p>Hi {escape(name)},</p><p>Someone, hopefully you, tried to sign up with this "
        "address, but you already have an account. Sign in with your password, or choose "
        "<b>Forgot password</b> if you do not remember it.</p>",
    )
    return await send_email(
        to_email, name, f"{BRAND}: you already have an account", text, html
    )


async def send_request(
    to_email: str, to_name: str, who: str, where: str, message: str
) -> bool:
    text = f"{who} ({where}) asks:\n\n{message}\n\nOpen the super admin page to deal with it."
    html = _page(
        f"{who} asks for your help",
        f"<p><b>{escape(who)}</b> at <b>{escape(where)}</b> wrote:</p>"
        '<blockquote style="margin:12px 0;padding:8px 14px;border-left:3px solid #4a00e0;'
        f'background:#f6f6ff;">{escape(message).replace(chr(10), "<br>")}</blockquote>',
    )
    return await send_email(
        to_email, to_name, f"{BRAND}: {who} asks for your help", text, html
    )
