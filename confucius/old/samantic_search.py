from qdrant_client import models, QdrantClient
from sentence_transformers import SentenceTransformer


encoder = SentenceTransformer('qwen3-embedding:8b')
qdrant = QdrantClient(":memory:")

qdrant.recreate_collection(
    collection_name="compliance_test",
    vectors_config=models.VectorParams(
        size=encoder.get_sentence_embedding_dimension(),
        distance=models.Distance.COSINE
    )
)

qdrant.upload_records(
    collection_name="compliance_test",
    records=[
        models.Record(
            id=idx,
            vector=encoder.encode(doc['description']).tolist(),
            payload=doc
        ) for idx, doc in enumerate(documents)
    ]
)
