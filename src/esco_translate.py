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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def verify_dependencies():
    """Verify that all required dependencies are installed."""
    required_packages = {
        'tiktoken': '>=0.6.0',
        'sentencepiece': '>=0.1.99',
        'protobuf': '<4',
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
    def __init__(self, uri: str, user: str, password: str, device: str = None):
        # Verify dependencies first
        verify_dependencies()
        
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        
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
        
        # Load model and tokenizer with safe initialization
        try:
            # First try the safer T5Tokenizer
            self.tokenizer = T5Tokenizer.from_pretrained("tejagowda/t5-hebrew-translation")
            self.model = T5ForConditionalGeneration.from_pretrained("tejagowda/t5-hebrew-translation")
        except Exception as e:
            logger.warning(f"Failed to load with T5Tokenizer: {str(e)}")
            logger.info("Falling back to AutoTokenizer with legacy mode")
            # Fallback to AutoTokenizer with legacy mode
            self.tokenizer = AutoTokenizer.from_pretrained(
                "tejagowda/t5-hebrew-translation",
                use_fast=False,
                legacy=True
            )
            self.model = AutoModelForSeq2SeqLM.from_pretrained("tejagowda/t5-hebrew-translation")
        
        # Move model to appropriate device
        try:
            self.model = self.model.to(self.device)
            # Test if model works on device
            test_input = self.tokenizer("test", return_tensors="pt").to(self.device)
            with torch.no_grad():
                self.model.generate(test_input["input_ids"], max_length=10)
        except Exception as e:
            logger.warning(f"Error using {self.device}, falling back to CPU: {str(e)}")
            self.device = "cpu"
            self.model = self.model.to(self.device)
            
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
        """Translate English text to Hebrew using the T5 model with retries."""
        for attempt in range(max_retries):
            try:
                inputs = self.tokenizer(text, return_tensors="pt", max_length=512, truncation=True)
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                
                with torch.no_grad():
                    outputs = self.model.generate(
                        inputs["input_ids"],
                        max_length=512,
                        num_beams=4,
                        length_penalty=2.0,
                        early_stopping=True
                    )
                
                # Move output to CPU for decoding
                outputs = outputs.cpu()
                translated = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
                
                # Basic validation
                if not translated or len(translated.strip()) == 0:
                    raise ValueError("Empty translation")
                    
                return translated
                
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to translate after {max_retries} attempts: {str(e)}")
                    raise
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
    parser.add_argument("--uri", default="bolt://localhost:7687", help="Neo4j URI")
    parser.add_argument("--user", default="neo4j", help="Neo4j username")
    parser.add_argument("--password", required=True, help="Neo4j password")
    parser.add_argument("--property", required=True, help="Property to translate")
    parser.add_argument("--type", required=True, choices=["Skill", "Occupation", "SkillGroup", "ISCOGroup"],
                      help="Node type to translate")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for processing")
    parser.add_argument("--suffix", default="_he", help="Suffix for translated property")
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], help="Device to use for translation")

    args = parser.parse_args()

    translator = ESCOTranslator(args.uri, args.user, args.password, args.device)
    try:
        translator.translate_nodes(args.type, args.property, args.batch_size)
    finally:
        translator.close()

if __name__ == "__main__":
    main() 