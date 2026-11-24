"""
Visual reCAPTCHA solver using Claude API (like daily sweeps use).

Replaces the broken Groq Whisper audio approach with Claude vision API.
"""
import os
import base64
import httpx
import json
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
    
    # Detect media type
    if screenshot_bytes[:4] == b"\x89PNG":
        media_type = "image/png"
    elif screenshot_bytes[:2] in (b"\xff\xd8", b"\xff\xd9"):
        media_type = "image/jpeg"
    else:
        media_type = "image/png"  # assume
    
    # Build Claude API request (same pattern as _assess_one_anthropic)
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    
    # Base64 encode image
    b64_data = base64.b64encode(screenshot_bytes).decode("ascii")
    
    # Claude prompt for reCAPTCHA
    system_prompt = """You are solving Google reCAPTCHA audio challenges. The image shows a visual challenge with numbers or letters.

Your task: Extract ONLY the numbers and/or letters shown in the image. 

Output format: Return ONLY a JSON object with one key "answer" containing the extracted text with no spaces.
Example: {"answer": "7392"}

Do NOT include any explanation, just the JSON."""
    
    user_prompt = "What numbers and/or letters are shown in this reCAPTCHA image? Return JSON with 'answer' key."
    
    payload = {
        "model": "claude-sonnet-4-20250514",  # Same as enrichment_vision.py uses
        "max_tokens": 100,
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": [
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
                ],
            }
        ],
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # Extract text from response
            content = data.get("content", [])
            text_chunks = [b.get("text", "") for b in content if b.get("type") == "text"]
            raw_text = "\n".join(text_chunks).strip()
            
            # Parse JSON response
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
                # Try to extract from text
                log.warning("recaptcha_claude.json_parse_failed", raw=raw_text[:200])
                return None
                
    except Exception as exc:
        log.error("recaptcha_claude.api_error", error=str(exc)[:200])
        return None
