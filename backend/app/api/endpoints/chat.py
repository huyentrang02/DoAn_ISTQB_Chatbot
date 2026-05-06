from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
from fastapi.responses import StreamingResponse
from app.services.rag_service import rag_service

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    query: str
    history: Optional[List[ChatMessage]] = []
    image_base64: Optional[str] = None   # base64 ảnh đính kèm (không có prefix data:...)
    image_mime: Optional[str] = None     # vd: "image/png", "image/jpeg"


class ChatResponse(BaseModel):
    answer: str


@router.post("/chat")
async def chat(request: ChatRequest):
    history_dicts = (
        [{"role": m.role, "content": m.content} for m in request.history]
        if request.history
        else []
    )
    return StreamingResponse(
        rag_service.chat_stream(
            request.query,
            history=history_dicts,
            image_base64=request.image_base64,
            image_mime=request.image_mime,
        ),
        media_type="text/event-stream",
    )


