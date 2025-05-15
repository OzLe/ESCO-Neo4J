# ESCO Taxonomy Analysis Queries

This document contains useful Cypher queries for analyzing different aspects of the ESCO taxonomy graph.

## Basic Statistics

### Count of Different Node Types
*This query helps you understand the distribution of different types of nodes in your graph (Skills, Occupations, ISCO Groups, etc.). Useful for getting a quick overview of your data volume.*
```cypher
MATCH (n)
RETURN labels(n) as NodeType, count(*) as Count
ORDER BY Count DESC;
```

### Count of Different Relationship Types
*Shows the distribution of relationship types in your graph. Helps identify the most common types of connections between nodes.*
```cypher
MATCH ()-[r]->()
RETURN type(r) as RelationshipType, count(*) as Count
ORDER BY Count DESC;
```

## Skills Analysis

### Top Skills by Number of Relationships
*Identifies the most connected skills in the taxonomy. Skills with many relationships are likely to be fundamental or widely applicable across different domains.*
```cypher
MATCH (s:Skill)
OPTIONAL MATCH (s)-[r]->()
RETURN s.preferredLabel as Skill, count(r) as RelationshipCount
ORDER BY RelationshipCount DESC
LIMIT 20;
```

### Skills with Most Essential Relationships to Occupations
*Finds skills that are considered essential for the most number of occupations. These are likely to be core competencies required across many jobs.*
```cypher
MATCH (s:Skill)-[r:ESSENTIAL_FOR]->(o:Occupation)
RETURN s.preferredLabel as Skill, count(r) as EssentialOccupationCount
ORDER BY EssentialOccupationCount DESC
LIMIT 20;
```

### Skills with Most Optional Relationships to Occupations
*Identifies skills that are optional but commonly associated with many occupations. These might represent valuable but not mandatory competencies.*
```cypher
MATCH (s:Skill)-[r:OPTIONAL_FOR]->(o:Occupation)
RETURN s.preferredLabel as Skill, count(r) as OptionalOccupationCount
ORDER BY OptionalOccupationCount DESC
LIMIT 20;
```

## Occupation Analysis

### Occupations with Most Required Skills
*Shows which occupations require the most essential skills. These might be complex roles requiring diverse competencies.*
```cypher
MATCH (o:Occupation)<-[r:ESSENTIAL_FOR]-(s:Skill)
RETURN o.preferredLabel as Occupation, count(r) as RequiredSkillsCount
ORDER BY RequiredSkillsCount DESC
LIMIT 20;
```

### Occupations with Most Optional Skills
*Identifies occupations with the most optional skills. These might be roles with many possible skill paths or specializations.*
```cypher
MATCH (o:Occupation)<-[r:OPTIONAL_FOR]-(s:Skill)
RETURN o.preferredLabel as Occupation, count(r) as OptionalSkillsCount
ORDER BY OptionalSkillsCount DESC
LIMIT 20;
```

## ISCO Group Analysis

### ISCO Groups with Most Occupations
*Shows which ISCO groups contain the most occupations. Helps identify the most detailed or diverse occupational categories.*
```cypher
MATCH (i:ISCOGroup)<-[r:PART_OF_ISCOGROUP]-(o:Occupation)
RETURN i.preferredLabel as ISCOGroup, i.code as ISCOCode, count(r) as OccupationCount
ORDER BY OccupationCount DESC
LIMIT 20;
```

### ISCO Group Hierarchy Depth
*Analyzes the depth of the ISCO classification hierarchy. Deeper hierarchies indicate more detailed sub-categorization.*
```cypher
MATCH path = (i:ISCOGroup)-[:BROADER_THAN*]->(j:ISCOGroup)
RETURN i.preferredLabel as ISCOGroup, i.code as ISCOCode, length(path) as HierarchyDepth
ORDER BY HierarchyDepth DESC
LIMIT 20;
```

## Skill Group Analysis

### Skill Groups with Most Skills
*Identifies skill groups that contain the most individual skills. These might represent broad skill domains or categories.*
```cypher
MATCH (sg:SkillGroup)-[:BROADER_THAN]->(s:Skill)
RETURN sg.preferredLabel as SkillGroup, count(s) as SkillCount
ORDER BY SkillCount DESC
LIMIT 20;
```

