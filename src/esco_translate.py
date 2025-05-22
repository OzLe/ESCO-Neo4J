#!/usr/bin/env python3
import argparse
import logging
from typing import List, Optional, Dict
from tqdm import tqdm
from neo4j import GraphDatabase
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, T5Tokenizer, T5ForConditionalGeneration
import torch
from concurrent.futures import ThreadPoolExecutor
import gc
import time
from functools import lru_cache
import platform
import importlib
import yaml
import os
import glob


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.DEBUG)

def verify_dependencies():
    """Verify that all required dependencies are installed."""
    required_packages = {
        'tiktoken': '>=0.6.0',
        'sentencepiece': '>=0.1.99',
        'google.protobuf': '<4',
        'transformers': '>=4.49.1'
    }
    
    missing_packages = []
    for package, version in required_packages.items():
        try:
            importlib.import_module(package)
        except ImportError:
            missing_packages.append(f"{package}{version}")
    
    if missing_packages:
        raise ImportError(
            f"Missing required packages: {', '.join(missing_packages)}\n"
            "Please install them using:\n"
            f"pip install {' '.join(missing_packages)}"
        )

def get_device() -> str:
    """Determine the best available device for the current system."""
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available() and platform.processor() == "arm":
        return "mps"  # M1/M2 Mac
    return "cpu"

