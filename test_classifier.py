"""
Test the 3-tier classifier without WhatsApp or DB.
Run with:  python test_classifier.py
"""
import asyncio
from app.classifier.classifier import classify_message

TEST_MESSAGES = [
    # Tier 1 — exact
    "hi",
    "help",
    "1",
    "retry",
    # Tier 2 — keyword regex
    "stock gold ring",
    "how many bangles do we have",
    "dues Mehta Jewellers",
    "outstanding Sharma",
    "invoice Kapoor 120000",
    "dues report",
    # Tier 3 — LLM fallback
    "aaj kitna maal bacha hai",
    "Mehta ne abhi tak payment nahi kiya",
    "Patel ka hisaab kya hai",
    "I need to bill someone for 2 lakh",
]


async def run():
    print("=" * 55)
    print("OrchestrAI — Classifier Test")
    print("=" * 55)
    for msg in TEST_MESSAGES:
        result = await classify_message(msg, org_name="ShreeJewels")
        tier  = result["tier"]
        icon  = "⚡" if tier == 1 else "🔍" if tier == 2 else "🤖"
        print(f"\n{icon} T{tier} | Input : {msg}")
        print(f"       Intent: {result['intent']} | Entity: {result.get('entity_raw')}")
    print("\n" + "=" * 55)


if __name__ == "__main__":
    asyncio.run(run())