### Skill Group Hierarchy Depth
*Shows the depth of skill group hierarchies. Deeper hierarchies indicate more detailed skill categorization.*
```cypher
MATCH path = (sg:SkillGroup)-[:BROADER_THAN*]->(s:SkillGroup)
RETURN sg.preferredLabel as SkillGroup, length(path) as HierarchyDepth
ORDER BY HierarchyDepth DESC
LIMIT 20;
```

## Cross-Domain Analysis

### Skills Required Across Multiple ISCO Groups
*Identifies skills that are essential across different ISCO groups. These are likely to be transferable skills valuable across various occupational domains.*
```cypher
MATCH (s:Skill)-[:ESSENTIAL_FOR]->(o:Occupation)-[:PART_OF_ISCOGROUP]->(i:ISCOGroup)
RETURN s.preferredLabel as Skill, count(DISTINCT i) as ISCOGroupCount
ORDER BY ISCOGroupCount DESC
LIMIT 20;
```

### Most Common Skill Combinations
*Finds pairs of skills that are most frequently required together for occupations. Useful for identifying common skill sets and potential learning paths.*
```cypher
MATCH (s1:Skill)-[:ESSENTIAL_FOR]->(o:Occupation)<-[:ESSENTIAL_FOR]-(s2:Skill)
WHERE s1 <> s2
RETURN s1.preferredLabel as Skill1, s2.preferredLabel as Skill2, count(*) as CoOccurrenceCount
ORDER BY CoOccurrenceCount DESC
LIMIT 20;
```

## Path Analysis

### Shortest Path Between Two Skills
*Finds the shortest connection between two skills through any type of relationship. Useful for understanding how different skills are related in the taxonomy.*
```cypher
MATCH (s1:Skill {preferredLabel: 'Skill Name 1'}), (s2:Skill {preferredLabel: 'Skill Name 2'})
MATCH path = shortestPath((s1)-[*]-(s2))
RETURN path;
```

### Skills Required for a Specific Occupation Path
*Lists all essential skills required for a specific occupation. Useful for understanding the complete skill requirements for a particular role.*
```cypher
MATCH (o:Occupation {preferredLabel: 'Occupation Name'})<-[:ESSENTIAL_FOR]-(s:Skill)
RETURN o.preferredLabel as Occupation, collect(s.preferredLabel) as RequiredSkills;
```

### Occupations Related Through Skills (2 Hops)
*Finds occupations that are related through skills with a maximum of 2 hops. This helps identify occupations that share similar skill requirements or are connected through intermediate skills.*

```cypher
// Find occupations related through direct skill connections (1 hop)
MATCH (o1:Occupation {preferredLabel: 'Occupation Name'})<-[:ESSENTIAL_FOR]-(s:Skill)-[:ESSENTIAL_FOR]->(o2:Occupation)
WHERE o1 <> o2
RETURN o1.preferredLabel as SourceOccupation, 
       o2.preferredLabel as RelatedOccupation,
       collect(DISTINCT s.preferredLabel) as ConnectingSkills,
       'Direct' as ConnectionType;

// Find occupations related through intermediate skills (2 hops)
MATCH (o1:Occupation {preferredLabel: 'Occupation Name'})<-[:ESSENTIAL_FOR]-(s1:Skill)-[:RELATED_SKILL]-(s2:Skill)-[:ESSENTIAL_FOR]->(o2:Occupation)
WHERE o1 <> o2
RETURN o1.preferredLabel as SourceOccupation,
       o2.preferredLabel as RelatedOccupation,
       collect(DISTINCT s1.preferredLabel) as SourceSkills,
       collect(DISTINCT s2.preferredLabel) as TargetSkills,
       'Indirect' as ConnectionType;

// Combined query showing both direct and indirect connections
MATCH (o1:Occupation {preferredLabel: 'Occupation Name'})
OPTIONAL MATCH (o1)<-[:ESSENTIAL_FOR]-(s1:Skill)-[:ESSENTIAL_FOR]->(o2:Occupation)
WHERE o1 <> o2
WITH o1, o2, collect(DISTINCT s1.preferredLabel) as directSkills
OPTIONAL MATCH (o1)<-[:ESSENTIAL_FOR]-(s2:Skill)-[:RELATED_SKILL]-(s3:Skill)-[:ESSENTIAL_FOR]->(o3:Occupation)
WHERE o1 <> o3
WITH o1, o2, directSkills, o3, 
     collect(DISTINCT s2.preferredLabel) as sourceSkills,
     collect(DISTINCT s3.preferredLabel) as targetSkills
WITH o1, 
     collect(DISTINCT {
         occupation: o2.preferredLabel,
         type: 'Direct',
         connectingSkills: directSkills
     }) as directConnections,
     collect(DISTINCT {
         occupation: o3.preferredLabel,
         type: 'Indirect',
         sourceSkills: sourceSkills,
         targetSkills: targetSkills
     }) as indirectConnections
RETURN 
    o1.preferredLabel as SourceOccupation,
    directConnections as DirectConnections,
    indirectConnections as IndirectConnections;
```

