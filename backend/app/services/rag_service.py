import os
import re
import shutil
import hashlib
from datetime import datetime
from typing import List
from fastapi import UploadFile
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from supabase.client import create_client, Client
from app.core.config import settings

class RAGService:
    def __init__(self):
        self.embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=settings.GOOGLE_API_KEY)
        self.llm = ChatGoogleGenerativeAI(model="models/gemini-2.0-flash", temperature=0.7, google_api_key=settings.GOOGLE_API_KEY)
        
        self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        # We still keep vector_store for "add_documents" convenience, 
        # but we will implement custom search to avoid LangChain RPC issues
        self.vector_store = SupabaseVectorStore(
            client=self.supabase,
            embedding=self.embeddings,
            table_name="documents",
            query_name="match_documents_v2",
        )

    def _get_file_hash(self, file_path: str) -> str:
        """Calculate MD5 hash of file for deduplication"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _clean_text(self, text: str) -> str:
        """Clean PDF text from noise"""
        # Remove page numbers (e.g., "Page 123", "- 23 -")
        text = re.sub(r'Page\s+\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'-\s*\d+\s*-', '', text)
        
        # Remove excessive whitespace and newlines
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Max 2 consecutive newlines
        text = re.sub(r' +', ' ', text)  # Multiple spaces to single
        
        # Remove common PDF artifacts
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', text)  # Control characters
        
        return text.strip()

    def _check_duplicate(self, file_hash: str) -> bool:
        """Check if file already exists in database"""
        try:
            result = self.supabase.from_("documents").select("id").eq("metadata->>file_hash", file_hash).limit(1).execute()
            return len(result.data) > 0
        except Exception as e:
            print(f"Error checking duplicate: {e}")
            return False

    async def process_pdf(self, file: UploadFile):
        # Save temp file
        temp_file_path = f"temp_{file.filename}"
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        try:
            # Calculate file hash for deduplication
            file_hash = self._get_file_hash(temp_file_path)
            
            # Check if file already processed
            if self._check_duplicate(file_hash):
                return {
                    "status": "skipped",
                    "message": "File already exists in database",
                    "chunks_added": 0
                }

            # Load PDF
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(temp_file_path)
            docs = loader.load()

            # Clean text from each document
            cleaned_docs = []
            for doc in docs:
                cleaned_content = self._clean_text(doc.page_content)
                if cleaned_content:  # Skip empty pages
                    doc.page_content = cleaned_content
                    cleaned_docs.append(doc)

            # Split text with improved settings
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200,
                length_function=len,
                separators=["\n\n", "\n", ". ", " ", ""]  # Try to split on paragraphs first
            )
            splits = text_splitter.split_documents(cleaned_docs)

            # Enrich metadata
            upload_timestamp = datetime.now().isoformat()
            for i, split in enumerate(splits):
                split.metadata.update({
                    "source": file.filename,
                    "file_hash": file_hash,
                    "page": split.metadata.get("page", "unknown"),
                    "chunk_index": i,
                    "total_chunks": len(splits),
                    "upload_date": upload_timestamp,
                    "content_length": len(split.page_content)
                })

            # Embed and store in Supabase
            self.vector_store.add_documents(splits)
            
            return {
                "status": "success",
                "message": "File processed successfully",
                "chunks_added": len(splits),
                "file_hash": file_hash
            }
            
        finally:
            # Cleanup
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    async def search_similar(self, query: str, k: int = 4) -> List[Document]:
        # Generate embedding for the query manually
        query_embedding = self.embeddings.embed_query(query)
        
        # Call Supabase RPC directly to control parameters perfectly
        response = self.supabase.rpc(
            "match_documents_v2",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.5, # Adjust threshold as needed
                "match_count": k
            }
        ).execute()
        
        # Parse response to LangChain Documents
        documents = []
        for item in response.data:
            doc = Document(
                page_content=item.get("content"),
                metadata=item.get("metadata")
            )
            documents.append(doc)
            
        return documents

    async def chat(self, query: str):
        docs = await self.search_similar(query)
        
        if not docs:
            return "Xin lỗi, tôi không tìm thấy thông tin liên quan trong tài liệu ISTQB để trả lời câu hỏi của bạn."

        context = "\n\n".join([doc.page_content for doc in docs])
        
        prompt_template = """Bạn là một trợ lý ảo chuyên về ISTQB. Hãy trả lời câu hỏi sau dựa trên thông tin được cung cấp bên dưới. 

        Context:
        {context}

        Question:
        {question}

        Answer:"""
        
        prompt = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
        chain = prompt | self.llm
        
        response = await chain.ainvoke({"context": context, "question": query})
        return response.content

rag_service = RAGService()
