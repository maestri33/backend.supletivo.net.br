"""Private embedding endpoint. No public UI, persisted photos or access logging."""
from contextlib import asynccontextmanager
from io import BytesIO
import os
import threading

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from insightface.app import FaceAnalysis
from PIL import Image, ImageOps

model = None
model_lock = threading.Lock()
MAX_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 16_000_000


@asynccontextmanager
async def lifespan(app):
    global model
    model = FaceAnalysis(name=os.getenv("MODEL_NAME", "buffalo_l"),
                         root=os.getenv("MODEL_ROOT", "/models"),
                         allowed_modules=["detection", "recognition"],
                         providers=["CPUExecutionProvider"])
    model.prepare(ctx_id=-1, det_size=(640, 640))
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    if model is None:
        raise HTTPException(503, "Model not ready")
    return {"status": "ok", "loaded": True, "model": os.getenv("MODEL_NAME", "buffalo_l")}


@app.post("/embed")
def embed(file: UploadFile = File(...)):
    data = file.file.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, "Image must be between 1 byte and 10 MB")
    try:
        with Image.open(BytesIO(data)) as raw:
            if raw.width * raw.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("Too many pixels")
            image = cv2.cvtColor(np.array(ImageOps.exif_transpose(raw).convert("RGB")), cv2.COLOR_RGB2BGR)
    except Exception:
        raise HTTPException(400, "Invalid image") from None
    if model is None:
        raise HTTPException(503, "Model not ready")
    with model_lock:
        faces = model.get(image)
    if not faces:
        raise HTTPException(422, "No face detected")
    face = max(faces, key=lambda face: (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]))
    return {"embedding": face.normed_embedding.tolist(), "meta": {
        "det_score": float(face.det_score), "bbox": face.bbox.tolist(),
        "faces": len(faces), "model": os.getenv("MODEL_NAME", "buffalo_l")}}