## Advanced Analysis

### Graph Projection for Advanced Analysis
*Before running centrality or community detection algorithms, you need to project your graph into the GDS library. These steps create an in-memory projection of your graph that can be used for graph algorithms.*

```cypher
// First, create the graph projection
CALL gds.graph.project(
    'escoGraph',
    ['Skill', 'Occupation', 'ISCOGroup', 'SkillGroup'],
    ['ESSENTIAL_FOR', 'OPTIONAL_FOR', 'BROADER_THAN', 'PART_OF_ISCOGROUP', 'RELATED_SKILL']
);

// Verify the projection was created
CALL gds.graph.list();
```

### Skills with High Centrality (Betweenness)
*Identifies skills that act as bridges between different parts of the taxonomy. These skills might be particularly important for connecting different domains.*

```cypher
// Run betweenness centrality on the projected graph
CALL gds.betweenness.stream('escoGraph')
YIELD nodeId, score
MATCH (n) WHERE id(n) = nodeId
RETURN n.preferredLabel as Skill, score as BetweennessScore
ORDER BY BetweennessScore DESC
LIMIT 20;

// After you're done with the analysis, you can drop the graph projection
CALL gds.graph.drop('escoGraph');
```

### Community Detection in Skills
*Groups skills into communities based on their relationships. Helps identify clusters of related skills and potential skill domains.*

```cypher
// Run community detection on the projected graph
CALL gds.louvain.stream('escoGraph')
YIELD nodeId, communityId
MATCH (n) WHERE id(n) = nodeId
RETURN n.preferredLabel as Skill, communityId
ORDER BY communityId, n.preferredLabel;

// After you're done with the analysis, you can drop the graph projection
CALL gds.graph.drop('escoGraph');
```

## Semantic Enrichment Queries

### Complete Occupation Profile
*Extracts all related information for a specific occupation, including required skills, optional skills, ISCO group, and related occupations. Useful for creating comprehensive occupation profiles.*

```cypher
MATCH (o:Occupation {preferredLabel: 'Occupation Name'})
OPTIONAL MATCH (o)<-[r1:ESSENTIAL_FOR]-(s1:Skill)
OPTIONAL MATCH (o)<-[r2:OPTIONAL_FOR]-(s2:Skill)
OPTIONAL MATCH (o)-[:PART_OF_ISCOGROUP]->(i:ISCOGroup)
OPTIONAL MATCH (o)-[:BROADER_THAN]->(o2:Occupation)
OPTIONAL MATCH (o)<-[:BROADER_THAN]-(o3:Occupation)
RETURN 
    o.preferredLabel as Occupation,
    o.altLabels as AlternativeLabels,
    o.description as Description,
    collect(DISTINCT {
        skill: s1.preferredLabel,
        type: 'Essential'
    }) as EssentialSkills,
    collect(DISTINCT {
        skill: s2.preferredLabel,
        type: 'Optional'
    }) as OptionalSkills,
    collect(DISTINCT {
        iscoGroup: i.preferredLabel,
        iscoCode: i.code
    }) as ISCOGroups,
    collect(DISTINCT o2.preferredLabel) as BroaderOccupations,
    collect(DISTINCT o3.preferredLabel) as NarrowerOccupations;
```

### Complete Skill Profile
*Extracts all related information for a specific skill, including occupations that require it, related skills, and skill groups. Useful for creating comprehensive skill profiles.*

