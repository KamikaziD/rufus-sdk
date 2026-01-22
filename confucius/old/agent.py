import ollama
from qdrant_client import QdrantClient, models
from qdrant_client.http.models import PointStruct, VectorParams, Distance
import uuid


EMBEDDING_DIMENSIONS = {
    "nomic-embed-text": 768,
    "qwen3-embedding:8b": 4096,
}


class Agent:
    def __init__(self, ollama_model="qwen3-vl:4b", qdrant_host="localhost", qdrant_port=6333, embedding_model="qwen3-embedding:8b"):
        self.ollama_client = ollama.Client()
        self.qdrant_client: QdrantClient = QdrantClient(
            host=qdrant_host, port=qdrant_port)
        self.ollama_model = ollama_model
        self.embedding_model = embedding_model
        self.collection_name = "confucius_agent"
        self.embedding_dim = EMBEDDING_DIMENSIONS.get(embedding_model)

        if not self.embedding_dim:
            raise ValueError(
                f"Unknown embedding dimension for model {embedding_model}")

        # Check if collection exists and has the correct dimension
        try:
            exists = self.qdrant_client.collection_exists(self.collection_name)

            if exists:
                collection_info = self.qdrant_client.get_collection(
                    collection_name=self.collection_name)
                if collection_info.vectors_config.params.size != self.embedding_dim:
                    self.qdrant_client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(
                            size=self.embedding_dim, distance=Distance.COSINE)
                    )
        except Exception:
            # Collection does not exist, create it
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dim, distance=Distance.COSINE)
            )

    def get_completion(self, prompt: str, image_base64: str = None):
        messages = [{'role': 'system', 'content': "You are a senior marketing specialist. Assist the user with any Digital Marketing needs."}, {
            'role': 'user', 'content': prompt}]
        if image_base64:
            messages[0]['images'] = [image_base64]

        response = self.ollama_client.chat(
            model=self.ollama_model,
            messages=messages

        )
        content = response['message']['content']
        print("AGENT RES: ", response)
        # Remember the conversation
        self.remember(f"User prompt: {prompt}\nAgent response: {content}")
        return content

    def remember(self, text: str):
        if not text or not text.strip():
            return

        # Get embedding from ollama
        embedding = ollama.embeddings(
            model=self.embedding_model, prompt=text)['embedding']

        # Store in qdrant
        doc_id = str(uuid.uuid4())
        self.qdrant_client.upsert(
            collection_name=self.collection_name,
            wait=True,
            points=[
                PointStruct(id=doc_id, vector=embedding,
                            payload={"text": text})
            ],
        )
        return doc_id

    def recall(self, text: str, top_k: int = 1):
        if not text or not text.strip():
            return []

        # Get embedding for query
        embedding = ollama.embeddings(
            model=self.embedding_model, prompt=text)['embedding']

        # Search qdrant

        search_result = self.qdrant_client.search(
            collection_name=self.collection_name,
            query_vector=embedding,
            limit=top_k
        )
        return [hit.payload['text'] for hit in search_result]
