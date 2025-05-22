import os
import pandas as pd
from tqdm import tqdm
import logging
import argparse
import json
import yaml
from datetime import datetime
from neo4j import GraphDatabase
from neo4j_client import Neo4jClient
from embedding_utils import ESCOEmbedding
from logging_config import setup_logging

# ESCO v1.2.0 (English) – CSV classification import for Neo4j 5.x
# Oz Levi
# 2025-05-11

# Setup logging
logger = setup_logging()

class ESCOIngest:
    def __init__(self, config_path=None, profile='default'):
        """
        Initialize ESCO data ingestion
        
        Args:
            config_path (str): Path to YAML config file
            profile (str): Configuration profile to use ('default' or 'aura')
        """
        self.client = Neo4jClient(config_path, profile)
        self.config = self.client.config
        self.esco_dir = self.config['esco']['data_dir']
        
        # Use different batch sizes based on profile
        if profile == 'aura':
            # Smaller batch size for AuraDB to avoid timeouts
            self.batch_size = 1000
        else:
            # Larger batch size for local connections
            self.batch_size = self.config['esco']['batch_size']
        
        logger.info(f"Using batch size of {self.batch_size} for {profile} profile")

    def close(self):
        """Close the database connection"""
        self.client.close()

    def delete_all_data(self):
        """Delete all nodes and relationships from the database"""
        with self.client.driver.session() as session:
            # First drop all constraints
            constraints = [
                "DROP CONSTRAINT skill_uri IF EXISTS",
                "DROP CONSTRAINT skillgroup_uri IF EXISTS",
                "DROP CONSTRAINT occupation_uri IF EXISTS",
                "DROP CONSTRAINT iscogroup_uri IF EXISTS",
                "DROP CONSTRAINT iscogroup_code IF EXISTS"
            ]
            for constraint in constraints:
                self.client.execute_query(constraint, session=session)
            
            # Then delete all nodes and relationships
            query = "MATCH (n) DETACH DELETE n"
            self.client.execute_query(query, session=session)
            logger.info("Deleted all data from the database")

    def create_constraints(self):
        with self.client.driver.session() as session:
            constraints = [
                "CREATE CONSTRAINT skill_uri IF NOT EXISTS FOR (s:Skill) REQUIRE s.conceptUri IS UNIQUE",
                "CREATE CONSTRAINT skillgroup_uri IF NOT EXISTS FOR (sg:SkillGroup) REQUIRE sg.conceptUri IS UNIQUE",
                "CREATE CONSTRAINT occupation_uri IF NOT EXISTS FOR (o:Occupation) REQUIRE o.conceptUri IS UNIQUE",
                "CREATE CONSTRAINT iscogroup_uri IF NOT EXISTS FOR (g:ISCOGroup) REQUIRE g.conceptUri IS UNIQUE",
                "CREATE CONSTRAINT iscogroup_code IF NOT EXISTS FOR (g:ISCOGroup) REQUIRE g.code IS UNIQUE"
            ]
            for constraint in constraints:
                self.client.execute_query(constraint, session=session)
            logger.info("Created constraints")

    def process_csv_in_batches(self, file_path, process_func):
        """Process a CSV file in batches"""
        df = pd.read_csv(file_path)
        total_rows = len(df)
        
        with tqdm(total=total_rows, desc=f"Processing {os.path.basename(file_path)}", unit="rows",
                 bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]') as pbar:
            for start_idx in range(0, total_rows, self.batch_size):
                end_idx = min(start_idx + self.batch_size, total_rows)
                batch = df.iloc[start_idx:end_idx]
                process_func(batch)
                pbar.update(len(batch))

    def ingest_skill_groups(self):
        def process_batch(batch):
            with self.client.driver.session() as session:
                for _, row in batch.iterrows():
                    query = """
                    MERGE (sg:Skill:SkillGroup {conceptUri: $conceptUri})
                    SET sg += $properties
                    """
                    self.client.execute_query(query, 
                        parameters={'conceptUri': row['conceptUri'], 'properties': row.to_dict()},
                        session=session)

        file_path = os.path.join(self.esco_dir, 'skillGroups_en.csv')
        self.process_csv_in_batches(file_path, process_batch)
        logger.info("Ingested skill groups")

    def ingest_skills(self):
        def process_batch(batch):
            with self.client.driver.session() as session:
                for _, row in batch.iterrows():
                    query = """
                    MERGE (s:Skill {conceptUri: $conceptUri})
                    SET s += $properties
                    """
                    self.client.execute_query(query, 
                        parameters={'conceptUri': row['conceptUri'], 'properties': row.to_dict()},
                        session=session)

        file_path = os.path.join(self.esco_dir, 'skills_en.csv')
        self.process_csv_in_batches(file_path, process_batch)
        logger.info("Ingested skills")

    def ingest_occupations(self):
        def process_batch(batch):
            with self.client.driver.session() as session:
                for _, row in batch.iterrows():
                    query = """
                    MERGE (o:Occupation {conceptUri: $conceptUri})
                    SET o += $properties
                    """
                    self.client.execute_query(query, 
                        parameters={'conceptUri': row['conceptUri'], 'properties': row.to_dict()},
                        session=session)

        file_path = os.path.join(self.esco_dir, 'occupations_en.csv')
        self.process_csv_in_batches(file_path, process_batch)
        logger.info("Ingested occupations")

    def ingest_isco_groups(self):
        def process_batch(batch):
            with self.client.driver.session() as session:
                # First, ensure we don't have duplicate codes
                batch = batch.drop_duplicates(subset=['code'], keep='first')
                
                for _, row in batch.iterrows():
                    # First create the node without the code
                    query = """
                    MERGE (g:ISCOGroup {conceptUri: $conceptUri})
                    SET g += $properties
                    """
                    properties = row.to_dict()
                    code = properties.pop('code', None)  # Remove code from properties
                    self.client.execute_query(query, 
                        parameters={'conceptUri': row['conceptUri'], 'properties': properties},
                        session=session)
                    
                    # Then update the code if it exists
                    if code is not None:
                        update_query = """
                        MATCH (g:ISCOGroup {conceptUri: $conceptUri})
                        SET g.code = $code
                        """
                        self.client.execute_query(update_query, 
                            parameters={'conceptUri': row['conceptUri'], 'code': code},
                            session=session)

        file_path = os.path.join(self.esco_dir, 'ISCOGroups_en.csv')
        self.process_csv_in_batches(file_path, process_batch)
        logger.info("Ingested ISCO groups")

    def create_skill_hierarchy(self):
        def process_batch(batch):
            with self.client.driver.session() as session:
                # Convert batch to list of dictionaries
                data = batch[['conceptUri', 'broaderUri']].to_dict('records')
                
                query = """
                UNWIND $data as row
                MATCH (child:Skill {conceptUri: row.conceptUri})
                MATCH (parent:Skill {conceptUri: row.broaderUri})
                MERGE (parent)-[:BROADER_THAN]->(child)
                """
                self.client.execute_query(query, data=data, session=session)

        file_path = os.path.join(self.esco_dir, 'broaderRelationsSkillPillar_en.csv')
        self.process_csv_in_batches(file_path, process_batch)
        logger.info("Created skill hierarchy")

    def create_isco_hierarchy(self):
        def process_batch(batch):
            with self.client.driver.session() as session:
                # Convert batch to list of dictionaries
                data = batch[['conceptUri', 'broaderUri']].to_dict('records')
                
                query = """
                UNWIND $data as row
                MATCH (child:ISCOGroup {conceptUri: row.conceptUri})
                MATCH (parent:ISCOGroup {conceptUri: row.broaderUri})
                MERGE (parent)-[:BROADER_THAN]->(child)
                """
                self.client.execute_query(query, data=data, session=session)

        file_path = os.path.join(self.esco_dir, 'broaderRelationsOccPillar_en.csv')
        self.process_csv_in_batches(file_path, process_batch)
        logger.info("Created ISCO hierarchy")

    def create_occupation_isco_mapping(self):
        with self.client.driver.session() as session:
            query = """
            MATCH (o:Occupation)
            WITH o, o.iscoGroup as iscoCode
            MATCH (g:ISCOGroup {code: iscoCode})
            MERGE (o)-[:PART_OF_ISCOGROUP]->(g)
            """
            self.client.execute_query(query, session=session)
            logger.info("Created occupation-ISCO mapping")

    def create_occupation_skill_relations(self):
        def process_batch(batch):
            with self.client.driver.session() as session:
                # Prepare batch data for essential relations
                essential_data = batch[batch['relationType'] == 'essential'][['skillUri', 'occupationUri']].to_dict('records')
                # Prepare batch data for optional relations
                optional_data = batch[batch['relationType'] == 'optional'][['skillUri', 'occupationUri']].to_dict('records')
                
                # Process essential relations in batch
                if essential_data:
                    query = """
                    UNWIND $data as row
                    MATCH (s:Skill {conceptUri: row.skillUri})
                    MATCH (o:Occupation {conceptUri: row.occupationUri})
                    MERGE (s)-[:ESSENTIAL_FOR]->(o)
                    """
                    self.client.execute_query(query, data=essential_data, session=session)
                
                # Process optional relations in batch
                if optional_data:
                    query = """
                    UNWIND $data as row
                    MATCH (s:Skill {conceptUri: row.skillUri})
                    MATCH (o:Occupation {conceptUri: row.occupationUri})
                    MERGE (s)-[:OPTIONAL_FOR]->(o)
                    """
                    self.client.execute_query(query, data=optional_data, session=session)

        file_path = os.path.join(self.esco_dir, 'occupationSkillRelations_en.csv')
        self.process_csv_in_batches(file_path, process_batch)
        logger.info("Created occupation-skill relations")

    def create_skill_skill_relations(self):
        def process_batch(batch):
            with self.client.driver.session() as session:
                # Convert batch to list of dictionaries
                data = batch[['originalSkillUri', 'relatedSkillUri', 'relationType']].to_dict('records')
                
                query = """
                UNWIND $data as row
                MATCH (a:Skill {conceptUri: row.originalSkillUri})
                MATCH (b:Skill {conceptUri: row.relatedSkillUri})
                MERGE (a)-[:RELATED_SKILL {type: row.relationType}]->(b)
                """
                self.client.execute_query(query, data=data, session=session)

        file_path = os.path.join(self.esco_dir, 'skillSkillRelations_en.csv')
        self.process_csv_in_batches(file_path, process_batch)
        logger.info("Created skill-skill relations")

    def create_vector_indexes(self):
        """Create vector indexes for Neo4j vector search if supported"""
        try:
            with self.client.driver.session() as session:
                # Check Neo4j version
                version_result = session.run("CALL dbms.components() YIELD versions").single()
                version = version_result['versions'][0]
                major, minor, patch = map(int, version.split('.')[:3])
                
                if major > 5 or (major == 5 and minor >= 15):
                    # New vector index syntax for Neo4j 5.15+
                    session.run("""
                        CREATE VECTOR INDEX skill_embedding IF NOT EXISTS
                        FOR (s:Skill)
                        ON (s.embedding)
                        OPTIONS {
                            indexConfig: {
                                `vector.dimensions`: 384,
                                `vector.similarity_function`: 'cosine'
                            }
                        }
                    """)
                    
                    session.run("""
                        CREATE VECTOR INDEX occupation_embedding IF NOT EXISTS
                        FOR (o:Occupation)
                        ON (o.embedding)
                        OPTIONS {
                            indexConfig: {
                                `vector.dimensions`: 384,
                                `vector.similarity_function`: 'cosine'
                            }
                        }
                    """)
                elif major == 5 and minor >= 11:
                    # Old vector index syntax for Neo4j 5.11-5.14
                    session.run("""
                        CALL db.index.vector.createNodeIndex(
                            'skill_embedding',
                            'Skill',
                            'embedding',
                            384,
                            'cosine'
                        )
                    """)
                    
                    session.run("""
                        CALL db.index.vector.createNodeIndex(
                            'occupation_embedding',
                            'Occupation',
                            'embedding',
                            384,
                            'cosine'
                        )
                    """)
                else:
                    logger.warning(f"Vector indexes are not supported in Neo4j version {version}. Skipping vector index creation.")
                
                logger.info("Created vector indexes for semantic search")
        except Exception as e:
            logger.warning(f"Could not create vector indexes: {str(e)}. Continuing without vector indexes.")

    def generate_and_store_embeddings(self, embedding_util):
        """Generate embeddings for all skills and occupations"""
        # Get total count of nodes to process
        with self.client.driver.session() as session:
            # Get total count of skills and occupations
            count_query = """
                MATCH (n)
                WHERE n:Skill OR n:Occupation
                RETURN count(n) as count
            """
            total_nodes = session.run(count_query).single()["count"]
            
            # Create a single progress bar for all nodes
            with tqdm(total=total_nodes, desc="Generating embeddings", unit="nodes",
                     bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]') as pbar:
                
                # Process skills
                logger.info("Generating embeddings for skills")
                query = "MATCH (s:Skill) RETURN s.conceptUri as uri, s.preferredLabel as label, s.description as description, s.altLabels as altLabels"
                result = session.run(query)
                
                for record in result:
                    node_data = {
                        'preferredLabel': record['label'],
                        'description': record['description'],
                        'altLabels': record['altLabels']
                    }
                    
                    embedding = embedding_util.generate_node_embedding(node_data)
                    if embedding:
                        # Store embedding back in Neo4j
                        session.run(
                            "MATCH (s:Skill {conceptUri: $uri}) SET s.embedding = $embedding",
                            uri=record['uri'], embedding=embedding
                        )
                    pbar.update(1)
                
                # Process occupations
                logger.info("Generating embeddings for occupations")
                query = "MATCH (o:Occupation) RETURN o.conceptUri as uri, o.preferredLabel as label, o.description as description, o.altLabels as altLabels"
                result = session.run(query)
                
                for record in result:
                    node_data = {
                        'preferredLabel': record['label'],
                        'description': record['description'],
                        'altLabels': record['altLabels']
                    }
                    
                    embedding = embedding_util.generate_node_embedding(node_data)
                    if embedding:
                        session.run(
                            "MATCH (o:Occupation {conceptUri: $uri}) SET o.embedding = $embedding",
                            uri=record['uri'], embedding=embedding
                        )
                    pbar.update(1)
        
        logger.info("Completed embedding generation and storage")

    def run_ingest(self):
        """Run the complete ingestion process"""
        try:
            self.delete_all_data()  # Delete all data before starting
            self.create_constraints()
            self.ingest_skill_groups()
            self.ingest_skills()
            self.ingest_occupations()
            self.ingest_isco_groups()
            self.create_skill_hierarchy()
            self.create_isco_hierarchy()
            self.create_occupation_isco_mapping()
            self.create_occupation_skill_relations()
            self.create_skill_skill_relations()
            
            # Add vector indexes for semantic search (if supported)
            self.create_vector_indexes()
            
            # Generate embeddings
            from embedding_utils import ESCOEmbedding
            embedding_util = ESCOEmbedding()
            self.generate_and_store_embeddings(embedding_util)
            
            logger.info("ESCO data ingestion completed successfully")
        except Exception as e:
            logger.error(f"Error during ingestion: {str(e)}")
            raise
        finally:
            self.close()

    def run_embeddings_only(self):
        """Run only the embedding generation and indexing for semantic search"""
        try:
            # Create vector indexes (if supported)
            self.create_vector_indexes()
            
            # Generate embeddings
            from embedding_utils import ESCOEmbedding
            embedding_util = ESCOEmbedding()
            self.generate_and_store_embeddings(embedding_util)
            
            logger.info("Embedding generation and indexing completed successfully")
        except Exception as e:
            logger.error(f"Error during embedding generation: {str(e)}")
            raise
        finally:
            self.close()

def main():
    parser = argparse.ArgumentParser(description='ESCO Data Ingestion Tool')
    
    # Configuration parameters
    parser.add_argument('--config', type=str, help='Path to YAML config file')
    parser.add_argument('--profile', type=str, default='default',
                      choices=['default', 'aura'],
                      help='Configuration profile to use')
    
    # Execution mode
    parser.add_argument('--embeddings-only', action='store_true',
                      help='Run only the embedding generation and indexing (assumes ESCO graph exists)')
    
    args = parser.parse_args()
    
    # Create ingestor instance
    ingestor = ESCOIngest(config_path=args.config, profile=args.profile)
    
    try:
        # Run appropriate process
        if args.embeddings_only:
            ingestor.run_embeddings_only()
        else:
            ingestor.run_ingest()
    finally:
        ingestor.close()

if __name__ == "__main__":
    main() 