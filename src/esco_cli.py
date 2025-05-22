#!/usr/bin/env python3
import argparse
import logging
import os
import yaml
import json
from datetime import datetime
from neo4j import GraphDatabase
from semantic_search import ESCOSemanticSearch
from embedding_utils import ESCOEmbedding
from esco_ingest import create_ingestor
from esco_translate import ESCOTranslator
from download_model import download_model
from logging_config import setup_logging
import click
from pathlib import Path
from typing import Optional
from .weaviate_search import WeaviateSearchEngine
from .weaviate_client import WeaviateClient
from .embedding_utils import generate_embeddings
import pandas as pd

# Setup logging
logger = setup_logging()

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def colorize(text, color):
    """Add color to text if terminal supports it"""
    if os.getenv('NO_COLOR') or not os.isatty(1):
        return text
    return f"{color}{text}{Colors.ENDC}"

def print_header(text):
    """Print a section header"""
    print("\n" + "=" * 80)
    print(colorize(f" {text} ".center(80, "="), Colors.HEADER))
    print("=" * 80 + "\n")

def print_section(text):
    """Print a subsection header"""
    print("\n" + "-" * 80)
    print(colorize(f" {text} ".center(80, "-"), Colors.BLUE))
    print("-" * 80 + "\n")

def print_result(result, index=None):
    """Print a single search result"""
    if index is not None:
        prefix = f"{index}. "
    else:
        prefix = "• "
    
    # Print the main label with type
    type_str = colorize(f"[{result['type']}]", Colors.YELLOW)
    score_str = colorize(f"(Score: {result['score']:.4f})", Colors.GREEN)
    print(f"{prefix}{type_str} {result['label']} {score_str}")
    
    # Print description if available
    if result.get('description'):
        desc = result['description']
        if len(desc) > 100:
            desc = desc[:97] + "..."
        print(f"   {colorize('Description:', Colors.BOLD)} {desc}")

def print_related_nodes(related_graph):
    """Print related nodes in a structured format"""
    if not related_graph:
        return
    
    node = related_graph['node']
    print_section(f"Related entities for '{node['label']}'")
    
    for rel_type, rel_nodes in related_graph['related'].items():
        if not rel_nodes:
            continue
            
        # Format the relationship type
        rel_type_display = rel_type.replace('_', ' ').title()
        count = len(rel_nodes)
        print(f"\n{colorize(rel_type_display, Colors.BOLD)} ({count}):")
        
        # Print first 5 nodes
        for node in rel_nodes[:5]:
            print(f"  • {node['label']}")
        
        # Indicate if there are more
        if count > 5:
            print(f"  ... and {count - 5} more")

def format_json_output(data):
    """Format JSON output with consistent indentation"""
    return json.dumps(data, indent=2, ensure_ascii=False)

def load_config(config_path=None, profile='default'):
    """Load and validate configuration file"""
    if config_path is None:
        # Try to find config in default locations
        default_paths = [
            'config/neo4j_config.yaml',
            '../config/neo4j_config.yaml',
            os.path.expanduser('~/.esco/neo4j_config.yaml')
        ]
        for path in default_paths:
            if os.path.exists(path):
                config_path = path
                break
    
    if not config_path or not os.path.exists(config_path):
        raise FileNotFoundError(
            "Configuration file not found. Please specify --config or ensure "
            "config/neo4j_config.yaml exists."
        )
    
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        raise ValueError(f"Failed to load config file: {str(e)}")
    
    if not isinstance(config, dict):
        raise ValueError("Invalid config file format")
    
    if profile not in config:
        raise ValueError(f"Profile '{profile}' not found in config file")
    
    required_fields = ['uri', 'user', 'password']
    missing_fields = [field for field in required_fields if field not in config[profile]]
    if missing_fields:
        raise ValueError(f"Missing required fields in config: {', '.join(missing_fields)}")
    
    return config

