from typing import List
import google.generativeai as genai
from langchain_core.embeddings import Embeddings

class NativeGoogleEmbeddings(Embeddings):
    """Wrapper sử dụng Google Generative AI SDK trực tiếp để embed thay vì qua Langchain-Google"""
    def __init__(self, model: str, api_key: str, output_dimensionality: int = 768):
        self.model = model
        self.output_dimensionality = output_dimensionality
        genai.configure(api_key=api_key)
        
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        response = genai.embed_content(
            model=self.model,
            content=texts,
            task_type="retrieval_document",
            output_dimensionality=self.output_dimensionality
        )
        return response['embedding']

    def embed_query(self, text: str) -> List[float]:
        response = genai.embed_content(
            model=self.model,
            content=text,
            task_type="retrieval_query",
            output_dimensionality=self.output_dimensionality
        )
        return response['embedding']