```cypher
MATCH (s:Skill {preferredLabel: 'Skill Name'})
OPTIONAL MATCH (s)-[r1:ESSENTIAL_FOR]->(o1:Occupation)
OPTIONAL MATCH (s)-[r2:OPTIONAL_FOR]->(o2:Occupation)
OPTIONAL MATCH (s)-[:BROADER_THAN]->(s2:Skill)
OPTIONAL MATCH (s)<-[:BROADER_THAN]-(s3:Skill)
OPTIONAL MATCH (s)-[:RELATED_SKILL]-(s4:Skill)
OPTIONAL MATCH (s)-[:PART_OF_SKILLGROUP]->(sg:SkillGroup)
RETURN 
    s.preferredLabel as Skill,
    s.altLabels as AlternativeLabels,
    s.description as Description,
    collect(DISTINCT {
        occupation: o1.preferredLabel,
        type: 'Essential'
    }) as EssentialForOccupations,
    collect(DISTINCT {
        occupation: o2.preferredLabel,
        type: 'Optional'
    }) as OptionalForOccupations,
    collect(DISTINCT s2.preferredLabel) as BroaderSkills,
    collect(DISTINCT s3.preferredLabel) as NarrowerSkills,
    collect(DISTINCT s4.preferredLabel) as RelatedSkills,
    collect(DISTINCT sg.preferredLabel) as SkillGroups;
```

### Occupation-Skill Network
*Extracts the complete network of skills and occupations related to a specific occupation, including indirect relationships. Useful for understanding the broader context of an occupation.*

```cypher
MATCH (o:Occupation {preferredLabel: 'Occupation Name'})
OPTIONAL MATCH (o)<-[r1:ESSENTIAL_FOR]-(s1:Skill)
OPTIONAL MATCH (o)<-[r2:OPTIONAL_FOR]-(s2:Skill)
OPTIONAL MATCH (s1)-[:RELATED_SKILL]-(s3:Skill)
OPTIONAL MATCH (s2)-[:RELATED_SKILL]-(s4:Skill)
OPTIONAL MATCH (s3)-[:ESSENTIAL_FOR]->(o2:Occupation)
OPTIONAL MATCH (s4)-[:ESSENTIAL_FOR]->(o3:Occupation)
RETURN 
    o.preferredLabel as Occupation,
    collect(DISTINCT {
        skill: s1.preferredLabel,
        type: 'Direct Essential'
    }) as DirectEssentialSkills,
    collect(DISTINCT {
        skill: s2.preferredLabel,
        type: 'Direct Optional'
    }) as DirectOptionalSkills,
    collect(DISTINCT {
        skill: s3.preferredLabel,
        type: 'Related to Essential'
    }) as RelatedToEssentialSkills,
    collect(DISTINCT {
        skill: s4.preferredLabel,
        type: 'Related to Optional'
    }) as RelatedToOptionalSkills,
    collect(DISTINCT {
        occupation: o2.preferredLabel,
        type: 'Related via Essential Skills'
    }) as RelatedOccupationsViaEssential,
    collect(DISTINCT {
        occupation: o3.preferredLabel,
        type: 'Related via Optional Skills'
    }) as RelatedOccupationsViaOptional;
```

### Skill-Occupation Network
*Extracts the complete network of occupations and skills related to a specific skill, including indirect relationships. Useful for understanding the broader context of a skill.*

```cypher
MATCH (s:Skill {preferredLabel: 'Skill Name'})
OPTIONAL MATCH (s)-[r1:ESSENTIAL_FOR]->(o1:Occupation)
OPTIONAL MATCH (s)-[r2:OPTIONAL_FOR]->(o2:Occupation)
OPTIONAL MATCH (o1)-[:PART_OF_ISCOGROUP]->(i1:ISCOGroup)
OPTIONAL MATCH (o2)-[:PART_OF_ISCOGROUP]->(i2:ISCOGroup)
OPTIONAL MATCH (s)-[:RELATED_SKILL]-(s2:Skill)
OPTIONAL MATCH (s2)-[:ESSENTIAL_FOR]->(o3:Occupation)
OPTIONAL MATCH (s2)-[:OPTIONAL_FOR]->(o4:Occupation)
RETURN 
    s.preferredLabel as Skill,
    collect(DISTINCT {
        occupation: o1.preferredLabel,
        type: 'Direct Essential'
    }) as DirectEssentialOccupations,
    collect(DISTINCT {
        occupation: o2.preferredLabel,
        type: 'Direct Optional'
    }) as DirectOptionalOccupations,
    collect(DISTINCT {
        iscoGroup: i1.preferredLabel,
        type: 'Via Essential'
    }) as ISCOGroupsViaEssential,
    collect(DISTINCT {
        iscoGroup: i2.preferredLabel,
        type: 'Via Optional'
    }) as ISCOGroupsViaOptional,
    collect(DISTINCT {
        skill: s2.preferredLabel,
        type: 'Related'
    }) as RelatedSkills,
    collect(DISTINCT {
        occupation: o3.preferredLabel,
        type: 'Via Related Skills Essential'
    }) as OccupationsViaRelatedEssential,
    collect(DISTINCT {
        occupation: o4.preferredLabel,
        type: 'Via Related Skills Optional'
    }) as OccupationsViaRelatedOptional;
```

