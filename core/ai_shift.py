from __future__ import annotations

"""
AI helper for generating shift packets.

This module defines a single entry point `generate_shift_packet_ai_summary`
which takes structured incident context and returns a dict with:
    - input_summary
    - what_changed
    - why_it_matters
    - decision: { summary, decision_maker, decision_time }

The actual LLM / AI call is intentionally left as a placeholder so that
you can plug in your provider of choice (OpenAI, Azure OpenAI, etc.).
"""

from dataclasses import dataclass
import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any

from django.utils import timezone

from .models import Incident, ShiftPacket, SituationUpdate

try:
    # OpenAI Python SDK v1.x
    from openai import OpenAI  # type: ignore

    _openai_client: OpenAI | None = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:
    _openai_client = None


@dataclass
class IncidentContext:
    incident: Incident
    last_packet: Optional[ShiftPacket]
    situation_updates: List[SituationUpdate]


def _build_prompt_payload(ctx: IncidentContext) -> Dict[str, Any]:
    """
    Build a structured payload that can be serialized and sent to an AI provider.
    This keeps the core logic testable without depending on a specific API.
    """
    incident = ctx.incident
    last_packet = ctx.last_packet

    situation_payload = []
    for su in ctx.situation_updates:
        situation_payload.append(
            {
                "id": su.id,
                "time": su.update_time.isoformat(),
                "title": su.title,
                "description": su.description,
                "severity_change": su.severity_change,
                "status_change": su.status_change,
                "actions_taken": su.actions_taken,
                "resources_deployed": su.resources_deployed,
                "next_steps": su.next_steps,
                "department": su.department,
            }
        )

    payload: Dict[str, Any] = {
        "incident": {
            "id": incident.id,
            "title": incident.title,
            "severity": incident.severity,
            "status": incident.status,
            "description": incident.description,
            "impact": incident.impact,
            "next_action": incident.next_action,
            "created_at": incident.timestamp.isoformat(),
        },
        "last_shift_packet": None,
        "situation_updates_since_last_packet": situation_payload,
    }

    if last_packet is not None:
        payload["last_shift_packet"] = {
            "generated_at": last_packet.generated_at.isoformat(),
            "executive_summary": last_packet.executive_summary,
            "what_happened": last_packet.what_happened,
            "next_steps": last_packet.next_steps,
        }

    return payload


