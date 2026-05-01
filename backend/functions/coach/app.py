"""
Coach FastAPI app — streams Bedrock Claude responses with tool use.

Runs behind AWS Lambda Web Adapter. The adapter bridges a Function URL
configured with InvokeMode=RESPONSE_STREAM to this uvicorn server, so
FastAPI StreamingResponse chunks arrive at the browser as they're produced.

Tool loop:
  1. invoke_model_with_response_stream with tools defined
  2. stream text deltas straight to the client
  3. on stop_reason=tool_use: execute tool, append tool_result, re-invoke
  4. repeat until stop_reason != tool_use (typically "end_turn")
"""

import json
import logging
import os
from typing import Optional

import boto3
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from shared.coach_context import build_system_prompt
from shared.conversation_service import (
    resolve_thread,
    messages_for_bedrock,
    append_turn,
    maybe_summarize,
)
from shared.nutrition_service import (
    log_meal as svc_log_meal,
    log_water as svc_log_water,
    log_journal as svc_log_journal,
    log_workout as svc_log_workout,
    get_recent_meals as svc_get_recent_meals,
    delete_meal as svc_delete_meal,
    delete_water as svc_delete_water,
    delete_workout as svc_delete_workout,
)
from shared.workout_service import annotate_workout as svc_annotate_workout
from shared.workout_proposer import (
    propose_for_date as svc_propose_workout,
    write_proposal as svc_write_proposal,
    update_lateral_chain_phase as svc_update_lateral_chain_phase,
)
from shared.timezone import local_today_str

logger = logging.getLogger("coach")
logger.setLevel(logging.INFO)