### Graph Visualization Queries

#### Occupation Profile Graph
*Returns the complete graph structure for an occupation and its related nodes. Useful for visualizing the occupation's context in the taxonomy.*

```cypher
MATCH (o:Occupation {preferredLabel: 'Occupation Name'})
OPTIONAL MATCH (o)<-[r1:ESSENTIAL_FOR]-(s1:Skill)
OPTIONAL MATCH (o)<-[r2:OPTIONAL_FOR]-(s2:Skill)
OPTIONAL MATCH (o)-[:PART_OF_ISCOGROUP]->(i:ISCOGroup)
OPTIONAL MATCH (o)-[:BROADER_THAN]->(o2:Occupation)
OPTIONAL MATCH (o)<-[:BROADER_THAN]-(o3:Occupation)
RETURN o, s1, s2, i, o2, o3, r1, r2;
```

#### Skill Profile Graph
*Returns the complete graph structure for a skill and its related nodes. Useful for visualizing the skill's context in the taxonomy.*

```cypher
MATCH (s:Skill {preferredLabel: 'Skill Name'})
OPTIONAL MATCH (s)-[r1:ESSENTIAL_FOR]->(o1:Occupation)
OPTIONAL MATCH (s)-[r2:OPTIONAL_FOR]->(o2:Occupation)
OPTIONAL MATCH (s)-[:BROADER_THAN]->(s2:Skill)
OPTIONAL MATCH (s)<-[:BROADER_THAN]-(s3:Skill)
OPTIONAL MATCH (s)-[:RELATED_SKILL]-(s4:Skill)
OPTIONAL MATCH (s)-[:PART_OF_SKILLGROUP]->(sg:SkillGroup)
RETURN s, o1, o2, s2, s3, s4, sg, r1, r2;
```

#### Occupation-Skill Network Graph
*Returns the complete network graph for an occupation, including indirect relationships. Useful for visualizing the broader context of an occupation.*

```cypher
MATCH (o:Occupation {preferredLabel: 'Occupation Name'})
OPTIONAL MATCH (o)<-[r1:ESSENTIAL_FOR]-(s1:Skill)
OPTIONAL MATCH (o)<-[r2:OPTIONAL_FOR]-(s2:Skill)
OPTIONAL MATCH (s1)-[:RELATED_SKILL]-(s3:Skill)
OPTIONAL MATCH (s2)-[:RELATED_SKILL]-(s4:Skill)
OPTIONAL MATCH (s3)-[:ESSENTIAL_FOR]->(o2:Occupation)
OPTIONAL MATCH (s4)-[:ESSENTIAL_FOR]->(o3:Occupation)
RETURN o, s1, s2, s3, s4, o2, o3, r1, r2;
```

#### Skill-Occupation Network Graph
*Returns the complete network graph for a skill, including indirect relationships. Useful for visualizing the broader context of a skill.*

```cypher
MATCH (s:Skill {preferredLabel: 'Skill Name'})
OPTIONAL MATCH (s)-[r1:ESSENTIAL_FOR]->(o1:Occupation)
OPTIONAL MATCH (s)-[r2:OPTIONAL_FOR]->(o2:Occupation)
OPTIONAL MATCH (o1)-[:PART_OF_ISCOGROUP]->(i1:ISCOGroup)
OPTIONAL MATCH (o2)-[:PART_OF_ISCOGROUP]->(i2:ISCOGroup)
OPTIONAL MATCH (s)-[:RELATED_SKILL]-(s2:Skill)
OPTIONAL MATCH (s2)-[:ESSENTIAL_FOR]->(o3:Occupation)
OPTIONAL MATCH (s2)-[:OPTIONAL_FOR]->(o4:Occupation)
RETURN 
    s.preferredLabel as Skill,
    collect(DISTINCT {
        occupation: o1.preferredLabel,
        type: 'Direct Essential'
    }) as DirectEssentialOccupations,
    collect(DISTINCT {
        occupation: o2.preferredLabel,
        type: 'Direct Optional'
    }) as DirectOptionalOccupations,
    collect(DISTINCT {
        iscoGroup: i1.preferredLabel,
        type: 'Via Essential'
    }) as ISCOGroupsViaEssential,
    collect(DISTINCT {
        iscoGroup: i2.preferredLabel,
        type: 'Via Optional'
    }) as ISCOGroupsViaOptional,
    collect(DISTINCT {
        skill: s2.preferredLabel,
        type: 'Related'
    }) as RelatedSkills,
    collect(DISTINCT {
        occupation: o3.preferredLabel,
        type: 'Via Related Skills Essential'
    }) as OccupationsViaRelatedEssential,
    collect(DISTINCT {
        occupation: o4.preferredLabel,
        type: 'Via Related Skills Optional'
    }) as OccupationsViaRelatedOptional;
```

