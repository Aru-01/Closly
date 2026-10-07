from pydantic import BaseModel
from typing import List, Optional


class BrandInfo(BaseModel):
    name: str
    detected_from_logo: bool
    confidence: str
    logo_text: Optional[str] = None
    logo_symbol: Optional[str] = None


class EstimatedPrice(BaseModel):
    currency: str = "EUR"
    amount: float = 35.0
    range_min: float = 20.0
    range_max: float = 60.0
    confidence: str = "medium"


class DressAnalysisResult(BaseModel):
    is_garment: bool = True
    garment_type: str = "top"
    gender: str = "unisex"
    primary_color: str = "Neutral"
    secondary_colors: List[str] = []
    pattern: str = "solid"
    brand: BrandInfo
    estimated_price: EstimatedPrice
    notes: Optional[str] = None



class AnalyzeResponse(BaseModel):
    success: bool
    filename: str
    analysis: Optional[DressAnalysisResult] = None
    error: Optional[str] = None