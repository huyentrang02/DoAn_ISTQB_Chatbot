from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.rag_service import rag_service

router = APIRouter()

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    try:
        result = await rag_service.process_pdf(file)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
