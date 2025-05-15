import argparse
import json
from neo4j import GraphDatabase
from semantic_search import ESCOSemanticSearch
from embedding_utils import ESCOEmbedding
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description='ESCO Semantic Search')
    
    # Command-line arguments
    parser.add_argument('--query', type=str, required=True, help='Text query for semantic search')
    parser.add_argument('--type', type=str, choices=['Skill', 'Occupation', 'Both'], default='Both',
                      help='Node type to search')
    parser.add_argument('--limit', type=int, default=10, help='Maximum number of results')
    parser.add_argument('--related', action='store_true', help='Get related graph for top result')
    parser.add_argument('--search-only', action='store_true', 
                      help='Run only the search part without re-indexing (assumes data is already indexed)')
    parser.add_argument('--threshold', type=float, default=0.5,
                      help='Minimum similarity score threshold (0.0 to 1.0, default: 0.5)')
    
    # Neo4j connection parameters
    parser.add_argument('--uri', type=str, default='bolt://localhost:7687', help='Neo4j URI')
    parser.add_argument('--user', type=str, default='neo4j', help='Neo4j username')
    parser.add_argument('--password', type=str, required=True, help='Neo4j password')
    
    # Output format
    parser.add_argument('--json', action='store_true', help='Output results as JSON')
    
    args = parser.parse_args()
    
    # Connect to Neo4j
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    
    try:
        # Initialize services
        embedding_util = ESCOEmbedding()
        search_service = ESCOSemanticSearch(driver, embedding_util)
        
        # Perform search
        logger.info(f"Searching for '{args.query}' in {args.type} nodes...")
        try:
            results = search_service.search(
                args.query, 
                args.type, 
                args.limit, 
                args.search_only,
                args.threshold
            )
        except ValueError as e:
            logger.error(str(e))
            return
        
        if not results:
            logger.info("No results found.")
            return
        
        # Get related graph for top result if requested
        related_graph = None
        if args.related and results:
            top_result = results[0]
            logger.info(f"Getting related graph for {top_result['label']}...")
            related_graph = search_service.get_related_graph(top_result['uri'], top_result['type'])
        
        # Output results
        if args.json:
            # JSON output
            output = {
                "query": args.query,
                "results": results,
                "related_graph": related_graph
            }
            print(json.dumps(output, indent=2))
        else:
            # Console output
            print(f"\nSearch results for '{args.query}':")
            for i, result in enumerate(results):
                print(f"{i+1}. [{result['type']}] {result['label']} (Score: {result['score']:.4f})")
                if result['description']:
                    print(f"   Description: {result['description'][:100]}...")
            
            if related_graph:
                print(f"\nRelated entities for '{related_graph['node']['label']}':")
                for rel_type, rel_nodes in related_graph['related'].items():
                    if rel_nodes:
                        print(f"\n{rel_type.replace('_', ' ').title()} ({len(rel_nodes)}):")
                        for i, node in enumerate(rel_nodes[:5]):  # Show first 5 only
                            print(f"  - {node['label']}")
                        if len(rel_nodes) > 5:
                            print(f"  ... and {len(rel_nodes) - 5} more")
    
    finally:
        driver.close()

if __name__ == "__main__":
    main()