class ESCOTranslator:
    def __init__(self, config_path=None, profile='default', device: str = None):
        # Verify dependencies first
        verify_dependencies()
        
        # Load configuration
        if config_path is None:
            config_path = os.path.join('config', 'neo4j_config.yaml')
        
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Get Neo4j configuration for the specified profile
        neo4j_config = self.config[profile]
        
        # Initialize Neo4j driver with configuration
        self.driver = GraphDatabase.driver(
            neo4j_config['uri'],
            auth=(neo4j_config['user'], neo4j_config['password']),
            max_connection_lifetime=neo4j_config['max_connection_lifetime'],
            max_connection_pool_size=neo4j_config['max_connection_pool_size'],
            connection_timeout=neo4j_config['connection_timeout']
        )
        
        # Determine device
        if device is None:
            self.device = get_device()
        else:
            if device == "mps" and not torch.backends.mps.is_available():
                logger.warning("MPS requested but not available, falling back to CPU")
                self.device = "cpu"
            else:
                self.device = device
            
        logger.info(f"Using device: {self.device}")
        
        # Clear any existing CUDA cache
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # Set up model cache directory
        self.cache_dir = os.path.abspath("./model_cache")
        if not os.path.exists(self.cache_dir):
            raise RuntimeError(
                f"Model cache directory not found: {self.cache_dir}\n"
                "Please run 'python src/download_model.py' first to download the model."
            )
        
        # Find the actual model directory
        model_dirs = glob.glob(os.path.join(self.cache_dir, "**", "models--Helsinki-NLP--opus-mt-en-he"), recursive=True)
        if not model_dirs:
            raise RuntimeError(
                "Could not find model directory in cache.\n"
                "Please run 'python src/download_model.py' to download the model."
            )
        
        model_dir = model_dirs[0]
        logger.info(f"Found model directory: {model_dir}")
        
        # Find the latest snapshot directory
        snapshot_dirs = glob.glob(os.path.join(model_dir, "snapshots", "*"))
        if not snapshot_dirs:
            raise RuntimeError(
                "No snapshot directories found in model cache.\n"
                "Please run 'python src/download_model.py' to download the model."
            )
        
        # Use the first snapshot directory (they should be equivalent)
        self.model_dir = snapshot_dirs[0]
        logger.info(f"Using model directory: {self.model_dir}")
        
        # Load model and tokenizer with safe initialization
        try:
            # Use MarianMT model for English to Hebrew translation
            logger.info("Loading tokenizer from local cache...")
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_dir,
                    use_fast=False,
                    local_files_only=True
                )
            except Exception as e:
                logger.error(f"Failed to load tokenizer from cache: {str(e)}")
                raise RuntimeError(
                    "Failed to load tokenizer from cache. "
                    "Please run 'python src/download_model.py' to download the model."
                )
            
            logger.info("Loading model from local cache...")
            # For MPS devices, we need to be more careful with model loading
            if self.device == "mps":
                try:
                    # Clear any existing caches
                    torch.cuda.empty_cache()
                    if torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                    
                    # Load model on CPU first with explicit settings
                    logger.info("Loading model on CPU first...")
                    self.model = AutoModelForSeq2SeqLM.from_pretrained(
                        self.model_dir,
                        torch_dtype=torch.float32,
                        low_cpu_mem_usage=True,
                        local_files_only=True,
                        device_map="cpu"
                    )
                    
                    # Ensure model is in eval mode
                    self.model.eval()
                    
                    # Move to MPS after loading
                    logger.info("Moving model to MPS...")
                    self.model = self.model.to(self.device)
                    
                    # Run a small test to verify MPS compatibility
                    logger.info("Testing model on MPS...")
                    test_input = self.tokenizer("Hello", return_tensors="pt").to(self.device)
                    with torch.no_grad():
                        _ = self.model.generate(**test_input, max_length=10)
                    logger.info("MPS test successful")
                    
                except Exception as e:
                    logger.error(f"Failed to load model on MPS: {str(e)}")
                    logger.info("Falling back to CPU...")
                    self.device = "cpu"
                    # Clear memory before retrying on CPU
                    gc.collect()
                    if torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                    
                    self.model = AutoModelForSeq2SeqLM.from_pretrained(
                        self.model_dir,
                        torch_dtype=torch.float32,
                        low_cpu_mem_usage=True,
                        local_files_only=True,
                        device_map="cpu"
                    )
            else:
                try:
                    # For other devices, load directly to device
                    self.model = AutoModelForSeq2SeqLM.from_pretrained(
                        self.model_dir,
                        torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                        low_cpu_mem_usage=True,
                        device_map=self.device,
                        local_files_only=True
                    )
                except Exception as e:
                    logger.error(f"Failed to load model from cache: {str(e)}")
                    raise RuntimeError(
                        "Failed to load model from cache. "
                        "Please run 'python src/download_model.py' to download the model."
                    )
            
            # Set model to evaluation mode
            self.model.eval()
            
            # Run smoke test with a small batch
            logger.info("Running smoke test...")
            test_input = "Hello, how are you?"
            test_output = self.translate_text(test_input)
            if not test_output:
                raise ValueError("Smoke test failed - translation returned empty result")
            logger.info(f"Smoke test successful. Translated: {test_output}")
            
        except Exception as e:
            logger.error(f"Failed to initialize model: {str(e)}")
            # Clean up any partial initialization
            if hasattr(self, 'model'):
                del self.model
            if hasattr(self, 'tokenizer'):
                del self.tokenizer
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            raise
        
        # Ensure model is in eval mode
        self.model.eval()

    def close(self):
        """Clean up resources."""
        self.driver.close()
        # Clear device cache
        if self.device == "cuda":
            torch.cuda.empty_cache()
        elif self.device == "mps":
            torch.mps.empty_cache()
        gc.collect()

    @lru_cache(maxsize=1000)
    def translate_text(self, text: str, max_retries: int = 3) -> str:
        """Translate English text to Hebrew using the MarianMT model with retries."""
        # Preprocess text to handle potential issues
        text = text.strip()
        if not text:
            return ""
            
        # More aggressive text cleaning
        # Remove any non-ASCII characters that might cause issues
        base_text = ''.join(char for char in text if ord(char) < 128)
        # Normalize whitespace
        base_text = ' '.join(base_text.split())
        
        # Log the text being processed for debugging
        logger.debug(f"Processing text: {base_text}")
        
        for attempt in range(max_retries):
            try:
                # Add prefix for MarianMT model
                prompt = f"translate English to Hebrew: {base_text}"
                
                # Try to tokenize with explicit error handling
                try:
                    inputs = self.tokenizer(
                        prompt,
                        return_tensors="pt",
                        max_length=512,
                        truncation=True,
                        padding=True,
                        add_special_tokens=True
                    )
                except Exception as tokenizer_error:
                    logger.error(f"Tokenizer error: {str(tokenizer_error)}")
                    return text  # Return original text if tokenization fails
                
                # Move inputs to device
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                
                # Generate translation with memory-efficient settings
                with torch.no_grad():
                    try:
                        outputs = self.model.generate(
                            inputs["input_ids"],
                            max_length=512,
                            num_beams=4,
                            length_penalty=2.0,
                            early_stopping=True,
                            do_sample=False,
                            no_repeat_ngram_size=2,
                            use_cache=True
                        )
                    except RuntimeError as e:
                        if "MPS" in str(e):
                            logger.warning("MPS error, falling back to CPU for generation")
                            # Move model and inputs to CPU temporarily
                            self.model = self.model.to("cpu")
                            inputs = {k: v.to("cpu") for k, v in inputs.items()}
                            outputs = self.model.generate(
                                inputs["input_ids"],
                                max_length=512,
                                num_beams=4,
                                length_penalty=2.0,
                                early_stopping=True,
                                do_sample=False,
                                no_repeat_ngram_size=2,
                                use_cache=True
                            )
                            # Move model back to original device
                            self.model = self.model.to(self.device)
                        else:
                            raise
                
                # Move output to CPU for decoding
                outputs = outputs.cpu()
                translated = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
                
                # Basic validation
                if not translated or len(translated.strip()) == 0:
                    logger.warning(f"Empty translation for input: {text}")
                    return text
                    
                return translated
                
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to translate after {max_retries} attempts: {str(e)}")
                    logger.error(f"Problematic text was: {text}")
                    return text
                time.sleep(1)  # Wait before retry

    def get_nodes_to_translate(self, node_type: str, property_name: str) -> List[dict]:
        """Get nodes that need translation."""
        with self.driver.session() as session:
            result = session.run(
                f"""
                MATCH (n:{node_type})
                WHERE n.{property_name} IS NOT NULL
                AND n.{property_name + '_he'} IS NULL
                RETURN n.{property_name} as text, id(n) as node_id
                """
            )
            return [record for record in result]

    def update_node_translation(self, node_id: int, property_name: str, translated_text: str):
        """Update node with translated text."""
        with self.driver.session() as session:
            session.run(
                f"""
                MATCH (n)
                WHERE id(n) = $node_id
                SET n.{property_name + '_he'} = $translated_text
                """,
                node_id=node_id,
                translated_text=translated_text
            )

    def process_batch(self, batch: List[dict], property_name: str) -> Dict[int, str]:
        """Process a batch of nodes in parallel."""
        results = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_node = {
                executor.submit(self.translate_text, node["text"]): node["node_id"]
                for node in batch
            }
            
            for future in future_to_node:
                node_id = future_to_node[future]
                try:
                    translated_text = future.result()
                    results[node_id] = translated_text
                except Exception as e:
                    logger.error(f"Error translating node {node_id}: {str(e)}")
                    
        return results

    def translate_nodes(self, node_type: str, property_name: str, batch_size: int = 100):
        """Translate nodes in batches with improved error handling and performance."""
        nodes = self.get_nodes_to_translate(node_type, property_name)
        total_nodes = len(nodes)
        
        if total_nodes == 0:
            logger.info(f"No nodes found for translation (type: {node_type}, property: {property_name})")
            return

        logger.info(f"Found {total_nodes} nodes to translate")
        
        for i in tqdm(range(0, total_nodes, batch_size), desc="Translating batches"):
            batch = nodes[i:i + batch_size]
            
            # Process batch in parallel
            results = self.process_batch(batch, property_name)
            
            # Update nodes with translations
            for node_id, translated_text in results.items():
                try:
                    self.update_node_translation(node_id, property_name, translated_text)
                except Exception as e:
                    logger.error(f"Error updating node {node_id}: {str(e)}")
            
            # Clear cache periodically
            if i % (batch_size * 10) == 0:
                self.translate_text.cache_clear()
                if self.device == "cuda":
                    torch.cuda.empty_cache()
                elif self.device == "mps":
                    torch.mps.empty_cache()
                gc.collect()

def main():
    parser = argparse.ArgumentParser(description="Translate ESCO node properties to Hebrew")
    parser.add_argument("--config", type=str, help="Path to YAML config file")
    parser.add_argument("--profile", type=str, default='default',
                      choices=['default', 'aura'],
                      help="Configuration profile to use")
    parser.add_argument("--property", required=True, help="Property to translate")
    parser.add_argument("--type", required=True, choices=["Skill", "Occupation", "SkillGroup", "ISCOGroup"],
                      help="Node type to translate")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for processing")
    parser.add_argument("--suffix", default="_he", help="Suffix for translated property")
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], help="Device to use for translation")

    args = parser.parse_args()

    translator = ESCOTranslator(config_path=args.config, profile=args.profile, device=args.device)
    try:
        translator.translate_nodes(args.type, args.property, args.batch_size)
    finally:
        translator.close()

if __name__ == "__main__":
    main() 