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
    """Run ingestion if database doesn't exist - using pre-scraped data only."""
    if check_database_exists():
        print("✅ Vector database already exists")
        return True
    
    print("⚠️ Vector database not found. Creating from pre-scraped data...")
    print("This will take 2-3 minutes on first deployment...")
    
    try:
        # Import and run lightweight ingestion (no Playwright scraping)
        # Just process existing JSON files in data/raw/
        from ingest_prescrapped import ingest_from_existing_data
        success = ingest_from_existing_data()
        
        if success:
            print("✅ Database setup complete!")
            return True
        else:
            print("❌ Ingestion failed - check logs")
            return False
            
    except Exception as e:
        print(f"❌ Error during setup: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = setup_database()
    sys.exit(0 if success else 1)
