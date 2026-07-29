from sentence_transformers import SentenceTransformer

MODEL_NAME = "clip-ViT-B-32"

print(f"Descargando y preparando {MODEL_NAME}...")
SentenceTransformer(MODEL_NAME)
print("Modelo CLIP listo.")
