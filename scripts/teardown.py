#!/usr/bin/env python3
"""Teardown script for YouHoard development environment"""

import os
import shutil
from pathlib import Path

def teardown(remove_storage=False):
    """Remove all application state for fresh development start"""
    
    # Remove database files
    for db_file in ["youhoard.db", "youhoard.db-journal"]:
        if os.path.exists(db_file):
            os.remove(db_file)
            print(f"Removed {db_file}")
    
    # Clear storage directory
    if remove_storage:
        storage_path = Path("storage")
        if storage_path.exists():
            shutil.rmtree(storage_path)
            print("Cleared storage directory")
    
    print("✅ Teardown complete")

if __name__ == "__main__":
    teardown() 