def _call_ai_provider(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call the configured AI provider (OpenAI) and return a structured result.

    The function MUST return a dict with the following structure:

    {
        "input_summary": "...",
        "what_changed": "...",
        "why_it_matters": "...",
        "decision": {
            "summary": "...",
            "decision_maker": "...",
            "decision_time": "2026-03-12T10:15:00Z"  # or null
        }
    }
    """
    # If OpenAI client is not available or API key missing, fall back to a simple stub
    if _openai_client is None or not os.getenv("OPENAI_API_KEY"):
        incident_title = payload["incident"]["title"]
        updates_count = len(payload["situation_updates_since_last_packet"])

        input_summary = (
            f'Incident "{incident_title}" with {updates_count} new situation '
            f"update{'s' if updates_count != 1 else ''} since the last shift packet."
        )

        what_changed = (
            "New situation updates have been recorded. Review detailed logs for full context."
            if updates_count
            else "No new situation updates since the last shift packet."
        )

        why_it_matters = (
            "These updates may impact operational priorities, staffing, and stakeholder communications. "
            "They should be reviewed by the duty officer for potential escalation or de-escalation."
        )

        decision = {
            "summary": "No explicit decision identified from incoming data.",
            "decision_maker": "Unknown",
            "decision_time": None,
        }

        return {
            "input_summary": input_summary,
            "what_changed": what_changed,
            "why_it_matters": why_it_matters,
            "decision": decision,
        }

    incident = payload["incident"]
    last_packet = payload.get("last_shift_packet")
    updates = payload.get("situation_updates_since_last_packet", [])

    # Build a compact but explicit prompt for the model
    prompt_parts = [
        "You are an operations shift lead. Analyze the incident and updates.",
        "",
        "INCIDENT:",
        f"- ID: {incident.get('id')}",
        f"- Title: {incident.get('title')}",
        f"- Severity: {incident.get('severity')}",
        f"- Status: {incident.get('status')}",
        f"- Description: {incident.get('description')}",
        f"- Impact: {incident.get('impact')}",
        f"- Next action: {incident.get('next_action')}",
        f"- Created at: {incident.get('created_at')}",
        "",
    ]

    if last_packet:
        prompt_parts.extend(
            [
                "LAST SHIFT PACKET:",
                f"- Generated at: {last_packet.get('generated_at')}",
                f"- Executive summary: {last_packet.get('executive_summary')}",
                f"- What happened: {last_packet.get('what_happened')}",
                f"- Next steps: {last_packet.get('next_steps')}",
                "",
            ]
        )

    prompt_parts.append("SITUATION UPDATES SINCE LAST PACKET:")
    if not updates:
        prompt_parts.append("- None.")
    else:
        for su in updates:
            prompt_parts.append(
                f"- [{su.get('time')}] {su.get('title')}: {su.get('description')} "
                f"(severity_change={su.get('severity_change')}, status_change={su.get('status_change')}, "
                f"actions_taken={su.get('actions_taken')}, next_steps={su.get('next_steps')})"
            )

    prompt_parts.append(
        """
Return ONLY a JSON object with this exact structure:
{
  "input_summary": "...",
  "what_changed": "...",
  "why_it_matters": "...",
  "decision": {
    "summary": "...",
    "decision_maker": "...",
    "decision_time": "2026-03-12T10:15:00Z or null"
  }
}
Make the summaries concise and operational, not verbose.
""".strip()
    )

    prompt = "\n".join(prompt_parts)

    response = _openai_client.chat.completions.create(  # type: ignore[union-attr]
        model=os.getenv("OPENAI_MODEL_NAME", "gpt-4.1-mini"),
        messages=[
            {
                "role": "system",
                "content": "You generate concise, structured shift handoff summaries for emergency operations.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    content = response.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # If the model returns invalid JSON, fall back to a minimal structure
        data = {
            "input_summary": "",
            "what_changed": "",
            "why_it_matters": "",
            "decision": {
                "summary": "",
                "decision_maker": "",
                "decision_time": None,
            },
        }

    return {
        "input_summary": data.get("input_summary", ""),
        "what_changed": data.get("what_changed", ""),
        "why_it_matters": data.get("why_it_matters", ""),
        "decision": data.get("decision") or {
            "summary": "",
            "decision_maker": "",
            "decision_time": None,
        },
    }


def generate_shift_packet_ai_summary(ctx: IncidentContext) -> Dict[str, Any]:
    """
    Public entry point used by scheduler/views.

    Builds the prompt payload, calls the AI provider, and normalizes
    the result into a consistent dict with keys:
    - input_summary
    - what_changed
    - why_it_matters
    - decision_summary
    - decision_maker
    - decision_time (as datetime or None)
    """
    payload = _build_prompt_payload(ctx)
    raw = _call_ai_provider(payload)

    decision_block = raw.get("decision") or {}
    decision_time_raw = decision_block.get("decision_time")
    decision_time_dt: Optional[datetime] = None
    if isinstance(decision_time_raw, str):
        try:
            decision_time_dt = datetime.fromisoformat(decision_time_raw)
            if timezone.is_naive(decision_time_dt):
                decision_time_dt = timezone.make_aware(decision_time_dt, timezone.utc)
        except Exception:
            decision_time_dt = None

    return {
        "input_summary": raw.get("input_summary", "") or "",
        "what_changed": raw.get("what_changed", "") or "",
        "why_it_matters": raw.get("why_it_matters", "") or "",
        "decision_summary": decision_block.get("summary", "") or "",
        "decision_maker": decision_block.get("decision_maker", "") or "",
        "decision_time": decision_time_dt,
    }

