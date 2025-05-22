# ESCO Data Management and Search Tool

This tool is designed for managing, searching, and translating the ESCO (European Skills, Competences, Qualifications and Occupations) taxonomy in a Neo4j graph database. It provides a unified command-line interface for data ingestion, semantic search, and translation capabilities.

## Disclaimer

This tool is provided "AS IS", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose and noninfringement. In no event shall the authors or copyright holders be liable for any claim, damages or other liability, whether in an action of contract, tort or otherwise, arising from, out of or in connection with the software or the use or other dealings in the software.

## Prerequisites

- Python 3.8 or higher
- Neo4j Database (version 5.x) or Neo4j AuraDB
- ESCO CSV files (v1.2.0 or compatible)
- Docker and Docker Compose (for containerized deployment)

## Environment Setup

### Using Docker (Recommended)

The easiest way to run the application is using Docker Compose:

1. Build and start the containers:
```bash
docker-compose up -d
```

2. Check the logs:
```bash
docker-compose logs -f
```

The application will automatically connect to Neo4j once it's healthy.

### Using Conda (Alternative)

The easiest way to set up the environment is using the provided `environment.yml` file:

1. Create and activate the environment:
```bash
conda env create -f environment.yml
conda activate esco
```

2. Verify the installation:
```bash
python - <<'PY'
import tiktoken, sentencepiece, google.protobuf, transformers
print("All critical libraries imported successfully.")
PY
```

### Configuration

The tool uses a YAML configuration file for Neo4j connection settings. To set up:

1. Copy the sample configuration:
```bash
cp config/neo4j_config.sample.yaml config/neo4j_config.yaml
```

2. Edit `config/neo4j_config.yaml` with your Neo4j connection details:
   - For local Neo4j: Use the `default` profile
   - For AuraDB: Use the `aura` profile

3. Alternatively, you can set environment variables:
```bash
# For local Neo4j
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your-password"
export NEO4J_PROFILE="default"

# For AuraDB
export NEO4J_URI="neo4j+s://your-instance-id.databases.neo4j.io"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your-password"
export NEO4J_PROFILE="aura"

# Optional configuration
export NEO4J_MAX_RETRIES=5
export NEO4J_RETRY_DELAY=10
export NEO4J_MAX_CONNECTION_LIFETIME=1800
export NEO4J_MAX_CONNECTION_POOL_SIZE=100
export NEO4J_CONNECTION_TIMEOUT=60
```

### Docker Configuration

The application is configured to run in two containers:

1. **Neo4j Container**:
   - Runs Neo4j 5.11.0
   - Exposes ports 7474 (HTTP) and 7687 (Bolt)
   - Uses persistent volumes for data, logs, and plugins
   - Includes health checks
   - Configurable through environment variables

2. **ESCO Application Container**:
   - Runs the Python application
   - Connects to Neo4j using environment variables
   - Mounts data and logs directories
   - Waits for Neo4j to be healthy before starting

To customize the Docker setup:

1. Edit `docker-compose.yml`:
```yaml
services:
  neo4j:
    environment:
      - NEO4J_AUTH=neo4j/your-password
      - NEO4J_dbms_memory_pagecache_size=1G
      # ... other Neo4j settings

  esco-app:
    environment:
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=your-password
      # ... other application settings
```

2. For AuraDB, update the Neo4j connection:
```yaml
services:
  esco-app:
    environment:
      - NEO4J_URI=neo4j+s://your-instance-id.databases.neo4j.io
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=your-aura-password
      - NEO4J_PROFILE=aura
```

### Apple Silicon (M1/M2/M3) Notes

The `environment.yml` file is already configured for Apple Silicon Macs and includes:
- Native ARM64 builds for PyTorch with MPS support
- Properly pinned dependencies for compatibility
- Required system libraries through conda-forge

If you encounter any issues:

1. Ensure you're using the latest conda:
```bash
conda update -n base conda
```

2. Make sure user-site packages are not injected:
```bash
# inside the conda shell:
export PYTHONNOUSERSITE=1   # or add this in your ~/.zshrc
```

3. For diagnostic checks:
```bash
python - <<'PY'
import importlib.util, subprocess, sys, os
lib = importlib.util.find_spec('PIL._imaging').origin
print("Pillow C-extension:", lib)
print("Linked against:")
subprocess.check_call(["otool", "-L", lib])
PY
```

The output should list **$CONDA_PREFIX/lib/libjpeg.**dylib, not /usr/local/lib or /opt/homebrew/lib.

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd ESCO-Ingest
```

2. Choose your setup method:
   - For Docker: Follow the Docker setup instructions
   - For local development: Follow the Conda setup instructions

3. Configure your Neo4j connection as described in the Configuration section.

## Directory Structure

```
ESCO-Ingest/
├── config/
│   ├── neo4j_config.sample.yaml  # Sample configuration (safe to commit)
│   └── neo4j_config.yaml         # Your configuration (gitignored)
├── src/
│   ├── esco_cli.py              # Unified CLI interface
│   ├── esco_ingest.py           # Data ingestion implementation
│   ├── neo4j_client.py          # Neo4j client implementation
│   ├── embedding_utils.py       # Embedding generation utilities
│   ├── semantic_search.py       # Semantic search implementation
│   ├── esco_translate.py        # Translation implementation
│   └── download_model.py        # Model download utility
├── ESCO/                        # ESCO data directory (gitignored)
│   ├── skillGroups_en.csv
│   ├── skills_en.csv
│   ├── occupations_en.csv
│   ├── ISCOGroups_en.csv
│   ├── broaderRelationsSkillPillar_en.csv
│   ├── broaderRelationsOccPillar_en.csv
│   ├── occupationSkillRelations_en.csv
│   └── skillSkillRelations_en.csv
├── docker-compose.yml          # Docker Compose configuration
├── Dockerfile                 # Docker build configuration
├── environment.yml            # Conda environment definition
├── requirements.txt          # Pip requirements
└── README.md                 # This file
```

Place your ESCO CSV files in the `ESCO` directory. The tool expects the following files:
- `skillGroups_en.csv`
- `skills_en.csv`
- `occupations_en.csv`
- `ISCOGroups_en.csv`
- `broaderRelationsSkillPillar_en.csv`
- `broaderRelationsOccPillar_en.csv`
- `occupationSkillRelations_en.csv`
- `skillSkillRelations_en.csv`

## Usage

The tool provides a unified command-line interface (`esco_cli.py`) with several subcommands:

### General Help

```bash
# Show general help
python src/esco_cli.py --help

