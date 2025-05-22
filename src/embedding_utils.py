from sentence_transformers import SentenceTransformer
import logging
from tqdm import tqdm
from typing import List, Dict, Any
import sys

class ESCOEmbedding:
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        """Initialize with a sentence transformer model"""
        self.model = SentenceTransformer(model_name)
        self.vector_dim = self.model.get_sentence_embedding_dimension()
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initialized embedding model: {model_name} (dim: {self.vector_dim})")
        
    def generate_text_embedding(self, text):
        """Generate embedding for a single text"""
        if not text:
            return None
        # Disable SentenceTransformers' internal progress bar to keep output clean
        return self.model.encode(text, show_progress_bar=False).tolist()
    
    def generate_node_embedding(self, node_data):
        """Generate embedding from node data combining label and description"""
        label = node_data.get('preferredLabel', '')
        desc = node_data.get('description', '')
        alt_labels = node_data.get('altLabels', '')
        
        # Combine text fields for richer embedding
        text = f"{label}. {alt_labels}. {desc}".strip()
        if not text:
            return None
            
        return self.generate_text_embedding(text)
    
    def generate_batch_embeddings(self, nodes: List[Dict[str, Any]], batch_size: int = 1) -> List[Dict[str, Any]]:
        """
        Generate embeddings for a batch of nodes with progress tracking
        
        Args:
            nodes: List of node dictionaries containing text data
            batch_size: Number of nodes to process at once (default: 1 for one-by-one processing)
            
        Returns:
            List of dictionaries containing the original node data and their embeddings
        """
        total_nodes = len(nodes)
        self.logger.info(f"Starting batch embedding generation for {total_nodes} nodes")
        
        results = []
        processed_count = 0
        failed_count = 0
        
        # Show a single clean progress bar for the whole batch
        with tqdm(
            total=total_nodes,
            desc="Generating embeddings",
            unit="nodes",
            dynamic_ncols=True,
            smoothing=0.1,
            disable=False,      # Force display even in non‑TTY contexts
            leave=True
        ) as pbar:
            for i in range(0, total_nodes, batch_size):
                batch = nodes[i:i + batch_size]
                
                for node in batch:
                    try:
                        embedding = self.generate_node_embedding(node)
                        if embedding:
                            node['embedding'] = embedding
                            results.append(node)
                        else:
                            failed_count += 1
                            self.logger.warning(f"Failed to generate embedding for node: {node.get('preferredLabel', 'Unknown')}")
                    except Exception as e:
                        failed_count += 1
                        self.logger.error(f"Error generating embedding for node {node.get('preferredLabel', 'Unknown')}: {str(e)}")
                    
                    processed_count += 1
                    pbar.update(1)
                    
                    # Log progress every 1000 nodes instead of 100
                    if processed_count % 1000 == 0 or processed_count == total_nodes:
                        self.logger.info(f"Processed {processed_count}/{total_nodes} nodes (Success: {len(results)}, Failed: {failed_count})")
        
        success_rate = (len(results) / total_nodes) * 100
        self.logger.info(f"Completed embedding generation. Success rate: {success_rate:.2f}% ({len(results)}/{total_nodes} nodes, Failed: {failed_count})")
        return results