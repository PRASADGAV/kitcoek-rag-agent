"""
Setup script to initialize the vector database if it doesn't exist.
This runs automatically on Streamlit Cloud deployment.
"""

import os
import sys
from pathlib import Path


def check_database_exists():
    """Check if ChromaDB vector database exists."""
    chroma_path = os.getenv("CHROMA_DB_PATH", "data/chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION_NAME", "kitcoek")
    
    # Check if directory exists and has files
    db_dir = Path(chroma_path)
    if not db_dir.exists():
        return False
    
    # Check if it has actual data (not just empty directory)
    has_files = any(db_dir.rglob("*"))
    return has_files


def setup_database():
    """Run ingestion if database doesn't exist."""
    if check_database_exists():
        print("✅ Vector database already exists")
        return True
    
    print("⚠️ Vector database not found. Running ingestion...")
    print("This may take 5-10 minutes on first deployment...")
    
    try:
        # Run ingest.py
        import subprocess
        result = subprocess.run(
            [sys.executable, "ingest.py"],
            capture_output=True,
            text=True,
            timeout=900  # 15 minute timeout
        )
        
        if result.returncode == 0:
            print("✅ Database setup complete!")
            return True
        else:
            print(f"❌ Ingestion failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Ingestion timed out (>15 minutes)")
        return False
    except Exception as e:
        print(f"❌ Error during setup: {e}")
        return False


if __name__ == "__main__":
    success = setup_database()
    sys.exit(0 if success else 1)