bedrock = boto3.client("bedrock-runtime", region_name="us-west-2")
MODEL_ID = os.environ.get("COACH_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 6

app = FastAPI()
# CORS is handled by the Lambda Function URL's own Cors config — do not add
# a FastAPI CORSMiddleware here or browsers will see duplicate
# Access-Control-Allow-Origin headers and reject the response.


TOOLS = [
    {
        "name": "log_meal",
        "description": (
            "Estimate macros for a free-form meal description AND save it to today's "
            "nutrition log in one step. Use this any time Mateo mentions eating or "
            "drinking something. Captures calories, protein, carbs, fat, hydration "
            "(water_oz) for beverages, and caffeine (mg)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Free-form description of what was eaten, e.g. 'green tea', 'half chicken bake', 'oikos shake and a banana'.",
                }
            },
            "required": ["text"],
        },
    },
    {
        "name": "log_water",
        "description": (
            "Log plain water intake in ounces. Only use this when Mateo explicitly mentions water "
            "(not a beverage that contains water — for those use log_meal)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "oz": {
                    "type": "number",
                    "description": "Ounces of water consumed.",
                }
            },
            "required": ["oz"],
        },
    },
    {
        "name": "log_journal",
        "description": (
            "Capture Mateo's reflection and/or tag how he's feeling. Use when he mentions "
            "mood, stress, soreness, alcohol, sauna, back flare, or tells you how the day "
            "went. Morning = check-in about last night; evening (slot='evening') = day-end "
            "reflection. Slots write to separate fields on the same daily row — calling with "
            "slot='evening' will NOT clobber the morning entry. Prefer slot='evening' after "
            "6pm local when Mateo is recapping the day. If he writes a narrative, pass it as "
            "`text`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of tags. Optional — omit if the entry is narrative-only. "
                        "Behavior tags: alcohol, caffeine_late, ate_late, heavy_meal, "
                        "hydrated, screens_bed, late_bedtime, meditated, stretched, sauna, "
                        "cold, sunlight_am, stress, social, travel, sick, back_flare. "
                        "Supplement tags (use when Mateo mentions taking them today): "
                        "creatine, zinc, d3_k2, fish_oil, vitamin_c, l_theanine, rx, "
                        "5_htp, b_complex. 'rx' is Adderall — always use the generic "
                        "'rx' tag, never 'adderall'."
                    ),
                },
                "mood": {"type": "integer", "minimum": 1, "maximum": 5, "description": "1 (bad) - 5 (great)"},
                "stress": {"type": "integer", "minimum": 1, "maximum": 5, "description": "1 (none) - 5 (extreme)"},
                "soreness": {"type": "integer", "minimum": 1, "maximum": 5, "description": "1 (none) - 5 (very). Morning slot only."},
                "slot": {
                    "type": "string",
                    "enum": ["morning", "evening"],
                    "description": "Which slot this entry belongs to. Default 'morning'.",
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Free-form narrative, captured verbatim from what Mateo said. "
                        "Keep his voice; don't summarize into third person."
                    ),
                },
            },
        },
    },
    {
        "name": "get_recent_meals",
        "description": "Look up meals logged over the last N days. Use when you need context on what Mateo has eaten, or to find a meal_id you need to delete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 7,
                    "description": "How many days back to fetch. Default 1 (today).",
                }
            },
        },
    },
    {
        "name": "delete_meal",
        "description": (
            "Delete a previously-logged meal and its companion water row. "
            "Use ONLY to correct a mistake you (or Mateo) made — e.g. you logged the "
            "wrong item, or the user asked you to remove something. Call get_recent_meals "
            "first if you don't know the meal_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_id": {
                    "type": "string",
                    "description": "The meal_id to delete (e.g. 'meal_1777318094580').",
                },
            },
            "required": ["meal_id"],
        },
    },
    {
        "name": "delete_water",
        "description": (
            "Delete a previously-logged standalone water row. Use ONLY to correct a "
            "duplicate or wrong log_water call. get_recent_meals returns water rows "
            "with kind='water' and water_id — use that water_id here."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "water_id": {
                    "type": "string",
                    "description": "The water_id to delete (e.g. 'water_1777323846487').",
                },
            },
            "required": ["water_id"],
        },
    },
    {
        "name": "log_workout",
        "description": (
            "Estimate + log a free-form workout description. Use when Mateo says "
            "he finished training — e.g. 'just did push day 45 min', 'easy Z2 run', "
            "'mobility this morning'. Writes a manual workout row; Strava syncs "
            "still work independently."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Free-form workout description — what he did, how long, how hard.",
                }
            },
            "required": ["text"],
        },
    },
    {
        "name": "delete_workout",
        "description": (
            "Delete a previously-logged workout row. Use ONLY to correct a mistake — "
            "e.g. you logged a duplicate or the wrong type. get_recent_meals returns "
            "workout rows with kind='workout' and workout_id — use that workout_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workout_id": {
                    "type": "string",
                    "description": "The workout_id to delete (e.g. 'manual_1777318094580' or a numeric Strava id).",
                },
            },
            "required": ["workout_id"],
        },
    },
    {
        "name": "annotate_workout",
        "description": (
            "Attach detailed lift/cardio data (exercises, sets, reps, weight, supersets, session notes) "
            "to an EXISTING workout row for a given date. Use this when Mateo describes the lifts he "
            "did — e.g. 'bench 4x5 @ 205, OHP 3x8 @ 115, incline DB 3x10' or any free-form session "
            "notes. The parser handles progressive sets, ramps, supersets, and cardio circuits. "
            "If no workout exists for the date, one is created. Prefer this over log_workout when "
            "there's structured lift detail to capture; log_workout is for quick 'I did a 30 min run' "
            "cases with no lift breakdown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Free-form lift/cardio notes exactly as Mateo wrote them.",
                },
                "date": {
                    "type": "string",
                    "description": "Date YYYY-MM-DD. Defaults to today. Set if Mateo says 'yesterday's workout' or gives a specific date.",
                },
                "workout_id": {
                    "type": "string",
                    "description": "Optional. Target a specific workout row when the date has multiple sessions (e.g. Mateo did a Morning Workout AND a Lunch Walk). Use get_recent_meals first to find workout_ids — workout rows come back with kind='workout' and a workout_id field. If omitted, annotation lands on the most recent workout for the date.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "propose_workout",
        "description": (
            "Generate today's workout proposal (main workout type + the "
            "phase-appropriate Lateral Chain activation circuit). Use when "
            "Mateo asks 'what should I train?', 'what's the plan today?', "
            "or wants to refresh an existing proposal. Also writes the "
            "proposal so the Today card picks it up. No input required."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_lateral_chain_phase",
        "description": (
            "Update Mateo's current Lateral Chain Rebuild program phase "
            "(1=Activation, 2=Strength, 3=Power). Use when Mateo confirms "
            "he's advancing OR says he's already past the current phase — "
            "e.g. 'I can do bent-knee Copenhagens fine, bump me to phase 2'. "
            "Subsequent workout proposals will use the new phase's circuit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phase": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                    "description": "New phase (1, 2, or 3).",
                },
                "reason": {
                    "type": "string",
                    "description": "Short note on why — what Mateo said that confirmed the advance.",
                },
            },
            "required": ["phase"],
        },
    },
    {
        "name": "generate_weekly_summary",
        "description": (
            "Read the last 7 days of journal entries and daily scores and return a compact "
            "narrative summary Mateo can reflect on. Use when he asks 'how was this week', "
            "'what did I log this week', or on Sunday evenings when he's wrapping up. "
            "Returns structured data; inline the highlights in your reply."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _execute_tool(name: str, args: dict) -> dict:
    try:
        if name == "log_meal":
            return svc_log_meal(args.get("text", ""))
        if name == "log_water":
            return svc_log_water(args.get("oz", 0))
        if name == "log_journal":
            return svc_log_journal(
                tags=args.get("tags") if "tags" in args else None,
                mood=args.get("mood"),
                stress=args.get("stress"),
                soreness=args.get("soreness"),
                slot=args.get("slot"),
                text=args.get("text"),
            )
        if name == "generate_weekly_summary":
            return _weekly_summary()
        if name == "get_recent_meals":
            return {"meals": svc_get_recent_meals(int(args.get("days", 1)))}
        if name == "delete_meal":
            return svc_delete_meal(args.get("meal_id", ""))
        if name == "delete_water":
            return svc_delete_water(args.get("water_id", ""))
        if name == "log_workout":
            return svc_log_workout(args.get("text", ""))
        if name == "delete_workout":
            return svc_delete_workout(args.get("workout_id", ""))
        if name == "annotate_workout":
            return svc_annotate_workout(
                args.get("text", ""),
                date=args.get("date"),
                workout_id=args.get("workout_id"),
            )
        if name == "propose_workout":
            today_str = local_today_str()
            proposal = svc_propose_workout(today_str)
            svc_write_proposal(today_str, proposal)
            return proposal
        if name == "set_lateral_chain_phase":
            return svc_update_lateral_chain_phase(
                int(args.get("phase", 1)),
                reason=args.get("reason"),
            )
        return {"error": f"unknown tool {name}"}
    except Exception as e:
        logger.exception("tool %s failed", name)
        return {"error": str(e)}


def _weekly_summary() -> dict:
    """Aggregate the last 7 days of journal entries + daily scores into a
    compact structured payload the coach inlines into its reply."""
    from datetime import datetime, timedelta
    from shared.db import get_table, get_item

    journal_table = get_table("JOURNAL_TABLE")
    scores_table = get_table("DAILY_SCORES_TABLE")
    workouts_table = get_table("WORKOUTS_TABLE")
    from shared.db import query_items

    today_str = local_today_str()
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")

    days = []
    tag_counts: dict = {}
    mood_vals = []
    stress_vals = []
    recovery_vals = []
    sleep_mins = []
    strain_vals = []
    narratives = []
    workouts_summary = []

    for i in range(7):
        d = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        j = get_item(journal_table, {"date": d}) or {}
        s = get_item(scores_table, {"date": d}) or {}
        ws = query_items(workouts_table, "date", d) or []

        for t in (j.get("tags") or []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
        if j.get("mood") is not None:
            mood_vals.append(j["mood"])
        if j.get("stress") is not None:
            stress_vals.append(j["stress"])
        if s.get("recovery") is not None:
            recovery_vals.append(s["recovery"])
        if s.get("strain") is not None:
            strain_vals.append(s["strain"])
        sm = (s.get("sleep") or {}).get("total_min")
        if sm:
            sleep_mins.append(sm)
        if j.get("morning_text"):
            narratives.append({"date": d, "slot": "morning", "text": j["morning_text"][:400]})
        if j.get("evening_text"):
            narratives.append({"date": d, "slot": "evening", "text": j["evening_text"][:400]})
        for w in ws:
            workouts_summary.append({
                "date": d,
                "title": w.get("title") or w.get("type") or "workout",
                "dur": w.get("dur"),
                "strain": w.get("strain"),
            })

        days.append({
            "date": d,
            "recovery": s.get("recovery"),
            "strain": s.get("strain"),
            "sleep_hours": round(sm / 60, 1) if sm else None,
            "mood": j.get("mood"),
            "tags": j.get("tags") or [],
        })

    def _avg(vs):
        return round(sum(vs) / len(vs), 1) if vs else None

    top_tags = sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "week_of": (today_dt - timedelta(days=6)).strftime("%Y-%m-%d"),
        "through": today_str,
        "days": days,
        "avg_recovery": _avg(recovery_vals),
        "avg_strain": _avg(strain_vals),
        "avg_sleep_hours": round(sum(sleep_mins) / len(sleep_mins) / 60, 1) if sleep_mins else None,
        "avg_mood": _avg(mood_vals),
        "avg_stress": _avg(stress_vals),
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "narratives": narratives,
        "workouts": workouts_summary,
    }


_MAX_IMAGES_PER_TURN = 5
_MAX_IMAGE_B64_BYTES = 1_500_000  # ~1.1 MB raw after base64 → fits the 1 MB stream budget when combined
_ALLOWED_IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _to_bedrock_messages(messages: list) -> list:
    """Convert the frontend ChatMessage list to Bedrock's content-block format.

    Handles image blocks on user turns. Images from historical user turns are
    stripped — only the *latest* user turn keeps its images — so repeated
    Bedrock calls in the tool loop don't re-upload the same bytes each round,
    and so earlier photos don't balloon the payload past the 1 MB streaming
    limit over a long conversation.
    """
    out: list = []

    # Identify the index of the latest user turn in the *input* list so we
    # know which message gets to keep its images.
    latest_user_idx = -1
    for i, m in enumerate(messages):
        if m.get("from") == "me":
            latest_user_idx = i

    for i, m in enumerate(messages):
        role = "user" if m.get("from") == "me" else "assistant"
        text = (m.get("text") or "").strip()
        raw_images = m.get("images") if role == "user" and i == latest_user_idx else []
        if not isinstance(raw_images, list):
            raw_images = []

        content: list = []
        kept = 0
        for img in raw_images:
            if kept >= _MAX_IMAGES_PER_TURN:
                break
            if not isinstance(img, dict):
                continue
            data = img.get("base64")
            media_type = img.get("mediaType") or img.get("media_type")
            if not data or not media_type:
                continue
            if media_type not in _ALLOWED_IMAGE_MEDIA_TYPES:
                logger.warning("rejected image with media_type=%s", media_type)
                continue
            if len(data) > _MAX_IMAGE_B64_BYTES:
                logger.warning("rejected oversized image (%d bytes base64)", len(data))
                continue
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": data,
                },
            })
            kept += 1

        if text:
            content.append({"type": "text", "text": text})

        # Skip entirely if the turn ended up empty (no text, no valid images).
        if not content:
            continue
        out.append({"role": role, "content": content})

    return out