def setup_neo4j_connection(config, profile='default'):
    """Setup Neo4j connection using config parameters"""
    neo4j_config = config[profile]
    return GraphDatabase.driver(
        neo4j_config['uri'],
        auth=(neo4j_config['user'], neo4j_config['password']),
        max_connection_lifetime=neo4j_config.get('max_connection_lifetime', 3600),
        max_connection_pool_size=neo4j_config.get('max_connection_pool_size', 50),
        connection_timeout=neo4j_config.get('connection_timeout', 30)
    )

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
    logging.getLogger('tqdm').setLevel(logging.WARNING)  # Reduce tqdm logging
    logging.getLogger('sentence_transformers').setLevel(logging.WARNING)  # Reduce sentence-transformers logging
    logging.getLogger('transformers').setLevel(logging.WARNING)  # Reduce transformers logging
    
    # Disable tqdm progress bars for specific modules
    import tqdm
    tqdm.tqdm.monitor_interval = 0  # Disable tqdm monitoring
    
    return logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(
        description='ESCO Data Management and Search CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download translation model
  python esco_cli.py download-model

  # Ingest ESCO data
  python esco_cli.py ingest --config config/neo4j_config.yaml

  # Search for skills
  python esco_cli.py search --query "python programming" --type Skill

  # Translate nodes
  python esco_cli.py translate --type Skill --property prefLabel

  # Get help for a specific command
  python esco_cli.py search --help
        """
    )

    # Common Neo4j connection parameters
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument('--config', type=str, help='Path to YAML config file')
    common_parser.add_argument('--profile', type=str, default='default', 
                             choices=['default', 'aura'],
                             help='Configuration profile to use')
    common_parser.add_argument('--quiet', action='store_true',
                             help='Reduce output verbosity')

    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Download model command
    download_parser = subparsers.add_parser('download-model', help='Download translation model')

    # Ingest command
    ingest_parser = subparsers.add_parser('ingest', parents=[common_parser], help='Ingest ESCO data')
    ingest_parser.add_argument('--embeddings-only', action='store_true', help='Only generate embeddings')
    ingest_parser.add_argument('--delete-all', action='store_true', help='Delete all data before ingestion')

    # Search command
    search_parser = subparsers.add_parser('search', parents=[common_parser], help='Search ESCO data')
    search_parser.add_argument('--query', type=str, required=True, help='Text query for semantic search')
    search_parser.add_argument('--type', type=str, choices=['Skill', 'Occupation', 'Both'], default='Both',
                            help='Node type to search')
    search_parser.add_argument('--limit', type=int, default=10, help='Maximum number of results')
    search_parser.add_argument('--related', action='store_true', help='Get related graph for top result')
    search_parser.add_argument('--search-only', action='store_true', 
                            help='Run only the search part without re-indexing')
    search_parser.add_argument('--threshold', type=float, default=0.5,
                            help='Minimum similarity score threshold (0.0 to 1.0)')
    search_parser.add_argument('--json', action='store_true', help='Output results as JSON')
    search_parser.add_argument('--profile-search', action='store_true',
                            help='Perform semantic search and retrieve complete occupation profiles')

    # Translate command
    translate_parser = subparsers.add_parser('translate', parents=[common_parser], help='Translate ESCO data')
    translate_parser.add_argument('--type', type=str, required=True, 
                               choices=['Skill', 'Occupation', 'SkillGroup', 'ISCOGroup'],
                               help='Type of nodes to translate')
    translate_parser.add_argument('--property', type=str, required=True,
                               choices=['prefLabel', 'altLabel', 'description'],
                               help='Property to translate')
    translate_parser.add_argument('--batch-size', type=int, default=100,
                               help='Number of nodes to process in each batch')
    translate_parser.add_argument('--device', type=str, choices=['cpu', 'cuda', 'mps'],
                               help='Device to use for translation')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == 'download-model':
            print_header("Downloading Translation Model")
            download_model()
            print(colorize("\n✓ Model downloaded successfully", Colors.GREEN))
            return

        # For commands that need Neo4j connection
        if args.command in ['ingest', 'search', 'translate']:
            # Load config
            config = load_config(args.config, args.profile)
            
            # Setup Neo4j connection
            driver = setup_neo4j_connection(config, args.profile)

            if args.command == 'ingest':
                print_header("ESCO Data Ingestion")
                ingestor = create_ingestor(args.config, args.profile)
                if args.delete_all:
                    print_section("Deleting Existing Data")
                    ingestor.delete_all_data()
                    print(colorize("✓ All data deleted", Colors.GREEN))
                
                print_section("Starting Ingestion")
                if args.embeddings_only:
                    print("Generating embeddings only...")
                    ingestor.run_embeddings_only()
                else:
                    print("Running full ingestion...")
                    ingestor.run_ingest()
                ingestor.close()
                print(colorize("\n✓ Ingestion completed successfully", Colors.GREEN))

            elif args.command == 'search':
                print_header("ESCO Semantic Search")
                print(f"Query: {colorize(args.query, Colors.BOLD)}")
                print(f"Type: {colorize(args.type, Colors.BOLD)}")
                print(f"Threshold: {colorize(str(args.threshold), Colors.BOLD)}")
                
                embedding_util = ESCOEmbedding()
                search_service = ESCOSemanticSearch(driver, embedding_util)
                
                print_section("Searching...")
                
                if args.profile_search:
                    if args.type != "Occupation":
                        print(colorize("\nWarning: Profile search is only available for Occupation type. Switching to Occupation type.", Colors.YELLOW))
                        args.type = "Occupation"
                    
                    results = search_service.semantic_search_with_profile(
                        args.query,
                        args.limit,
                        args.threshold
                    )
                    
                    if not results:
                        print(colorize("\nNo results found.", Colors.YELLOW))
                        return
                    
                    print_section("Search Results with Profiles")
                    for i, result in enumerate(results, 1):
                        search_result = result['search_result']
                        print_result(search_result, i)
                        print_related_nodes(result['profile'])
                    
                    if args.json:
                        print("\n" + format_json_output({
                            "query": args.query,
                            "parameters": {
                                "limit": args.limit,
                                "similarity_threshold": args.threshold
                            },
                            "results": results
                        }))
                else:
                    results = search_service.search(
                        args.query, 
                        args.type, 
                        args.limit, 
                        args.search_only,
                        args.threshold
                    )

                    if not results:
                        print(colorize("\nNo results found.", Colors.YELLOW))
                        return

                    print_section("Search Results")
                    for i, result in enumerate(results, 1):
                        print_result(result, i)

                    if args.related and results:
                        print_related_nodes(search_service.get_related_graph(results[0]['uri'], results[0]['type']))

                    if args.json:
                        related_graph = None
                        if args.related and results:
                            related_graph = search_service.get_related_graph(results[0]['uri'], results[0]['type'])
                        print("\n" + format_json_output({
                            "query": args.query,
                            "results": results,
                            "related_graph": related_graph
                        }))

            elif args.command == 'translate':
                print_header("ESCO Translation")
                print(f"Type: {colorize(args.type, Colors.BOLD)}")
                print(f"Property: {colorize(args.property, Colors.BOLD)}")
                print(f"Batch Size: {colorize(str(args.batch_size), Colors.BOLD)}")
                if args.device:
                    print(f"Device: {colorize(args.device, Colors.BOLD)}")
                
                print_section("Starting Translation")
                translator = ESCOTranslator(args.config, args.profile, args.device)
                translator.translate_nodes(args.type, args.property, args.batch_size)
                translator.close()
                print(colorize("\n✓ Translation completed successfully", Colors.GREEN))

    except Exception as e:
        print(colorize(f"\nError: {str(e)}", Colors.RED))
        raise
    finally:
        if 'driver' in locals():
            driver.close()

@click.group()
def cli():
    """ESCO Data Management and Search Tool"""
    pass

@cli.command()
@click.option('--db-type', type=click.Choice(['neo4j', 'weaviate']), required=True,
              help='Type of database to ingest into')
@click.option('--config', type=str, help='Path to configuration file')
@click.option('--profile', default='default', help='Configuration profile to use')
@click.option('--delete-all', is_flag=True, help='Delete all existing data before ingestion')
@click.option('--embeddings-only', is_flag=True, help='Run only the embedding generation and indexing')
def ingest(db_type: str, config: str, profile: str, delete_all: bool, embeddings_only: bool):
    """Ingest ESCO data into the specified database."""
    try:
        # Create ingestor instance
        ingestor = create_ingestor(db_type, config, profile)
        
        if delete_all:
            click.echo("Deleting all existing data...")
            ingestor.delete_all_data()
        
        # Run appropriate process
        if embeddings_only:
            click.echo("Running embeddings-only mode...")
            ingestor.run_embeddings_only()
        else:
            click.echo("Running full ingestion...")
            ingestor.run_ingest()
        
        click.echo("Ingestion completed successfully!")
        
    except Exception as e:
        logger.error(f"Ingestion failed: {str(e)}")
        raise click.ClickException(str(e))
    finally:
        ingestor.close()

@cli.command()
@click.option('--query', required=True, help='Search query')
@click.option('--limit', default=10, help='Maximum number of results')
@click.option('--certainty', default=0.75, help='Minimum similarity threshold (0-1)')
@click.option('--config', default='config/weaviate_config.yaml', help='Path to Weaviate configuration file')
@click.option('--profile', default='default', help='Configuration profile to use')
@click.option('--json', is_flag=True, help='Output results in JSON format')
def search_weaviate(query: str, limit: int, certainty: float, config: str, profile: str, json: bool):
    """Search ESCO data using Weaviate."""
    try:
        # Initialize search engine
        engine = WeaviateSearchEngine(config, profile)
        
        # Perform search
        results = engine.search(
            query=query,
            limit=limit,
            certainty=certainty
        )
        
        # Output results
        if json:
            click.echo(json.dumps(results, indent=2))
        else:
            click.echo(engine.format_results(results))
            
    except Exception as e:
        logger.error(f"Search failed: {str(e)}")
        raise click.ClickException(str(e))

if __name__ == "__main__":
    main() 