
"""Text Processor to split text in chunks"""
from typing import List
from langchain.text_splitter import RecursiveCharacterTextSplitter as rct
from transformers import AutoTokenizer


# pylint: disable=too-few-public-methods
class TextProcessor:
    """Handles text processing tasks."""

    def __init__(self, embedding_model: str,
                 chunk_size: int):
        self.tokenizer = AutoTokenizer.from_pretrained(embedding_model)
        self.splitter = rct.from_huggingface_tokenizer(
            self.tokenizer,
            chunk_size=chunk_size,
            chunk_overlap=0
        )

    def split_text(self, text: str) -> List[str]:
        """Split text into chunks."""
        return self.splitter.split_text(text)
