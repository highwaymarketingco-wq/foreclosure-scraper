"""
Visual reCAPTCHA solver using Claude API (like daily sweeps use).

Replaces the broken Groq Whisper audio approach with Claude vision API.
"""
import os
import base64
import structlog
from typing import Optional

log = structlog.get_logger()


async def solve_recaptcha_visual_claude(screenshot_bytes: bytes) -> Optional[str]:
    """
    Solve a visual reCAPTCHA image challenge using Claude API.
    
    Args:
        screenshot_bytes: PNG/JPEG screenshot of the reCAPTCHA image grid
        
    Returns:
        Answer string (numbers/letters) or None if failed
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
    system_prompt = """You are solving Google reCAPTCHA challenges. The image shows numbers or letters.

Extract ONLY the actual challenge digits/letters shown. Ignore any UI elements, buttons, or instructions.

Output format: Return ONLY a JSON object with one key "answer" containing the extracted text with no spaces.
Example: {"answer": "7392"}

If you see multiple challenge images (grid), focus on the main challenge area only."""
    
    user_prompt = "What numbers and/or letters are shown in this reCAPTCHA challenge? Return JSON with 'answer' key containing ONLY the digits/letters."
    
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
        
        # Parse JSON response
        import json
        try:
            parsed = json.loads(raw_text)
            answer = parsed.get("answer", "").strip()
            if answer:
                log.info("recaptcha_claude.solved", answer=answer[:20])
                return answer
            else:
                log.warning("recaptcha_claude.empty_answer", raw=raw_text[:200])
                return None
        except json.JSONDecodeError:
            log.warning("recaptcha_claude.json_parse_failed", raw=raw_text[:200])
            return None
                
    except Exception as exc:
        log.error("recaptcha_claude.api_error", error=str(exc)[:200])
        return None
