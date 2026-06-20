"""
Run once to confirm Brevo key works:
    python test_brevo.py
"""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

BREVO_API_KEY = os.getenv("BREVO_API_KEY")


def test_brevo(to_email: str):
    payload = {
        "sender": {"name": "OrchestrAI Test", "email": "sales@aitamate.com"},
        "to": [{"email": "kartikbatchu2003@gmail.com", "name": "Test User"}],
        "subject": "🔐 OrchestrAI — Brevo Test",
        "htmlContent": """
        <div style="font-family:Arial,sans-serif;max-width:480px">
          <h2>✅ Brevo is connected!</h2>
          <p>Your OTP email setup is working correctly.</p>
          <div style="font-size:36px;font-weight:bold;letter-spacing:12px;
                      text-align:center;padding:16px;background:#f0f0ff;
                      border-radius:8px;color:#4a00e0;margin:16px 0;">
            7 4 2 9
          </div>
          <p style="color:#888;font-size:12px;">— OrchestrAI · ShreeJewels</p>
        </div>
        """
    }

    resp = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        json=payload,
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"}
    )

    if resp.status_code == 201:
        print(f"✅ Email sent to {to_email}")
    else:
        print(f"❌ Failed: {resp.status_code} — {resp.text}")


if __name__ == "__main__":
    test_brevo("YOUR_EMAIL_HERE")  # ← replace with your email
