"""
Lightweight ingestion that uses pre-scraped data from data/raw/
This avoids running Playwright on Streamlit Cloud.
"""

import os
import json
from pathlib import Path
from typing import List, Dict

def load_prescrapped_data() -> List[Dict]:
    """Load all pre-scraped JSON files from data/raw/"""
    documents = []
    
    # Load web pages
    pages_dir = Path("data/raw/pages")
    if pages_dir.exists():
        for json_file in sorted(pages_dir.glob("*.json")):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    doc = json.load(f)
                    if doc.get("content") and len(doc["content"].strip()) > 100:
                        documents.append({
                            "content": doc["content"],
                            "source": doc.get("url", str(json_file)),
                            "title": doc.get("title", "KITCOEK Page"),
                            "type": "webpage"
                        })
            except Exception as e:
                print(f"Warning: Failed to load {json_file}: {e}")
    
    # Load PDFs
    pdfs_dir = Path("data/raw/pdfs")
    if pdfs_dir.exists():
        for json_file in sorted(pdfs_dir.glob("*.json")):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    doc = json.load(f)
                    if doc.get("content") and len(doc["content"].strip()) > 100:
                        documents.append({
                            "content": doc["content"],
                            "source": doc.get("url", str(json_file)),
                            "title": doc.get("title", "KITCOEK Document"),
                            "type": "pdf"
                        })
            except Exception as e:
                print(f"Warning: Failed to load {json_file}: {e}")
    
    print(f"✅ Loaded {len(documents)} pre-scraped documents")
    return documents


def ingest_from_existing_data() -> bool:
    """Process pre-scraped data and create vector database."""
    try:
        print("📂 Loading pre-scraped data...")
        documents = load_prescrapped_data()
        
        if not documents:
            print("❌ No pre-scraped data found in data/raw/")
            return False
        
        print(f"📄 Processing {len(documents)} documents...")
        
        # Import chunker and vectorstore
        from src.chunker.chunker import chunk_documents
        from src.vectorstore.store import VectorStore
        
        # Chunk documents
        print("✂️ Chunking documents...")
        chunks = chunk_documents(documents)
        print(f"✅ Created {len(chunks)} chunks")
        
        if not chunks:
            print("❌ No chunks created")
            return False
        
        # Initialize vector store
        print("🔮 Initializing vector store...")
        vector_store = VectorStore()
        
        # Add chunks to vector store
        print("💾 Adding chunks to ChromaDB...")
        vector_store.add_documents(chunks)
        
        # Verify
        count = vector_store.count()
        print(f"✅ Vector database ready with {count} chunks!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during ingestion: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import sys
    success = ingest_from_existing_data()
    sys.exit(0 if success else 1)
