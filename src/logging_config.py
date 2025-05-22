import logging
import os

def setup_logging(level=logging.INFO):
    """Setup logging configuration for all modules
    
    Args:
        level (int): Logging level (default: logging.INFO)
    """
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Configure logging format
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Configure root logger
    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=[
            logging.StreamHandler(),  # Console handler
            logging.FileHandler('logs/esco.log')  # File handler
        ]
    )
    
    # Set specific logger levels
    logging.getLogger('neo4j').setLevel(logging.WARNING)  # Reduce Neo4j driver logging
    logging.getLogger('urllib3').setLevel(logging.WARNING)  # Reduce urllib3 logging
    
    return logging.getLogger(__name__) 