# Show help for a specific command
python src/esco_cli.py search --help
```

### Download Translation Model

```bash
python src/esco_cli.py download-model
```

### Data Ingestion

```bash
# Full ingestion
python src/esco_cli.py ingest --config config/neo4j_config.yaml

# Embeddings only
python src/esco_cli.py ingest --config config/neo4j_config.yaml --embeddings-only

# Delete existing data and re-ingest
python src/esco_cli.py ingest --config config/neo4j_config.yaml --delete-all
```

### Semantic Search

```bash
# Basic search
python src/esco_cli.py search --query "python programming"

# Search with options
python src/esco_cli.py search \
    --query "python programming" \
    --type Skill \
    --limit 5 \
    --threshold 0.7 \
    --related

# JSON output
python src/esco_cli.py search --query "python programming" --json
```

### Translation

```bash
# Translate skills
python src/esco_cli.py translate --type Skill --property prefLabel

# Translate with options
python src/esco_cli.py translate \
    --type Skill \
    --property prefLabel \
    --batch-size 50 \
    --device mps
```

## Output Format

The CLI provides structured, color-coded output for better readability:

### Search Results
```
========================================================================
 ESCO Semantic Search 
========================================================================

Query: python programming
Type: Skill
Threshold: 0.5

----------------------------------------------------------------
 Searching... 
----------------------------------------------------------------

----------------------------------------------------------------
 Search Results 
----------------------------------------------------------------

1. [Skill] Python Programming (Score: 0.9234)
   Description: The ability to write and maintain Python code...

2. [Skill] Python Development (Score: 0.8912)
   Description: Experience in developing applications using Python...
```

### Related Entities
```
----------------------------------------------------------------
 Related entities for 'Python Programming' 
----------------------------------------------------------------

Essential Skills (3):
  • Object-Oriented Programming
  • Software Development
  • Version Control

Optional Skills (5):
  • Web Development
  • Database Management
  • ... and 2 more
```

### Progress and Status
```
========================================================================
 ESCO Data Ingestion 
========================================================================

----------------------------------------------------------------
 Starting Ingestion 
----------------------------------------------------------------

Running full ingestion...
✓ Ingestion completed successfully
```

## Configuration Profiles

The tool supports two configuration profiles:

### Default Profile (Local Development)
```yaml
default:
  uri: "bolt://localhost:7687"
  user: "neo4j"
  password: "your-password"
  max_retries: 3
  retry_delay: 5
  max_connection_lifetime: 3600
  max_connection_pool_size: 50
  connection_timeout: 30
```

### Aura Profile (Production)
```yaml
aura:
  uri: "neo4j+s://your-instance-id.databases.neo4j.io"
  user: "neo4j"
  password: "your-password"
  max_retries: 5
  retry_delay: 10
  max_connection_lifetime: 1800
  max_connection_pool_size: 100
  connection_timeout: 60
```

## Data Model

The tool creates the following node types and relationships:

### Nodes
- `Skill`: Represents individual skills
- `SkillGroup`: Represents groups of skills
- `Occupation`: Represents occupations
- `ISCOGroup`: Represents ISCO classification groups

### Relationships
- `BROADER_THAN`: Hierarchical relationships between skills and ISCO groups
- `PART_OF_ISCOGROUP`: Links occupations to their ISCO groups
- `ESSENTIAL_FOR`: Links essential skills to occupations
- `OPTIONAL_FOR`: Links optional skills to occupations
- `RELATED_SKILL`: Links related skills with their relationship type

## Performance

The tool processes data in batches to optimize memory usage and performance:
- Default batch size: 50,000 rows for ingestion
- Configurable batch size for translation
- Efficient vector indexes for semantic search
- Support for multiple devices (CPU, CUDA, MPS)

## Error Handling

The tool includes comprehensive error handling:
- Clear error messages with color coding
- Proper resource cleanup
- Validation of configuration and input
- Graceful handling of connection issues

## Troubleshooting

If you encounter issues:

1. Configuration:
   - Verify Neo4j connection details
   - Check config file permissions
   - Ensure correct profile is selected

2. Data:
   - Verify all required CSV files are present
   - Check CSV file formats
   - Ensure proper file permissions

3. Search:
   - Verify embeddings are generated
   - Check vector indexes in Neo4j
   - Try search-only mode if needed

4. Translation:
   - Ensure model is downloaded
   - Check device compatibility
   - Adjust batch size if needed

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

This is a simple tool for testing and visualization purposes. While contributions are welcome, please note that this is not intended for production use. If you find any issues or have suggestions for improvements, feel free to open an issue or submit a pull request. 