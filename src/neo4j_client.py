import os
import time
import yaml
import logging
from urllib.parse import urlparse
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, AuthError, ClientError

logger = logging.getLogger(__name__)

class Neo4jClient:
    def __init__(self, config_path=None, profile='default'):
        """
        Initialize Neo4j client with configuration
        
        Args:
            config_path (str): Path to YAML config file
            profile (str): Configuration profile to use ('default' or 'aura')
        """
        self.config = self._load_config(config_path, profile)
        self.driver = None
        self._connect()

    def _load_config(self, config_path, profile):
        """Load configuration from YAML file"""
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'neo4j_config.yaml')
        
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Get the requested profile
            profile_config = config.get(profile, config['default'])
            
            # Create a new config that includes both profile and root-level settings
            merged_config = {**config}  # Start with all root-level config
            merged_config.update(profile_config)  # Override with profile-specific settings
            
            # Override with environment variables if they exist
            if 'NEO4J_URI' in os.environ:
                merged_config['uri'] = os.environ['NEO4J_URI']
            if 'NEO4J_USER' in os.environ:
                merged_config['user'] = os.environ['NEO4J_USER']
            if 'NEO4J_PASSWORD' in os.environ:
                merged_config['password'] = os.environ['NEO4J_PASSWORD']
            
            return merged_config
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            raise

    def _connect(self):
        """Establish connection with retry logic"""
        for attempt in range(self.config['max_retries']):
            try:
                # Validate and potentially modify URI
                parsed_uri = urlparse(self.config['uri'])
                if parsed_uri.scheme == 'neo4j+s':
                    # AuraDB connection - ensure proper format
                    if not self.config['uri'].startswith('neo4j+s://'):
                        self.config['uri'] = self.config['uri'].replace('bolt://', 'neo4j+s://')
                elif parsed_uri.scheme == 'bolt':
                    # Local connection - ensure proper format
                    if not self.config['uri'].startswith('bolt://'):
                        self.config['uri'] = f'bolt://{parsed_uri.netloc}'
                
                self.driver = GraphDatabase.driver(
                    self.config['uri'],
                    auth=(self.config['user'], self.config['password']),
                    max_connection_lifetime=self.config['max_connection_lifetime'],
                    max_connection_pool_size=self.config['max_connection_pool_size'],
                    connection_timeout=self.config['connection_timeout']
                )
                
                # Test connection
                with self.driver.session() as session:
                    session.run("RETURN 1")
                logger.info(f"Successfully connected to Neo4j at {self.config['uri']}")
                return
                
            except (ServiceUnavailable, AuthError, ClientError) as e:
                if attempt < self.config['max_retries'] - 1:
                    logger.warning(f"Connection attempt {attempt + 1} failed: {str(e)}. Retrying in {self.config['retry_delay']} seconds...")
                    time.sleep(self.config['retry_delay'])
                else:
                    logger.error(f"Failed to connect after {self.config['max_retries']} attempts: {str(e)}")
                    raise

    def execute_query(self, query, parameters=None, session=None, data=None):
        """Execute a query with retry logic
        
        Args:
            query (str): The Cypher query to execute
            parameters (dict, optional): Query parameters
            session (Session, optional): Existing Neo4j session to use
            data (list, optional): List of dictionaries for UNWIND operations
        """
        # If data is provided, use it as parameters
        if data is not None:
            parameters = {'data': data}
        
        for attempt in range(self.config['max_retries']):
            try:
                if session:
                    return session.run(query, parameters or {})
                else:
                    with self.driver.session() as s:
                        return s.run(query, parameters or {})
            except (ServiceUnavailable, ClientError) as e:
                if attempt < self.config['max_retries'] - 1:
                    logger.warning(f"Query attempt {attempt + 1} failed: {str(e)}. Retrying in {self.config['retry_delay']} seconds...")
                    time.sleep(self.config['retry_delay'])
                else:
                    logger.error(f"Failed to execute query after {self.config['max_retries']} attempts: {str(e)}")
                    raise

    def execute_transaction(self, queries, parameters=None):
        """Execute multiple queries in a single transaction"""
        with self.driver.session() as session:
            with session.begin_transaction() as tx:
                for query in queries:
                    tx.run(query, parameters or {})
                tx.commit()

    def close(self):
        """Close the database connection"""
        if self.driver:
            self.driver.close()
            self.driver = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close() 