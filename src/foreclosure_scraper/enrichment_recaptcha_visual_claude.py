"""
Visual reCAPTCHA solver using Claude API (like daily sweeps use).

Replaces the broken Groq Whisper audio approach with Claude vision API.
"""
import os
import base64
import structlog
from typing import Optional

log = structlog.get_logger()


async def solve_recaptcha_visual_claude(screenshot_bytes: bytes):
    """
    Solve a visual reCAPTCHA challenge using Claude API.
    
    Args:
        screenshot_bytes: PNG/JPEG screenshot of the reCAPTCHA challenge
        
    Returns:
        Dict with "type" and either "answer" (text) or "clicks" (grid coordinates),
        or None if failed
    """
    # Get Claude API key (same pattern as enrichment_vision.py)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        for path in ["~/.secrets/anthropic_api_key.txt", ".secrets/anthropic_api_key.txt"]:
            try:
                with open(os.path.expanduser(path)) as f:
                    api_key = f.read().strip()
                if api_key:
                    break
            except Exception:
                pass
    
    if not api_key:
        log.warning("recaptcha_claude.no_api_key")
        return None
    
    # Import SDK (same as enrichment_vision.py)
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        log.error("recaptcha_claude.sdk_missing", hint="pip install anthropic")
        return None
    
    # Detect media type
    if screenshot_bytes[:4] == b"\x89PNG":
        media_type = "image/png"
    elif screenshot_bytes[:2] in (b"\xff\xd8", b"\xff\xd9"):
        media_type = "image/jpeg"
    else:
        media_type = "image/png"  # assume
    
    # Base64 encode image
    b64_data = base64.b64encode(screenshot_bytes).decode("ascii")
    
    # Claude prompt for reCAPTCHA
    system_prompt = """You are solving Google reCAPTCHA challenges.

TWO TYPES:
1. Text/number challenges: Extract the digits/letters shown
2. Image grid challenges: Identify which grid squares contain the target object

For IMAGE GRID challenges (e.g., "Select all images with buses"):
- Analyze each square in the grid
- Return JSON with "grid_clicks": array of [row, col] coordinates (0-indexed)
- Example: {"grid_clicks": [[0,1], [2,3]]} means top row 2nd square, 3rd row 4th square

For TEXT challenges:
- Return JSON with "answer": the text/numbers shown
- Example: {"answer": "7392"}

Be precise with grid coordinates. Row 0 is top, Column 0 is left."""
    
    user_prompt = """Analyze this reCAPTCHA challenge.

If it's an IMAGE GRID (select all X):
- Return JSON with "grid_clicks": [[row, col], ...] for squares containing the target
- Use 0-indexed coordinates

If it's TEXT/NUMBERS:
- Return JSON with "answer": the text shown

Return ONLY the JSON, no explanation."""
    
    # Build message content (same pattern as enrichment_vision.py)
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64_data,
            },
        },
        {
            "type": "text",
            "text": user_prompt,
        },
    ]
    
    try:
        # Use AsyncAnthropic SDK (same as enrichment_vision.py)
        client = AsyncAnthropic(api_key=api_key, max_retries=2, timeout=30.0)
        resp = await client.messages.create(
            model="claude-sonnet-4-5-20250929",  # Same model as enrichment_vision.py uses
            max_tokens=100,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
        )
        
        # Extract text (same pattern as enrichment_vision.py)
        text_chunks = [b.text for b in resp.content if hasattr(b, "text")]
        raw_text = "\n".join(text_chunks).strip()
        
        # Strip markdown code blocks if present
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()
        
        # Parse JSON response
        import json
        try:
            parsed = json.loads(raw_text)
            
            # Check for grid clicks (image challenge)
            if "grid_clicks" in parsed:
                clicks = parsed.get("grid_clicks", [])
                if clicks:
                    log.info("recaptcha_claude.grid_solved", clicks=clicks[:10])
                    return {"type": "grid", "clicks": clicks}
                else:
                    log.warning("recaptcha_claude.empty_grid", raw=raw_text[:200])
                    return None
            
            # Check for text answer
            answer = parsed.get("answer", "").strip()
            if answer:
                log.info("recaptcha_claude.text_solved", answer=answer[:20])
                return {"type": "text", "answer": answer}
            else:
                log.warning("recaptcha_claude.empty_answer", raw=raw_text[:200])
                return None
        except json.JSONDecodeError:
            log.warning("recaptcha_claude.json_parse_failed", raw=raw_text[:200])
            return None
                
    except Exception as exc:
        log.error("recaptcha_claude.api_error", error=str(exc)[:200])
        return None
