from typing import Optional

from app.services.rag_service import rag_service
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    query: str
    image_base64: Optional[str] = None  # base64 ảnh đính kèm (không có prefix data:...)
    image_mime: Optional[str] = None  # vd: "image/png", "image/jpeg"


class ChatResponse(BaseModel):
    answer: str


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    answer = await rag_service.chat(
        request.query,
        image_base64=request.image_base64,
        image_mime=request.image_mime,
    )
    return ChatResponse(answer=answer)
