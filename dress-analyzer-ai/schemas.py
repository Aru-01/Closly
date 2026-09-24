from pydantic import BaseModel
from typing import List, Optional


class BrandInfo(BaseModel):
    name: str
    detected_from_logo: bool
    confidence: str
    logo_text: Optional[str] = None
    logo_symbol: Optional[str] = None


class EstimatedPrice(BaseModel):
    currency: str
    amount: float
    range_min: float
    range_max: float
    confidence: str


class DressAnalysisResult(BaseModel):
    garment_type: str
    gender: str
    primary_color: str
    secondary_colors: List[str] = []
    pattern: str
    brand: BrandInfo
    estimated_price: EstimatedPrice
    notes: Optional[str] = None


class AnalyzeResponse(BaseModel):
    success: bool
    filename: str
    analysis: Optional[DressAnalysisResult] = None
    error: Optional[str] = None