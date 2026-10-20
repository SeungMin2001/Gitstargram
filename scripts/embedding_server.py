"""Native Apple Silicon (MPS) OpenAI-compatible embedding server for Qwen/Qwen3-Embedding-0.6B."""

import os
import time
from typing import Union

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModel, AutoTokenizer

MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "Qwen/Qwen3-Embedding-0.6B")
PORT = int(os.environ.get("EMBEDDING_PORT", "8002"))
HOST = os.environ.get("EMBEDDING_HOST", "127.0.0.1")

app = FastAPI(title="Gitstargram Embedding Server", version="0.1.0")

device = "mps" if torch.backends.mps.is_available() else "cpu"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, padding_side="left")
model = AutoModel.from_pretrained(MODEL_NAME, torch_dtype=torch.float16 if device == "mps" else torch.float32).to(device).eval()
DIMENSIONS = int(model.config.hidden_size)


class EmbeddingRequest(BaseModel):
    model: str = MODEL_NAME
    input: Union[str, list[str]]


def last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "device": device, "dimensions": DIMENSIONS}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "owned_by": "local-mps",
                "dimensions": DIMENSIONS,
                "device": device,
            }
        ],
    }


@app.post("/v1/embeddings")
def create_embeddings(payload: EmbeddingRequest):
    texts = [payload.input] if isinstance(payload.input, str) else payload.input
    if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
        raise HTTPException(422, "Input texts must be non-empty strings")
    if len(texts) > 64:
        raise HTTPException(422, "Batch size exceeds maximum of 64")
    started = time.perf_counter()
    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=2048,
        return_tensors="pt",
    ).to(device)
    with torch.no_grad():
        outputs = model(**encoded)
        pooled = last_token_pool(outputs.last_hidden_state, encoded["attention_mask"])
        normalized = torch.nn.functional.normalize(pooled.float(), p=2, dim=1).cpu().tolist()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    prompt_tokens = int(encoded["attention_mask"].sum().item())
    return {
        "object": "list",
        "model": MODEL_NAME,
        "dimensions": DIMENSIONS,
        "latency_ms": elapsed_ms,
        "data": [
            {"object": "embedding", "index": idx, "embedding": vec}
            for idx, vec in enumerate(normalized)
        ],
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
