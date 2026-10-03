"""JSON schemas for Ollama structured output + the merged episode document."""

from __future__ import annotations

_LT = {
    "lower_third_title": {"type": "string", "maxLength": 48},
    "lower_third_sub": {"type": "string", "maxLength": 64},
}

TOM_SCHEMA = {
    "type": "object",
    "required": ["episode_title", "episode_description", "segments"],
    "properties": {
        "episode_title": {"type": "string", "maxLength": 90},
        "episode_description": {"type": "string"},
        "segments": {
            "type": "array", "minItems": 3,
            "items": {
                "type": "object",
                "required": ["kind", "text"],
                "properties": {
                    "kind": {"enum": ["intro", "story", "handover"]},
                    "item_slot": {"type": "string"},
                    "text": {"type": "string", "minLength": 10},
                    **_LT,
                },
            },
        },
    },
}

ANNIKA_SCHEMA = {
    "type": "object",
    "required": ["short_title", "short_hook", "segments"],
    "properties": {
        "short_title": {"type": "string", "maxLength": 80},
        "short_hook": {"type": "string"},
        "segments": {
            "type": "array", "minItems": 3,
            "items": {
                "type": "object",
                "required": ["kind", "text"],
                "properties": {
                    "kind": {"enum": ["archive_intro", "archive_story", "signoff"]},
                    "item_slot": {"type": "string"},
                    "text": {"type": "string", "minLength": 10},
                    **_LT,
                },
            },
        },
    },
}

TOM_KINDS = {"intro", "story", "handover"}
ANNIKA_KINDS = {"archive_intro", "archive_story", "signoff"}
STORY_KINDS = {"story", "archive_story"}
