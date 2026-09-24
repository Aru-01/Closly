from fastapi import APIRouter, UploadFile, File
from schemas import AnalyzeResponse
from service import analyze_dress_image

router = APIRouter(prefix="/api/v1", tags=["Dress Analysis"])


@router.post("/analyze-dress", response_model=AnalyzeResponse)
async def analyze_dress(file: UploadFile = File(...)):
    try:
        result = await analyze_dress_image(file)
        return AnalyzeResponse(
            success=True,
            filename=file.filename,
            analysis=result
        )
    except Exception as e:
        return AnalyzeResponse(
            success=False,
            filename=file.filename,
            error=str(e)
        )