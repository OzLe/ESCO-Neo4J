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
from esco_ingest import ESCOIngest
from esco_translate import ESCOTranslator
from download_model import download_model

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
                if args.delete_all:
                    print_section("Deleting Existing Data")
                    ingest = ESCOIngest(args.config, args.profile)
                    ingest.delete_all_data()
                    print(colorize("✓ All data deleted", Colors.GREEN))
                
                print_section("Starting Ingestion")
                if args.embeddings_only:
                    print("Generating embeddings only...")
                    ingest.run_embeddings_only()
                else:
                    print("Running full ingestion...")
                    ingest.run_ingest()
                ingest.close()
                print(colorize("\n✓ Ingestion completed successfully", Colors.GREEN))

            elif args.command == 'search':
                print_header("ESCO Semantic Search")
                print(f"Query: {colorize(args.query, Colors.BOLD)}")
                print(f"Type: {colorize(args.type, Colors.BOLD)}")
                print(f"Threshold: {colorize(str(args.threshold), Colors.BOLD)}")
                
                embedding_util = ESCOEmbedding()
                search_service = ESCOSemanticSearch(driver, embedding_util)
                
                print_section("Searching...")
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

if __name__ == "__main__":
    main() 