@app.post("/api/coach")
async def coach_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    raw_messages = body.get("messages") or []
    if not raw_messages:
        return JSONResponse({"error": "no messages provided"}, status_code=400)

    snapshot = body.get("snapshot")
    conversation_id = body.get("conversation_id") or body.get("conversationId")
    system_prompt = build_system_prompt(snapshot if isinstance(snapshot, dict) else None)

    # Client sends the full visible chat log; we only care about the latest
    # user turn (with images). Everything prior comes from persisted history.
    latest_user_raw = None
    for m in reversed(raw_messages):
        if m.get("from") == "me":
            latest_user_raw = m
            break
    if latest_user_raw is None:
        return JSONResponse({"error": "last message must be from user"}, status_code=400)

    latest_user_bedrock = _to_bedrock_messages([latest_user_raw])
    if not latest_user_bedrock:
        return JSONResponse({"error": "latest user turn is empty"}, status_code=400)

    thread = resolve_thread(conversation_id)
    persisted_history = messages_for_bedrock(thread)
    initial_history = persisted_history + latest_user_bedrock

    def stream():
        history = list(initial_history)
        assistant_text_accum: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "system": system_prompt,
                "tools": TOOLS,
                "messages": history,
            }
            try:
                resp = bedrock.invoke_model_with_response_stream(
                    modelId=MODEL_ID,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(request_body),
                )
            except Exception as e:
                logger.exception("bedrock call failed")
                yield f"\n[coach error: {e}]"
                return

            assistant_content: list = []
            stop_reason: Optional[str] = None
            current_blocks: dict = {}

            for event in resp.get("body", []):
                chunk = event.get("chunk")
                if not chunk:
                    continue
                try:
                    data = json.loads(chunk.get("bytes", b"").decode("utf-8"))
                except Exception:
                    continue
                etype = data.get("type")

                if etype == "content_block_start":
                    idx = data.get("index", 0)
                    block = dict(data.get("content_block") or {})
                    if block.get("type") == "text":
                        block["text"] = ""
                    elif block.get("type") == "tool_use":
                        block["_json_buffer"] = ""
                    current_blocks[idx] = block

                elif etype == "content_block_delta":
                    idx = data.get("index", 0)
                    delta = data.get("delta") or {}
                    block = current_blocks.get(idx)
                    if block is None:
                        continue
                    if delta.get("type") == "text_delta":
                        piece = delta.get("text", "")
                        block["text"] = block.get("text", "") + piece
                        yield piece
                    elif delta.get("type") == "input_json_delta":
                        block["_json_buffer"] = block.get("_json_buffer", "") + delta.get("partial_json", "")

                elif etype == "content_block_stop":
                    idx = data.get("index", 0)
                    block = current_blocks.pop(idx, None)
                    if block is None:
                        continue
                    if block.get("type") == "tool_use":
                        raw = block.pop("_json_buffer", "") or "{}"
                        try:
                            block["input"] = json.loads(raw)
                        except Exception:
                            block["input"] = {}
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "input": block.get("input", {}),
                        })
                    elif block.get("type") == "text":
                        text_out = block.get("text", "")
                        assistant_content.append({"type": "text", "text": text_out})
                        if text_out:
                            assistant_text_accum.append(text_out)

                elif etype == "message_delta":
                    delta = data.get("delta") or {}
                    if delta.get("stop_reason"):
                        stop_reason = delta["stop_reason"]

                elif etype == "message_stop":
                    pass

            if stop_reason != "tool_use":
                _persist_turn(thread, latest_user_raw, assistant_text_accum)
                return

            history.append({"role": "assistant", "content": assistant_content})
            tool_results = []
            for blk in assistant_content:
                if blk.get("type") != "tool_use":
                    continue
                result = _execute_tool(blk.get("name", ""), blk.get("input") or {})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": blk.get("id"),
                    "content": json.dumps(result, default=str),
                })
            if not tool_results:
                _persist_turn(thread, latest_user_raw, assistant_text_accum)
                return
            history.append({"role": "user", "content": tool_results})

        _persist_turn(thread, latest_user_raw, assistant_text_accum)
        yield "\n[coach: tool loop depth exceeded]"

    headers = {"X-Conversation-Id": thread.get("conversation_id", "")}
    return StreamingResponse(stream(), media_type="text/plain", headers=headers)


def _persist_turn(thread: dict, user_raw: dict, assistant_text_accum: list) -> None:
    assistant_text = "".join(assistant_text_accum).strip()
    if not assistant_text and not (user_raw.get("text") or user_raw.get("images")):
        return
    user_msg = {
        "from": "me",
        "t": user_raw.get("t", ""),
        "text": user_raw.get("text", ""),
        "images": user_raw.get("images") or [],
    }
    assistant_msg = {
        "from": "coach",
        "t": _stamp_now(),
        "text": assistant_text,
    }
    append_turn(thread, user_msg, assistant_msg)
    try:
        maybe_summarize(thread, bedrock, MODEL_ID)
    except Exception:
        logger.exception("maybe_summarize failed")


def _stamp_now() -> str:
    import datetime as _dt
    # Keep the same "h:mmam/pm" format the frontend uses.
    now = _dt.datetime.now()
    hour = now.hour % 12 or 12
    suffix = "am" if now.hour < 12 else "pm"
    return f"{hour}:{now.minute:02d}{suffix}"


@app.get("/health")
def health():
    return {"ok": True}
