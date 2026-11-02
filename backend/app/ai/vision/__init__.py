"""S4-2 视觉门面：业务层只 import 这里。"""
from app.ai.vision.mistake_ocr import VisionError, VisionExtract, extract_mistake

__all__ = ["VisionError", "VisionExtract", "extract_mistake"]