from __future__ import annotations

from app.graph.runtime import academic_text_stream, clear_messages, get_messages


async def research_assistant_stream(
    prompt: str,
    image: str | None,
    thread_id: str,
    chart_type_hint: str | None = None,
    top_k: int = 5,
    max_steps: int = 8,
):
    async for chunk in academic_text_stream(
        message=prompt,
        image_url=image,
        thread_id=thread_id,
        chart_type_hint=chart_type_hint,
        top_k=top_k,
        max_steps=max_steps,
    ):
        yield chunk
