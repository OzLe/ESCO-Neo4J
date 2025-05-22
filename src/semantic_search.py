import logging
from embedding_utils import ESCOEmbedding
from logging_config import setup_logging

# Setup logging
logger = setup_logging()

class ESCOSemanticSearch:
    def __init__(self, driver, embedding_util=None):
        """Initialize with Neo4j driver and optional embedding utility"""
        self.driver = driver
        self.embedding_util = embedding_util or ESCOEmbedding()
    
    def is_data_indexed(self, node_type="Skill"):
        """Check if the data is already indexed with embeddings"""
        with self.driver.session() as session:
            if node_type == "Skill":
                result = session.run("""
                    MATCH (s:Skill)
                    WHERE s.embedding IS NOT NULL
                    RETURN count(s) as count
                """)
            elif node_type == "Occupation":
                result = session.run("""
                    MATCH (o:Occupation)
                    WHERE o.embedding IS NOT NULL
                    RETURN count(o) as count
                """)
            else:
                result = session.run("""
                    MATCH (n)
                    WHERE (n:Skill OR n:Occupation) AND n.embedding IS NOT NULL
                    RETURN count(n) as count
                """)
            
            count = result.single()["count"]
            return count > 0
        
    def search(self, query_text, node_type="Skill", limit=10, search_only=False, similarity_threshold=0.5):
        """Search for semantically similar nodes
        
        Args:
            query_text (str): The text to search for
            node_type (str): Type of nodes to search ("Skill", "Occupation", or "Both")
            limit (int): Maximum number of results to return
            search_only (bool): If True, only perform search without re-indexing
            similarity_threshold (float): Minimum similarity score (0.0 to 1.0)
        """
        # Check if data is indexed if in search-only mode
        if search_only and not self.is_data_indexed(node_type):
            raise ValueError("Data is not indexed. Please run the full pipeline first or disable search-only mode.")
        
        # Generate query embedding
        query_embedding = self.embedding_util.generate_text_embedding(query_text)
        if not query_embedding:
            logging.error("Failed to generate embedding for query text")
            return []
        
        with self.driver.session() as session:
            # Perform vector search in Neo4j
            if node_type == "Skill":
                result = session.run("""
                    MATCH (s:Skill)
                    WHERE s.embedding IS NOT NULL
                    WITH s, vector.similarity.cosine(s.embedding, $query_embedding) AS score
                    WHERE score > $threshold
                    RETURN s.conceptUri AS uri, s.preferredLabel AS label, 
                           s.description AS description, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, query_embedding=query_embedding, limit=limit, threshold=similarity_threshold)
            elif node_type == "Occupation":
                result = session.run("""
                    MATCH (o:Occupation)
                    WHERE o.embedding IS NOT NULL
                    WITH o, vector.similarity.cosine(o.embedding, $query_embedding) AS score
                    WHERE score > $threshold
                    RETURN o.conceptUri AS uri, o.preferredLabel AS label, 
                           o.description AS description, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, query_embedding=query_embedding, limit=limit, threshold=similarity_threshold)
            else:
                # Search both skills and occupations
                result = session.run("""
                    MATCH (n)
                    WHERE (n:Skill OR n:Occupation) AND n.embedding IS NOT NULL
                    WITH n, 
                         labels(n)[0] AS type,
                         vector.similarity.cosine(n.embedding, $query_embedding) AS score
                    WHERE score > $threshold
                    RETURN n.conceptUri AS uri, n.preferredLabel AS label, 
                           n.description AS description, type, score
                    ORDER BY score DESC
                    LIMIT $limit
                """, query_embedding=query_embedding, limit=limit, threshold=similarity_threshold)
            
            # Process results
            search_results = []
            for record in result:
                search_results.append({
                    "uri": record["uri"],
                    "label": record["label"],
                    "description": record.get("description", ""),
                    "type": record.get("type", node_type),
                    "score": record["score"]
                })
            
            return search_results
    
    def get_related_graph(self, uri, node_type="Skill"):
        """Get related graph for a node"""
        with self.driver.session() as session:
            if node_type == "Skill":
                result = session.run("""
                    MATCH (s:Skill {conceptUri: $uri})
                    OPTIONAL MATCH (s)-[r1:ESSENTIAL_FOR]->(o:Occupation)
                    OPTIONAL MATCH (s)-[r2:OPTIONAL_FOR]->(o2:Occupation)
                    OPTIONAL MATCH (s)-[r3:RELATED_SKILL]-(s2:Skill)
                    OPTIONAL MATCH (s)-[r4:BROADER_THAN]->(s3:Skill)
                    OPTIONAL MATCH (s)<-[r5:BROADER_THAN]-(s4:Skill)
                    RETURN s AS node,
                           collect(DISTINCT o) AS essential_occupations,
                           collect(DISTINCT o2) AS optional_occupations,
                           collect(DISTINCT s2) AS related_skills,
                           collect(DISTINCT s3) AS broader_skills,
                           collect(DISTINCT s4) AS narrower_skills
                """, uri=uri)
            elif node_type == "Occupation":
                result = session.run("""
                    MATCH (o:Occupation {conceptUri: $uri})
                    OPTIONAL MATCH (s1:Skill)-[r1:ESSENTIAL_FOR]->(o)
                    OPTIONAL MATCH (s2:Skill)-[r2:OPTIONAL_FOR]->(o)
                    OPTIONAL MATCH (o)-[r3:PART_OF_ISCOGROUP]->(i:ISCOGroup)
                    OPTIONAL MATCH (o)-[r4:BROADER_THAN]->(o2:Occupation)
                    OPTIONAL MATCH (o)<-[r5:BROADER_THAN]-(o3:Occupation)
                    RETURN o AS node,
                           collect(DISTINCT s1) AS essential_skills,
                           collect(DISTINCT s2) AS optional_skills,
                           collect(DISTINCT i) AS isco_groups,
                           collect(DISTINCT o2) AS broader_occupations,
                           collect(DISTINCT o3) AS narrower_occupations
                """, uri=uri)
            
            # Format the result as structured data
            results = result.single()
            if not results:
                return None
                
            # Process results into a structured format
            graph_data = {
                "node": self._format_node(results["node"]),
                "related": {}
            }
            
            if node_type == "Skill":
                graph_data["related"]["essential_occupations"] = self._format_nodes(results["essential_occupations"])
                graph_data["related"]["optional_occupations"] = self._format_nodes(results["optional_occupations"])
                graph_data["related"]["related_skills"] = self._format_nodes(results["related_skills"])
                graph_data["related"]["broader_skills"] = self._format_nodes(results["broader_skills"])
                graph_data["related"]["narrower_skills"] = self._format_nodes(results["narrower_skills"])
            else:
                graph_data["related"]["essential_skills"] = self._format_nodes(results["essential_skills"])
                graph_data["related"]["optional_skills"] = self._format_nodes(results["optional_skills"])
                graph_data["related"]["isco_groups"] = self._format_nodes(results["isco_groups"])
                graph_data["related"]["broader_occupations"] = self._format_nodes(results["broader_occupations"])
                graph_data["related"]["narrower_occupations"] = self._format_nodes(results["narrower_occupations"])
            
            return graph_data
    
    def _format_node(self, node):
        """Format node data for output"""
        if not node:
            return None
        return {
            "uri": node.get("conceptUri"),
            "label": node.get("preferredLabel"),
            "description": node.get("description", "")
        }
    
    def _format_nodes(self, nodes):
        """Format multiple nodes for output"""
        return [self._format_node(node) for node in nodes if node]

    def semantic_search_with_profile(self, query_text, limit=10, similarity_threshold=0.5):
        """Perform semantic search and retrieve complete occupation profiles
        
        Args:
            query_text (str): The text to search for
            limit (int): Maximum number of results to return
            similarity_threshold (float): Minimum similarity score (0.0 to 1.0)
            
        Returns:
            list: List of dictionaries containing search results with complete occupation profiles
        """
        # First hop: Perform semantic search for occupations
        search_results = self.search(
            query_text=query_text,
            node_type="Occupation",
            limit=limit,
            similarity_threshold=similarity_threshold
        )
        
        # Second hop: Retrieve complete profiles for each result
        complete_results = []
        for result in search_results:
            profile = self.get_related_graph(result["uri"], node_type="Occupation")
            if profile:
                # Combine search result with complete profile
                complete_result = {
                    "search_result": result,
                    "profile": profile
                }
                complete_results.append(complete_result)
        
        return complete_results