#!/usr/bin/env python3
import logging
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import os
import shutil
import sys
import glob

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def verify_model_files(cache_dir):
    """Verify that all required model files are present."""
    # Get the actual model directory (it might be in a subdirectory)
    model_dirs = glob.glob(os.path.join(cache_dir, "**", "models--Helsinki-NLP--opus-mt-en-he"), recursive=True)
    if not model_dirs:
        logger.error("Could not find model directory in cache")
        return False
    
    model_dir = model_dirs[0]
    logger.info(f"Found model directory: {model_dir}")
    
    # Find the latest snapshot directory
    snapshot_dirs = glob.glob(os.path.join(model_dir, "snapshots", "*"))
    if not snapshot_dirs:
        logger.error("No snapshot directories found")
        return False
    
    # Use the first snapshot directory (they should be equivalent)
    snapshot_dir = snapshot_dirs[0]
    logger.info(f"Using snapshot directory: {snapshot_dir}")
    
    # List of required files with their possible variations
    required_files = {
        "model": ["model.safetensors", "pytorch_model.bin"],
        "config": ["config.json"],
        "tokenizer": ["tokenizer_config.json", "tokenizer.json"],
        "vocabulary": ["vocab.json"],
        "source_spm": ["source.spm"],
        "target_spm": ["target.spm"]
    }
    
    missing_files = []
    for category, files in required_files.items():
        found = False
        for file in files:
            if os.path.exists(os.path.join(snapshot_dir, file)):
                found = True
                logger.info(f"Found {category} file: {file}")
                break
        if not found:
            missing_files.append(f"{category} ({', '.join(files)})")
    
    if missing_files:
        logger.error(f"Missing required model files: {', '.join(missing_files)}")
        return False
    
    logger.info("All required model files are present")
    return True

def download_model():
    """Download the MarianMT model and tokenizer to local cache."""
    cache_dir = os.path.abspath("./model_cache")
    
    # Create cache directory if it doesn't exist
    os.makedirs(cache_dir, exist_ok=True)
    
    # Clear existing cache if it exists
    if os.path.exists(cache_dir):
        logger.info("Clearing existing model cache...")
        shutil.rmtree(cache_dir)
        os.makedirs(cache_dir)
    
    model_name = "Helsinki-NLP/opus-mt-en-he"
    
    try:
        logger.info(f"Downloading tokenizer to {cache_dir}...")
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            use_fast=False,
            cache_dir=cache_dir,
            local_files_only=False
        )
        logger.info("Tokenizer downloaded successfully")
        
        logger.info(f"Downloading model to {cache_dir}...")
        model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            low_cpu_mem_usage=True,
            local_files_only=False
        )
        logger.info("Model downloaded successfully")
        
        # Verify all required files are present
        if not verify_model_files(cache_dir):
            logger.error("Model download incomplete. Please try again.")
            sys.exit(1)
        
        logger.info("Model download and verification completed successfully")
        
    except Exception as e:
        logger.error(f"Failed to download model: {str(e)}")
        if os.path.exists(cache_dir):
            logger.info("Cleaning up incomplete download...")
            shutil.rmtree(cache_dir)
        sys.exit(1)

if __name__ == "__main__":
    download_model()