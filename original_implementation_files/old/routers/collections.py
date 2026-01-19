from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from typing import List, Any, Dict
from old.services.qdrant import qdrant_service
from old.services.ollama import ollama_service
from old.services.redis_service import redis_service
from pypdf import PdfReader
import io

router = APIRouter()

@router.get("/")
async def list_collections():
    """List all Qdrant collections"""
    try:
        collections = await qdrant_service.list_collections()
        return {"collections": collections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create")
async def create_collection(name: str, vector_size: int = 768):
    """Create a new collection"""
    try:
        await qdrant_service.create_collection(name, vector_size)
        return {"success": True, "collection": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{collection_name}")
async def delete_collection(collection_name: str):
    """Delete a collection"""
    try:
        await qdrant_service.delete_collection(collection_name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
    collection: str = Form(...)
):
    """Upload and vectorize documents"""
    try:
        # Get embedding model
        agent_models = await redis_service.get("agent_models")
        embedding_model = agent_models.get("embedding", "nomic-embed-text") if agent_models else "nomic-embed-text"
        
        results = []
        
        for file in files:
            # Read file content
            content = await file.read()
            
            # Parse based on file type
            if file.filename.endswith('.txt'):
                text = content.decode('utf-8')
            elif file.filename.endswith('.pdf'):
                pdf_reader = PdfReader(io.BytesIO(content))
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text()
            else:
                # Skip unsupported file types
                continue
            
            # Chunk text
            chunks = chunk_text(text, 500)
            
            # Generate embeddings and store
            for i, chunk in enumerate(chunks):
                embedding = await ollama_service.generate_embedding(chunk["text"], embedding_model)
                
                payload = {
                    "text": chunk["text"],
                    "source": file.filename,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    **chunk["metadata"]
                }
                
                await qdrant_service.add_point(collection, embedding, payload)
            
            results.append({
                "filename": file.filename,
                "chunks": len(chunks),
                "status": "success"
            })
        
        # Publish event
        await redis_service.publish("agent_events", {
            "type": "documents_uploaded",
            "collection": collection,
            "files": len(files)
        })
        
        return {"results": results}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def chunk_text(text: str, chunk_size: int = 500) -> List[Dict[str, Any]]:
    """Chunk text into smaller pieces"""
    chunks = []
    sentences = [s.strip() for s in text.split('.') if s.strip()]
    
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) > chunk_size and current_chunk:
            chunks.append({
                "text": current_chunk.strip(),
                "metadata": {"length": len(current_chunk)}
            })
            current_chunk = sentence
        else:
            current_chunk += (". " if current_chunk else "") + sentence
    
    if current_chunk:
        chunks.append({
            "text": current_chunk.strip(),
            "metadata": {"length": len(current_chunk)}
        })
    
    return chunks