#### Custom Graph Visualization with Properties
*Returns a graph with specific properties for better visualization. You can customize the properties shown for each node type.*

```cypher
MATCH (o:Occupation {preferredLabel: 'Occupation Name'})
OPTIONAL MATCH (o)<-[r1:ESSENTIAL_FOR]-(s1:Skill)
OPTIONAL MATCH (o)<-[r2:OPTIONAL_FOR]-(s2:Skill)
OPTIONAL MATCH (o)-[:PART_OF_ISCOGROUP]->(i:ISCOGroup)
OPTIONAL MATCH (o)-[:BROADER_THAN]->(o2:Occupation)
OPTIONAL MATCH (o)<-[:BROADER_THAN]-(o3:Occupation)
RETURN 
    o {.preferredLabel, .description, type: 'Occupation'} as Occupation,
    s1 {.preferredLabel, type: 'Skill', relation: 'Essential'} as EssentialSkills,
    s2 {.preferredLabel, type: 'Skill', relation: 'Optional'} as OptionalSkills,
    i {.preferredLabel, .code, type: 'ISCOGroup'} as ISCOGroup,
    o2 {.preferredLabel, type: 'Occupation', relation: 'Broader'} as BroaderOccupations,
    o3 {.preferredLabel, type: 'Occupation', relation: 'Narrower'} as NarrowerOccupations,
    r1, r2;
```

#### Query Examples for Semantic Search
```cypher
// Semantic search for skills similar to "programming"
MATCH (s:Skill)
WHERE s.embedding IS NOT NULL
WITH s, vector.similarity.cosine(s.embedding, $query_embedding) AS score
WHERE score > 0.6
RETURN s.preferredLabel AS Skill, s.description AS Description, score
ORDER BY score DESC
LIMIT 10;

// Find occupations that require semantically similar skills to "data analysis"
MATCH (querySkill:Skill)
WHERE querySkill.preferredLabel CONTAINS "data analysis"
MATCH (s:Skill)
WHERE s.embedding IS NOT NULL AND s <> querySkill
WITH s, vector.similarity.cosine(s.embedding, querySkill.embedding) AS score
WHERE score > 0.7
MATCH (s)-[:ESSENTIAL_FOR]->(o:Occupation)
RETURN DISTINCT o.preferredLabel AS Occupation, 
       collect(DISTINCT s.preferredLabel) AS SimilarSkills,
       count(DISTINCT s) AS SkillCount
ORDER BY SkillCount DESC
LIMIT 10;
```

## Notes

1. For advanced analysis queries:
   - Make sure the Neo4j Graph Data Science library is installed
   - The graph projection step is required before running centrality or community detection
   - The projection creates an in-memory copy of your graph optimized for graph algorithms
   - Remember to drop the projection when you're done to free up memory
2. Replace placeholder values (like 'Skill Name 1', 'Occupation Name') with actual values from your graph.
3. Adjust LIMIT clauses based on your needs and data volume.
4. Some queries might need optimization for large datasets.
5. For semantic enrichment queries:
   - Replace 'Occupation Name' or 'Skill Name' with the actual label you want to analyze
   - The queries return structured data that can be easily processed for semantic enrichment
   - Consider adding filters to focus on specific aspects of the relationships
   - The network queries might return large result sets for highly connected nodes
6. For graph visualization queries:
   - These queries return the actual graph structure instead of text data
   - Use Neo4j Browser's visualization features to explore the results
   - The graph structure makes it easier to understand relationships
   - You can customize the properties shown for each node type
   - Consider using different colors for different node types in the visualization
   - The custom graph visualization query can be modified to show different properties

## Usage Tips

1. Start with basic statistics to understand your graph's structure
2. Use path analysis to understand relationships between different elements
3. Apply filters to focus on specific aspects of the taxonomy
4. Combine queries to create more complex analyses
5. Use visualization tools in Neo4j Browser to better understand the results 