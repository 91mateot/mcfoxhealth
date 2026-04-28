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
            "Tag how Mateo is feeling or what happened. Use when he mentions mood, stress, "
            "soreness, alcohol, sauna, back flare, etc. Overwrites the journal entry for today."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of tags. Valid: alcohol, caffeine_late, ate_late, heavy_meal, "
                        "hydrated, screens_bed, late_bedtime, meditated, stretched, sauna, "
                        "cold, sunlight_am, stress, social, travel, sick, back_flare."
                    ),
                },
                "mood": {"type": "integer", "minimum": 1, "maximum": 5, "description": "1 (bad) - 5 (great)"},
                "stress": {"type": "integer", "minimum": 1, "maximum": 5, "description": "1 (none) - 5 (extreme)"},
                "soreness": {"type": "integer", "minimum": 1, "maximum": 5, "description": "1 (none) - 5 (very)"},
            },
            "required": ["tags"],
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
]


def _execute_tool(name: str, args: dict) -> dict:
    try:
        if name == "log_meal":
            return svc_log_meal(args.get("text", ""))
        if name == "log_water":
            return svc_log_water(args.get("oz", 0))
        if name == "log_journal":
            return svc_log_journal(
                tags=args.get("tags", []),
                mood=args.get("mood"),
                stress=args.get("stress"),
                soreness=args.get("soreness"),
            )
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
        return {"error": f"unknown tool {name}"}
    except Exception as e:
        logger.exception("tool %s failed", name)
        return {"error": str(e)}


def _to_bedrock_messages(messages: list) -> list:
    """Convert the frontend ChatMessage list to Bedrock's content-block format."""
    out = []
    for m in messages:
        role = "user" if m.get("from") == "me" else "assistant"
        text = m.get("text", "")
        if not text:
            continue
        out.append({"role": role, "content": [{"type": "text", "text": text}]})
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
    system_prompt = build_system_prompt(snapshot if isinstance(snapshot, dict) else None)
    messages = _to_bedrock_messages(raw_messages)

    if not messages or messages[-1]["role"] != "user":
        return JSONResponse({"error": "last message must be from user"}, status_code=400)

    def stream():
        history = list(messages)
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
                        assistant_content.append({"type": "text", "text": block.get("text", "")})

                elif etype == "message_delta":
                    delta = data.get("delta") or {}
                    if delta.get("stop_reason"):
                        stop_reason = delta["stop_reason"]

                elif etype == "message_stop":
                    pass

            if stop_reason != "tool_use":
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
                return
            history.append({"role": "user", "content": tool_results})

        yield "\n[coach: tool loop depth exceeded]"

    return StreamingResponse(stream(), media_type="text/plain")


@app.get("/health")
def health():
    return {"ok": True}
