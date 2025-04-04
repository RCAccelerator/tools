#!/usr/bin/env python3
import argparse
from vllm import LLM, SamplingParams
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.entrypoints.openai.api_server import serve_api
import os

def main():
    parser = argparse.ArgumentParser(description="Start an embedding server with vLLM")
    parser.add_argument("--model", type=str, default="BAAI/bge-large-en-v1.5", 
                        help="Model path or Hugging Face ID")
    parser.add_argument("--host", type=str, default="0.0.0.0", 
                        help="Host to bind the server to")
    parser.add_argument("--port", type=int, default=8000, 
                        help="Port to bind the server to")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.9, 
                        help="GPU memory utilization target (0.0 to 1.0)")
    parser.add_argument("--max-model-len", type=int, default=512, 
                        help="Maximum sequence length")
    
    args = parser.parse_args()
    
    # Configure engine arguments
    engine_args = AsyncEngineArgs(
        model=args.model,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_model_len=args.max_model_len,
        enable_embedding=True,
        dtype="float16"  # Use half precision for better performance
    )
    
    # Start the OpenAI-compatible API server
    serve_api(
        engine_args=engine_args,
        served_model=args.model,
        host=args.host,
        port=args.port,
        embedding_only=True  # Only expose embedding endpoints
    )

if __name__ == "__main__":
    main()