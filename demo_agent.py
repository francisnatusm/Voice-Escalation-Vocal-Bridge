#!/usr/bin/env python3
"""
demo_agent.py — Voice AI Builder Challenge demo script.

Simulates a deployment agent that discovers no rollback plan and escalates
to the developer via a Vocal Bridge web session for a voice decision.

On mobile, use the Vocal Bridge dashboard (HTTPS) to call Nate — a local HTTP
join page cannot access the microphone on phones.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

VOCAL_BRIDGE_BASE_URL = "https://vocalbridgeai.com"
TOKEN_ENDPOINT = f"{VOCAL_BRIDGE_BASE_URL}/api/v1/token"
LOGS_ENDPOINT = f"{VOCAL_BRIDGE_BASE_URL}/api/v1/logs"
DASHBOARD_URL = f"{VOCAL_BRIDGE_BASE_URL}/app/dashboard"
RESPONSE_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 1.5


def parse_decision(text: str) -> str | None:
    """Map spoken choice to option_1 or option_2 — say one or two on the call."""
    normalized = text.lower().strip()
    words = set(normalized.split())

    if words & {"one", "1", "first"} or "option 1" in normalized or "option one" in normalized:
        return "option_1"
    if words & {"two", "2", "second"} or "option 2" in normalized or "option two" in normalized:
        return "option_2"
    return None


def request_session_token(api_key: str, agent_id: str | None = None) -> dict:
    """Request a LiveKit web session token from the Vocal Bridge REST API."""
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    if agent_id:
        headers["X-Agent-Id"] = agent_id

    response = requests.post(
        TOKEN_ENDPOINT,
        headers=headers,
        json={"participant_name": "Natus"},
        timeout=30,
    )

    if not response.ok:
        detail = response.text.strip()
        try:
            detail = response.json().get("detail", detail)
        except ValueError:
            pass
        raise requests.HTTPError(
            f"{response.status_code} {response.reason}: {detail}",
            response=response,
        )

    return response.json()


def api_headers(api_key: str, agent_id: str | None) -> dict[str, str]:
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    if agent_id:
        headers["X-Agent-Id"] = agent_id
    return headers


def parse_started_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_dashboard_session(room_name: str | None) -> bool:
    return "-test-" in (room_name or "")


def fetch_session_transcript(
    api_key: str,
    agent_id: str | None,
    session_id: str,
) -> list[dict]:
    response = requests.get(
        f"{LOGS_ENDPOINT}/{session_id}",
        headers=api_headers(api_key, agent_id),
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("transcript") or []


def extract_user_text(transcript: list[dict]) -> list[str]:
    texts: list[str] = []
    for item in transcript:
        if item.get("role") != "user":
            continue
        text = str(item.get("content", "")).strip()
        if text:
            texts.append(text)
    return texts


async def wait_for_voice_decision(
    api_key: str,
    agent_id: str | None,
    since: datetime,
) -> str:
    """
    Poll Vocal Bridge logs for a dashboard web call started after escalation.

    Returns one of: 'option_1', 'option_2', 'timeout', or 'unclear'.
    """
    headers = api_headers(api_key, agent_id)
    deadline = time.time() + RESPONSE_TIMEOUT_SECONDS
    seen_user_text: list[str] = []

    while time.time() < deadline:
        try:
            response = await asyncio.to_thread(
                requests.get,
                LOGS_ENDPOINT,
                headers=headers,
                params={"limit": 20},
                timeout=15,
            )
            response.raise_for_status()
            sessions = response.json().get("sessions") or []

            candidates = []
            for summary in sessions:
                started_at = summary.get("started_at")
                if not started_at:
                    continue
                if parse_started_at(started_at) < since:
                    continue
                if summary.get("call_direction") != "web":
                    continue
                candidates.append(summary)

            candidates.sort(
                key=lambda summary: (
                    is_dashboard_session(summary.get("room_name")),
                    summary.get("started_at", ""),
                ),
                reverse=True,
            )

            for summary in candidates:
                session_id = summary.get("id")
                if not session_id:
                    continue

                transcript = await asyncio.to_thread(
                    fetch_session_transcript,
                    api_key,
                    agent_id,
                    session_id,
                )
                user_texts = extract_user_text(transcript)
                if not user_texts:
                    continue

                for text in user_texts:
                    if text in seen_user_text:
                        continue
                    seen_user_text.append(text)
                    decision = parse_decision(" ".join(seen_user_text))
                    if decision:
                        return decision
        except requests.RequestException:
            pass

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    if seen_user_text:
        return "unclear"
    return "timeout"


def main() -> None:
    load_dotenv()
    escalation_started = datetime.now(timezone.utc)

    print("[Agent] Starting pre-deployment checks...")
    print("[Agent] Checking rollback configuration...")
    time.sleep(2)
    print("[Agent] ⚠ WARNING: No rollback plan configured for this deployment.")
    print("[Agent] This action is irreversible. Human decision required.")
    print("[Agent] Initiating voice escalation via Vocal Bridge...")

    api_key = os.getenv("VOCAL_BRIDGE_API_KEY")
    if not api_key:
        print("[Agent] ERROR: VOCAL_BRIDGE_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)

    agent_id = os.getenv("VOCAL_BRIDGE_AGENT_ID")

    try:
        session = request_session_token(api_key, agent_id)
    except requests.RequestException as exc:
        print(f"[Agent] ERROR: Failed to create Vocal Bridge session: {exc}")
        sys.exit(1)

    room_name = session.get("room_name")
    if not room_name:
        print("[Agent] ERROR: Vocal Bridge returned an incomplete session response.")
        sys.exit(1)

    print(f"[Agent] Escalation registered. Room: {room_name}")
    print("[Agent] 📞 Web call session started.")
    print(f"[Agent] On your phone, open: {DASHBOARD_URL}")
    print("[Agent] Tap Nate → Start call.")
    print("[Agent] Listen to the options Nate presents, then say one or two.")
    print("[Agent] Waiting for your voice decision...")

    try:
        outcome = asyncio.run(
            wait_for_voice_decision(api_key, agent_id, escalation_started)
        )
    except Exception as exc:
        print(f"[Agent] ERROR: Voice session failed: {exc}")
        sys.exit(1)

    if outcome == "option_1":
        print("[Agent] ✅ Option 1 selected — halting as instructed.")
        sys.exit(0)

    if outcome == "option_2":
        print("[Agent] ✅ Option 2 selected — resuming as instructed.")
        sys.exit(0)

    if outcome == "timeout":
        print("[Agent] ⏱ No response received. Deployment halted for safety.")
        sys.exit(1)

    print("[Agent] ❓ Response unclear. Deployment halted. Awaiting manual review.")
    sys.exit(1)


if __name__ == "__main__":
    main()
